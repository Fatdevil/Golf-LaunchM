import asyncio
import cv2
import numpy as np
import time
import json
import uuid
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from models import CalibrationConfig, MeasureResult
import logging

logger = logging.getLogger("MeasureEngine")

class AudioTrigger:
    def __init__(self, callback, device_index=None):
        self.callback = callback
        self.baseline_rms = 0.0
        self.is_calibrating = True
        self.stream = None
        self.device_index = device_index
        self.has_sounddevice = False
        
        try:
            import sounddevice as sd
            self.has_sounddevice = True
        except ImportError:
            logger.warning("sounddevice not available, falling back to optical flow trigger")
            self.has_sounddevice = False

    def start(self):
        if not self.has_sounddevice:
            return
            
        import sounddevice as sd
        try:
            self.stream = sd.InputStream(
                samplerate=44100,
                blocksize=220,   # ~5ms at 44100Hz
                channels=1,
                dtype='float32',
                callback=self._audio_callback,
                device=self.device_index
            )
            self.stream.start()
            logger.info("AudioTrigger started successfully")
        except Exception as e:
            logger.error(f"Failed to start AudioTrigger: {e}")
            self.has_sounddevice = False

    def _audio_callback(self, indata, frames, time_info, status):
        rms = np.sqrt(np.mean(indata**2))
        
        # Calibrate baseline first 2 seconds
        if self.is_calibrating:
            self.baseline_rms = self.baseline_rms * 0.95 + rms * 0.05
            return
        
        # Impact = RMS spike > 15x baseline
        if self.baseline_rms > 0 and rms > self.baseline_rms * 15:
            import time
            self.callback(time.time())

    def stop_calibration(self):
        self.is_calibrating = False

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

class MeasureEngine:
    def __init__(self, camera_index: int, config: CalibrationConfig, 
                 shot_queue: asyncio.Queue, measure_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        """
        Camera index 2 should be on dedicated USB 3.0 root hub for best performance.
        If frame drops occur, reduce to 720p/30fps.
        """
        self.camera_index = camera_index
        self.config = config
        self.shot_queue = shot_queue
        self.measure_queue = measure_queue
        self.loop = loop
        
        self.cap = None
        self.running = False
        self.thread_pool = ThreadPoolExecutor(max_workers=3)
        self.impact_time = 0.0
        self.impact_frame_idx = -1
        self.frame_buffer = []  # stores (time, frame, index)
        self.buffer_size = 60   # 1 second at 60fps
        
        self.audio_trigger = AudioTrigger(self._on_audio_impact)

    def _on_audio_impact(self, timestamp: float):
        if self.impact_time == 0.0:
            self.impact_time = timestamp
            logger.info(f"Audio impact triggered at {timestamp}")

    def start(self):
        self.running = True
        self.audio_trigger.start()
        # Calibrate audio baseline for 2 seconds
        self.loop.call_later(2.0, self.audio_trigger.stop_calibration)
        self.loop.run_in_executor(self.thread_pool, self._capture_loop)

    def stop(self):
        self.running = False
        self.audio_trigger.stop()
        if self.cap:
            self.cap.release()
        self.thread_pool.shutdown(wait=False)

    def _calibrate_geometry(self, frame_height: int, frame_width: int):
        # 100-120cm camera height
        H_mm = self.config.camera_height_cm * 10
        tilt_rad = np.radians(self.config.camera_tilt_deg)
        
        # Simple camera projection math
        # pixels_per_mm = frame_height / (2 * H * tan(tilt/2))
        self.config.pixels_per_mm = frame_height / (2 * H_mm * np.tan(tilt_rad / 2))
        
        # Ground plane assumed at lower 20% of frame if not auto-detected
        self.config.ground_plane_y = int(frame_height * 0.8)
        logger.info(f"Geometry calibrated: {self.config.pixels_per_mm:.4f} px/mm, Ground Y: {self.config.ground_plane_y}")

    def _capture_loop(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 60)

        if not self.cap.isOpened():
            logger.error(f"Failed to open Measure Camera {self.camera_index}")
            return

        ret, frame = self.cap.read()
        if ret:
            self._calibrate_geometry(frame.shape[0], frame.shape[1])

        frame_idx = 0
        prev_gray = None

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
                
            current_time = time.time()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Optical Flow Fallback Trigger (if no audio impact registered)
            if not self.audio_trigger.has_sounddevice and self.impact_time == 0.0 and prev_gray is not None:
                roi_top = max(0, self.config.ground_plane_y - int(frame.shape[0]*0.15))
                roi_bottom = min(frame.shape[0], self.config.ground_plane_y + int(frame.shape[0]*0.15))
                
                diff = cv2.absdiff(prev_gray[roi_top:roi_bottom, :], gray[roi_top:roi_bottom, :])
                _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                motion_pixels = cv2.countNonZero(thresh)
                
                # Sudden motion spike
                if motion_pixels > 500:
                    self.impact_time = current_time
                    logger.info(f"Optical impact triggered at {current_time} (motion px: {motion_pixels})")

            prev_gray = gray
            
            self.frame_buffer.append((current_time, frame, frame_idx))
            if len(self.frame_buffer) > self.buffer_size:
                self.frame_buffer.pop(0)

            # Check if 25 frames have passed since impact
            if self.impact_time > 0 and len(self.frame_buffer) >= 30:
                # find frame index matching impact time
                impact_idx = -1
                for i, (t, f, idx) in enumerate(self.frame_buffer):
                    if t >= self.impact_time:
                        impact_idx = i
                        break
                
                if impact_idx != -1 and (len(self.frame_buffer) - impact_idx) >= 25:
                    # Extract 30 frame clip (5 pre, 25 post)
                    start_idx = max(0, impact_idx - 5)
                    end_idx = min(len(self.frame_buffer), impact_idx + 25)
                    clip = [f for _, f, _ in self.frame_buffer[start_idx:end_idx]]
                    
                    self.impact_frame_idx = impact_idx - start_idx
                    
                    # Submit for processing asynchronously
                    self.loop.run_in_executor(self.thread_pool, self._process_clip, clip, self.impact_frame_idx, current_time)
                    
                    # Reset state for next shot
                    self.impact_time = 0.0
                    self.impact_frame_idx = -1

            frame_idx += 1

    def detect_ball_classical(self, frame, roi_rect):
        """Finds white circle in roi"""
        x, y, w, h = roi_rect
        roi = frame[y:y+h, x:x+w]
        
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower_white = np.array([0, 0, 200])
        upper_white = np.array([180, 30, 255])
        
        mask = cv2.inRange(hsv, lower_white, upper_white)
        mask = cv2.erode(mask, None, iterations=1)
        mask = cv2.dilate(mask, None, iterations=2)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_ball = None
        highest_conf = 0.0
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 20 < area < 500:
                perimeter = cv2.arcLength(cnt, True)
                circularity = 4 * np.pi * (area / (perimeter * perimeter)) if perimeter > 0 else 0
                if circularity > 0.65:
                    (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                    conf = circularity
                    if conf > highest_conf:
                        highest_conf = conf
                        # Map back to full frame coordinates
                        best_ball = (int(cx + x), int(cy + y), conf, radius)
                        
        return best_ball

    def track_ball_trajectory(self, frames, impact_frame_idx):
        positions = [] # [x, y, frame_idx, conf]
        
        kf = cv2.KalmanFilter(4, 2)
        kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        kf.transitionMatrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
        kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.03
        
        h, w = frames[impact_frame_idx].shape[:2]
        
        roi_rect = (int(w*0.2), int(h*0.5), int(w*0.6), int(h*0.4)) # Initial roi around ground
        
        for i in range(impact_frame_idx, len(frames)):
            ball = self.detect_ball_classical(frames[i], roi_rect)
            if ball:
                bx, by, conf, _ = ball
                positions.append([bx, by, i, conf])
                
                # init kf on first find
                if len(positions) == 1:
                    kf.statePre = np.array([[bx], [by], [0], [0]], np.float32)
                    kf.statePost = np.array([[bx], [by], [0], [0]], np.float32)
                else:
                    kf.correct(np.array([[np.float32(bx)], [np.float32(by)]]))
                
                pred = kf.predict()
                # Update ROI for next frame based on prediction
                p_x, p_y = int(pred[0]), int(pred[1])
                roi_rect = (max(0, p_x - 100), max(0, p_y - 100), 200, 200)
            else:
                if len(positions) > 0:
                    pred = kf.predict()
                    p_x, p_y = int(pred[0]), int(pred[1])
                    positions.append([p_x, p_y, i, 0.1])
                    roi_rect = (max(0, p_x - 150), max(0, p_y - 150), 300, 300)
                    
        return positions

    def detect_club(self, frames, impact_frame_idx):
        # Extract club_path from 5 frames before impact
        club_positions = []
        # Simplified: fallback logic
        return club_positions

    def calculate_raw_measurements(self, ball_positions, club_positions, fps):
        if len(ball_positions) < 4:
            return 0.0, 0.0, 0.0, 0.0, 0.0
            
        high_conf_balls = [b for b in ball_positions if b[3] > 0.4]
        if len(high_conf_balls) < 3:
             return 0.0, 0.0, 0.0, 0.0, 0.0
             
        # Ball speed
        b_start = high_conf_balls[0]
        b_end = high_conf_balls[-1]
        
        frames_elapsed = b_end[2] - b_start[2]
        if frames_elapsed == 0: return 0.0, 0.0, 0.0, 0.0, 0.0
        
        dx = b_end[0] - b_start[0]
        dy = b_end[1] - b_start[1]
        dist_px = np.sqrt(dx**2 + dy**2)
        
        dist_mm = dist_px / max(0.1, self.config.pixels_per_mm)
        v_ms = (dist_mm / 1000.0) / (frames_elapsed / float(fps))
        ball_speed_mph = v_ms * 2.23694
        
        # Launch Angle
        tilt_rad = np.radians(self.config.camera_tilt_deg)
        vert_px = dy * np.cos(tilt_rad) - dx * np.sin(tilt_rad)
        horiz_px = dx
        
        launch_angle_deg = np.degrees(np.arctan2(-vert_px, abs(horiz_px))) + self.config.camera_tilt_deg
        
        # Launch Direction
        direction_deg = np.degrees(np.arctan2(horiz_px, -dy)) if dy != 0 else 0.0
        
        # Estimation physics for carry (simple formulation)
        carry_yards = (ball_speed_mph * 1.5) * (0.8 + (launch_angle_deg / 100))
        
        return ball_speed_mph, v_ms, launch_angle_deg, direction_deg, carry_yards

    def _process_clip(self, frames, impact_frame_idx, timestamp):
        fps = 60.0
        
        ball_positions = self.track_ball_trajectory(frames, impact_frame_idx)
        club_positions = self.detect_club(frames, impact_frame_idx)
        
        b_mph, b_ms, l_angle, l_dir, carry = self.calculate_raw_measurements(ball_positions, club_positions, fps)
        
        high_conf_count = sum(1 for b in ball_positions if b[3] > 0.4)
        
        result = MeasureResult(
            measure_id=str(uuid.uuid4()),
            shot_id="",
            timestamp=str(timestamp),
            ball_speed_ms_raw=b_ms,
            launch_angle_deg_raw=l_angle,
            launch_direction_deg_raw=l_dir,
            club_speed_ms_raw=0.0,
            ball_speed_mph=b_mph,
            launch_angle_deg=l_angle,
            launch_direction_deg=l_dir,
            club_speed_mph=0.0,
            carry_yards_estimated=carry,
            ball_detect_confidence=min(1.0, high_conf_count / 10.0),
            track_frames=len(ball_positions),
            impact_confidence=0.9 if self.audio_trigger.has_sounddevice else 0.6,
            club_detected=False,
            is_approved=True,
            rejection_reason="",
            ball_positions_json=json.dumps(ball_positions),
            club_positions_json=json.dumps(club_positions),
            impact_frame=impact_frame_idx
        )
        
        # Quality check
        if result.track_frames < 5: result.is_approved = False; result.rejection_reason = "Track length too short"
        if result.ball_speed_mph < 10 or result.ball_speed_mph > 220: result.is_approved = False; result.rejection_reason = "Impossible ball speed"
        if result.launch_angle_deg < -5 or result.launch_angle_deg > 60: result.is_approved = False; result.rejection_reason = "Launch angle out of bounds"
        
        self.print_measurement(result)
        
        asyncio.run_coroutine_threadsafe(self.measure_queue.put(result), self.loop)

    def print_measurement(self, r: MeasureResult):
        dir_str = f"{abs(r.launch_direction_deg):.1f}° " + ("R" if r.launch_direction_deg > 0 else "L")
        conf_icon = "✓" if r.is_approved else "✗"
        
        print("  ┌─────────────────────────────────────┐")
        print("  │  MEASURE ENGINE                     │")
        print("  ├─────────────────────────────────────┤")
        print(f"  │  Ball Speed:   {r.ball_speed_mph:6.1f} mph  (raw)    │")
        print(f"  │  Launch Angle: {r.launch_angle_deg:6.1f}°    (raw)     │")
        print(f"  │  Direction:    {dir_str:6s}      (raw)     │")
        print(f"  │  Club Speed:   {r.club_speed_mph:6.1f} mph  (raw)     │")
        print(f"  │  Carry Est:    {r.carry_yards_estimated:6.1f} yds  (est)     │")
        print(f"  │  Track frames: {r.track_frames:2d}/25               │")
        print(f"  │  Confidence:   {r.ball_detect_confidence:4.2f} {conf_icon:<14}│")
        print("  └─────────────────────────────────────┘")


class MeasureSyncService:
    def __init__(self, skytrak_queue: asyncio.Queue, measure_queue: asyncio.Queue, paired_queue: asyncio.Queue):
        self.skytrak_queue = skytrak_queue
        self.measure_queue = measure_queue
        self.paired_queue = paired_queue
        
        self.recent_skytrak = []
        self.recent_measure = []

    async def run(self):
        while True:
            try:
                # Poll queues asynchronously
                if not self.measure_queue.empty():
                    meas = await self.measure_queue.get()
                    self.recent_measure.append(meas)
                    
                if not self.skytrak_queue.empty():
                    st = await self.skytrak_queue.get()
                    self.recent_skytrak.append(st)

                # Prune old data (> 10 seconds)
                now = time.time()
                self.recent_measure = [m for m in self.recent_measure if now - float(m.timestamp) < 10.0]
                self.recent_skytrak = [s for s in self.recent_skytrak if now - float(s.time_received) < 10.0 if hasattr(s, "time_received")]
                
                # Pair logic
                for m in list(self.recent_measure):
                    for idx, st in enumerate(self.recent_skytrak):
                        # Combine if within 5 seconds
                        try:
                            st_time = float(st.get("time_received", now))
                        except:
                            st_time = now
                            
                        if abs(float(m.timestamp) - st_time) < 5.0:
                            m.shot_id = st.get("shot_id", "")
                            await self.save_pair_to_db(m, st)
                            self.recent_measure.remove(m)
                            self.recent_skytrak.pop(idx)
                            break
                            
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in MeasureSyncService: {e}")

    async def save_pair_to_db(self, m: MeasureResult, st: dict):
        # Database code implementation omitted for brevity, logic sits in database.py
        import database
        import datetime
        
        st_ball = st.get("ball", {})
        
        pair = {
            "pair_id": str(uuid.uuid4()),
            "measure_id": m.measure_id,
            "shot_id": m.shot_id,
            "session_id": "session1",
            "paired_at": str(datetime.datetime.now()),
            "camera_ball_speed": m.ball_speed_mph,
            "camera_launch_angle": m.launch_angle_deg,
            "camera_direction": m.launch_direction_deg,
            "camera_club_speed": m.club_speed_mph,
            "camera_carry": m.carry_yards_estimated,
            "skytrak_ball_speed": st_ball.get("speed_mph", 0.0),
            "skytrak_launch_angle": st_ball.get("launch_angle_deg", 0.0),
            "skytrak_direction": st_ball.get("launch_direction_deg", 0.0),
            "skytrak_carry": st_ball.get("carry_yards", 0.0),
            "skytrak_total_spin": st_ball.get("total_spin_rpm", 0.0),
            "delta_ball_speed": m.ball_speed_mph - st_ball.get("speed_mph", 0.0),
            "delta_launch_angle": m.launch_angle_deg - st_ball.get("launch_angle_deg", 0.0),
            "delta_direction": m.launch_direction_deg - st_ball.get("launch_direction_deg", 0.0),
            "delta_carry": m.carry_yards_estimated - st_ball.get("carry_yards", 0.0),
            "quality_score": m.ball_detect_confidence,
            "is_training_sample": 1 if m.is_approved else 0,
            "camera_height_cm": 110.0,
            "ball_type": "real"
        }
        
        await database.save_measure_paired(pair)
        await self.paired_queue.put(pair)
        
        # Print Faculty
        print("  ┌─────────────────────────────────────┐")
        print("  │  SkyTrak Facit:                     │")
        print(f"  │  Ball Speed:   {st_ball.get('speed_mph', 0.0):6.1f} mph           │")
        print(f"  │  Δ Speed:      {pair['delta_ball_speed']:+6.1f} mph           │")
        print(f"  │  Δ Launch:     {pair['delta_launch_angle']:+6.1f}°              │")
        print(f"  │  Δ Direction:  {pair['delta_direction']:+6.1f}°              │")
        print("  └─────────────────────────────────────┘")
