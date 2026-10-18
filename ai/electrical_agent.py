"""
electrical_agent.py
--------------------
Agent 1 — Electrical Risk Agent

Analyses electrical parameters available in Firebase.
Since the existing Tinkercad setup does not expose raw voltage/current,
this agent works with LDR values as a proxy for solar output and gracefully
marks unavailable parameters as N/A.
"""

import logging
import math
from typing import Any, Dict

from .ollama_client import query_ollama
from .prompts import electrical_agent_prompt

logger = logging.getLogger("ELECTRICAL AGENT")

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_ACTION_BY_RISK = {
    "LOW": "MONITOR",
    "MEDIUM": "INSPECTION_REQUIRED",
    "HIGH": "SAFE_MODE",
}


def _ldr_average(sensors: dict) -> str:
    """Compute average LDR reading as a proxy for electrical output level."""
    keys = ["topLeft", "topRight", "bottomLeft", "bottomRight"]
    values = [sensors.get(k) for k in keys if sensors.get(k) is not None]
    if not values:
        return "N/A"
    avg = sum(values) / len(values)
    return f"{avg:.1f}"


def run(sensor_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the Electrical Risk Agent.

    Parameters
    ----------
    sensor_data : dict
        The full /floatingSolarPanel Firebase node.

    Returns
    -------
    dict  — electrical risk assessment
    """
    sensors = sensor_data.get("sensors", {}) if sensor_data else {}
    ldr_avg = _ldr_average(sensors)
    voltage = sensors.get(
        "solarVoltage",
        sensors.get("solarV", sensors.get("voltage"))
    )

    prompt_data = {
        "voltage": voltage if voltage is not None else "N/A",
        "current": sensors.get("current", "N/A"),
        "power": sensors.get("power", "N/A"),
        "ldr_avg": ldr_avg,
    }

    logger.info("Running electrical risk analysis …")
    result = query_ollama(electrical_agent_prompt(prompt_data))

    if _valid_model_result(result):
        result["risk"] = str(result["risk"]).strip().upper()
        result["recommended_action"] = (
            str(result["recommended_action"]).strip().upper()
        )
        result["confidence"] = float(result["confidence"])
        result["reason"] = result["reason"].strip()
        logger.info(f"Risk: {result['risk']} (confidence: {result.get('confidence', '?')})")
        return _apply_voltage_availability(result, voltage)

    logger.warning(
        "Electrical agent: unusable Ollama result — using rule-based fallback."
    )
    return _apply_voltage_availability(
        _rule_based_fallback(ldr_avg),
        voltage,
    )


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


def _apply_voltage_availability(
    result: Dict[str, Any],
    raw_voltage: Any,
) -> Dict[str, Any]:
    if raw_voltage is not None:
        try:
            valid_voltage = (
                not isinstance(raw_voltage, bool)
                and math.isfinite(float(raw_voltage))
                and 0.0 <= float(raw_voltage) <= 5.0
            )
        except (TypeError, ValueError):
            valid_voltage = False
    else:
        valid_voltage = False

    if valid_voltage:
        return result

    current_risk = str(result.get("risk", "LOW")).upper()
    if _RISK_ORDER.get(current_risk, 0) < _RISK_ORDER["MEDIUM"]:
        current_risk = "MEDIUM"
    result["risk"] = current_risk
    result["recommended_action"] = _ACTION_BY_RISK[current_risk]
    result["confidence"] = max(float(result.get("confidence", 0.5)), 0.95)
    message = (
        "Solar voltage reading is missing or invalid; electrical conditions "
        "cannot be confirmed."
    )
    existing_reason = str(result.get("reason", "")).strip()
    result["reason"] = f"{existing_reason} {message}".strip()
    logger.warning("%s Reading=%r", message, raw_voltage)
    return result


def _rule_based_fallback(ldr_avg: str) -> Dict[str, Any]:
    """Deterministic fallback when Ollama is unavailable."""
    try:
        avg = float(ldr_avg) if ldr_avg != "N/A" else None
    except ValueError:
        avg = None

    if avg is not None and avg < 50:
        return {
            "risk": "MEDIUM",
            "confidence": 0.6,
            "reason": "Possible anomaly: LDR readings are unusually low (potential obstruction or failure).",
            "recommended_action": "INSPECTION_REQUIRED",
        }

    return {
        "risk": "LOW",
        "confidence": 0.7,
        "reason": "Electrical parameters within expected range based on available sensor data.",
        "recommended_action": "MONITOR",
    }
