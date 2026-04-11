import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_tenant_settings import (
    evaluate_required_settings,
    format_missing_settings_message,
    get_missing_required_settings,
    parse_tenant_settings_payload,
)


class TestFabricTenantSettings(unittest.TestCase):
    def test_parse_tenant_settings_payload_supports_tenant_settings_key(self):
        payload = """
        {
          "tenantSettings": [
            {"settingName": "OntologyPreview", "enabled": true}
          ]
        }
        """
        settings = parse_tenant_settings_payload(payload)
        self.assertTrue(settings["OntologyPreview"]["enabled"])

    def test_parse_tenant_settings_payload_supports_value_key(self):
        payload = """
        {
          "value": [
            {"settingName": "RTHAnomalyDetectionTenantSwitch", "enabled": false}
          ]
        }
        """
        settings = parse_tenant_settings_payload(payload)
        self.assertFalse(settings["RTHAnomalyDetectionTenantSwitch"]["enabled"])

    def test_evaluate_required_settings_marks_missing_setting(self):
        checks = evaluate_required_settings(
            {
                "OntologyPreview": {
                    "settingName": "OntologyPreview",
                    "enabled": True,
                    "delegateToCapacity": True,
                }
            }
        )
        missing = get_missing_required_settings(checks)
        self.assertEqual(1, len(missing))
        self.assertEqual(
            "RTHAnomalyDetectionTenantSwitch",
            missing[0].requirement.setting_name,
        )

    def test_format_missing_settings_message_mentions_wait_and_reason(self):
        checks = evaluate_required_settings({})
        message = format_missing_settings_message(get_missing_required_settings(checks))
        self.assertIn("wait up to 15 minutes", message)
        self.assertIn("Users can create Ontology (preview) items", message)
        self.assertIn("Detect anomalies in Real-Time Intelligence (Preview)", message)
