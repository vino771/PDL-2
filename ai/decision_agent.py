"""
decision_agent.py
-----------------
Agent 4 — Decision / Orchestrator Agent

Combines results from the three specialist agents into a single
risk assessment and recommended action.

The deterministic safety_controller.py has FINAL authority —
this agent only suggests; it cannot bypass safety rules.
"""

import logging
from typing import Any, Dict

from .ollama_client import query_ollama
from .prompts import decision_agent_prompt

logger = logging.getLogger("DECISION")

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

def _highest_risk(*risks: str) -> str:
    """Return the highest risk level from the given values."""
    valid = [r.upper() for r in risks if str(r).upper() in _RISK_ORDER]
    if not valid:
        return "LOW"
    return max(valid, key=lambda r: _RISK_ORDER[r])


def _action_from_risk(risk: str) -> str:
    mapping = {"HIGH": "SAFE_MODE", "MEDIUM": "INSPECTION_REQUIRED", "LOW": "MONITOR"}
    return mapping.get(risk.upper(), "MONITOR")


def run(
    electrical: Dict[str, Any],
    environmental: Dict[str, Any],
    maintenance: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Combine agent outputs into a final decision.

    Parameters
    ----------
    electrical    : output of electrical_agent.run()
    environmental : output of environmental_agent.run()
    maintenance   : output of maintenance_agent.run()

    Returns
    -------
    dict — final risk assessment (before safety_controller override)
    """
    logger.info("Running decision orchestration …")

    e_risk = str(electrical.get("risk", "LOW")).upper()
    v_risk = str(environmental.get("risk", "LOW")).upper()
    m_priority = str(maintenance.get("priority", "LOW")).upper()
    maintenance_required = maintenance.get("maintenance_required", False)
    if maintenance_required and m_priority == "LOW":
        m_priority = "MEDIUM"

    
    result = query_ollama(
        decision_agent_prompt(electrical, environmental, maintenance)
    )

    # Validate the actual model response before accepting it.
    if isinstance(result, dict) and result:
        risk = str(result.get("overall_risk", "")).strip().upper()
        action = str(result.get("recommended_action", "")).strip().upper()
        reason = result.get("reason")
        maintenance_required = result.get("maintenance_required")
        confidence = result.get("confidence")

        valid_risks = {"LOW", "MEDIUM", "HIGH"}
        valid_actions = {
            "MONITOR",
            "SAFE_MODE",
            "INSPECTION_REQUIRED",
        }

        valid_confidence = (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and 0.0 <= confidence <= 1.0
        )

        valid_response = (
            risk in valid_risks
            and action in valid_actions
            and action == _action_from_risk(risk)
            and valid_confidence
            and isinstance(reason, str)
            and bool(reason.strip())
            and isinstance(maintenance_required, bool)
        )

        if valid_response:
            minimum_risk = _highest_risk(e_risk, v_risk, m_priority)
            final_risk = _highest_risk(risk, minimum_risk)
            final_reason = reason.strip()
            if final_risk != risk:
                final_reason = (
                    f"{final_reason} Deterministic agent risk floor escalated "
                    f"the decision to {final_risk}."
                )
            result["overall_risk"] = final_risk
            result["recommended_action"] = _action_from_risk(final_risk)
            result["confidence"] = float(confidence)
            result["reason"] = final_reason
            result["maintenance_required"] = (
                maintenance_required or result["maintenance_required"]
            )

            # Attach summaries from the specialist agents.
            result["electrical_risk"] = e_risk
            result["environmental_risk"] = v_risk
            result["maintenance_priority"] = m_priority

            logger.info(
                "[DECISION] Valid Ollama decision accepted | "
                "Risk=%s | Action=%s | Confidence=%.2f",
                result["overall_risk"],
                result["recommended_action"],
                float(confidence),
            )
            return result

        logger.warning(
            "[DECISION] Invalid Ollama output rejected. "
            "Risk=%r | Action=%r | Confidence=%r | "
            "Maintenance=%r. Using rule-based fallback.",
            risk,
            action,
            confidence,
            maintenance_required,
        )

    else:
        logger.warning(
            "[DECISION] Ollama returned no usable decision. "
            "Using rule-based fallback."
        )

    return _rule_based_decision(
        electrical,
        environmental,
        maintenance,
    )



def _rule_based_decision(electrical, environmental, maintenance) -> Dict[str, Any]:
    """Deterministic decision combination."""
    e_risk = electrical.get("risk", "LOW")
    v_risk = environmental.get("risk", "LOW")
    m_priority = maintenance.get("priority", "LOW")
    maintenance_required = maintenance.get("maintenance_required", False)
    if maintenance_required and m_priority == "LOW":
        m_priority = "MEDIUM"

    overall = _highest_risk(e_risk, v_risk, m_priority)
    action = _action_from_risk(overall)

    reasons = []
    if e_risk != "LOW":
        reasons.append(electrical.get("reason", f"Electrical risk: {e_risk}."))
    if v_risk != "LOW":
        reasons.append(environmental.get("reason", f"Environmental risk: {v_risk}."))
    if maintenance.get("maintenance_required"):
        reasons.append(maintenance.get("reason", f"Maintenance priority: {m_priority}."))

    if not reasons:
        reasons.append("All agents report normal conditions.")

    # Average confidence
    confidences = [
        electrical.get("confidence", 0.5),
        environmental.get("confidence", 0.5),
        maintenance.get("confidence", 0.5) if "confidence" in maintenance else 0.5,
    ]
    avg_conf = round(sum(confidences) / len(confidences), 2)

    return {
        "overall_risk": overall,
        "confidence": avg_conf,
        "recommended_action": action,
        "reason": " ".join(reasons),
        "maintenance_required": maintenance_required,
        "electrical_risk": e_risk,
        "environmental_risk": v_risk,
        "maintenance_priority": m_priority,
    }
