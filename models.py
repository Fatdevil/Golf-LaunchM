from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class ShotData:
    DeviceID: str
    Units: str
    ShotNumber: int
    APIversion: str
    BallData: Dict[str, float]
    ClubData: Dict[str, float]
    ShotDataOptions: Dict[str, bool]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ShotData':
        return cls(
            DeviceID=data.get("DeviceID", "SkyTrak"),
            Units=data.get("Units", "Yards"),
            ShotNumber=data.get("ShotNumber", 0),
            APIversion=data.get("APIversion", "1"),
            BallData=data.get("BallData", {}),
            ClubData=data.get("ClubData", {}),
            ShotDataOptions=data.get("ShotDataOptions", {})
        )

@dataclass
class CalibrationConfig:
    camera_height_cm: float = 110.0
    camera_tilt_deg: float = 35.0
    ball_type: str = "real"
    units: str = "yards"
    camera_index: int = 2
    pixels_per_mm: float = 0.0
    ground_plane_y: int = 0

@dataclass  
class MeasureResult:
    measure_id: str
    shot_id: str
    timestamp: str
    
    # Raw camera measurements
    ball_speed_ms_raw: float
    launch_angle_deg_raw: float
    launch_direction_deg_raw: float
    club_speed_ms_raw: float
    
    # Converted values
    ball_speed_mph: float
    launch_angle_deg: float
    launch_direction_deg: float
    club_speed_mph: float
    carry_yards_estimated: float
    
    # Quality
    ball_detect_confidence: float
    track_frames: int
    impact_confidence: float
    club_detected: bool
    is_approved: bool
    rejection_reason: str
    
    # Raw tracking data
    ball_positions_json: str
    club_positions_json: str
    impact_frame: int

