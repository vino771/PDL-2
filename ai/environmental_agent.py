"""
environmental_agent.py
-----------------------
Agent 2 — Environmental Risk Agent

Analyses temperature, humidity, water level, and historical trends.
Falls back to deterministic rules when Ollama is unavailable.
"""

import logging
import math
import os
from typing import Any, Dict, List

from .ollama_client import query_ollama
from .prompts import environmental_agent_prompt

logger = logging.getLogger("ENVIRONMENT AGENT")

# ----- Safety thresholds (deterministic rule-base) -----
TEMP_HIGH = 40.0       # °C
TEMP_CRITICAL = 50.0   # °C
WATER_HIGH = 70.0      # %
WATER_CRITICAL = 85.0  # %
HUMIDITY_HIGH = 90.0   # %
WATER_RAPID_RISE = 15  # % increase across last few readings
# pH thresholds for this project's simulated water-quality checks.
# Confirm the appropriate operating range for the actual water body.
PH_LOW = float(os.getenv("PH_LOW", "6.5"))
PH_HIGH = float(os.getenv("PH_HIGH", "8.5"))
PH_CRITICAL_LOW = float(os.getenv("PH_CRITICAL_LOW", "3.0"))
PH_CRITICAL_HIGH = float(os.getenv("PH_CRITICAL_HIGH", "11.0"))

if not (0 <= PH_CRITICAL_LOW <= PH_LOW <= PH_HIGH <= PH_CRITICAL_HIGH <= 14):
    raise ValueError("Configure pH limits in order within the 0–14 pH scale.")

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_ACTION_BY_RISK = {
    "LOW": "MONITOR",
    "MEDIUM": "INSPECTION_REQUIRED",
    "HIGH": "SAFE_MODE",
}

def _detect_rapid_rise(history: List[Dict], field_path: tuple) -> bool:
    """
    Return True if the field has risen by WATER_RAPID_RISE or more across
    the last 5 historical records.
    """
    def _get(record, path):
        v = record
        for k in path:
            if isinstance(v, dict):
                v = v.get(k)
            else:
                return None
        return v

    readings = [_get(h, field_path) for h in history[-5:]]
    readings = [r for r in readings if r is not None]
    if len(readings) < 2:
        return False
    total_change = readings[-1] - readings[0]
    return total_change >= WATER_RAPID_RISE

def _apply_ph_safety(
    result: Dict[str, Any],
    sensors: Dict[str, Any],
) -> Dict[str, Any]:
    """Ensure pH alerts, including missing readings, cannot be ignored."""

    raw_ph = sensors.get(
        "pH",
        sensors.get("ph", sensors.get("waterPH"))
    )

    if raw_ph is None:
        ph = None
        required_risk = "MEDIUM"
        message = "pH reading unavailable; water quality cannot be confirmed."
    else:
        try:
            if isinstance(raw_ph, bool):
                raise ValueError("boolean is not a pH reading")
            ph = float(raw_ph)
        except (TypeError, ValueError):
            logger.warning("Invalid pH reading: %r", raw_ph)
            ph = None
            required_risk = "MEDIUM"
            message = f"Invalid pH reading ({raw_ph!r}); water quality cannot be confirmed."
        else:
            if not math.isfinite(ph) or not 0.0 <= ph <= 14.0:
                logger.warning("pH reading outside the valid 0–14 scale: %r", raw_ph)
                ph = None
                required_risk = "MEDIUM"
                message = f"Invalid pH reading ({raw_ph!r}); expected a value from 0 to 14."
            elif ph < PH_LOW or ph > PH_HIGH:
                required_risk = (
                    "HIGH"
                    if ph < PH_CRITICAL_LOW or ph > PH_CRITICAL_HIGH
                    else "MEDIUM"
                )
                message = (
                    f"Abnormal pH detected ({ph:g}); configured acceptable range "
                    f"is {PH_LOW}–{PH_HIGH}."
                )
            else:
                return result

    current_risk = str(result.get("risk", "LOW")).upper()
    if _RISK_ORDER.get(current_risk, 0) < _RISK_ORDER[required_risk]:
        current_risk = required_risk
    result["risk"] = current_risk
    result["recommended_action"] = _ACTION_BY_RISK[current_risk]
    result["confidence"] = max(float(result.get("confidence", 0.5)), 0.95)

    existing_reason = str(result.get("reason", "")).strip()
    if message not in existing_reason:
        result["reason"] = f"{existing_reason} {message}".strip()

    logger.warning(
        "pH safety rule triggered | reading=%r | Risk=%s | Action=%s",
        raw_ph,
        result.get("risk"),
        result.get("recommended_action"),
    )

    return result
def run(sensor_data: Dict[str, Any], history: List[Dict]) -> Dict[str, Any]:
    """
    Run the Environmental Risk Agent.

    Parameters
    ----------
    sensor_data : dict — full Firebase /floatingSolarPanel node
    history     : list — recent historical records (may be empty)

    Returns
    -------
    dict — environmental risk assessment
    """
    sensors = sensor_data.get("sensors", {}) if sensor_data else {}
    tracking = sensor_data.get("tracking", {}) if sensor_data else {}

    prompt_data = {
        "temperature": sensors.get("temperature", "N/A"),
        "humidity": sensors.get("humidity", "N/A"),
        "waterLevel": sensors.get("waterLevel", "N/A"),
        "pH": sensors.get(
            "pH",
            sensors.get("ph", sensors.get("waterPH", "N/A"))
        ),
        "trackingStatus": tracking.get("status", "N/A"),
    }

    logger.info("Running environmental risk analysis …")
    result = query_ollama(environmental_agent_prompt(prompt_data, history))

    if _valid_model_result(result):
        result["risk"] = str(result["risk"]).strip().upper()
        result["recommended_action"] = (
            str(result["recommended_action"]).strip().upper()
        )
        result["confidence"] = float(result["confidence"])
        result["reason"] = result["reason"].strip()
        logger.info(f"Risk: {result['risk']} (confidence: {result.get('confidence', '?')})")
        return _apply_ph_safety(result, sensors)

    logger.warning(
        "Environmental agent: unusable Ollama result — using rule-based fallback."
    )
    fallback_result = _rule_based_fallback(sensors, history)
    return _apply_ph_safety(fallback_result, sensors)


def _valid_model_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    risk = str(result.get("risk", "")).strip().upper()
    action = str(result.get("recommended_action", "")).strip().upper()
    confidence = result.get("confidence")
    return (
        risk in _RISK_ORDER
        and action in set(_ACTION_BY_RISK.values())
        and action == _ACTION_BY_RISK[risk]
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and 0.0 <= confidence <= 1.0
        and isinstance(result.get("reason"), str)
        and bool(result["reason"].strip())
    )


def _rule_based_fallback(sensors: dict, history: list) -> Dict[str, Any]:
    """Deterministic environmental risk classification."""
    temp = sensors.get("temperature")
    water = sensors.get("waterLevel")
    humidity = sensors.get("humidity")

    rapid_water_rise = _detect_rapid_rise(history, ("sensors", "waterLevel"))

    reasons = []
    risk = "LOW"
    action = "MONITOR"

    # --- Temperature checks ---
    if temp is not None:
        if temp >= TEMP_CRITICAL:
            risk = "HIGH"
            action = "SAFE_MODE"
            reasons.append(f"Critical temperature detected ({temp}°C).")
        elif temp >= TEMP_HIGH:
            risk = "MEDIUM" if risk != "HIGH" else risk
            action = "INSPECTION_REQUIRED" if action == "MONITOR" else action
            reasons.append(f"High temperature detected ({temp}°C).")

    # --- Water level checks ---
    if water is not None:
        if water >= WATER_CRITICAL:
            risk = "HIGH"
            action = "SAFE_MODE"
            reasons.append(f"Critical water level ({water}%).")
        elif water >= WATER_HIGH:
            risk = "HIGH" if risk == "HIGH" else "MEDIUM"
            action = "SAFE_MODE" if risk == "HIGH" else action
            reasons.append(f"High water level ({water}%).")

    if rapid_water_rise:
        risk = "HIGH"
        action = "SAFE_MODE"
        reasons.append("Rapid water level increase detected.")

    # --- Humidity check ---
    if humidity is not None and humidity >= HUMIDITY_HIGH:
        if risk == "LOW":
            risk = "MEDIUM"
        reasons.append(f"High humidity ({humidity}%).")

    if not reasons:
        reasons.append("All environmental parameters within safe range.")

    return {
        "risk": risk,
        "confidence": 0.85,
        "reason": " ".join(reasons),
        "recommended_action": action,
    }
