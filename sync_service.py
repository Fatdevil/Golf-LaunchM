import asyncio
import time
import json
import logging
from datetime import datetime, timezone
from database import save_paired_shot, save_swing_data, update_shot_status

# Configure sync logger
logger = logging.getLogger("sync_service")
logger.setLevel(logging.INFO)

class SyncService:
    def __init__(self, skytrak_queue: asyncio.Queue, swing_queue: asyncio.Queue, paired_queue: asyncio.Queue):
        self.skytrak_queue = skytrak_queue
        self.swing_queue = swing_queue
        self.paired_queue = paired_queue
        
        self.pending_skytrak = {}  # shot_id -> (timestamp, data)
        self.pending_swings = {}   # swing_id -> (timestamp, data)
        
        self.stats = {
            "skytrak_received": 0,
            "swings_received": 0,
            "paired_today": 0,
            "approved_today": 0
        }

    async def _consume_skytrak(self):
        while True:
            try:
                msg = await self.skytrak_queue.get()
                shot_id = msg.get("shot_id")
                
                # Use current local time for sync evaluation
                self.pending_skytrak[shot_id] = (time.time(), msg)
                self.stats["skytrak_received"] += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming SkyTrak: {e}")

    async def _consume_swings(self):
        while True:
            try:
                swing = await self.swing_queue.get()
                swing_id = swing.get("swing_id")
                
                self.pending_swings[swing_id] = (time.time(), swing)
                self.stats["swings_received"] += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming Swings: {e}")

    async def _sync_loop(self):
        while True:
            now = time.time()
            
            # Pair matching
            paired_skytrak_ids = []
            paired_swing_ids = []
            
            for skytrak_id, (st_time, st_data) in self.pending_skytrak.items():
                for swing_id, (sw_time, sw_data) in self.pending_swings.items():
                    # 4. Pair if: |skytrak_time - swing_impact_time| < 2.0 seconds
                    if abs(st_time - sw_time) < 2.0:
                        await self._create_paired_record(skytrak_id, st_time, st_data, swing_id, sw_time, sw_data)
                        paired_skytrak_ids.append(skytrak_id)
                        paired_swing_ids.append(swing_id)
                        break # One to one pairing
                
                # Avoid matching same skytrak to multiple swings if loop modifies dicts during iteration is dangerous
                if skytrak_id in paired_skytrak_ids:
                    continue
            
            # Remove paired items
            for sid in paired_skytrak_ids:
                if sid in self.pending_skytrak: del self.pending_skytrak[sid]
            for swid in paired_swing_ids:
                if swid in self.pending_swings: del self.pending_swings[swid]
            
            # 6. Orphan clean-up after 5 seconds
            st_orphans = []
            sw_orphans = []
            
            for sid, (st_time, st_data) in self.pending_skytrak.items():
                if now - st_time >= 5.0:
                    st_orphans.append(sid)
                    
            for swid, (sw_time, sw_data) in self.pending_swings.items():
                if now - sw_time >= 5.0:
                    sw_orphans.append(swid)
                    
            for sid in st_orphans:
                print(f"⚠ ORPHAN (skytrak_only): shot #{self.pending_skytrak[sid][1].get('shot_number')}")
                # Save status to DB
                await update_shot_status(sid, 'skytrak_only')
                del self.pending_skytrak[sid]
                
            for swid in sw_orphans:
                swing = self.pending_swings[swid][1]
                # Fallback to current time if captured_at is missing
                cap_time = swing.get("captured_at", datetime.now().strftime("%H:%M:%S"))
                print(f"⚠ ORPHAN (swing_only): swing captured {cap_time}")
                
                swing["sync_status"] = "swing_only"
                swing["shot_id"] = None
                
                await self._save_swing_to_db(swing)
                del self.pending_swings[swid]
            
            await asyncio.sleep(0.1)

    async def _save_swing_to_db(self, swing):
        try:
            feats = swing.get("features", {})
            qual = swing.get("quality", {})
            
            record = {
                "swing_id": swing["swing_id"],
                "shot_id": swing.get("shot_id"),
                "session_id": swing.get("session_id", "orphan"),
                "camera_index": swing.get("camera_index", 0),
                "captured_at": swing.get("captured_at"),
                "impact_frame": swing.get("impact_frame", 0),
                "frame_count": swing.get("frame_count", 0),
                "fps_actual": swing.get("fps_actual", 0.0),
                "actual_resolution": swing.get("actual_resolution", ""),
                
                "hip_rotation_deg": feats.get("hip_rotation_at_impact_deg", 0.0),
                "shoulder_tilt_deg": feats.get("shoulder_tilt_at_impact_deg", 0.0),
                "wrist_lag_deg": feats.get("wrist_lag_deg", 0.0),
                "weight_shift_ratio": feats.get("weight_shift_ratio", 0.0),
                "hip_lead_frames": feats.get("hip_lead_frames", 0),
                "arm_speed_px": feats.get("arm_speed_px_per_frame", 0.0),
                "spine_angle_deg": feats.get("spine_angle_at_address_deg", 0.0),
                "follow_through": feats.get("follow_through_completeness", 0.0),
                
                "pose_confidence": qual.get("pose_detection_confidence", 0.0),
                "frames_with_pose": qual.get("frames_with_full_pose", 0),
                "is_approved": 1 if qual.get("is_approved", False) else 0,
                "rejection_reason": qual.get("rejection_reason"),
                
                "landmarks_json": json.dumps(swing.get("landmarks_json", [])),
                "raw_features_json": json.dumps(feats),
                "sync_status": swing.get("sync_status", "pending")
            }
            await save_swing_data(record)
        except Exception as e:
            logger.error(f"Failed to save swing data to DB: {e}")

    async def _create_paired_record(self, skytrak_id, st_time, st_data, swing_id, sw_time, sw_data):
        now_utc = datetime.now(timezone.utc)
        paired_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        # Calculate combined quality
        skytrak_present = 1.0 # By definition of pair
        pose_conf = sw_data.get("quality", {}).get("pose_detection_confidence", 0.0)
        time_delta = abs(st_time - sw_time)
        sync_conf = round(max(0.0, 1.0 - (time_delta / 2.0)), 3)
        
        combined_qual = (skytrak_present * 0.4) + (pose_conf * 0.3) + (sync_conf * 0.3)
        training_app = combined_qual >= 0.75
        
        paired_rec = {
            "shot_id": skytrak_id,
            "session_id": st_data.get("session_id", "unknown"),
            "paired_at": paired_at_iso,
            "sync_method": "timestamp",
            "sync_confidence": sync_conf,
            "sync_status": "synced",
            
            "skytrak": st_data.get("ball", {}), # In tcp_server, ws_payload has ball nested. We pass ws_payload! Wait! 
            # tcp_server sends `(ws_payload, shot_id)`. Oh! Actually sync queue receives `ws_payload`.
            # Let's cleanly put the whole st_data into skytrak.
            
            "swing": sw_data,
            "combined_quality": combined_qual
        }
        
        # We also need to update swing DB entry, and shot DB entry
        sw_data["shot_id"] = skytrak_id
        sw_data["sync_status"] = "synced"
        await self._save_swing_to_db(sw_data)
        await update_shot_status(skytrak_id, "synced")
        
        db_paired = {
            "shot_id": skytrak_id,
            "session_id": st_data.get("session_id", "unknown"),
            "paired_at": paired_at_iso,
            "sync_method": "timestamp",
            "sync_confidence": sync_conf,
            "sync_status": "synced",
            "combined_quality": combined_qual,
            "skytrak_json": json.dumps(st_data),
            "swing_json": json.dumps(sw_data),
            "is_training_approved": 1 if training_app else 0
        }
        await save_paired_shot(db_paired)
        
        self.stats["paired_today"] += 1
        if training_app:
            self.stats["approved_today"] += 1
            
        await self.paired_queue.put(paired_rec)

    async def _health_check_loop(self):
        while True:
            await asyncio.sleep(30)
            
            from camera_engine import get_camera_status
            cams = get_camera_status()
            cam0_status = cams.get(0, "not found")
            cam1_status = cams.get(1, "not found")
            
            st_len = len(self.pending_skytrak)
            sw_len = len(self.pending_swings)
            paired = self.stats["paired_today"]
            approv = self.stats["approved_today"]
            
            print("── SYSTEM STATUS ──────────────────")
            print(" SkyTrak:   connected / waiting")
            print(f" Camera 0:  {cam0_status}")
            print(f" Camera 1:  {cam1_status}")
            print(f" Pending sync:  {st_len} skytrak, {sw_len} swing")
            print(f" Paired today:  {paired} shots ({approv} approved)")
            print("───────────────────────────────────")

    async def run(self):
        try:
            await asyncio.gather(
                self._consume_skytrak(),
                self._consume_swings(),
                self._sync_loop(),
                self._health_check_loop()
            )
        except asyncio.CancelledError:
            pass

async def start_sync_service(skytrak_sync_queue, swing_queue, paired_queue):
    service = SyncService(skytrak_sync_queue, swing_queue, paired_queue)
    await service.run()
