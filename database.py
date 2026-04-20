import aiosqlite
import os

DB_DIR = "./data"
DB_FILE = os.path.join(DB_DIR, "shots.db")

async def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shots (
                shot_id TEXT PRIMARY KEY,
                shot_number INTEGER,
                received_at TEXT,
                session_id TEXT,
                ball_speed REAL,
                launch_angle REAL,
                launch_direction REAL,
                total_spin REAL,
                back_spin REAL,
                side_spin REAL,
                spin_axis REAL,
                carry_distance REAL,
                club_speed REAL,
                club_data_available INTEGER,
                raw_json TEXT,
                sync_status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

async def save_shot(db_record):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO shots (
                shot_id, shot_number, received_at, session_id,
                ball_speed, launch_angle, launch_direction, total_spin,
                back_spin, side_spin, spin_axis, carry_distance,
                club_speed, club_data_available, raw_json, sync_status
            ) VALUES (
                :shot_id, :shot_number, :received_at, :session_id,
                :ball_speed, :launch_angle, :launch_direction, :total_spin,
                :back_spin, :side_spin, :spin_axis, :carry_distance,
                :club_speed, :club_data_available, :raw_json, 'pending'
            )
        """, db_record)
        await db.commit()
