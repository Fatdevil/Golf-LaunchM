import asyncio
import uuid
from tcp_server import start_gspro_server
from websocket_server import start_websocket_server
from database import init_db

async def main():
    session_id = str(uuid.uuid4())
    print("Starting SkyTrak Bridge...")
    print(f"Session ID: {session_id}")
    
    # Init DB
    await init_db()
    
    shot_queue = asyncio.Queue()
    
    # Start tasks
    ws_task = asyncio.create_task(start_websocket_server(shot_queue))
    tcp_task = asyncio.create_task(start_gspro_server(session_id, shot_queue))
    
    try:
        await asyncio.gather(ws_task, tcp_task)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
