import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_ingestion import (
    ORDERBOOK_MAPPING_REFERENCE,
    TRADES_MAPPING_REFERENCE,
    build_inline_ingest_command,
    build_order_record,
    build_trade_record,
)


class TestFabricIngestion(unittest.TestCase):
    def test_build_trade_record_maps_fields_for_trades_table(self):
        record = build_trade_record(
            {
                "event_id": "trade-1",
                "timestamp": "2026-04-11T07:00:00Z",
                "exchange_id": "SGX",
                "symbol": "DBS",
                "price": 38.2,
                "quantity": 100.0,
                "buyer_id": "BROKER_A",
                "seller_id": "BROKER_B",
                "order_type": "LIMIT",
                "venue": "SGX_MAIN",
            }
        )
        self.assertEqual("trade-1", record["trade_id"])
        self.assertEqual("2026-04-11T07:00:00Z", record["event_time"])
        self.assertEqual("DBS", record["symbol"])

    def test_build_order_record_maps_fields_for_orderbook_table(self):
        record = build_order_record(
            {
                "event_id": "order-1",
                "timestamp": "2026-04-11T07:00:00Z",
                "exchange_id": "SGX",
                "symbol": "DBS",
                "side": "buy",
                "price": 38.2,
                "quantity": 100.0,
                "action": "add",
                "broker_id": "BROKER_A",
            }
        )
        self.assertEqual("order-1", record["event_id"])
        self.assertEqual("2026-04-11T07:00:00Z", record["event_time"])
        self.assertEqual("add", record["action"])

    def test_inline_ingest_command_uses_multijson_and_mapping_reference(self):
        command = build_inline_ingest_command(
            table="TRADES",
            records=[{"trade_id": "trade-1", "event_time": "2026-04-11T07:00:00Z"}],
            mapping_reference=TRADES_MAPPING_REFERENCE,
        )
        self.assertIn("format='multijson'", command)
        self.assertIn(
            f"ingestionMappingReference='{TRADES_MAPPING_REFERENCE}'", command
        )
        payload = command.split("<|\n", 1)[1]
        self.assertEqual(
            {"trade_id": "trade-1", "event_time": "2026-04-11T07:00:00Z"},
            json.loads(payload),
        )
        self.assertNotEqual(TRADES_MAPPING_REFERENCE, ORDERBOOK_MAPPING_REFERENCE)
