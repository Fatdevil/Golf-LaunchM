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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS swing_data (
                swing_id TEXT PRIMARY KEY,
                shot_id TEXT,
                session_id TEXT,
                camera_index INTEGER,
                captured_at TEXT,
                impact_frame INTEGER,
                frame_count INTEGER,
                fps_actual REAL,
                actual_resolution TEXT,
                hip_rotation_deg REAL,
                shoulder_tilt_deg REAL,
                wrist_lag_deg REAL,
                weight_shift_ratio REAL,
                hip_lead_frames INTEGER,
                arm_speed_px REAL,
                spine_angle_deg REAL,
                follow_through REAL,
                pose_confidence REAL,
                frames_with_pose INTEGER,
                is_approved INTEGER,
                rejection_reason TEXT,
                landmarks_json TEXT,
                raw_features_json TEXT,
                sync_status TEXT DEFAULT 'pending'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paired_shots (
                shot_id TEXT PRIMARY KEY,
                session_id TEXT,
                paired_at TEXT,
                sync_method TEXT,
                sync_confidence REAL,
                sync_status TEXT,
                combined_quality REAL,
                skytrak_json TEXT,
                swing_json TEXT,
                is_training_approved INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS coaching_reports (
                report_id TEXT PRIMARY KEY,
                session_id TEXT,
                created_at TEXT,
                shot_count INTEGER,
                approved_count INTEGER,
                model_version TEXT,
                prompt_tokens INTEGER,
                response_tokens INTEGER,
                session_summary TEXT,
                primary_finding TEXT,
                coaching_points_json TEXT,
                next_session_focus TEXT,
                encouraging_note TEXT,
                raw_response TEXT,
                status TEXT
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

async def update_shot_status(shot_id: str, new_status: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE shots SET sync_status = ? WHERE shot_id = ?",
            (new_status, shot_id)
        )
        await db.commit()

async def save_swing_data(swing_record: dict):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO swing_data (
                swing_id, shot_id, session_id, camera_index, captured_at,
                impact_frame, frame_count, fps_actual, actual_resolution,
                hip_rotation_deg, shoulder_tilt_deg, wrist_lag_deg, weight_shift_ratio,
                hip_lead_frames, arm_speed_px, spine_angle_deg, follow_through,
                pose_confidence, frames_with_pose, is_approved, rejection_reason,
                landmarks_json, raw_features_json, sync_status
            ) VALUES (
                :swing_id, :shot_id, :session_id, :camera_index, :captured_at,
                :impact_frame, :frame_count, :fps_actual, :actual_resolution,
                :hip_rotation_deg, :shoulder_tilt_deg, :wrist_lag_deg, :weight_shift_ratio,
                :hip_lead_frames, :arm_speed_px, :spine_angle_deg, :follow_through,
                :pose_confidence, :frames_with_pose, :is_approved, :rejection_reason,
                :landmarks_json, :raw_features_json, :sync_status
            )
        """, swing_record)
        await db.commit()

async def save_paired_shot(paired_record: dict):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO paired_shots (
                shot_id, session_id, paired_at, sync_method, sync_confidence,
                sync_status, combined_quality, skytrak_json, swing_json, is_training_approved
            ) VALUES (
                :shot_id, :session_id, :paired_at, :sync_method, :sync_confidence,
                :sync_status, :combined_quality, :skytrak_json, :swing_json, :is_training_approved
            )
        """, paired_record)
        await db.commit()

async def get_session_shots(session_id: str):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM paired_shots 
            WHERE session_id = ? AND is_training_approved = 1
            ORDER BY paired_at ASC
        """, (session_id,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_history_stats(current_session_id: str):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT session_id, 
                   AVG(combined_quality) as avg_quality,
                   COUNT(*) as shot_count
            FROM paired_shots
            WHERE session_id != ?
            GROUP BY session_id
            ORDER BY MAX(paired_at) DESC
            LIMIT 3
        """, (current_session_id,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def save_coaching_report(report: dict):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO coaching_reports (
                report_id, session_id, created_at, shot_count, approved_count,
                model_version, prompt_tokens, response_tokens, session_summary,
                primary_finding, coaching_points_json, next_session_focus,
                encouraging_note, raw_response, status
            ) VALUES (
                :report_id, :session_id, :created_at, :shot_count, :approved_count,
                :model_version, :prompt_tokens, :response_tokens, :session_summary,
                :primary_finding, :coaching_points_json, :next_session_focus,
                :encouraging_note, :raw_response, :status
            )
        """, report)
        await db.commit()

async def get_latest_coaching_report(session_id: str):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM coaching_reports 
            WHERE session_id = ? AND status = 'success'
            ORDER BY created_at DESC LIMIT 1
        """, (session_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_coaching_history(limit: int = 10):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM coaching_reports
            WHERE status = 'success'
            ORDER BY created_at DESC LIMIT ?
        """, (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
