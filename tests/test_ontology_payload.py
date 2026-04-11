import base64
import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from build_ontology_payload import ONTOLOGY_DISPLAY_NAME, build_create_request


class TestOntologyPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rdf_path = PROJECT_ROOT / "ontology" / "market-surveillance.rdf"
        cls.payload = build_create_request(rdf_path)
        cls.parts = {
            part["path"]: json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
            for part in cls.payload["definition"]["parts"]
        }

    def test_display_name_matches_fabric_rules(self):
        self.assertEqual(self.payload["displayName"], ONTOLOGY_DISPLAY_NAME)
        self.assertRegex(
            ONTOLOGY_DISPLAY_NAME,
            re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$"),
        )

    def test_definition_contains_required_parts(self):
        self.assertEqual({}, self.parts["definition.json"])
        self.assertEqual("Ontology", self.parts[".platform"]["metadata"]["type"])

        entity_parts = [
            path
            for path in self.parts
            if path.startswith("EntityTypes/") and path.endswith("/definition.json")
        ]
        relationship_parts = [
            path
            for path in self.parts
            if path.startswith("RelationshipTypes/")
            and path.endswith("/definition.json")
        ]

        self.assertEqual(11, len(entity_parts))
        self.assertEqual(13, len(relationship_parts))

    def test_broker_entity_uses_identifier_and_display_name(self):
        broker = next(
            payload
            for path, payload in self.parts.items()
            if path.startswith("EntityTypes/") and payload.get("name") == "Broker"
        )
        properties = {prop["name"]: prop for prop in broker["properties"]}

        self.assertIn("brokerId", properties)
        self.assertIn("brokerName", properties)
        self.assertIn(properties["brokerId"]["id"], broker["entityIdParts"])
        self.assertEqual(
            properties["brokerName"]["id"], broker["displayNamePropertyId"]
        )

    def test_owned_by_relationship_references_entity_ids(self):
        entity_ids = {
            payload["name"]: payload["id"]
            for path, payload in self.parts.items()
            if path.startswith("EntityTypes/")
        }
        relationship = next(
            payload
            for path, payload in self.parts.items()
            if path.startswith("RelationshipTypes/") and payload.get("name") == "ownedBy"
        )

        self.assertEqual(entity_ids["Broker"], relationship["source"]["entityTypeId"])
        self.assertEqual(entity_ids["Fund"], relationship["target"]["entityTypeId"])
