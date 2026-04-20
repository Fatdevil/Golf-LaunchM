# SkyTrak Bridge

Intercepts SkyTrak launch monitor data (mocking the GSPro TCP protocol) and broadcasts it to WebSocket clients (like an iPhone app).

## Requirements
- Python 3.11+
- Asyncio

## Startup Instructions

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the bridge application:
   ```bash
   python main.py
   ```
3. Start the SkyTrak app and connect to GSPro
4. Connect iPhone to `ws://[PC_IP]:8765`

All shots are automatically saved to `./data/shots.db` via SQLite.
