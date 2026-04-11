import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_config import derive_ingest_uri


class TestFabricConfig(unittest.TestCase):
    def test_derive_ingest_uri_prefixes_host(self):
        uri = "https://trd-abc.z7.kusto.fabric.microsoft.com"
        self.assertEqual(
            "https://ingest-trd-abc.z7.kusto.fabric.microsoft.com",
            derive_ingest_uri(uri),
        )

    def test_derive_ingest_uri_is_idempotent(self):
        uri = "https://ingest-trd-abc.z7.kusto.fabric.microsoft.com"
        self.assertEqual(uri, derive_ingest_uri(uri))
