import base64
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from build_reflex_payload import build_create_request


class TestReflexPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_create_request(
            config_path=PROJECT_ROOT / "data_activator" / "reflex_triggers.json",
            workspace_id="7aff0db9-c02a-42eb-bb95-3252574d7b84",
            cluster_uri="https://trd-3k9jp9t566xww6svgc.z7.kusto.fabric.microsoft.com",
            database="surveillance",
            alert_recipient="admin@example.com",
        )
        cls.parts = {
            part["path"]: json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
            for part in cls.payload["definition"]["parts"]
        }

    def test_reflex_payload_has_required_structure(self):
        self.assertEqual("Surveillance Alerts", self.payload["displayName"])
        self.assertIn("ReflexEntities.json", self.parts)
        self.assertIn(".platform", self.parts)

    def test_reflex_entities_include_one_container_source_event_rule_per_trigger(self):
        entities = self.parts["ReflexEntities.json"]
        self.assertEqual(16, len(entities))

        type_counts = {}
        for entity in entities:
            type_counts[entity["type"]] = type_counts.get(entity["type"], 0) + 1

        self.assertEqual(4, type_counts["container-v1"])
        self.assertEqual(4, type_counts["kqlSource-v1"])
        self.assertEqual(8, type_counts["timeSeriesView-v1"])

    def test_kql_sources_target_eventhouse(self):
        entities = self.parts["ReflexEntities.json"]
        kql_sources = [e for e in entities if e["type"] == "kqlSource-v1"]
        self.assertEqual(4, len(kql_sources))
        for source in kql_sources:
            payload = source["payload"]
            self.assertEqual("surveillance", payload["eventhouseItem"]["databaseName"])
            self.assertEqual(
                "trd-3k9jp9t566xww6svgc.z7.kusto.fabric.microsoft.com",
                payload["eventhouseItem"]["clusterHostName"],
            )
            self.assertEqual(
                "7aff0db9-c02a-42eb-bb95-3252574d7b84", payload["metadata"]["workspaceId"]
            )

    def test_rules_are_enabled_event_triggers(self):
        entities = self.parts["ReflexEntities.json"]
        rules = [
            e
            for e in entities
            if e["type"] == "timeSeriesView-v1"
            and e["payload"]["definition"]["type"] == "Rule"
        ]
        self.assertEqual(4, len(rules))
        for rule in rules:
            self.assertTrue(rule["payload"]["definition"]["settings"]["shouldRun"])
            instance = json.loads(rule["payload"]["definition"]["instance"])
            self.assertEqual("EventTrigger", instance["templateId"])
            self.assertIn("ActStep", [step["name"] for step in instance["steps"]])
