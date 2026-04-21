import asyncio
import sys
import uuid
import logging
import time
import threading
import msvcrt

from tcp_server import start_gspro_server
from websocket_server import start_websocket_server
from database import init_db

try:
    from camera_engine import start_camera_engine, SwingAnalyzer
    from sync_service import start_sync_service
    HAS_CV = True
except ImportError as e:
    HAS_CV = False
    print(f"Failed to import camera dependencies: {e}. Running in SkyTrak-only mode.")

try:
    from coaching_engine import start_fastapi, SessionAnalyzer
    HAS_COACHING = True
except ImportError as e:
    HAS_COACHING = False
    print(f"Failed to import coaching engine: {e}")

async def queue_router(input_queue, ws_out_queue, sync_out_queue):
    while True:
        try:
            item = await input_queue.get()
            ws_payload, shot_id = item
            await ws_out_queue.put(item)
            await sync_out_queue.put(ws_payload)
        except asyncio.CancelledError:
            break

async def paired_shot_printer(paired_queue, shared_state):
    while True:
        try:
            record = await paired_queue.get()
            # Update inactivity timer on newly paired shot!
            shared_state["last_shot_time"] = time.time()
            shared_state["shots_today"] += 1
            shared_state["warned_5m"] = False
            
            st = record.get("skytrak", {})
            sw = record.get("swing", {})
            st_speed = st.get("speed_mph", 0)
            carry = st.get("carry_yards", 0)
            hip_rot = sw.get("features", {}).get("hip_rotation_at_impact_deg", 0)
            wrist = sw.get("features", {}).get("wrist_lag_deg", 0)
            sync_conf = record.get("sync_confidence", 0)
            qual = record.get("combined_quality", 0)
            app = record.get("is_training_approved", False)
            app_str = "✓ Training approved" if app else "✗ Rejected for training"
            
            print(f"\n ✓ SHOT PAIRED")
            print(f" ────────────────────────────────────")
            print(f"  Ball Speed:   {st_speed:.1f} mph")
            print(f"  Carry:        {carry:.1f} yds")
            print(f"  Hip rotation: {hip_rot:.1f}° at impact")
            print(f"  Wrist lag:    {wrist:.1f}°")
            print(f"  Sync conf:    {sync_conf:.2f}")
            print(f"  Quality:      {qual:.2f} {app_str}")
            print(f" ────────────────────────────────────\n")
        except asyncio.CancelledError:
            break

async def inactivity_monitor(shared_state, session_id):
    while HAS_COACHING:
        await asyncio.sleep(1)
        if not shared_state["coaching_triggered"] and shared_state["shots_today"] > 0:
            elapsed = time.time() - shared_state["last_shot_time"]
            if elapsed > 300 and not shared_state["warned_5m"]:
                print("\n[Timer] Session coaching in 5 min (press 'c' to trigger now)")
                shared_state["warned_5m"] = True
            
            if elapsed > 600:
                shared_state["coaching_triggered"] = True
                print("\n[Timer] 10 minutes inactive. Generating coaching report...")
                analyzer = SessionAnalyzer(session_id)
                asyncio.create_task(analyzer.run())

def keyboard_listener(loop, shared_state, session_id):
    while HAS_COACHING:
        if msvcrt.kbhit():
            key = msvcrt.getch()
            if key in [b'c', b'C']:
                if not shared_state["coaching_triggered"] and shared_state["shots_today"] > 0:
                    shared_state["coaching_triggered"] = True
                    print("\nManual coaching trigger activated ('c' pressed)...")
                    analyzer = SessionAnalyzer(session_id)
                    asyncio.run_coroutine_threadsafe(analyzer.run(), loop)
        time.sleep(0.1)

async def main():
    session_id = str(uuid.uuid4())
    print("Starting SkyTrak Bridge & Vision Engine...")
    print(f"Session ID: {session_id}")
    
    await init_db()
    
    shared_state = {
        "last_shot_time": time.time(),
        "shots_today": 0,
        "coaching_triggered": False,
        "warned_5m": False
    }
    
    # Core Queues
    shot_queue = asyncio.Queue()            
    ws_queue = asyncio.Queue()              
    skytrak_sync_queue = asyncio.Queue()    
    swing_queue = asyncio.Queue()           
    paired_queue = asyncio.Queue()          
    processing_queue = asyncio.Queue()      
    
    tasks = []
    
    tasks.append(asyncio.create_task(queue_router(shot_queue, ws_queue, skytrak_sync_queue)))
    tasks.append(asyncio.create_task(start_websocket_server(ws_queue)))
    tasks.append(asyncio.create_task(start_gspro_server(session_id, shot_queue)))
    tasks.append(asyncio.create_task(paired_shot_printer(paired_queue, shared_state)))
    
    if HAS_CV:
        loop = asyncio.get_running_loop()
        c0 = start_camera_engine(0, processing_queue, loop)
        c1 = start_camera_engine(1, processing_queue, loop)
        analyzer = SwingAnalyzer(processing_queue, swing_queue)
        tasks.append(asyncio.create_task(analyzer.run()))
        tasks.append(asyncio.create_task(start_sync_service(skytrak_sync_queue, swing_queue, paired_queue)))
        
    if HAS_COACHING:
        loop = asyncio.get_running_loop()
        tasks.append(asyncio.create_task(inactivity_monitor(shared_state, session_id)))
        
        kb_thread = threading.Thread(target=keyboard_listener, args=(loop, shared_state, session_id), daemon=True)
        kb_thread.start()
        
        fa_thread = threading.Thread(target=start_fastapi, daemon=True)
        fa_thread.start()
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_CV:
            c0.stop()
            c1.stop()

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
