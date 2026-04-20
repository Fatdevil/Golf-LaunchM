import asyncio
import json
import uuid
import sys
from datetime import datetime, timezone
from models import ShotData
from database import save_shot

async def handle_client(reader, writer, session_id, shot_queue):
    peername = writer.get_extra_info('peername')
    if peername:
        print(f"[TCP] SkyTrak connected from {peername}", file=sys.stderr)
    else:
        print(f"[TCP] SkyTrak connected", file=sys.stderr)
        
    decoder = json.JSONDecoder()
    buffer = ""
    
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
                
            buffer += data.decode('utf-8')
            
            while buffer:
                buffer = buffer.lstrip()
                if not buffer:
                    break
                    
                try:
                    payload, idx = decoder.raw_decode(buffer)
                    buffer = buffer[idx:]
                    
                    shot_data = ShotData.from_dict(payload)
                    options = shot_data.ShotDataOptions
                    
                    is_heartbeat = options.get("IsHeartBeat", False)
                    
                    if not is_heartbeat:
                        # Process shot data
                        if shot_data.BallData and shot_data.ShotNumber > 0:
                            shot_id = str(uuid.uuid4())
                            now_utc = datetime.now(timezone.utc)
                            # Custom timestamp format requested: 2026-04-20T08:33:00.000Z
                            received_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                            received_at_display = now_utc.astimezone().strftime("%H:%M:%S")
                            
                            b_speed = float(shot_data.BallData.get("Speed", 0.0))
                            l_angle = float(shot_data.BallData.get("VLA", 0.0))
                            dir_angle = float(shot_data.BallData.get("HLA", 0.0))
                            dir_str = "R" if dir_angle > 0 else "L" if dir_angle < 0 else ""
                            abs_dir = abs(dir_angle)
                            
                            t_spin = float(shot_data.BallData.get("TotalSpin", 0.0))
                            b_spin = float(shot_data.BallData.get("BackSpin", 0.0))
                            s_spin = float(shot_data.BallData.get("SideSpin", 0.0))
                            s_axis = float(shot_data.BallData.get("SpinAxis", 0.0))
                            carry = float(shot_data.BallData.get("CarryDistance", 0.0))
                            
                            club_speed = float(shot_data.ClubData.get("Speed", 0.0)) if shot_data.ClubData else 0.0
                            club_avail = bool(options.get("ContainsClubData", False))
                            
                            print(f"════════════════════════════════════")
                            print(f" SHOT #{shot_data.ShotNumber} received at {received_at_display}")
                            print(f"────────────────────────────────────")
                            print(f" Ball Speed:      {b_speed:.1f} mph")
                            print(f" Launch Angle:     {l_angle:.1f}°")
                            if abs_dir == 0.0:
                                print(f" Direction:         0.0°")
                            else:
                                print(f" Direction:         {abs_dir:.1f}° {dir_str}")
                            print(f" Total Spin:     {t_spin:.0f} rpm")
                            print(f" Back Spin:      {b_spin:.0f} rpm")
                            print(f" Side Spin:      {s_spin:.0f} rpm")
                            print(f" Carry:          {carry:.1f} yds")
                            print(f"────────────────────────────────────")
                            
                            db_record = {
                                "shot_id": shot_id,
                                "shot_number": shot_data.ShotNumber,
                                "received_at": received_at_iso,
                                "session_id": session_id,
                                "ball_speed": b_speed,
                                "launch_angle": l_angle,
                                "launch_direction": dir_angle,
                                "total_spin": t_spin,
                                "back_spin": b_spin,
                                "side_spin": s_spin,
                                "spin_axis": s_axis,
                                "carry_distance": carry,
                                "club_speed": club_speed,
                                "club_data_available": 1 if club_avail else 0,
                                "raw_json": json.dumps(payload)
                            }
                            
                            try:
                                await save_shot(db_record)
                            except Exception as e:
                                print(f"[DB Error] Failed to save shot: {e}", file=sys.stderr)
                                
                            ws_payload = {
                                "event": "shot",
                                "shot_id": shot_id,
                                "timestamp": received_at_iso,
                                "shot_number": shot_data.ShotNumber,
                                "ball": {
                                    "speed_mph": b_speed,
                                    "launch_angle_deg": l_angle,
                                    "launch_direction_deg": dir_angle,
                                    "total_spin_rpm": t_spin,
                                    "back_spin_rpm": b_spin,
                                    "side_spin_rpm": s_spin,
                                    "spin_axis_deg": s_axis,
                                    "carry_yards": carry
                                },
                                "club": {
                                    "speed_mph": club_speed,
                                    "data_available": club_avail
                                },
                                "source": "skytrak_original"
                            }
                            
                            await shot_queue.put((ws_payload, shot_id))
                            
                    # Always ack after processing payload
                    response = {
                        "Code": 200,
                        "Message": "Shot received OK"
                    }
                    writer.write(json.dumps(response).encode('utf-8'))
                    await writer.drain()
                        
                except json.JSONDecodeError:
                    break
                    
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[TCP Error] Connection error: {e}", file=sys.stderr)
    finally:
        print(f"[TCP] SkyTrak disconnected.", file=sys.stderr)
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

async def start_gspro_server(session_id, shot_queue):
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, session_id, shot_queue),
        '127.0.0.1', 921
    )
    
    addr = server.sockets[0].getsockname()
    print(f"GSPro TCP Emulator listening on {addr}")
    
    async with server:
        await server.serve_forever()
