import base64
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from build_anomaly_detector_payload import build_create_request


class TestAnomalyDetectorPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_create_request(
            workspace_id="7aff0db9-c02a-42eb-bb95-3252574d7b84",
            artifact_id="dbb4afc6-81b9-4a8b-b1bc-681af7c01284",
        )
        cls.parts = {
            part["path"]: json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
            for part in cls.payload["definition"]["parts"]
        }
        cls.config = cls.parts["Configurations.json"]["univariateConfigurations"][0]

    def test_payload_has_expected_top_level_shape(self):
        self.assertEqual("Market Price Anomalies", self.payload["displayName"])
        self.assertEqual("AnomalyDetectorV1", self.payload["definition"]["format"])
        self.assertIn(".platform", self.parts)
        self.assertIn("Configurations.json", self.parts)

    def test_payload_targets_kql_db_trades_price_by_symbol(self):
        self.assertEqual("TRADES", self.config["fabricDataSource"]["tableName"])
        self.assertEqual("event_time", self.config["fabricDataSource"]["timestampColumnName"])
        self.assertEqual("symbol", self.config["fabricDataSource"]["instanceIDColumnName"])
        self.assertEqual("price", self.config["fabricDataSource"]["attributeColumnName"])
        self.assertEqual("KqlDb", self.config["fabricDataSource"]["dataSourceType"])

    def test_payload_enables_auto_publish(self):
        self.assertTrue(self.config["detectionSettings"]["autoPublish"])
        self.assertEqual(95, self.config["detectionSettings"]["confidence"])
        self.assertEqual("SR", self.config["modelOption"]["modelSelection"]["modelAlgorithm"])
        self.assertEqual(
            "Spectral Residual",
            self.config["modelOption"]["modelSelection"]["modelName"],
        )
