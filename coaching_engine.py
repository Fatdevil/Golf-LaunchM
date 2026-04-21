import os
import json
import uuid
from datetime import datetime, timezone
import logging
import asyncio
from dotenv import load_dotenv
import anthropic
from fastapi import FastAPI, BackgroundTasks, HTTPException
import uvicorn

from database import (
    get_session_shots,
    get_history_stats,
    save_coaching_report,
    get_latest_coaching_report,
    get_coaching_history
)

load_dotenv()
logger = logging.getLogger("coaching_engine")
logger.setLevel(logging.INFO)

MIN_SHOTS_FOR_COACHING = 5
api_key = os.getenv("ANTHROPIC_API_KEY")

if not api_key:
    logger.error("ANTHROPIC_API_KEY not set in .env")

app = FastAPI(title="SkyTrak Coaching Engine")

anthropic_client = None
if api_key:
    anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)

class SessionAnalyzer:
    def __init__(self, session_id):
        self.session_id = session_id
        
    def _extract_averages(self, items, key_prefix):
        res = {}
        if not items: return res
        
        # Determine if reading swing or skytrak
        for k in ["ball_speed", "launch_angle", "carry_yards", "total_spin_rpm",
                  "hip_rotation_at_impact_deg", "shoulder_tilt_at_impact_deg", 
                  "wrist_lag_deg", "weight_shift_ratio", "hip_lead_frames", 
                  "arm_speed_px_per_frame", "spine_angle_at_address_deg", 
                  "follow_through_completeness"]:
                  
            vals = []
            for item in items:
                # SkyTrak check
                if "ball" in item:
                    sk_ball = item["ball"]
                    if k in sk_ball: vals.append(sk_ball[k])
                # Swing check
                elif "features" in item:
                    sw_f = item["features"]
                    if k in sw_f: vals.append(sw_f[k])
            
            if len(vals) > 0:
                res[f"avg_{k}"] = sum(vals) / len(vals)
        return res

    async def run(self):
        shots = await get_session_shots(self.session_id)
        approved_count = len(shots)
        
        if approved_count < MIN_SHOTS_FOR_COACHING:
            print(f"⚠ Only {approved_count} approved shots — need {MIN_SHOTS_FOR_COACHING} minimum. Hit more balls and try again.")
            return None
            
        print(f"Aggregating {approved_count} shots for Coaching Analysis...")
        
        # Sort by combined_quality for best/worst
        sorted_shots = sorted(shots, key=lambda x: x["combined_quality"], reverse=True)
        best_5 = sorted_shots[:5]
        worst_5 = sorted_shots[-5:] if len(sorted_shots) >= 10 else sorted_shots[-(len(sorted_shots)//2):]
        
        best_parsed = []
        worst_parsed = []
        for s in best_5:
            st = json.loads(s["skytrak_json"])
            sw = json.loads(s.get("swing_json", "{}"))
            # Combine dicts conceptually for the generic _extract_averages func
            best_parsed.append({**st, **sw})
            
        for s in worst_5:
            st = json.loads(s["skytrak_json"])
            sw = json.loads(s.get("swing_json", "{}"))
            worst_parsed.append({**st, **sw})
            
        best_avgs = self._extract_averages(best_parsed, "best")
        worst_avgs = self._extract_averages(worst_parsed, "worst")
        
        deltas = []
        for key in best_avgs.keys():
            if key in worst_avgs:
                delta = best_avgs[key] - worst_avgs[key]
                deltas.append((key, delta, abs(delta)))
                
        # Sort by absolute delta
        deltas.sort(key=lambda x: x[2], reverse=True)
        top_3 = deltas[:3]
        
        history = await get_history_stats(self.session_id)
        history_summary = "No previous history found."
        if history:
            history_summary = "\\n".join([f"Session {h['session_id'][:8]} - Quality: {h['avg_quality']:.2f} ({h['shot_count']} shots)" for h in history])
            
        return await self._call_anthropic(approved_count, best_avgs, worst_avgs, top_3, history_summary)

    async def _call_anthropic(self, approved_count, b, w, top_3, history_summary):
        if not anthropic_client:
            logger.error("Anthropic client not initialized.")
            return None
            
        t1_n, t1_v, _ = top_3[0] if len(top_3) > 0 else ("none", 0, 0)
        t2_n, t2_v, _ = top_3[1] if len(top_3) > 1 else ("none", 0, 0)
        t3_n, t3_v, _ = top_3[2] if len(top_3) > 2 else ("none", 0, 0)
        
        prompt = f"""
Analyze this golf practice session and provide coaching advice.

SESSION SUMMARY:
- Total shots analyzed: {approved_count}
- Session date: {datetime.now().strftime("%Y-%m-%d")}
- Approved for analysis: {approved_count}

BEST SHOTS (avg values):
Ball Speed: {b.get("avg_speed_mph", b.get("avg_ball_speed", 0)):.1f} mph
Launch Angle: {b.get("avg_launch_angle_deg", 0):.1f}°
Carry: {b.get("avg_carry_yards", 0):.1f} yds
Total Spin: {b.get("avg_total_spin_rpm", 0):.0f} rpm
Hip Rotation at Impact: {b.get("avg_hip_rotation_at_impact_deg", 0):.1f}°
Shoulder Tilt: {b.get("avg_shoulder_tilt_at_impact_deg", 0):.1f}°
Wrist Lag: {b.get("avg_wrist_lag_deg", 0):.1f}°
Weight Shift: {b.get("avg_weight_shift_ratio", 0):.2f}
Hip Lead Frames: {b.get("avg_hip_lead_frames", 0):.1f}
Arm Speed: {b.get("avg_arm_speed_px_per_frame", 0):.1f} px/frame
Spine Angle at Address: {b.get("avg_spine_angle_at_address_deg", 0):.1f}°
Follow Through: {b.get("avg_follow_through_completeness", 0):.2f}

WORST SHOTS (avg values):
Ball Speed: {w.get("avg_speed_mph", w.get("avg_ball_speed", 0)):.1f} mph
Launch Angle: {w.get("avg_launch_angle_deg", 0):.1f}°
Carry: {w.get("avg_carry_yards", 0):.1f} yds
Total Spin: {w.get("avg_total_spin_rpm", 0):.0f} rpm
Hip Rotation at Impact: {w.get("avg_hip_rotation_at_impact_deg", 0):.1f}°
Shoulder Tilt: {w.get("avg_shoulder_tilt_at_impact_deg", 0):.1f}°
Wrist Lag: {w.get("avg_wrist_lag_deg", 0):.1f}°
Weight Shift: {w.get("avg_weight_shift_ratio", 0):.2f}
Hip Lead Frames: {w.get("avg_hip_lead_frames", 0):.1f}
Arm Speed: {w.get("avg_arm_speed_px_per_frame", 0):.1f} px/frame
Spine Angle at Address: {w.get("avg_spine_angle_at_address_deg", 0):.1f}°
Follow Through: {w.get("avg_follow_through_completeness", 0):.2f}

TOP 3 DIFFERENCES (best vs worst):
1. {t1_n}: {t1_v:+.1f}
2. {t2_n}: {t2_v:+.1f}  
3. {t3_n}: {t3_v:+.1f}

PREVIOUS SESSION HISTORY:
{history_summary}

Respond ONLY with this JSON structure, no other text:
{{
  "session_summary": "2-3 sentence overview",
  "primary_finding": "The single most important biomechanical finding with specific numbers",
  "coaching_points": [
    {{
      "priority": 1,
      "focus_area": "hip_rotation",
      "observation": "specific observation with numbers",
      "drill": "specific drill name and instructions",
      "expected_improvement": "what metric will improve"
    }}
  ],
  "next_session_focus": "specific goal for next session",
  "encouraging_note": "brief positive observation"
}}
"""
        try:
            response = await anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system="You are an expert PGA-certified golf coach with 20 years of experience. You analyze biomechanical data and launch monitor statistics to give precise, actionable coaching advice. Always be specific with numbers. Never give generic advice. Format your response as valid JSON only.",
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text
            
            # Extract JSON block if claud wrapped it 
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].strip()
                
            parsed = json.loads(raw_text)
            
            # Apply padding/truncation validation
            points = parsed.get("coaching_points", [])
            if not isinstance(points, list):
                points = []
            
            while len(points) < 3:
                points.append({
                    "priority": len(points) + 1,
                    "focus_area": "consistency",
                    "observation": "Insufficient data for this point",
                    "drill": "Continue collecting swing data",
                    "expected_improvement": "Better analysis with more shots"
                })
            parsed["coaching_points"] = points[:3]
            
            await self._save_and_print_report(approved_count, parsed, response.usage)
            return parsed
        except Exception as e:
            logger.error(f"Claude API failed: {e}")
            return None

    async def _save_and_print_report(self, count, parsed, usage):
        report_id = str(uuid.uuid4())
        record = {
            "report_id": report_id,
            "session_id": self.session_id,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "shot_count": count,
            "approved_count": count,
            "model_version": "claude-sonnet-4-20250514",
            "prompt_tokens": getattr(usage, "input_tokens", 0),
            "response_tokens": getattr(usage, "output_tokens", 0),
            "session_summary": parsed.get("session_summary", ""),
            "primary_finding": parsed.get("primary_finding", ""),
            "coaching_points_json": json.dumps(parsed.get("coaching_points", [])),
            "next_session_focus": parsed.get("next_session_focus", ""),
            "encouraging_note": parsed.get("encouraging_note", ""),
            "raw_response": json.dumps(parsed),
            "status": "success"
        }
        await save_coaching_report(record)
        
        pts = parsed.get("coaching_points", [])
        p1 = f"{pts[0]['focus_area']}: {pts[0]['drill']}" if len(pts) > 0 else "N/A"
        p2 = f"{pts[1]['focus_area']}: {pts[1]['drill']}" if len(pts) > 1 else "N/A"
        p3 = f"{pts[2]['focus_area']}: {pts[2]['drill']}" if len(pts) > 2 else "N/A"
        v1 = p1[:40] + "..." if len(p1) > 40 else p1
        v2 = p2[:40] + "..." if len(p2) > 40 else p2
        v3 = p3[:40] + "..." if len(p3) > 40 else p3
        
        print("\n  ╔═══════════════════════════════════════╗")
        print("  ║  COACHING REPORT READY                ║")
        print("  ╠═══════════════════════════════════════╣")
        print(f"  ║  Session: {self.session_id[:8]:<28}║")
        print(f"  ║  Shots analyzed: {count:<21}║")
        print("  ║  Primary finding:                     ║")
        pf = record["primary_finding"]
        pf_display = (pf[:36] + "...") if len(pf) > 36 else pf
        print(f"  ║  {pf_display:<37}║")
        print("  ╠═══════════════════════════════════════╣")
        print("  ║  TOP 3 COACHING POINTS:               ║")
        print(f"  ║  1. {v1:<34}║")
        print(f"  ║  2. {v2:<34}║")
        print(f"  ║  3. {v3:<34}║")
        print("  ╚═══════════════════════════════════════╝\n")


# FastAPI routes
@app.get("/coaching/session/{session_id}")
async def get_session_coaching(session_id: str):
    report = await get_latest_coaching_report(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="Coaching report not found")
    report["coaching_points_json"] = json.loads(report["coaching_points_json"])
    return report

@app.post("/coaching/generate/{session_id}")
async def generate_session_coaching(session_id: str, background_tasks: BackgroundTasks):
    analyzer = SessionAnalyzer(session_id)
    result = await analyzer.run()
    if not result:
        raise HTTPException(status_code=400, detail="Failed to generate coaching (check logs/mins shots)")
    return {"status": "success", "report": result}

@app.get("/coaching/history/{player_id}")
async def get_history(player_id: str):
    # Using generic history limits for now since user auth isn't fully built
    return await get_coaching_history(10)

def start_fastapi():
    import asyncio as _asyncio
    loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(loop)
    config = uvicorn.Config(
        app, host="127.0.0.1", 
        port=8766, log_level="warning"
    )
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())
