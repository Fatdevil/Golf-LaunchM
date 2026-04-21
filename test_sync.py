import asyncio
import time
import json
import uuid
from sync_service import SyncService
from database import init_db

async def run_tests():
    await init_db()
    
    st_q = asyncio.Queue()
    sw_q = asyncio.Queue()
    p_q = asyncio.Queue()
    
    svc = SyncService(st_q, sw_q, p_q)
    
    # Start service consumers
    sync_task = asyncio.create_task(svc._sync_loop())
    st_consume = asyncio.create_task(svc._consume_skytrak())
    sw_consume = asyncio.create_task(svc._consume_swings())
    
    print("\n--- TEST 1: PERFECT PAIRING ---")
    shot_id = str(uuid.uuid4())
    swing_id = str(uuid.uuid4())
    
    st_mock = {"shot_id": shot_id, "shot_number": 1, "ball": {"speed_mph": 160.0}}
    sw_mock = {
        "swing_id": swing_id, 
        "impact_frame": 100, 
        "features": {"hip_rotation_at_impact_deg": 45.0},
        "quality": {"pose_detection_confidence": 0.9}
    }
    
    await st_q.put(st_mock)
    await sw_q.put(sw_mock)
    
    # Give sync loop time to process
    await asyncio.sleep(0.5)
    
    assert p_q.qsize() == 1, "Failed to pair perfect match"
    paired = await p_q.get()
    print("Test 1 Passed: Perfect match established")
    assert paired["combined_quality"] >= 0.67 # (1.0*0.4 + 0.9*0.3)
    
    print("\n--- TEST 2: SKYLARK BEFORE SWING (WITHIN 2s) ---")
    shot_id2 = str(uuid.uuid4())
    swing_id2 = str(uuid.uuid4())
    
    await st_q.put({"shot_id": shot_id2, "shot_number": 2, "ball": {}})
    await asyncio.sleep(1.0)
    await sw_q.put({"swing_id": swing_id2, "quality": {"pose_detection_confidence": 0.5}})
    
    await asyncio.sleep(0.5)
    assert p_q.qsize() == 1, "Failed to pair with 1s gap"
    await p_q.get()
    print("Test 2 Passed: 1s gap paired correctly")
    
    print("\n--- TEST 3: ORPHAN (SWING ONLY) ---")
    await sw_q.put({"swing_id": str(uuid.uuid4()), "quality": {"pose_detection_confidence": 0.8}})
    await asyncio.sleep(6.0) # Wait 6 seconds for orphan timeout
    assert len(svc.pending_swings) == 0, "Failed to clear orphan swing"
    print("Test 3 Passed: Orphan swing timed out and cleared after 5+ seconds")
    
    print("\n--- TEST 4: ORPHAN (SKYTRAK ONLY) ---")
    await st_q.put({"shot_id": str(uuid.uuid4()), "shot_number": 14, "ball": {}})
    await asyncio.sleep(6.0) # Wait 6 seconds
    assert len(svc.pending_skytrak) == 0, "Failed to clear orphan skytrak shot"
    print("Test 4 Passed: Orphan SkyTrak shot timed out and cleared after 5+ seconds\n")
    
    sync_task.cancel()
    st_consume.cancel()
    sw_consume.cancel()
    
if __name__ == "__main__":
    import sys
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    asyncio.run(run_tests())
