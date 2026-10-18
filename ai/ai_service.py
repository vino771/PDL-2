"""
ai_service.py
-------------
Main AI Service — entry point for the AI monitoring layer.

Orchestrates:
  1. Read sensor data from Firebase (existing paths, read-only)
  2. Run three specialist agents (electrical, environmental, maintenance)
  3. Combine via Decision Agent
  4. Apply deterministic Safety Controller
  5. Write results to /floatingSolarPanel/aiAnalysis (new node)
  6. Send alerts if required

Runs on a configurable interval (default 30 seconds).
If Ollama is offline, all agents fall back to deterministic rules.
The existing dashboard/Firebase pipeline is never interrupted.

Usage:
    python -m ai.ai_service
  or:
    python ai/ai_service.py
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ---- Ensure project root is on sys.path so imports work ----
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- Load .env from project root ----
from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

# ---- Configure logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AI SERVICE")

AI_ANALYSIS_INTERVAL = int(os.getenv("AI_ANALYSIS_INTERVAL", "30"))

# ---- Import AI modules ----
from ai.firebase_reader import get_sensor_data, get_historical_data, write_ai_analysis
from ai.ollama_client import is_ollama_online
from ai import electrical_agent, environmental_agent, maintenance_agent, decision_agent
from ai.safety_controller import apply_safety_rules
from ai.alert_manager import maybe_send_alert


def run_analysis(sensor_data: dict, history: list) -> dict:
    """Run all agents and return the final safety-controlled result."""

    # ---- Agent 1: Electrical ----
    electrical = electrical_agent.run(sensor_data)
    logger.info(f"[ELECTRICAL AGENT] Risk: {electrical.get('risk', 'N/A')}")

    # ---- Agent 2: Environmental ----
    environmental = environmental_agent.run(sensor_data, history)
    logger.info(f"[ENVIRONMENT AGENT] Risk: {environmental.get('risk', 'N/A')}")

    # ---- Agent 3: Maintenance ----
    maintenance = maintenance_agent.run(sensor_data, history)
    logger.info(f"[MAINTENANCE AGENT] Risk: {maintenance.get('priority', 'N/A')}")

    # ---- Agent 4: Decision ----
    decision = decision_agent.run(electrical, environmental, maintenance)
    logger.info(
        f"[DECISION] Overall Risk: {decision.get('overall_risk', 'N/A')} "
        f"| Action: {decision.get('recommended_action', 'N/A')}"
    )

    # ---- Safety Controller (deterministic override) ----
    final = apply_safety_rules(decision, sensor_data)
    logger.info(f"[SAFETY] Action: {final.get('final_action', 'N/A')}")

    # Print simulated action clearly
    print("\n" + "=" * 50)
    print(final.get("simulated_action", ""))
    print("=" * 50 + "\n")

    return final


def _write_status(payload: dict) -> None:
    if not write_ai_analysis(payload):
        logger.error("Could not persist AI status update to Firebase.")


def main():
    logger.info("=" * 60)
    logger.info("  AI-Assisted Floating Solar Panel Monitoring Service")
    logger.info("=" * 60)
    logger.info(f"Analysis interval: {AI_ANALYSIS_INTERVAL}s")
    logger.info(f"Ollama model: {os.getenv('OLLAMA_MODEL', 'qwen2.5:0.5b')}")

    _write_status({"aiStatus": "AI ONLINE", "lastError": None})

    while True:
        try:
            cycle_start = time.time()

            # --- Check Ollama status ---
            ollama_up = is_ollama_online()
            ai_status = "AI ONLINE" if ollama_up else "AI OFFLINE (rule-based mode)"
            logger.info(f"Ollama status: {ai_status}")

            # --- Read sensor data ---
            sensor_data = get_sensor_data()
            if not sensor_data:
                logger.warning("No sensor data — skipping analysis cycle.")
                _write_status({
                    "aiStatus": "AI WARNING",
                    "lastError": "No sensor data received from Firebase.",
                })
                time.sleep(AI_ANALYSIS_INTERVAL)
                continue

            logger.info("[FIREBASE] Sensor data received.")

            # --- Read historical data ---
            history = get_historical_data(limit=20)

            # --- Run analysis ---
            logger.info("[AI] Starting analysis …")
            _write_status({"aiStatus": "AI ANALYZING", "lastError": None})
            result = run_analysis(sensor_data, history)

            # --- Enrich result ---
            result["aiStatus"] = (
                "AI WARNING"
                if result.get("overall_risk") in ("HIGH",)
                else "AI ONLINE"
            )

            # --- Write to Firebase (new node only) ---
            firebase_payload = {
                "aiStatus": result["aiStatus"],
                "overall_risk": result.get("overall_risk", "UNKNOWN"),
                "confidence": result.get("confidence", 0),
                "recommended_action": result.get("recommended_action", "MONITOR"),
                "final_action": result.get("final_action", "MONITOR"),
                "reason": result.get("reason", ""),
                "maintenance_required": result.get("maintenance_required", False),
                "maintenance_priority": result.get("maintenance_priority", "LOW"),
                "electrical_risk": result.get("electrical_risk", "N/A"),
                "environmental_risk": result.get("environmental_risk", "N/A"),
                "safety_override": result.get("safety_override", False),
                "simulated_action": result.get("simulated_action", ""),
                "evaluated_at": result.get("evaluated_at", ""),
            }
            if not write_ai_analysis(firebase_payload, replace=True):
                logger.error("Completed AI analysis was not persisted to Firebase.")
                _write_status({
                    "aiStatus": "AI ERROR",
                    "lastError": "Completed analysis could not be persisted to Firebase.",
                    "errorUpdatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                })

            # --- Send alerts if needed ---
            maybe_send_alert(result)

            # --- Summary log ---
            logger.info(
                f"[SUMMARY] Risk={result.get('overall_risk')} | "
                f"Action={result.get('final_action')} | "
                f"Maintenance={result.get('maintenance_required')}"
            )

            elapsed = time.time() - cycle_start
            sleep_time = max(0, AI_ANALYSIS_INTERVAL - elapsed)
            logger.info(f"Next analysis in {sleep_time:.1f}s …\n")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("AI service stopped by user.")
            _write_status({"aiStatus": "AI OFFLINE"})
            break
        except Exception as exc:
            logger.error(f"Unexpected error in AI service loop: {exc}", exc_info=True)
            _write_status({
                "aiStatus": "AI ERROR",
                "lastError": str(exc),
                "errorUpdatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            time.sleep(AI_ANALYSIS_INTERVAL)


if __name__ == "__main__":
    main()
