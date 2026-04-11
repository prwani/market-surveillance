#!/usr/bin/env python3
"""
Ingest simulated market data directly into Fabric Eventhouse via KQL inline ingestion.

Generates simulated exchange events using SimulationEngine and ingests trades into
the TRADES table and orders into ORDER_BOOK_EVENTS using `.ingest inline into table`
KQL commands in batches.

Usage:
    python scripts/ingest-to-eventhouse.py --exchanges SGX HKEX --duration 120
    python scripts/ingest-to-eventhouse.py --seed 42 --duration 600 --kql-db surveillance

Requires:
    pip install azure-identity azure-kusto-data
"""

import argparse
import os
import random
import sys
import time
from datetime import datetime, timezone

# Ensure src/ is importable
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SRC_ROOT = os.path.join(_REPO_ROOT, "src")
_SIM_ROOT = os.path.join(_SRC_ROOT, "simulator")
for _p in (_SRC_ROOT, _SIM_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fabric_ingestion import (
    ORDERBOOK_MAPPING_REFERENCE,
    TRADES_MAPPING_REFERENCE,
    build_inline_ingest_command,
    build_order_record,
    build_trade_record,
)
from fabric_config import resolve_setting
from exchange_data_simulator import SimulationEngine, TradeEvent, OrderBookEvent

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    HAS_KUSTO = True
except ImportError:
    HAS_KUSTO = False


DEFAULT_KQL_DB = "surveillance"
DEFAULT_BATCH_SIZE = 50


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ingest simulated market data into Fabric Eventhouse"
    )
    parser.add_argument(
        "--exchanges",
        nargs="+",
        default=["SGX"],
        help="Exchange IDs to simulate (default: SGX)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=120,
        help="Simulation duration in seconds (default: 120)",
    )
    parser.add_argument(
        "--events-per-second",
        type=int,
        default=20,
        help="Normal events per second per symbol (default: 20)",
    )
    parser.add_argument(
        "--backfill-seconds",
        type=int,
        default=0,
        help=(
            "Shift the generated timeline this many seconds into the past. "
            "Use a value equal to --duration to generate history ending near now."
        ),
    )
    parser.add_argument(
        "--inject-price-anomaly",
        action="store_true",
        help="Inject a sudden price anomaly into the generated trade stream",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--kql-uri",
        default=None,
        help="KQL query URI (defaults to KQL_URI env or `azd env get-value KQL_URI`)",
    )
    parser.add_argument(
        "--kql-db",
        default=None,
        help=(
            "KQL database name (defaults to KQL_DB env or "
            f"`azd env get-value KQL_DB`, else {DEFAULT_KQL_DB})"
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Inline ingestion batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    return parser.parse_args()


def ingest_batch(client, db, table, records, mapping_reference):
    """Ingest JSON rows using the existing Eventhouse ingestion mappings."""
    cmd = build_inline_ingest_command(
        table=table,
        records=records,
        mapping_reference=mapping_reference,
    )
    client.execute_mgmt(db, cmd)


def main():
    args = parse_args()

    if not HAS_KUSTO:
        print("ERROR: azure-identity and azure-kusto-data are required.")
        print("  pip install azure-identity azure-kusto-data")
        sys.exit(1)

    kql_uri = args.kql_uri or resolve_setting("KQL_URI")
    kql_db = args.kql_db or resolve_setting("KQL_DB") or DEFAULT_KQL_DB
    if not kql_uri:
        print("ERROR: KQL query URI not configured.")
        print("  Set KQL_URI, pass --kql-uri, or select the correct azd environment.")
        sys.exit(1)

    if args.seed is not None:
        random.seed(args.seed)

    print("=" * 60)
    print("  Eventhouse Inline Ingestion")
    print("=" * 60)
    print(f"  Exchanges : {', '.join(args.exchanges)}")
    print(f"  Duration  : {args.duration}s")
    print(f"  Events/s  : {args.events_per_second}")
    print(f"  KQL URI   : {kql_uri}")
    print(f"  KQL DB    : {kql_db}")
    print(f"  Batch size: {args.batch_size}")
    if args.seed is not None:
        print(f"  Seed      : {args.seed}")
    if args.backfill_seconds > 0:
        print(f"  Backfill  : {args.backfill_seconds}s")
    if args.inject_price_anomaly:
        print("  Price anom: enabled")
    print()

    # ── Generate events ───────────────────────────────────────────
    print("[1/3] Generating simulated events...")
    config = {
        "exchanges": args.exchanges,
        "duration": args.duration,
        "events_per_second": args.events_per_second,
        "inject_spoofing": True,
        "spoofing_start": max(5, args.duration // 6),
        "spoofing_repeat": max(3, args.duration // 40),
        "inject_layering": True,
        "layering_start": max(8, args.duration // 5),
        "inject_wash_trading": True,
        "wash_start": max(10, args.duration // 4),
        "inject_price_anomaly": args.inject_price_anomaly,
        "price_anomaly_start": max(15, args.duration // 2),
        "anomaly_direction": "up",
    }
    engine = SimulationEngine(config)
    if args.backfill_seconds > 0:
        engine.base_ts = time.time() - args.backfill_seconds
    raw_events = engine.generate_all_events()
    stats = engine.get_statistics()

    start_ts = datetime.fromtimestamp(engine.base_ts, tz=timezone.utc)
    end_ts = datetime.fromtimestamp(engine.base_ts + args.duration, tz=timezone.utc)
    print(
        "  Timeline: "
        f"{start_ts.isoformat()} -> {end_ts.isoformat()}"
    )

    trades = [e for e in raw_events if isinstance(e, TradeEvent)]
    orders = [e for e in raw_events if isinstance(e, OrderBookEvent)]
    print(f"  Total events: {stats['total_events']}")
    print(f"  Trades: {len(trades)}, Orders: {len(orders)}")
    print(f"  Manipulation events: {stats['manipulation_events']} "
          f"({stats['manipulation_rate_pct']}%)")

    # ── Connect to Eventhouse ─────────────────────────────────────
    print("\n[2/3] Connecting to Fabric Eventhouse...")
    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        kql_uri, credential
    )
    client = KustoClient(kcsb)
    print("  ✓ Connected")

    # ── Ingest trades ─────────────────────────────────────────────
    print(f"\n[3/3] Ingesting into Eventhouse...")
    t0 = time.time()

    trade_records = [build_trade_record(t) for t in trades]
    trade_batches = [
        trade_records[i : i + args.batch_size]
        for i in range(0, len(trade_records), args.batch_size)
    ]
    print(f"  Ingesting {len(trades)} trades in {len(trade_batches)} batches...")
    for idx, batch in enumerate(trade_batches, 1):
        ingest_batch(
            client,
            kql_db,
            "TRADES",
            batch,
            TRADES_MAPPING_REFERENCE,
        )
        if idx % 10 == 0 or idx == len(trade_batches):
            print(f"    TRADES batch {idx}/{len(trade_batches)}")

    order_records = [build_order_record(o) for o in orders]
    order_batches = [
        order_records[i : i + args.batch_size]
        for i in range(0, len(order_records), args.batch_size)
    ]
    print(f"  Ingesting {len(orders)} orders in {len(order_batches)} batches...")
    for idx, batch in enumerate(order_batches, 1):
        ingest_batch(
            client,
            kql_db,
            "ORDER_BOOK_EVENTS",
            batch,
            ORDERBOOK_MAPPING_REFERENCE,
        )
        if idx % 10 == 0 or idx == len(order_batches):
            print(f"    ORDER_BOOK_EVENTS batch {idx}/{len(order_batches)}")

    elapsed = time.time() - t0
    print(f"\n  ✓ Ingestion complete in {elapsed:.1f}s")

    # ── Verify row counts ─────────────────────────────────────────
    print("\n  Verifying row counts...")
    for table in ("TRADES", "ORDER_BOOK_EVENTS"):
        try:
            resp = client.execute_query(args.kql_db, f"{table} | count")
            count = 0
            for row in resp.primary_results[0]:
                count = row[0]
            print(f"    {table}: {count} rows")
        except Exception as exc:
            print(f"    {table}: could not verify ({exc})")

    print("\n" + "=" * 60)
    print(f"  Done — {len(trades)} trades + {len(orders)} orders ingested")
    print("=" * 60)


if __name__ == "__main__":
    main()
