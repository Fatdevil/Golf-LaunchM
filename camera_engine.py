import cv2
import mediapipe as mp
import numpy as np
import threading
import collections
import time
import asyncio
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger("camera_engine")
logger.setLevel(logging.INFO)

# Global status dict for health checks
_camera_status = {}

def get_camera_status():
    return _camera_status

class CameraCaptureThread(threading.Thread):
    def __init__(self, camera_index, processing_queue, loop):
        super().__init__()
        self.camera_index = camera_index
        self.processing_queue = processing_queue
        self.loop = loop
        self.running = threading.Event()
        self.running.set()
        self.cap = None

        self.actual_w = 0
        self.actual_h = 0
        self.actual_fps = 0.0

        _camera_status[self.camera_index] = "initializing"

    def _setup_camera(self):
        # Open camera
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_index) # fallback backend
            
        if not self.cap.isOpened():
            _camera_status[self.camera_index] = "not found"
            logger.warning(f"Camera {self.camera_index} not found.")
            return False

        # Try resolutions/fps
        modes = [
            (1920, 1080, 60),
            (1920, 1080, 30),
            (1280, 720, 60),
            (1280, 720, 30)
        ]
        
        selected = None
        for w, h, target_fps in modes:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_FPS, target_fps)
            
            # Read a test frame to ensure it applied
            ret, frame = self.cap.read()
            if ret:
                aw = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                ah = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                afps = self.cap.get(cv2.CAP_PROP_FPS)
                if aw == w and ah == h:
                    selected = (int(aw), int(ah), afps if afps > 0 else target_fps)
                    break
                    
        if not selected:
            aw = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            ah = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            afps = self.cap.get(cv2.CAP_PROP_FPS)
            selected = (int(aw), int(ah), afps if afps > 0 else 30.0)

        self.actual_w, self.actual_h, self.actual_fps = selected
        status_str = f"{self.actual_w}x{self.actual_h}@{self.actual_fps}fps"
        _camera_status[self.camera_index] = status_str
        logger.info(f"Camera {self.camera_index} configured: {status_str}")
        return True

    def run(self):
        if not self._setup_camera():
            return

        buffer = collections.deque(maxlen=180)
        motion_threshold = 500000 # Configurable energy threshold
        
        prev_roi_gray = None
        in_swing = False
        empty_frames_count = 0
        
        swing_clip = []
        start_frame_idx = 0
        frame_counter = 0

        # ROI for motion detection: center lower half (approx torso/hips)
        roi_x1 = int(self.actual_w * 0.3)
        roi_x2 = int(self.actual_w * 0.7)
        roi_y1 = int(self.actual_h * 0.4)
        roi_y2 = int(self.actual_h * 0.9)

        while self.running.is_set():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            frame_counter += 1
            buffer.append(frame)

            # Extract ROI
            roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_roi_gray is None:
                prev_roi_gray = gray
                continue

            # Compute absolute difference
            frame_delta = cv2.absdiff(prev_roi_gray, gray)
            prev_roi_gray = gray
            
            energy = np.sum(frame_delta)
            
            if energy > motion_threshold:
                if not in_swing:
                    in_swing = True
                    start_frame_idx = frame_counter
                    # Prepend the last 30 frames from buffer
                    lookback = min(30, len(buffer))
                    swing_clip = list(buffer)[-lookback:]
                else:
                    swing_clip.append(frame)
                empty_frames_count = 0
            else:
                if in_swing:
                    swing_clip.append(frame)
                    empty_frames_count += 1
                    if empty_frames_count > 30: # Swing ended
                        in_swing = False
                        # Package and send to processing queue
                        if len(swing_clip) > 40: # Min duration constraint
                            clip_data = {
                                "camera_index": self.camera_index,
                                "fps_actual": self.actual_fps,
                                "actual_resolution": f"{self.actual_w}x{self.actual_h}",
                                "frames": swing_clip.copy(),
                                "start_frame_idx": start_frame_idx,
                                "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                            }
                            # Send to async queue nicely
                            asyncio.run_coroutine_threadsafe(
                                self.processing_queue.put(clip_data),
                                self.loop
                            )
                        swing_clip = []
                        empty_frames_count = 0

        self.cap.release()

    def stop(self):
        self.running.clear()


class SwingAnalyzer:
    def __init__(self, processing_queue, swing_queue):
        self.processing_queue = processing_queue
        self.swing_queue = swing_queue
        
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

    async def run(self):
        while True:
            try:
                clip_data = await self.processing_queue.get()
                await self.process_clip(clip_data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MediaPipe error: {e}")

    async def process_clip(self, clip_data):
        frames = clip_data["frames"]
        camera_idx = clip_data["camera_index"]
        
        landmarks_seq = []
        confidences = []
        
        # 1. Extract Landmarks
        for f in frames:
            rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            res = self.pose.process(rgb)
            
            if res.pose_landmarks:
                frame_lms = []
                vis_sum = 0
                for lm in res.pose_landmarks.landmark:
                    frame_lms.append({
                        "x": lm.x, "y": lm.y, "z": lm.z, "v": lm.visibility
                    })
                    vis_sum += lm.visibility
                landmarks_seq.append(frame_lms)
                confidences.append(vis_sum / 33.0)
            else:
                landmarks_seq.append(None)
                confidences.append(0.0)
                
        # 2. Find Impact Frame & Calculate Features
        features, quality = self._extract_features(landmarks_seq, confidences)
        
        # Construct final dict
        swing_dict = {
            "swing_id": str(uuid.uuid4()),
            "camera_index": camera_idx,
            "captured_at": clip_data["captured_at"],
            "swing_start_frame": clip_data["start_frame_idx"],
            "swing_end_frame": clip_data["start_frame_idx"] + len(frames),
            "impact_frame": features.pop("impact_frame", 0),
            "frame_count": len(frames),
            "fps_actual": clip_data["fps_actual"],
            "actual_resolution": clip_data["actual_resolution"],
            "landmarks_json": landmarks_seq,
            "features": features,
            "quality": quality
        }
        
        await self.swing_queue.put(swing_dict)

    def _extract_features(self, lms_seq, confs):
        total_frames = len(lms_seq)
        if total_frames < 20 or total_frames > 200:
            return {"impact_frame": 0}, self._rej("Duration out of bounds", confs)
            
        full_pose_count = sum(1 for c in confs if c > 0.7)
        if full_pose_count / total_frames < 0.7:
            return {"impact_frame": 0}, self._rej("Not enough full poses", confs)
            
        # Find max wrist speed (Right wrist ID = 16)
        speeds = []
        for i in range(1, total_frames):
            prev = lms_seq[i-1]
            curr = lms_seq[i]
            if not prev or not curr:
                speeds.append(0)
                continue
            dx = curr[16]["x"] - prev[16]["x"]
            dy = curr[16]["y"] - prev[16]["y"]
            speeds.append(np.sqrt(dx*dx + dy*dy))
            
        if not speeds or max(speeds) < 0.05: # very arbitrary threshold
            return {"impact_frame": 0}, self._rej("No impact detected", confs)
            
        impact_frame = np.argmax(speeds) + 1
        
        # Calculate specifics
        imp_lm = lms_seq[impact_frame]
        
        hip_rot = 0.0
        sh_tilt = 0.0
        if imp_lm:
            # 23=LHip, 24=RHip
            dx = imp_lm[23]["x"] - imp_lm[24]["x"]
            dz = imp_lm[23]["z"] - imp_lm[24]["z"]
            hip_rot = np.degrees(np.arctan2(dz, dx))
            
            # 11=LSh, 12=RSh
            dy = imp_lm[11]["y"] - imp_lm[12]["y"]
            dx2 = imp_lm[11]["x"] - imp_lm[12]["x"]
            sh_tilt = np.degrees(np.arctan2(dy, dx2))
            
        arm_speed = np.mean(speeds[max(0, impact_frame-5):impact_frame]) * 1920.0 # roughly px
        
        weight_shift = 0.5
        if lms_seq[0] and imp_lm:
            shift = lms_seq[0][23]["x"] - imp_lm[23]["x"]
            weight_shift = 0.5 + shift # mocked
            
        feats = {
            "impact_frame": int(impact_frame),
            "hip_rotation_at_impact_deg": float(hip_rot),
            "shoulder_tilt_at_impact_deg": float(sh_tilt),
            "wrist_lag_deg": 78.0, # mocked angle
            "weight_shift_ratio": float(weight_shift),
            "hip_lead_frames": 5, # mocked
            "arm_speed_px_per_frame": float(arm_speed),
            "spine_angle_at_address_deg": 28.0, # mocked
            "follow_through_completeness": 0.9 # mocked
        }
        
        q = {
            "pose_detection_confidence": np.mean(confs),
            "frames_with_full_pose": full_pose_count,
            "is_approved": True,
            "rejection_reason": None
        }
        return feats, q

    def _rej(self, reason, confs):
        return {
            "pose_detection_confidence": float(np.mean(confs)) if confs else 0.0,
            "frames_with_full_pose": sum(1 for c in confs if c > 0.7) if confs else 0,
            "is_approved": False,
            "rejection_reason": reason
        }

def start_camera_engine(camera_index, processing_queue, loop):
    thread = CameraCaptureThread(camera_index, processing_queue, loop)
    thread.start()
    return thread
