import asyncio
import json
import websockets

shots = [
    {
        "Speed": 158.2, "VLA": 10.8, "HLA": -0.8,
        "TotalSpin": 2680, "BackSpin": 2580, "SideSpin": -230,
        "SpinAxis": -5.1, "CarryDistance": 268.3
    },
    {
        "Speed": 120.5, "VLA": 16.2, "HLA": 1.2,
        "TotalSpin": 6200, "BackSpin": 6100, "SideSpin": 350,
        "SpinAxis": 3.2, "CarryDistance": 168.7
    },
    {
        "Speed": 155.0, "VLA": 11.5, "HLA": 3.8,
        "TotalSpin": 3100, "BackSpin": 2800, "SideSpin": 980,
        "SpinAxis": 19.2, "CarryDistance": 248.0
    },
    {
        "Speed": 95.0, "VLA": 26.5, "HLA": 0.2,
        "TotalSpin": 9200, "BackSpin": 9100, "SideSpin": 80,
        "SpinAxis": 0.5, "CarryDistance": 118.5
    },
    {
        "Speed": 162.0, "VLA": 7.2, "HLA": -1.5,
        "TotalSpin": 3800, "BackSpin": 3600, "SideSpin": -520,
        "SpinAxis": -8.1, "CarryDistance": 255.0
    }
]

def make_heartbeat():
    return {
        "DeviceID": "SkyTrak",
        "Units": "Yards",
        "ShotNumber": 0,
        "APIversion": "1",
        "BallData": {},
        "ClubData": {},
        "ShotDataOptions": {
            "ContainsBallData": False,
            "ContainsClubData": False,
            "LaunchMonitorIsReady": True,
            "LaunchMonitorBallDetected": False,
            "IsHeartBeat": False
        }
    }

def make_shot(shot_number, ball_data):
    return {
        "DeviceID": "SkyTrak",
        "Units": "Yards",
        "ShotNumber": shot_number,
        "APIversion": "1",
        "BallData": ball_data,
        "ClubData": {},
        "ShotDataOptions": {
            "ContainsBallData": True,
            "ContainsClubData": False,
            "LaunchMonitorIsReady": True,
            "LaunchMonitorBallDetected": True,
            "IsHeartBeat": False
        }
    }

ws_received_count = 0

async def websocket_listener():
    global ws_received_count
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as websocket:
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                if data.get("event") == "shot":
                    ws_received_count += 1
                    shot_num = data.get("shot_number")
                    ball = data.get("ball", {})
                    speed = ball.get("speed_mph")
                    angle = ball.get("launch_angle_deg")
                    carry = ball.get("carry_yards")
                    print(f"📡 WebSocket received: Shot {shot_num} | {speed} mph | {angle}° | {carry} yds")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")

async def tcp_sender():
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', 921)
    except ConnectionRefusedError:
        print("❌ Could not connect to GSPro server on 127.0.0.1:921. Is main.py running?")
        return 0
        
    ack_count = 0
    
    for i, ball_data in enumerate(shots, 1):
        if i > 1:
            await asyncio.sleep(2) # Paired with 1s wait below = 3 seconds between shots
            
        # Send heartbeat
        hb = make_heartbeat()
        writer.write(json.dumps(hb).encode('utf-8'))
        await writer.drain()
        
        # Read the heartbeat ack
        try:
            await asyncio.wait_for(reader.read(1024), timeout=1.0)
        except asyncio.TimeoutError:
            pass
            
        await asyncio.sleep(1)
        
        # Send actual shot JSON
        shot_payload = make_shot(i, ball_data)
        writer.write(json.dumps(shot_payload).encode('utf-8'))
        await writer.drain()
        
        # Read the shot ack
        try:
            response = await asyncio.wait_for(reader.read(1024), timeout=1.0)
            if b'"Code": 200' in response:
                print(f"✓ Shot {i} acknowledged by bridge")
                ack_count += 1
        except asyncio.TimeoutError:
            print(f"❌ Shot {i} response timed out")

    writer.close()
    await writer.wait_closed()
    return ack_count

async def main():
    # Start background WebSocket listener
    ws_task = asyncio.create_task(websocket_listener())
    
    # Allow WS time to connect
    await asyncio.sleep(0.5)
    
    # Run TCP transmission
    ack_count = await tcp_sender()
    
    # Allow WS time to receive the final background broadcast
    await asyncio.sleep(0.5)
    ws_task.cancel()
    
    print("\n✅ All 5 shots sent and acknowledged" if ack_count == 5 else f"\n⚠️ Sent {ack_count}/5 shots correctly")
    print(f"✅ WebSocket received {ws_received_count}/5 shots")

import sys
if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    asyncio.run(main())
