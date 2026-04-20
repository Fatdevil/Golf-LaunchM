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
