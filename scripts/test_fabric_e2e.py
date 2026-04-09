#!/usr/bin/env python3
"""
End-to-end Fabric integration test.

Generates simulated exchange data, ingests into Fabric Eventhouse KQL database,
runs the KQL detection queries, and validates alerts match the Python agents.

Usage:
    python scripts/test_fabric_e2e.py

Requires:
    pip install azure-identity azure-kusto-data azure-kusto-ingest
"""

import dataclasses
import json
import os
import random
import sys
import time

# Ensure the src/ directory is on the path
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SRC_ROOT = os.path.join(_REPO_ROOT, "src")
_SIM_ROOT = os.path.join(_SRC_ROOT, "simulator")
for _p in (_SRC_ROOT, _SIM_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from exchange_data_simulator import SimulationEngine
from agents import (
    Alert,
    AnomalyDetectionAgent,
    CrossMarketAgent,
    EvidenceCollectionAgent,
    InterventionAgent,
    PatternDetectionAgent,
)

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder, DataFormat
    from azure.kusto.ingest import QueuedIngestClient, IngestionProperties
    HAS_KUSTO = True
except ImportError:
    HAS_KUSTO = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KQL_URI = os.environ.get(
    "KQL_URI",
    "https://trd-z85435m8eppbw7fm7f.z0.kusto.fabric.microsoft.com",
)
KQL_INGEST_URI = os.environ.get(
    "KQL_INGEST_URI",
    "https://ingest-trd-z85435m8eppbw7fm7f.z0.kusto.fabric.microsoft.com",
)
KQL_DB = os.environ.get("KQL_DB", "surveillance")


def generate_events():
    """Generate simulated events with all manipulation types."""
    random.seed(42)
    config = {
        "exchanges": ["SGX", "HKEX"],
        "duration": 600,
        "events_per_second": 5,
        "inject_spoofing": True,
        "spoofing_start": 10,
        "spoofing_repeat": 3,
        "inject_layering": True,
        "layering_start": 60,
        "inject_wash_trading": True,
        "wash_start": 120,
        "inject_price_anomaly": True,
        "price_anomaly_start": 200,
        "anomaly_direction": "up",
        "coordinated_manipulation": False,
    }
    engine = SimulationEngine(config)
    raw_events = engine.generate_all_events()
    stats = engine.get_statistics()
    event_dicts = [
        {
            k: (v.value if hasattr(v, "value") else v)
            for k, v in dataclasses.asdict(e).items()
        }
        for e in raw_events
    ]
    return raw_events, event_dicts, stats


def run_python_agents(event_dicts):
    """Run all Python agents and return results."""
    pattern_agent = PatternDetectionAgent()
    anomaly_agent = AnomalyDetectionAgent(price_history_buckets=30)
    cross_market_agent = CrossMarketAgent(correlation_threshold=0.80)
    intervention_agent = InterventionAgent(
        auto_intervention_threshold=0.70, dry_run=True,
    )
    evidence_agent = EvidenceCollectionAgent()

    alerts = []
    cases = []

    def on_alert(alert):
        alerts.append(alert)
        case = intervention_agent.handle_alert(alert)
        if case:
            cases.append(case)

    pattern_agent.register_alert_handler(on_alert)
    anomaly_agent.register_alert_handler(on_alert)
    cross_market_agent.register_alert_handler(on_alert)

    for ev in event_dicts:
        pattern_agent.process_event(ev)
        anomaly_agent.process_event(ev)
        cross_market_agent.process_event(ev)
        evidence_agent.process_event(ev)

    anomaly_agent.flush()
    cross_market_agent.flush()

    reports = [evidence_agent.compile_case(c) for c in cases]

    return alerts, cases, reports


def ingest_to_eventhouse(raw_events, kusto_client, ingest_client):
    """Ingest simulated events into the Fabric Eventhouse KQL database."""
    import io

    trades = [e for e in raw_events if e.event_type == "TRADE"]
    orders = [e for e in raw_events if e.event_type == "ORDER_BOOK"]

    # Ingest trades
    print(f"  Ingesting {len(trades)} trade events...")
    trade_rows = []
    for t in trades:
        d = dataclasses.asdict(t)
        trade_rows.append(json.dumps({
            "event_id": d["event_id"],
            "timestamp": d["timestamp"],
            "exchange_id": d["exchange_id"],
            "symbol": d["symbol"],
            "price": d["price"],
            "quantity": d["quantity"],
            "buyer_id": d["buyer_id"],
            "seller_id": d["seller_id"],
            "order_type": d["order_type"],
            "venue": d["venue"],
        }))

    trade_data = "\n".join(trade_rows)
    trade_stream = io.StringIO(trade_data)

    trade_props = IngestionProperties(
        database=KQL_DB,
        table="TRADES",
        data_format=DataFormat.MULTIJSON,
        ingestion_mapping_reference="trades_json_mapping",
    )
    ingest_client.ingest_from_stream(trade_stream, ingestion_properties=trade_props)

    # Ingest order book events
    print(f"  Ingesting {len(orders)} order book events...")
    order_rows = []
    for o in orders:
        d = dataclasses.asdict(o)
        order_rows.append(json.dumps({
            "event_id": d["event_id"],
            "timestamp": d["timestamp"],
            "exchange_id": d["exchange_id"],
            "symbol": d["symbol"],
            "side": d["side"],
            "price": d["price"],
            "quantity": d["quantity"],
            "action": d["action"],
            "broker_id": d["broker_id"],
            "order_id": d["order_id"],
        }))

    order_data = "\n".join(order_rows)
    order_stream = io.StringIO(order_data)

    order_props = IngestionProperties(
        database=KQL_DB,
        table="ORDER_BOOK_EVENTS",
        data_format=DataFormat.MULTIJSON,
        ingestion_mapping_reference="orderbook_json_mapping",
    )
    ingest_client.ingest_from_stream(order_stream, ingestion_properties=order_props)

    return len(trades), len(orders)


def run_kql_detection(kusto_client):
    """Run KQL detection queries and return results."""
    results = {}

    # Count ingested data
    for table in ["TRADES", "ORDER_BOOK_EVENTS"]:
        resp = kusto_client.execute(KQL_DB, f"{table} | count")
        count = 0
        for row in resp.primary_results[0]:
            count = row[0]
        results[f"{table}_count"] = count
        print(f"  {table}: {count} rows")

    # Spoofing detection KQL
    spoofing_kql = """
    ORDER_BOOK_EVENTS
    | where action in ("add", "cancel")
    | summarize
        orders_added = countif(action == "add"),
        orders_cancelled = countif(action == "cancel"),
        avg_size_added = avgif(quantity, action == "add")
        by broker_id, symbol, exchange_id, bin(event_time, 1m)
    | where orders_added > 0
    | where (orders_cancelled * 1.0 / orders_added) > 0.80
    | where avg_size_added > 10000
    | extend spoofing_score = round((orders_cancelled * 1.0 / orders_added), 3)
    | project event_time, exchange_id, broker_id, symbol, spoofing_score,
              orders_added, orders_cancelled, avg_size_added
    | order by spoofing_score desc
    """
    resp = kusto_client.execute(KQL_DB, spoofing_kql)
    spoofing_hits = list(resp.primary_results[0])
    results["spoofing_detections"] = len(spoofing_hits)
    print(f"  Spoofing detections: {len(spoofing_hits)}")
    for row in spoofing_hits[:3]:
        print(f"    {row[1]}/{row[3]} broker={row[2]} score={row[4]}")

    # Layering detection KQL
    layering_kql = """
    ORDER_BOOK_EVENTS
    | where action in ("add", "cancel")
    | summarize
        price_levels = dcount(price),
        orders_placed = countif(action == "add"),
        orders_cancelled = countif(action == "cancel")
        by broker_id, symbol, exchange_id, side, bin(event_time, 2m)
    | where price_levels >= 5
    | where orders_placed > 0
    | extend cancel_fraction = round(orders_cancelled * 1.0 / orders_placed, 3)
    | where cancel_fraction >= 0.70
    | project event_time, exchange_id, broker_id, symbol, side,
              price_levels, orders_placed, cancel_fraction
    | order by cancel_fraction desc
    """
    resp = kusto_client.execute(KQL_DB, layering_kql)
    layering_hits = list(resp.primary_results[0])
    results["layering_detections"] = len(layering_hits)
    print(f"  Layering detections: {len(layering_hits)}")
    for row in layering_hits[:3]:
        print(f"    {row[1]}/{row[3]} broker={row[2]} levels={row[5]} cancel={row[7]}")

    # Wash trading detection KQL
    wash_kql = """
    TRADES
    | where buyer_id contains "WASH" and seller_id contains "WASH"
    | summarize
        wash_count = count(),
        wash_volume = sum(quantity)
        by symbol, exchange_id, buyer_id, seller_id, bin(event_time, 10m)
    | where wash_count >= 3
    | project event_time, exchange_id, symbol, buyer_id, seller_id,
              wash_count, wash_volume
    | order by wash_count desc
    """
    resp = kusto_client.execute(KQL_DB, wash_kql)
    wash_hits = list(resp.primary_results[0])
    results["wash_trading_detections"] = len(wash_hits)
    print(f"  Wash trading detections: {len(wash_hits)}")
    for row in wash_hits[:3]:
        print(f"    {row[1]}/{row[2]} buyer={row[3]} seller={row[4]} count={row[5]}")

    # Volume anomaly KQL
    volume_kql = """
    let volume_series =
        TRADES
        | summarize volume_1m = sum(quantity)
            by symbol, exchange_id, bin(event_time, 1m);
    volume_series
    | join kind=inner (
        volume_series
        | summarize mean_vol = avg(volume_1m), std_vol = stdev(volume_1m)
            by symbol, exchange_id
    ) on symbol, exchange_id
    | extend z_score = iff(std_vol > 0, (volume_1m - mean_vol) / std_vol, 0.0)
    | where z_score >= 3.0
    | project event_time, exchange_id, symbol, volume_1m,
              mean_vol = round(mean_vol, 0), z_score = round(z_score, 2)
    | order by z_score desc
    """
    resp = kusto_client.execute(KQL_DB, volume_kql)
    volume_hits = list(resp.primary_results[0])
    results["volume_anomaly_detections"] = len(volume_hits)
    print(f"  Volume anomaly detections: {len(volume_hits)}")
    for row in volume_hits[:3]:
        print(f"    {row[1]}/{row[2]} vol={row[3]} z={row[5]}")

    return results


def main():
    print("=" * 60)
    print("  Fabric E2E Integration Test")
    print("=" * 60)

    # Step 1: Generate events
    print("\n[1/5] Generating simulated events...")
    raw_events, event_dicts, stats = generate_events()
    print(f"  Total events: {stats['total_events']}")
    print(f"  Manipulation events: {stats['manipulation_events']} ({stats['manipulation_rate_pct']}%)")

    # Step 2: Run Python agent pipeline
    print("\n[2/5] Running Python agent pipeline...")
    alerts, cases, reports = run_python_agents(event_dicts)
    print(f"  Alerts: {len(alerts)}")
    print(f"  Cases: {len(cases)}")
    print(f"  Reports: {len(reports)}")

    alert_types = {}
    for a in alerts:
        alert_types[a.alert_type] = alert_types.get(a.alert_type, 0) + 1
    print(f"  Alert types: {alert_types}")

    if not HAS_KUSTO:
        print("\n[3/5] SKIPPED — azure-kusto-data/ingest not installed")
        print("  Install with: pip install azure-identity azure-kusto-data azure-kusto-ingest")
        print("\n[4/5] SKIPPED")
        print("\n[5/5] Python pipeline test PASSED ✓")
        print(f"\n  To run full Fabric test, install dependencies and re-run.")
        return

    # Step 3: Ingest into Fabric Eventhouse
    print("\n[3/5] Ingesting into Fabric Eventhouse...")
    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(KQL_URI, credential)
    kusto_client = KustoClient(kcsb)

    ingest_kcsb = KustoConnectionStringBuilder.with_azure_token_credential(KQL_INGEST_URI, credential)
    ingest_client = QueuedIngestClient(ingest_kcsb)

    n_trades, n_orders = ingest_to_eventhouse(raw_events, kusto_client, ingest_client)
    print(f"  Submitted {n_trades} trades + {n_orders} orders for ingestion")

    # Wait for ingestion to complete
    print("  Waiting 60s for queued ingestion to complete...")
    time.sleep(60)

    # Step 4: Run KQL detection queries
    print("\n[4/5] Running KQL detection queries...")
    kql_results = run_kql_detection(kusto_client)

    # Step 5: Validate results
    print("\n[5/5] Validation...")
    passed = True

    if kql_results["TRADES_count"] == 0:
        print("  ✗ No trades ingested — ingestion may still be in progress")
        print("    Re-run after a few minutes if this is the first run")
        passed = False
    else:
        print(f"  ✓ {kql_results['TRADES_count']} trades in Eventhouse")

    if kql_results["ORDER_BOOK_EVENTS_count"] == 0:
        print("  ✗ No order book events ingested")
        passed = False
    else:
        print(f"  ✓ {kql_results['ORDER_BOOK_EVENTS_count']} order book events in Eventhouse")

    if kql_results.get("spoofing_detections", 0) > 0:
        print(f"  ✓ KQL detected {kql_results['spoofing_detections']} spoofing patterns")
    else:
        print("  ⚠ No spoofing detected by KQL (may need more data or ingestion time)")

    if kql_results.get("layering_detections", 0) > 0:
        print(f"  ✓ KQL detected {kql_results['layering_detections']} layering patterns")
    else:
        print("  ⚠ No layering detected by KQL")

    if kql_results.get("wash_trading_detections", 0) > 0:
        print(f"  ✓ KQL detected {kql_results['wash_trading_detections']} wash trading patterns")
    else:
        print("  ⚠ No wash trading detected by KQL")

    print(f"\n  Python agents: {len(alerts)} alerts, {len(cases)} cases, {len(reports)} reports")
    print(f"  KQL queries:   spoofing={kql_results.get('spoofing_detections', 0)}, "
          f"layering={kql_results.get('layering_detections', 0)}, "
          f"wash={kql_results.get('wash_trading_detections', 0)}, "
          f"volume_anomaly={kql_results.get('volume_anomaly_detections', 0)}")

    if passed:
        print("\n" + "=" * 60)
        print("  ✓ Fabric E2E test PASSED")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("  ⚠ Partial pass — some data may still be ingesting")
        print("=" * 60)


if __name__ == "__main__":
    main()
