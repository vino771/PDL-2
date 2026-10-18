"""
chatbot.py
----------
Ollama-backed chatbot for the Floating Solar Panel dashboard.

Design constraints (from project requirements)
-----------------------------------------------
- Uses the already-installed local model qwen2.5:0.5b via the existing
  Ollama HTTP API.
- Reuses OLLAMA_BASE_URL and OLLAMA_MODEL from ollama_client.py's env vars.
- Returns free-text replies — does NOT attempt to extract JSON.
- Read-only: never writes to Firebase, never enqueues servo commands.
- Gracefully handles Ollama offline, timeouts, and malformed responses.
- Does not re-run any AI analysis agents.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("CHATBOT")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

# Generous timeout for chat — model may be slower on first load.
CHAT_TIMEOUT = 60

_SYSTEM_PROMPT = """\
You are a helpful assistant for a Floating Solar Panel (FPS) monitoring system.
You have access to the latest sensor readings and AI analysis shown below as context.
Answer questions about sensor readings, environmental conditions, electrical status,
water quality, solar tracking, maintenance recommendations, and operational safety.

IMPORTANT RULES:
- Distinguish clearly between: (a) actual sensor readings, (b) AI model inferences,
  (c) configured thresholds, and (d) general domain knowledge.
- If a reading is listed as N/A or missing, say so — never invent a value.
- If data may be stale, say so.
- You are strictly READ-ONLY. Never suggest or imply that you can move the servos,
  change Firebase values, or trigger any control action. Direct the user to use the
  Servo Control section of the dashboard for that.
- Keep answers concise and focused on the FPS system.
"""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context_snapshot(data: Dict[str, Any]) -> str:
    """
    Convert the Firebase /floatingSolarPanel dict into a compact text block
    for inclusion in the system prompt context.

    Works with whatever keys are present — missing keys are shown as N/A.
    """
    if not isinstance(data, dict):
        return "No sensor data is currently available."

    sensors = data.get("sensors") or {}
    tracking = data.get("tracking") or {}
    system = data.get("system") or {}
    ai = data.get("aiAnalysis") or {}
    servo_ctrl = data.get("servoControl") or {}

    def v(d: dict, *keys):
        for k in keys:
            val = d.get(k)
            if val is not None:
                return str(val)
        return "N/A"

    lines = [
        "=== CURRENT FPS SENSOR READINGS ===",
        f"Temperature       : {v(sensors, 'temperature')} °C",
        f"Humidity          : {v(sensors, 'humidity')} %",
        f"Water Level       : {v(sensors, 'waterLevel')} %",
        f"Water pH          : {v(sensors, 'pH', 'ph', 'waterPH')}",
        f"Solar Voltage     : {v(sensors, 'solarVoltage', 'solarV', 'voltage')} V",
        f"LDR Top-Left      : {v(sensors, 'topLeft')}",
        f"LDR Top-Right     : {v(sensors, 'topRight')}",
        f"LDR Bottom-Left   : {v(sensors, 'bottomLeft')}",
        f"LDR Bottom-Right  : {v(sensors, 'bottomRight')}",
        "",
        "=== SOLAR TRACKING ===",
        f"Horizontal Angle  : {v(tracking, 'horizontalAngle')}°",
        f"Vertical Angle    : {v(tracking, 'verticalAngle')}°",
        f"Tracking Status   : {v(tracking, 'status')}",
        "",
        "=== SYSTEM STATUS ===",
        f"Temperature Status: {v(system, 'temperatureStatus')}",
        f"Water Status      : {v(system, 'waterStatus')}",
        f"LDR Status        : {v(system, 'ldrStatus')}",
        f"Overall Status    : {v(system, 'overallStatus')}",
        "",
        "=== AI ANALYSIS (model inference — may be up to 30s old) ===",
        f"AI Status         : {v(ai, 'aiStatus')}",
        f"Overall Risk      : {v(ai, 'overall_risk')}",
        f"Electrical Risk   : {v(ai, 'electrical_risk')}",
        f"Environmental Risk: {v(ai, 'environmental_risk')}",
        f"Maintenance Needed: {v(ai, 'maintenance_required')}",
        f"Maintenance Prio  : {v(ai, 'maintenance_priority')}",
        f"Recommended Action: {v(ai, 'recommended_action', 'final_action')}",
        f"Reason            : {v(ai, 'reason')}",
        f"Safety Override   : {v(ai, 'safety_override')}",
        f"Last Evaluated    : {v(ai, 'evaluated_at', 'lastUpdated')}",
        "",
        "=== SERVO CONTROL STATE ===",
        f"Mode              : {v(servo_ctrl, 'mode')}",
        f"Requested H       : {v(servo_ctrl, 'requestedH')}°",
        f"Requested V       : {v(servo_ctrl, 'requestedV')}°",
        f"Command Status    : {v(servo_ctrl, 'status')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama chat
# ---------------------------------------------------------------------------

def _is_ollama_online() -> bool:
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def chat_with_ollama(
    messages: List[Dict[str, str]],
    system_context: str,
) -> str:
    """
    Send the conversation history to Ollama and return a free-text reply.

    Parameters
    ----------
    messages      : list of {"role": "user"|"assistant", "content": str}
    system_context: compact sensor snapshot to append to the system prompt

    Returns
    -------
    str — the assistant's reply, or an informative error message.
    """
    if not _is_ollama_online():
        return (
            "⚠️ Ollama is not reachable at "
            f"`{OLLAMA_BASE_URL}`. "
            "Please ensure Ollama is running and the `qwen2.5:0.5b` model is loaded. "
            "Try: `ollama serve` and `ollama run qwen2.5:0.5b`."
        )

    full_system = f"{_SYSTEM_PROMPT}\n{system_context}"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": full_system},
            *messages,
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 512,
        },
    }

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=CHAT_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        reply = body.get("message", {}).get("content", "").strip()
        if not reply:
            logger.warning("Ollama returned an empty chat reply.")
            return "The model returned an empty response. Please try again."
        return reply

    except requests.exceptions.ConnectionError:
        logger.warning("Ollama connection error during chat.")
        return (
            "⚠️ Could not connect to Ollama. "
            "Ensure `ollama serve` is running."
        )
    except requests.exceptions.Timeout:
        logger.warning("Ollama chat request timed out after %ss.", CHAT_TIMEOUT)
        return (
            f"⚠️ The model took longer than {CHAT_TIMEOUT}s to respond. "
            "Try a shorter question or check if the model is loaded."
        )
    except Exception as exc:
        logger.exception("Unexpected error during Ollama chat.")
        return f"⚠️ An unexpected error occurred: {exc}"
