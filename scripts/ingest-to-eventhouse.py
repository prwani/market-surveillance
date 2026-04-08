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
import dataclasses
import os
import random
import sys
import time

# Ensure repo root is importable
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from exchange_data_simulator import SimulationEngine, TradeEvent, OrderBookEvent

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    HAS_KUSTO = True
except ImportError:
    HAS_KUSTO = False


DEFAULT_KQL_URI = "https://trd-z85435m8eppbw7fm7f.z0.kusto.fabric.microsoft.com"
DEFAULT_KQL_DB = "surveillance"
BATCH_SIZE = 50


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
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--kql-uri",
        default=os.environ.get("KQL_URI", DEFAULT_KQL_URI),
        help=f"KQL query URI (default: {DEFAULT_KQL_URI})",
    )
    parser.add_argument(
        "--kql-db",
        default=os.environ.get("KQL_DB", DEFAULT_KQL_DB),
        help=f"KQL database name (default: {DEFAULT_KQL_DB})",
    )
    return parser.parse_args()


def build_trade_row(ev):
    """Build a TSV row for a TradeEvent matching the TRADES table schema."""
    d = dataclasses.asdict(ev)
    return "\t".join(
        [
            str(d.get("event_id", "")),
            str(d.get("timestamp", "")),
            str(d.get("exchange_id", "")),
            str(d.get("symbol", "")),
            str(d.get("price", 0)),
            str(d.get("quantity", 0)),
            str(d.get("buyer_id", "")),
            str(d.get("seller_id", "")),
            str(d.get("order_type", "")),
            str(d.get("venue", "")),
        ]
    )


def build_order_row(ev):
    """Build a TSV row for an OrderBookEvent matching ORDER_BOOK_EVENTS schema."""
    d = dataclasses.asdict(ev)
    return "\t".join(
        [
            str(d.get("event_id", "")),
            str(d.get("timestamp", "")),
            str(d.get("exchange_id", "")),
            str(d.get("symbol", "")),
            str(d.get("side", "")),
            str(d.get("price", 0)),
            str(d.get("quantity", 0)),
            str(d.get("action", "")),
            str(d.get("broker_id", "")),
        ]
    )


def ingest_batch(client, db, table, rows):
    """Ingest a batch of TSV rows using .ingest inline into table."""
    data_block = "\n".join(rows)
    cmd = f".ingest inline into table {table} <|\n{data_block}"
    client.execute_mgmt(db, cmd)


def main():
    args = parse_args()

    if not HAS_KUSTO:
        print("ERROR: azure-identity and azure-kusto-data are required.")
        print("  pip install azure-identity azure-kusto-data")
        sys.exit(1)

    if args.seed is not None:
        random.seed(args.seed)

    print("=" * 60)
    print("  Eventhouse Inline Ingestion")
    print("=" * 60)
    print(f"  Exchanges : {', '.join(args.exchanges)}")
    print(f"  Duration  : {args.duration}s")
    print(f"  KQL URI   : {args.kql_uri}")
    print(f"  KQL DB    : {args.kql_db}")
    print(f"  Batch size: {BATCH_SIZE}")
    if args.seed is not None:
        print(f"  Seed      : {args.seed}")
    print()

    # ── Generate events ───────────────────────────────────────────
    print("[1/3] Generating simulated events...")
    config = {
        "exchanges": args.exchanges,
        "duration": args.duration,
        "events_per_second": 20,
        "inject_spoofing": True,
        "spoofing_start": max(5, args.duration // 6),
        "spoofing_repeat": max(3, args.duration // 40),
        "inject_layering": True,
        "layering_start": max(8, args.duration // 5),
        "inject_wash_trading": True,
        "wash_start": max(10, args.duration // 4),
        "inject_price_anomaly": False,
    }
    engine = SimulationEngine(config)
    raw_events = engine.generate_all_events()
    stats = engine.get_statistics()

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
        args.kql_uri, credential
    )
    client = KustoClient(kcsb)
    print("  ✓ Connected")

    # ── Ingest trades ─────────────────────────────────────────────
    print(f"\n[3/3] Ingesting into Eventhouse...")
    t0 = time.time()

    trade_rows = [build_trade_row(t) for t in trades]
    trade_batches = [
        trade_rows[i : i + BATCH_SIZE]
        for i in range(0, len(trade_rows), BATCH_SIZE)
    ]
    print(f"  Ingesting {len(trades)} trades in {len(trade_batches)} batches...")
    for idx, batch in enumerate(trade_batches, 1):
        ingest_batch(client, args.kql_db, "TRADES", batch)
        if idx % 10 == 0 or idx == len(trade_batches):
            print(f"    TRADES batch {idx}/{len(trade_batches)}")

    order_rows = [build_order_row(o) for o in orders]
    order_batches = [
        order_rows[i : i + BATCH_SIZE]
        for i in range(0, len(order_rows), BATCH_SIZE)
    ]
    print(f"  Ingesting {len(orders)} orders in {len(order_batches)} batches...")
    for idx, batch in enumerate(order_batches, 1):
        ingest_batch(client, args.kql_db, "ORDER_BOOK_EVENTS", batch)
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
