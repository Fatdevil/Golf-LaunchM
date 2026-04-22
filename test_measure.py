import asyncio
import cv2
import numpy as np
import pytest
from models import CalibrationConfig, MeasureResult
from measure_engine import MeasureEngine, MeasureSyncService

@pytest.fixture
def engine():
    config = CalibrationConfig(
        camera_height_cm=110.0,
        camera_tilt_deg=35.0,
        camera_index=2
    )
    # create loop
    loop = asyncio.new_event_loop()
    return MeasureEngine(camera_index=2, config=config, shot_queue=asyncio.Queue(), measure_queue=asyncio.Queue(), loop=loop)

def test_calibration_geometry(engine):
    # frame 1080p
    engine._calibrate_geometry(1080, 1920)
    assert engine.config.pixels_per_mm > 0.0
    assert engine.config.ground_plane_y == int(1080 * 0.8)

def test_ball_detection_synthetic(engine):
    # Synthetic frame: black background, white ball at (500, 500)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.circle(frame, (500, 500), 10, (255, 255, 255), -1)
    
    # Bounding box covering the circle
    roi = (450, 450, 200, 200)
    ball = engine.detect_ball_classical(frame, roi)
    
    assert ball is not None
    bx, by, conf, radius = ball
    assert abs(bx - 500) <= 2
    assert abs(by - 500) <= 2
    assert conf > 0.6

@pytest.mark.asyncio
async def test_measure_sync_pairing():
    # Setup queues
    sk_q = asyncio.Queue()
    m_q = asyncio.Queue()
    p_q = asyncio.Queue()
    
    sync = MeasureSyncService(skytrak_queue=sk_q, measure_queue=m_q, paired_queue=p_q)
    
    import time
    now = time.time()
    
    m_res = MeasureResult(
        measure_id="m1", shot_id="", timestamp=str(now),
        ball_speed_ms_raw=70.0, launch_angle_deg_raw=10.0, launch_direction_deg_raw=0.0,
        club_speed_ms_raw=0.0, ball_speed_mph=156.0, launch_angle_deg=10.0,
        launch_direction_deg=0.0, club_speed_mph=0.0, carry_yards_estimated=250.0,
        ball_detect_confidence=0.9, track_frames=10, impact_confidence=0.9,
        club_detected=False, is_approved=True, rejection_reason="",
        ball_positions_json="[]", club_positions_json="[]", impact_frame=5
    )
    
    st_mock = {
        "shot_id": "st1",
        "time_received": str(now + 1.0),
        "ball": {
            "speed_mph": 158.0,
            "launch_angle_deg": 10.5,
            "launch_direction_deg": -1.0,
            "carry_yards": 260.0
        }
    }
    
    # Preload queues
    await m_q.put(m_res)
    await sk_q.put(st_mock)
    
    # Run sync for one cycle
    task = asyncio.create_task(sync.run())
    await asyncio.sleep(0.5)
    
    # Verify paired output
    pair = await p_q.get()
    assert pair["measure_id"] == "m1"
    assert pair["shot_id"] == "st1"
    
    assert pair["delta_ball_speed"] == -2.0  # 156.0 - 158.0
    task.cancel()

if __name__ == "__main__":
    import sys
    pytest.main([__file__])
