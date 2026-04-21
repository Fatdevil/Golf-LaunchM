import asyncio
import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
import os

# mock env before importing
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-mock-key"

from database import init_db, save_paired_shot, get_session_shots
from coaching_engine import SessionAnalyzer, MIN_SHOTS_FOR_COACHING

async def seed_mock_data(session_id):
    await init_db()
    for i in range(6):
        quality = 0.9 if i < 3 else 0.4
        st = {"speed_mph": 150 + i, "carry_yards": 250 + i}
        sw = {"features": {"hip_rotation_at_impact_deg": 40 + i, "wrist_lag_deg": 80 - i}}
        
        record = {
            "shot_id": str(uuid.uuid4()),
            "session_id": session_id,
            "paired_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "sync_method": "timestamp",
            "sync_confidence": 0.95,
            "sync_status": "synced",
            "combined_quality": quality,
            "skytrak_json": json.dumps(st),
            "swing_json": json.dumps(sw),
            "is_training_approved": 1
        }
        await save_paired_shot(record)

async def test_analyzer_logic():
    session_id = str(uuid.uuid4())
    await seed_mock_data(session_id)
    
    analyzer = SessionAnalyzer(session_id)
    
    mock_claude_response = {
        "session_summary": "Great session.",
        "primary_finding": "Your hip rotation is amazing.",
        "coaching_points": [
            {
                "priority": 1,
                "focus_area": "hip",
                "observation": "Too much spin",
                "drill": "Step drill",
                "expected_improvement": "More power"
            }
        ], # Notice only 1 point, to test padding
        "next_session_focus": "Speed",
        "encouraging_note": "Keep it up"
    }
    
    class MockMessage:
        def __init__(self):
            self.content = [type('obj', (object,), {'text': json.dumps(mock_claude_response)})]
            self.usage = type('obj', (object,), {'input_tokens': 100, 'output_tokens': 50})
    
    with patch('coaching_engine.anthropic_client') as mock_client:
        mock_client.messages.create = AsyncMock(return_value=MockMessage())
        
        result = await analyzer.run()
        
        # Verify JSON
        assert result is not None
        assert "coaching_points" in result
        
        # Verify padding to exactly 3 points
        assert len(result["coaching_points"]) == 3
        assert result["coaching_points"][0]["focus_area"] == "hip"
        assert result["coaching_points"][1]["focus_area"] == "consistency"
        assert result["coaching_points"][2]["focus_area"] == "consistency"
        
        print("\nTest passed! JSON padding and API mocking succeeded.")

if __name__ == "__main__":
    import sys
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(test_analyzer_logic())
