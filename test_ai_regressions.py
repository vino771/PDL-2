import unittest
from unittest.mock import patch

import firebase_admin

with patch.object(firebase_admin, "initialize_app"):
    from ai import firebase_reader

from ai import (
    alert_manager,
    decision_agent,
    electrical_agent,
    environmental_agent,
    maintenance_agent,
)
from ai.safety_controller import apply_safety_rules


class InMemoryReference:
    def __init__(self):
        self.data = {}

    def update(self, payload):
        self.data.update(payload)

    def set(self, payload):
        self.data = dict(payload)

    def get(self):
        return self.data


bridge_sensor_reference = InMemoryReference()
bridge_tracking_reference = InMemoryReference()
with (
    patch("firebase_admin.credentials.Certificate", return_value=object()),
    patch.object(firebase_admin, "initialize_app"),
    patch(
        "firebase_admin.db.reference",
        side_effect=[bridge_sensor_reference, bridge_tracking_reference],
    ),
):
    import firebase_bridge

with (
    patch("firebase_admin.credentials.Certificate", return_value=object()),
    patch.object(firebase_admin, "initialize_app"),
):
    import firebase_service


class AiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.model_low = {
            "risk": "LOW",
            "confidence": 0.7,
            "reason": "Model reports low risk.",
            "recommended_action": "MONITOR",
        }

    def test_status_update_preserves_completed_analysis(self):
        reference = InMemoryReference()
        reference.data = {
            "overall_risk": "LOW",
            "reason": "Previous completed result",
            "final_action": "MONITOR",
        }
        with patch.object(firebase_reader.db, "reference", return_value=reference):
            self.assertTrue(
                firebase_reader.write_ai_analysis({"aiStatus": "AI ANALYZING"})
            )
        self.assertEqual(reference.data["overall_risk"], "LOW")
        self.assertEqual(reference.data["reason"], "Previous completed result")
        self.assertEqual(reference.data["aiStatus"], "AI ANALYZING")
        self.assertIn("lastUpdated", reference.data)

    def test_completed_analysis_replaces_partial_and_has_dashboard_fields(self):
        reference = InMemoryReference()
        reference.data = {"aiStatus": "AI ANALYZING", "stale": "remove"}
        payload = {
            "aiStatus": "AI ONLINE",
            "overall_risk": "LOW",
            "confidence": 0.8,
            "recommended_action": "MONITOR",
            "final_action": "MONITOR",
            "reason": "All agents report normal conditions.",
            "maintenance_required": False,
            "maintenance_priority": "LOW",
            "electrical_risk": "LOW",
            "environmental_risk": "LOW",
            "safety_override": False,
            "simulated_action": "SIMULATED ACTION: monitor",
            "evaluated_at": "2026-10-16T14:00:00+05:30",
        }
        with patch.object(firebase_reader.db, "reference", return_value=reference):
            self.assertTrue(firebase_reader.write_ai_analysis(payload, replace=True))
        self.assertNotIn("stale", reference.data)
        self.assertEqual(reference.data["aiStatus"], "AI ONLINE")
        self.assertTrue(set(payload).issubset(reference.data))
        self.assertIn("lastUpdated", reference.data)

    def test_firebase_write_failure_returns_false(self):
        with patch.object(
            firebase_reader.db, "reference", side_effect=RuntimeError("write failed")
        ), self.assertLogs("FIREBASE", level="ERROR") as captured:
            self.assertFalse(firebase_reader.write_ai_analysis({"aiStatus": "AI ERROR"}))
        self.assertIn("Failed to write AI analysis", "\n".join(captured.output))

    def test_firebase_read_failure_is_not_reported_as_empty_data(self):
        with patch.object(
            firebase_reader.db, "reference", side_effect=RuntimeError("read failed")
        ), self.assertLogs("FIREBASE", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                firebase_reader.get_sensor_data()

    def test_firebase_readers_use_the_existing_root_node(self):
        expected = {"sensors": {"ph": 7.0}}
        reference = InMemoryReference()
        reference.data = expected
        with patch.object(firebase_reader.db, "reference", return_value=reference) as ref:
            self.assertEqual(firebase_reader.get_sensor_data(), expected)
            ref.assert_called_once_with("/floatingSolarPanel")
        with patch.object(firebase_service.db, "reference", return_value=reference) as ref:
            self.assertEqual(firebase_service.get_data(), expected)
            ref.assert_called_once_with("/floatingSolarPanel")

    def test_environmental_ph_rules_override_low_model_response(self):
        cases = (
            ({"ph": 7.0}, "LOW", "MONITOR"),
            ({"ph": 6.0}, "MEDIUM", "INSPECTION_REQUIRED"),
            ({"ph": 2.0}, "HIGH", "SAFE_MODE"),
            ({}, "MEDIUM", "INSPECTION_REQUIRED"),
            ({"ph": "invalid"}, "MEDIUM", "INSPECTION_REQUIRED"),
        )
        for sensors, risk, action in cases:
            with self.subTest(sensors=sensors), patch.object(
                environmental_agent, "query_ollama", return_value=self.model_low.copy()
            ):
                result = environmental_agent.run({"sensors": sensors}, [])
            self.assertEqual(result["risk"], risk)
            self.assertEqual(result["recommended_action"], action)

    def test_ph_rules_also_apply_when_ollama_is_unavailable(self):
        with patch.object(environmental_agent, "query_ollama", return_value=None):
            result = environmental_agent.run(
                {"sensors": {"ph": 2.0}},
                [],
            )
        self.assertEqual(result["risk"], "HIGH")
        self.assertEqual(result["recommended_action"], "SAFE_MODE")

    def test_safety_controller_independently_enforces_ph(self):
        for sensors, action in (
            ({"ph": 6.0}, "INSPECTION_REQUIRED"),
            ({"ph": 2.0}, "SAFE_MODE"),
            ({}, "INSPECTION_REQUIRED"),
            ({"ph": "bad"}, "INSPECTION_REQUIRED"),
        ):
            with self.subTest(sensors=sensors):
                result = apply_safety_rules(
                    {
                        "overall_risk": "LOW",
                        "recommended_action": "MONITOR",
                        "reason": "Model reports low risk.",
                    },
                    {"sensors": sensors},
                )
                self.assertEqual(result["final_action"], action)

    def test_decision_risk_cannot_override_specialist_risk(self):
        model_decision = {
            "overall_risk": "LOW",
            "confidence": 0.9,
            "recommended_action": "MONITOR",
            "reason": "Model reports low risk.",
            "maintenance_required": False,
        }
        with patch.object(
            decision_agent, "query_ollama", return_value=model_decision
        ):
            result = decision_agent.run(
                {"risk": "LOW"},
                {"risk": "MEDIUM"},
                {"priority": "LOW", "maintenance_required": False},
            )
        self.assertEqual(result["overall_risk"], "MEDIUM")
        self.assertEqual(result["recommended_action"], "INSPECTION_REQUIRED")

    def test_invalid_model_decision_uses_rule_based_fallback(self):
        model_decision = {
            "overall_risk": "LOW|MEDIUM|HIGH",
            "confidence": "high",
            "recommended_action": "MONITOR",
            "reason": "placeholder",
            "maintenance_required": False,
        }
        with patch.object(
            decision_agent, "query_ollama", return_value=model_decision
        ):
            result = decision_agent.run(
                {"risk": "LOW"},
                {"risk": "HIGH"},
                {"priority": "LOW", "maintenance_required": False},
            )
        self.assertEqual(result["overall_risk"], "HIGH")
        self.assertEqual(result["recommended_action"], "SAFE_MODE")

    def test_maintenance_priority_and_flag_are_consistent(self):
        model_maintenance = {
            "maintenance_required": False,
            "priority": "HIGH",
            "reason": "Repeated anomalies detected.",
            "recommended_action": "MONITOR",
        }
        with patch.object(
            maintenance_agent, "query_ollama", return_value=model_maintenance
        ):
            result = maintenance_agent.run({"sensors": {}}, [])
        self.assertTrue(result["maintenance_required"])
        self.assertEqual(result["priority"], "HIGH")
        self.assertEqual(result["recommended_action"], "INSPECTION_REQUIRED")

    def test_electrical_agent_uses_bridge_voltage_field(self):
        with patch.object(
            electrical_agent, "query_ollama", return_value=self.model_low.copy()
        ) as query:
            result = electrical_agent.run(
                {"sensors": {"solarVoltage": 3.7, "topLeft": 500}}
            )
        self.assertIn("Voltage: 3.7", query.call_args.args[0])
        self.assertEqual(result["risk"], "LOW")

    def test_missing_solar_voltage_is_not_classified_as_low(self):
        with patch.object(electrical_agent, "query_ollama", return_value=None):
            result = electrical_agent.run({"sensors": {"topLeft": 500}})
        self.assertEqual(result["risk"], "MEDIUM")
        self.assertEqual(result["recommended_action"], "INSPECTION_REQUIRED")
        self.assertIn("cannot be confirmed", result["reason"])

    def test_bridge_sensor_upload_and_command_routes(self):
        client = firebase_bridge.app.test_client()
        self.assertEqual(client.get("/health").status_code, 200)
        with (
            patch.object(firebase_bridge, "sensor_ref", bridge_sensor_reference),
            patch.object(firebase_bridge, "tracking_ref", bridge_tracking_reference),
        ):
            response = client.get(
                "/send?out=500,501,502,503,90,45,6.99,3.7"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["result"], "updated")
        self.assertEqual(bridge_sensor_reference.data["ph"], 6.99)
        self.assertEqual(bridge_sensor_reference.data["solarVoltage"], 3.7)
        self.assertEqual(
            bridge_tracking_reference.data["horizontalAngle"],
            90,
        )

        response = client.post("/cmd", json={"cmd": "PING"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"queued": True})
        self.assertEqual(client.get("/cmd").get_data(as_text=True), "PING")

    def test_disabled_alert_integrations_do_not_send_external_requests(self):
        with (
            patch.object(alert_manager, "EMAIL_ENABLED", False),
            patch.object(alert_manager, "TELEGRAM_ENABLED", False),
            patch.object(alert_manager.smtplib, "SMTP") as smtp,
            patch.object(alert_manager.requests, "post") as post,
        ):
            self.assertFalse(alert_manager.send_email_alert({}))
            self.assertFalse(alert_manager.send_telegram_alert({}))
        smtp.assert_not_called()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
