import asyncio
import websockets
import json

connected_clients = set()

async def client_handler(websocket):
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    except Exception:
        pass
    finally:
        connected_clients.remove(websocket)

async def broadcast_shots(shot_queue):
    while True:
        ws_payload, shot_id = await shot_queue.get()
        print(f" Saved: shot_id {shot_id}")
        print(f" WebSocket clients: {len(connected_clients)} connected")
        print(f"════════════════════════════════════")
        
        if connected_clients:
            msg = json.dumps(ws_payload)
            await asyncio.gather(
                *(client.send(msg) for client in connected_clients),
                return_exceptions=True
            )
            
        shot_queue.task_done()

async def start_websocket_server(shot_queue):
    print("WebSocket Server listening on 0.0.0.0:8765")
    
    server = await websockets.serve(client_handler, "0.0.0.0", 8765)
    
    # Run the broadcast task
    await broadcast_shots(shot_queue)
    
    await server.wait_closed()
