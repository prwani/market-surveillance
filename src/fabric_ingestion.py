"""Helpers for inline Eventhouse ingestion using JSON mappings."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

TRADES_MAPPING_REFERENCE = "trades_json_mapping"
ORDERBOOK_MAPPING_REFERENCE = "orderbook_json_mapping"


def _as_dict(event: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(event):
        return dataclasses.asdict(event)
    return dict(event)


def build_trade_record(event: Any) -> dict[str, Any]:
    data = _as_dict(event)
    return {
        "trade_id": data.get("event_id", ""),
        "event_time": data.get("timestamp", ""),
        "exchange_id": data.get("exchange_id", ""),
        "symbol": data.get("symbol", ""),
        "price": data.get("price", 0),
        "quantity": data.get("quantity", 0),
        "buyer_id": data.get("buyer_id", ""),
        "seller_id": data.get("seller_id", ""),
        "order_type": data.get("order_type", ""),
        "venue": data.get("venue", ""),
    }


def build_order_record(event: Any) -> dict[str, Any]:
    data = _as_dict(event)
    return {
        "event_id": data.get("event_id", ""),
        "event_time": data.get("timestamp", ""),
        "exchange_id": data.get("exchange_id", ""),
        "symbol": data.get("symbol", ""),
        "side": data.get("side", ""),
        "price": data.get("price", 0),
        "quantity": data.get("quantity", 0),
        "action": data.get("action", ""),
        "broker_id": data.get("broker_id", ""),
    }


def build_inline_ingest_command(
    *, table: str, records: list[dict[str, Any]], mapping_reference: str
) -> str:
    payload = "\n".join(
        json.dumps(record, separators=(",", ":"), ensure_ascii=True) for record in records
    )
    return (
        f".ingest inline into table {table} "
        f"with (format='multijson', ingestionMappingReference='{mapping_reference}') <|\n"
        f"{payload}"
    )
