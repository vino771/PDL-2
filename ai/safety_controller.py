"""
safety_controller.py
---------------------
Deterministic Safety Controller — has FINAL authority over all actions.

The LLM (Ollama) is used only for analysis and prediction.
This controller overrides any AI recommendation that violates hard safety rules.

Rules:
  1. Critical water level → SAFE_MODE (always)
  2. Critical temperature → SAFE_MODE (always)
  3. Any HIGH risk from any agent → at minimum INSPECTION_REQUIRED
  4. Out-of-range pH → inspection; critical pH → SAFE_MODE
  5. Missing or invalid pH → INSPECTION_REQUIRED
  6. AI recommendation is accepted only if no rule was triggered

Simulated hardware actions are clearly labelled as "SIMULATED ACTION"
since the system runs on Tinkercad, not physical hardware.
"""

import logging
import math
from datetime import datetime
from typing import Any, Dict

from .environmental_agent import (
    PH_CRITICAL_HIGH,
    PH_CRITICAL_LOW,
    PH_HIGH,
    PH_LOW,
)

logger = logging.getLogger("SAFETY")

# ---- Hard limits (deterministic — never overridden by AI) ----
TEMP_SAFE_MODE_THRESHOLD = 50.0     # °C
WATER_SAFE_MODE_THRESHOLD = 85.0    # %
WATER_HIGH_THRESHOLD = 70.0         # %
TEMP_HIGH_THRESHOLD = 40.0          # °C
HUMIDITY_SAFE_THRESHOLD = 95.0      # %


# ---- Simulated action descriptions ----
SIMULATED_ACTIONS = {
    "SAFE_MODE": (
        "SIMULATED ACTION:\n"
        "  → Servo → Safe position\n"
        "  → Tracking Status → SAFE MODE\n"
        "  → System Status → PROTECTION MODE\n"
        "  → LED → RED"
    ),
    "INSPECTION_REQUIRED": (
        "SIMULATED ACTION:\n"
        "  → Alert flag → RAISED\n"
        "  → LED → AMBER\n"
        "  → System Status → NEEDS INSPECTION"
    ),
    "MONITOR": (
        "SIMULATED ACTION:\n"
        "  → System Status → NORMAL\n"
        "  → LED → GREEN"
    ),
}


def apply_safety_rules(
    decision: Dict[str, Any],
    sensor_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply deterministic safety rules on top of the AI decision.

    Parameters
    ----------
    decision    : output of decision_agent.run()
    sensor_data : raw Firebase sensor data

    Returns
    -------
    dict — final result with 'final_action' and 'simulated_action' keys added
    """
    sensors = sensor_data.get("sensors", {}) if sensor_data else {}
    temp = sensors.get("temperature")
    water = sensors.get("waterLevel")
    humidity = sensors.get("humidity")
    raw_ph = sensors.get("pH", sensors.get("ph", sensors.get("waterPH")))

    ai_action = decision.get("recommended_action", "MONITOR")
    override_reasons = []
    final_action = ai_action

    # ---- Rule 1: Critical temperature ----
    if temp is not None and temp >= TEMP_SAFE_MODE_THRESHOLD:
        final_action = "SAFE_MODE"
        override_reasons.append(
            f"SAFETY OVERRIDE: Temperature {temp}°C ≥ {TEMP_SAFE_MODE_THRESHOLD}°C critical threshold."
        )

    # ---- Rule 2: Critical water level ----
    if water is not None and water >= WATER_SAFE_MODE_THRESHOLD:
        final_action = "SAFE_MODE"
        override_reasons.append(
            f"SAFETY OVERRIDE: Water level {water}% ≥ {WATER_SAFE_MODE_THRESHOLD}% critical threshold."
        )

    # ---- Rule 3: High water level ----
    if water is not None and water >= WATER_HIGH_THRESHOLD and final_action == "MONITOR":
        final_action = "INSPECTION_REQUIRED"
        override_reasons.append(
            f"SAFETY OVERRIDE: Water level {water}% ≥ {WATER_HIGH_THRESHOLD}% — escalated to INSPECTION."
        )

    # ---- Rule 4: High temperature ----
    if temp is not None and temp >= TEMP_HIGH_THRESHOLD and final_action == "MONITOR":
        final_action = "INSPECTION_REQUIRED"
        override_reasons.append(
            f"SAFETY OVERRIDE: Temperature {temp}°C ≥ {TEMP_HIGH_THRESHOLD}°C — escalated to INSPECTION."
        )

    # ---- Rule 5: Critical humidity ----
    if humidity is not None and humidity >= HUMIDITY_SAFE_THRESHOLD:
        final_action = "SAFE_MODE"
        override_reasons.append(
            f"SAFETY OVERRIDE: Humidity {humidity}% ≥ {HUMIDITY_SAFE_THRESHOLD}% critical threshold."
        )

    # pH is checked independently of the model-based agent result.
    if raw_ph is None:
        ph = None
        ph_risk = "MEDIUM"
        ph_action = "INSPECTION_REQUIRED"
        ph_reason = "pH reading unavailable; water quality cannot be confirmed."
    else:
        try:
            if isinstance(raw_ph, bool):
                raise ValueError("boolean is not a pH reading")
            ph = float(raw_ph)
        except (TypeError, ValueError):
            ph = None
            ph_risk = "MEDIUM"
            ph_action = "INSPECTION_REQUIRED"
            ph_reason = f"Invalid pH reading ({raw_ph!r}); water quality cannot be confirmed."
        else:
            if not math.isfinite(ph) or not 0.0 <= ph <= 14.0:
                ph = None
                ph_risk = "MEDIUM"
                ph_action = "INSPECTION_REQUIRED"
                ph_reason = f"Invalid pH reading ({raw_ph!r}); expected a value from 0 to 14."
            elif ph < PH_LOW or ph > PH_HIGH:
                critical = ph < PH_CRITICAL_LOW or ph > PH_CRITICAL_HIGH
                ph_risk = "HIGH" if critical else "MEDIUM"
                ph_action = "SAFE_MODE" if critical else "INSPECTION_REQUIRED"
                ph_reason = (
                    f"pH {ph:g} is outside the configured {PH_LOW}–{PH_HIGH} range."
                )
            else:
                ph_risk = None
                ph_action = None
                ph_reason = ""

    if ph_risk:
        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        current_risk = str(decision.get("overall_risk", "LOW")).upper()
        if risk_order.get(current_risk, 0) < risk_order[ph_risk]:
            decision["overall_risk"] = ph_risk
            decision["recommended_action"] = ph_action
        action_order = {"MONITOR": 0, "INSPECTION_REQUIRED": 1, "SAFE_MODE": 2}
        if action_order.get(final_action, 0) < action_order[ph_action]:
            final_action = ph_action
        override_reasons.append(f"SAFETY OVERRIDE: {ph_reason}")
        decision["reason"] = (
            f"{str(decision.get('reason', '')).strip()} {ph_reason}".strip()
        )

    # ---- Rule 6: HIGH overall risk must never result in MONITOR ----
    if decision.get("overall_risk", "LOW") == "HIGH" and final_action == "MONITOR":
        final_action = "INSPECTION_REQUIRED"
        override_reasons.append(
            "SAFETY OVERRIDE: Overall risk is HIGH — minimum action escalated to INSPECTION_REQUIRED."
        )

    if override_reasons:
        for msg in override_reasons:
            logger.warning(msg)
        decision["safety_override"] = True
        decision["override_reasons"] = override_reasons
    else:
        decision["safety_override"] = False
        decision["override_reasons"] = []
        logger.info(f"Safety rules passed — AI action accepted: {final_action}")

    decision["final_action"] = final_action
    decision["simulated_action"] = SIMULATED_ACTIONS.get(final_action, SIMULATED_ACTIONS["MONITOR"])
    decision["evaluated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    logger.info(f"Action: {final_action}")
    return decision
