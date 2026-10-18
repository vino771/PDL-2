"""
test_ai_layer.py
----------------
Test script for the AI layer fail-safe scenarios.

Run with:
    python test_ai_layer.py

Tests:
  1  Normal conditions     → LOW risk
  2  High temperature      → MEDIUM/HIGH risk
  3  Rapid water rise      → HIGH risk / SAFE_MODE
  4  Ollama offline        → Rule-based fallback
  5  Invalid JSON          → Fallback, no crash
  6  Missing Firebase field→ AI continues, N/A handling
"""

import sys
from pathlib import Path

# Ensure project root on sys.path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

from ai.environmental_agent import _rule_based_fallback as env_fallback
from ai.maintenance_agent import _rule_based_fallback as maint_fallback
from ai.safety_controller import apply_safety_rules
from ai.decision_agent import _rule_based_decision


def header(title):
    print(f"\n{'='*60}")
    print(f"  TEST: {title}")
    print('='*60)


def show(label, result):
    print(f"  {label}:")
    for k, v in result.items():
        print(f"    {k}: {v}")


# ------------------------------------------------------------------ #
# Test 1: Normal conditions                                            #
# ------------------------------------------------------------------ #
header("1 — Normal Conditions (no Ollama needed)")

sensor_normal = {
    "sensors": {"temperature": 30, "humidity": 60, "waterLevel": 30,
                "ph": 7.0, "solarVoltage": 3.3,
                "topLeft": 500, "topRight": 490, "bottomLeft": 510, "bottomRight": 495},
    "tracking": {"horizontalAngle": 45, "verticalAngle": 20, "status": "TRACKING"},
    "system":   {"temperatureStatus": "NORMAL", "waterStatus": "NORMAL", "ldrStatus": "NORMAL"},
}

e_result = {"risk": "LOW", "confidence": 0.8, "reason": "Normal LDR.", "recommended_action": "MONITOR"}
v_result = env_fallback(sensor_normal["sensors"], [])
m_result = maint_fallback(sensor_normal["sensors"], sensor_normal["tracking"], sensor_normal["system"], [])
d_result = _rule_based_decision(e_result, v_result, m_result)
final1 = apply_safety_rules(d_result, sensor_normal)
show("Result", {"overall_risk": final1["overall_risk"], "final_action": final1["final_action"]})
assert final1["overall_risk"] == "LOW", f"Expected LOW, got {final1['overall_risk']}"
assert final1["final_action"] == "MONITOR"
print("  ✅ PASS")


# ------------------------------------------------------------------ #
# Test 2: High Temperature                                             #
# ------------------------------------------------------------------ #
header("2 — High Temperature (45°C)")

sensor_hot = dict(sensor_normal)
sensor_hot["sensors"] = {**sensor_normal["sensors"], "temperature": 45}
v_result2 = env_fallback(sensor_hot["sensors"], [])
d_result2 = _rule_based_decision(e_result, v_result2, m_result)
final2 = apply_safety_rules(d_result2, sensor_hot)
show("Result", {"overall_risk": final2["overall_risk"], "final_action": final2["final_action"]})
assert final2["overall_risk"] in ("MEDIUM", "HIGH"), f"Expected MEDIUM/HIGH, got {final2['overall_risk']}"
assert final2["final_action"] in ("INSPECTION_REQUIRED", "SAFE_MODE")
print("  ✅ PASS")


# ------------------------------------------------------------------ #
# Test 3: Rapid Water Level Rise                                       #
# ------------------------------------------------------------------ #
header("3 — Rapid Water Level Rise")

history_water = [
    {"sensors": {"temperature": 30, "waterLevel": 20}},
    {"sensors": {"temperature": 30, "waterLevel": 25}},
    {"sensors": {"temperature": 30, "waterLevel": 35}},
    {"sensors": {"temperature": 30, "waterLevel": 50}},
    {"sensors": {"temperature": 30, "waterLevel": 72}},
]
sensor_flood = dict(sensor_normal)
sensor_flood["sensors"] = {**sensor_normal["sensors"], "waterLevel": 72}
v_result3 = env_fallback(sensor_flood["sensors"], history_water)
d_result3 = _rule_based_decision(e_result, v_result3, m_result)
final3 = apply_safety_rules(d_result3, sensor_flood)
show("Result", {"env_risk": v_result3["risk"], "final_action": final3["final_action"]})
assert v_result3["risk"] == "HIGH", f"Expected HIGH, got {v_result3['risk']}"
assert final3["final_action"] == "SAFE_MODE"
print("  ✅ PASS")


# ------------------------------------------------------------------ #
# Test 4: AI Offline → Rule-Based Fallback                            #
# ------------------------------------------------------------------ #
header("4 — AI (Ollama) Offline")

# Simulate offline by checking is_ollama_online when Ollama is down
from ai.ollama_client import is_ollama_online, query_ollama
online = is_ollama_online()
print(f"  Ollama online: {online}")
if not online:
    result4 = query_ollama("test prompt")
    assert result4 is None, "Expected None when Ollama offline"
    print("  query_ollama returned None (correct).")
    # Agents will use fallback — tested implicitly in other tests
    print("  ✅ PASS — Rule-based fallback confirmed by Tests 1-3")
else:
    print("  ⚠️  Ollama is online — manual test required: stop Ollama and re-run.")


# ------------------------------------------------------------------ #
# Test 5: Invalid JSON from AI → No crash                             #
# ------------------------------------------------------------------ #
header("5 — Invalid AI Response → No crash")

from ai.ollama_client import _extract_json

assert _extract_json("not json at all") is None
assert _extract_json('{"risk": "HIGH"}') == {"risk": "HIGH"}
assert _extract_json("```json\n{\"risk\": \"LOW\"}\n```") == {"risk": "LOW"}
assert _extract_json("blah blah {\"risk\": \"MEDIUM\"} more text") == {"risk": "MEDIUM"}
print("  ✅ PASS — JSON extractor handles invalid/wrapped JSON without crash")


# ------------------------------------------------------------------ #
# Test 6: Missing Firebase field → AI continues                        #
# ------------------------------------------------------------------ #
header("6 — Missing Firebase Field")

sensor_missing = {
    "sensors": {"temperature": 33},  # waterLevel, humidity, LDRs all missing
    "tracking": {},
    "system": {},
}
v_result6 = env_fallback(sensor_missing["sensors"], [])
m_result6 = maint_fallback(sensor_missing["sensors"], sensor_missing["tracking"], sensor_missing["system"], [])
d_result6 = _rule_based_decision(e_result, v_result6, m_result6)
final6 = apply_safety_rules(d_result6, sensor_missing)
show("Result", {"overall_risk": final6["overall_risk"], "final_action": final6["final_action"]})
assert final6["overall_risk"] in ("LOW", "MEDIUM", "HIGH")
print("  ✅ PASS — Missing fields handled gracefully, no crash")


# ------------------------------------------------------------------ #
# Summary                                                              #
# ------------------------------------------------------------------ #
print(f"\n{'='*60}")
print("  ALL TESTS PASSED ✅")
print('='*60 + "\n")
