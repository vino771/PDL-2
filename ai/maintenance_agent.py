"""
maintenance_agent.py
---------------------
Agent 3 — Predictive Maintenance Agent

Analyses sensor patterns to predict maintenance needs before failures occur.
Uses conservative language: "possible anomaly", "inspection recommended", etc.
Falls back to deterministic rules when Ollama is unavailable.
"""

import logging
from typing import Any, Dict, List

from .ollama_client import query_ollama
from .prompts import maintenance_agent_prompt

logger = logging.getLogger("MAINTENANCE AGENT")

# ---- Detection thresholds ----
LDR_IMBALANCE_THRESHOLD = 200   # difference between any two LDR sensors
TEMP_SPIKE_THRESHOLD = 8        # °C rise between consecutive readings
TEMP_REPEATED_SPIKE_COUNT = 3   # number of spikes to trigger HIGH priority
TRACKING_ANOMALY_STATES = {"ERROR", "FAILED", "STUCK", "UNKNOWN"}


def _check_ldr_imbalance(sensors: dict) -> bool:
    """Return True if LDR sensors show significant imbalance (possible sensor fault)."""
    keys = ["topLeft", "topRight", "bottomLeft", "bottomRight"]
    values = [sensors.get(k) for k in keys if sensors.get(k) is not None]
    if len(values) < 2:
        return False
    return (max(values) - min(values)) > LDR_IMBALANCE_THRESHOLD


def _count_temperature_spikes(history: list) -> int:
    """Count consecutive temperature spikes in history."""
    temps = []
    for h in history:
        t = h.get("sensors", {}).get("temperature")
        if t is not None:
            temps.append(t)
    spikes = 0
    for i in range(1, len(temps)):
        if temps[i] - temps[i-1] >= TEMP_SPIKE_THRESHOLD:
            spikes += 1
    return spikes


def run(sensor_data: Dict[str, Any], history: List[Dict]) -> Dict[str, Any]:
    """
    Run the Predictive Maintenance Agent.

    Parameters
    ----------
    sensor_data : dict — full Firebase /floatingSolarPanel node
    history     : list — recent historical records (may be empty)

    Returns
    -------
    dict — maintenance assessment
    """
    sensors = sensor_data.get("sensors", {}) if sensor_data else {}
    tracking = sensor_data.get("tracking", {}) if sensor_data else {}
    system = sensor_data.get("system", {}) if sensor_data else {}

    prompt_data = {
        **sensors,
        "horizontalAngle": tracking.get("horizontalAngle", "N/A"),
        "verticalAngle": tracking.get("verticalAngle", "N/A"),
        "temperatureStatus": system.get("temperatureStatus", "N/A"),
        "waterStatus": system.get("waterStatus", "N/A"),
        "ldrStatus": system.get("ldrStatus", "N/A"),
    }

    logger.info("Running predictive maintenance analysis …")
    result = query_ollama(maintenance_agent_prompt(prompt_data, history))

    if _valid_model_result(result):
        result["priority"] = str(result["priority"]).strip().upper()
        result["recommended_action"] = (
            str(result["recommended_action"]).strip().upper()
        )
        result["maintenance_required"] = (
            result["maintenance_required"]
            or result["priority"] != "LOW"
            or str(result["recommended_action"]).strip().upper()
            in {"INSPECTION_REQUIRED", "IMMEDIATE_ACTION"}
        )
        if result["maintenance_required"] and result["priority"] == "LOW":
            result["priority"] = "MEDIUM"
        result["reason"] = result["reason"].strip()
        if result["maintenance_required"]:
            result["recommended_action"] = "INSPECTION_REQUIRED"
        logger.info(
            f"Maintenance required: {result['maintenance_required']} | Priority: {result['priority']}"
        )
        return result

    logger.warning(
        "Maintenance agent: unusable Ollama result — using rule-based fallback."
    )
    return _rule_based_fallback(sensors, tracking, system, history)


def _valid_model_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        isinstance(result.get("maintenance_required"), bool)
        and str(result.get("priority", "")).strip().upper()
        in {"LOW", "MEDIUM", "HIGH"}
        and isinstance(result.get("reason"), str)
        and bool(result["reason"].strip())
        and str(result.get("recommended_action", "")).strip().upper()
        in {"NONE", "MONITOR", "INSPECTION_REQUIRED", "IMMEDIATE_ACTION"}
    )


def _rule_based_fallback(sensors: dict, tracking: dict, system: dict, history: list) -> Dict[str, Any]:
    """Deterministic predictive maintenance classification."""
    reasons = []
    priority = "LOW"
    required = False
    action = "NONE"

    # LDR imbalance
    if _check_ldr_imbalance(sensors):
        reasons.append("Possible LDR sensor imbalance detected — inspection recommended.")
        priority = "MEDIUM"
        required = True
        action = "INSPECTION_REQUIRED"

    # Temperature spikes in history
    spike_count = _count_temperature_spikes(history)
    if spike_count >= TEMP_REPEATED_SPIKE_COUNT:
        reasons.append(
            f"Repeated temperature spikes detected ({spike_count} occurrences) — potential thermal issue."
        )
        priority = "HIGH"
        required = True
        action = "INSPECTION_REQUIRED"
    elif spike_count > 0:
        reasons.append(f"Temperature spike observed ({spike_count} occurrence) — monitoring recommended.")
        if priority == "LOW":
            priority = "LOW"
            action = "MONITOR"

    # Tracking anomaly
    tracking_status = str(tracking.get("status", "")).upper()
    if tracking_status in TRACKING_ANOMALY_STATES:
        reasons.append(f"Possible tracking anomaly: status='{tracking_status}'.")
        if priority not in ("HIGH",):
            priority = "MEDIUM"
        required = True
        action = "INSPECTION_REQUIRED"

    # System-level flags
    for status_key, label in [
        ("temperatureStatus", "temperature"),
        ("waterStatus", "water level"),
        ("ldrStatus", "LDR"),
    ]:
        val = str(system.get(status_key, "")).upper()
        if val in ("CRITICAL", "ERROR", "WARNING", "DANGER", "HIGH"):
            reasons.append(f"System reported {label} status: {val}.")
            if priority == "LOW":
                priority = "MEDIUM"
                required = True
                action = "INSPECTION_REQUIRED"

    if not reasons:
        reasons.append("No significant maintenance indicators detected.")

    return {
        "maintenance_required": required,
        "priority": priority,
        "reason": " ".join(reasons),
        "recommended_action": action,
    }
