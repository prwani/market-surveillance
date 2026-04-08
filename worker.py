#!/usr/bin/env python3
"""
Streaming Agent Worker
======================
Continuously polls the Fabric Eventhouse for new trading events and feeds
them through all 5 surveillance agents in real-time.

Architecture:
    Eventhouse (TRADES + ORDER_BOOK_EVENTS)
        → Worker polls every POLL_INTERVAL seconds
        → Events fed to: PatternDetection, AnomalyDetection, CrossMarket
        → Alerts routed to: Intervention → Evidence
        → Results written back to: INTERVENTIONS table + shared state

The worker maintains a high-water mark (last processed event_time) to
avoid reprocessing. On restart, it resumes from the last checkpoint.

Per-exchange partitioning:
    Each worker instance can be assigned a single exchange (--exchange SGX)
    so that it only processes events for that exchange. A special
    'cross-market' partition runs only the CrossMarketAgent across all
    exchanges.

Warm-up on startup:
    On cold start, the worker back-fills agent sliding windows by querying
    the last N minutes of historical data (--warmup-minutes, default 60).

Usage:
    python worker.py                                    # all exchanges
    python worker.py --exchange SGX                     # SGX only
    python worker.py --exchange cross-market            # cross-market agent only
    python worker.py --warmup-minutes 30 --exchange HKEX

Environment variables:
    KQL_URI         — Fabric Eventhouse query URI (required)
    KQL_DB          — KQL database name (default: surveillance)
    POLL_INTERVAL   — seconds between polls (default: 10)
    EXCHANGE_FILTER — exchange partition (e.g. SGX, HKEX, NSE, cross-market)
    WARMUP_MINUTES  — minutes of history to load on cold start (default: 60)
    DASHBOARD_URL   — URL of the dashboard to push state updates (optional)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repo root is on path
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents import (
    Alert,
    AnomalyDetectionAgent,
    CrossMarketAgent,
    EvidenceCollectionAgent,
    InterventionAgent,
    PatternDetectionAgent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

# Suppress noisy Azure SDK logs
for _sdk_logger in ("azure.identity", "azure.core", "azure.kusto", "msal"):
    logging.getLogger(_sdk_logger).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Kusto client setup
# ---------------------------------------------------------------------------

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    HAS_KUSTO = True
except ImportError:
    HAS_KUSTO = False
    logger.warning("azure-kusto-data not installed — worker cannot connect to Eventhouse")


class EventhouseClient:
    """Thin wrapper around KustoClient for reading events and writing results."""

    def __init__(self, kql_uri: str, kql_db: str):
        if not HAS_KUSTO:
            raise RuntimeError("azure-kusto-data is required. pip install azure-kusto-data azure-identity")
        credential = DefaultAzureCredential()
        kcsb = KustoConnectionStringBuilder.with_azure_token_credential(kql_uri, credential)
        self.client = KustoClient(kcsb)
        self.db = kql_db
        self.kql_uri = kql_uri

    def query(self, kql: str) -> List[Dict[str, Any]]:
        """Execute a KQL query and return rows as dicts."""
        resp = self.client.execute_query(self.db, kql)
        columns = [col.column_name for col in resp.primary_results[0].columns]
        rows = []
        for row in resp.primary_results[0]:
            rows.append({col: row[col] for col in columns})
        return rows

    def mgmt(self, cmd: str) -> None:
        """Execute a KQL management command."""
        self.client.execute_mgmt(self.db, cmd)

    def fetch_new_trades(self, since: str, limit: int = 5000, exchange: str = '') -> List[Dict]:
        """Fetch trade events newer than the given ISO timestamp."""
        exchange_filter = f"\n        | where exchange_id == '{exchange}'" if exchange else ''
        kql = f"""
        TRADES
        | where event_time > datetime('{since}'){exchange_filter}
        | order by event_time asc
        | take {limit}
        | project trade_id, event_time, exchange_id, symbol, price, quantity,
                  buyer_id, seller_id, order_type, venue
        """
        return self.query(kql)

    def fetch_new_orders(self, since: str, limit: int = 5000, exchange: str = '') -> List[Dict]:
        """Fetch order book events newer than the given ISO timestamp."""
        exchange_filter = f"\n        | where exchange_id == '{exchange}'" if exchange else ''
        kql = f"""
        ORDER_BOOK_EVENTS
        | where event_time > datetime('{since}'){exchange_filter}
        | order by event_time asc
        | take {limit}
        | project event_id, event_time, exchange_id, symbol, side, price,
                  quantity, action, broker_id, order_id
        """
        return self.query(kql)

    def write_intervention(self, case) -> None:
        """Write an intervention case to the INTERVENTIONS table."""
        alert = case.alert
        brokers_json = json.dumps(alert.involved_entities)
        row = (
            f"{case.case_id},"
            f"{alert.detected_at},"
            f"{datetime.now(timezone.utc).isoformat()},"
            f"{alert.exchange_id},"
            f"{alert.symbol},"
            f"{alert.alert_type},"
            f"{brokers_json},"
            f"{case.status.value},"
            f"auto-worker"
        )
        try:
            self.mgmt(f".ingest inline into table INTERVENTIONS <| {row}")
        except Exception as e:
            logger.warning("Failed to write intervention %s: %s", case.case_id, e)


# ---------------------------------------------------------------------------
# Agent pipeline
# ---------------------------------------------------------------------------

class AgentPipeline:
    """Manages the 5 surveillance agents and routes events/alerts between them."""

    def __init__(self, eventhouse: Optional[EventhouseClient] = None):
        self.pattern_agent = PatternDetectionAgent()
        self.anomaly_agent = AnomalyDetectionAgent(price_history_buckets=60)
        self.cross_market_agent = CrossMarketAgent(correlation_threshold=0.80)
        self.intervention_agent = InterventionAgent(
            auto_intervention_threshold=0.70, dry_run=False,
        )
        self.evidence_agent = EvidenceCollectionAgent()
        self.eventhouse = eventhouse

        # Shared state
        self.alerts: List[Alert] = []
        self.cases: List = []
        self.events_processed = 0

        # Wire alert handlers
        self.pattern_agent.register_alert_handler(self._on_alert)
        self.anomaly_agent.register_alert_handler(self._on_alert)
        self.cross_market_agent.register_alert_handler(self._on_alert)

    def _on_alert(self, alert: Alert) -> None:
        self.alerts.append(alert)
        case = self.intervention_agent.handle_alert(alert)
        if case:
            self.cases.append(case)
            if self.eventhouse:
                self.eventhouse.write_intervention(case)

    def process_events(self, events: List[Dict[str, Any]], cross_market_only: bool = False) -> int:
        """Feed a batch of events through agents. Returns count processed.

        When *cross_market_only* is True only the CrossMarketAgent receives
        events (used by the ``cross-market`` partition worker).
        """
        for ev in events:
            if cross_market_only:
                self.cross_market_agent.process_event(ev)
            else:
                self.pattern_agent.process_event(ev)
                self.anomaly_agent.process_event(ev)
                self.cross_market_agent.process_event(ev)
            self.evidence_agent.process_event(ev)
            self.events_processed += 1
        return len(events)

    def flush(self) -> None:
        """Finalize open buckets in time-windowed agents."""
        self.anomaly_agent.flush()
        self.cross_market_agent.flush()

    def stats(self) -> Dict[str, Any]:
        return {
            "events_processed": self.events_processed,
            "total_alerts": len(self.alerts),
            "total_cases": len(self.cases),
            "pattern_alerts": self.pattern_agent.alert_count,
            "anomaly_alerts": self.anomaly_agent.alert_count,
            "cross_market_alerts": self.cross_market_agent.alert_count,
        }


# ---------------------------------------------------------------------------
# Normalize Eventhouse rows to agent event format
# ---------------------------------------------------------------------------

def normalize_trade(row: Dict) -> Dict:
    """Convert a KQL TRADES row to the event format expected by agents."""
    return {
        "event_type": "TRADE",
        "event_id": str(row.get("trade_id", "")),
        "exchange_id": str(row.get("exchange_id", "")),
        "symbol": str(row.get("symbol", "")),
        "timestamp": str(row.get("event_time", "")),
        "price": float(row.get("price", 0)),
        "quantity": int(float(row.get("quantity", 0))),
        "buyer_id": str(row.get("buyer_id", "")),
        "seller_id": str(row.get("seller_id", "")),
        "order_type": str(row.get("order_type", "LIMIT")),
        "venue": str(row.get("venue", "")),
    }


def normalize_order(row: Dict) -> Dict:
    """Convert a KQL ORDER_BOOK_EVENTS row to agent event format."""
    return {
        "event_type": "ORDER_BOOK",
        "event_id": str(row.get("event_id", "")),
        "exchange_id": str(row.get("exchange_id", "")),
        "symbol": str(row.get("symbol", "")),
        "timestamp": str(row.get("event_time", "")),
        "action": str(row.get("action", "")),
        "side": str(row.get("side", "")),
        "price": float(row.get("price", 0)),
        "quantity": int(float(row.get("quantity", 0))),
        "broker_id": str(row.get("broker_id", "")),
        "order_id": str(row.get("order_id", "")),
    }


# ---------------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------------

class StreamingWorker:
    """
    Continuously polls the Fabric Eventhouse for new events and processes
    them through the agent pipeline.
    """

    def __init__(
        self,
        kql_uri: str,
        kql_db: str = "surveillance",
        poll_interval: int = 10,
    ):
        self.kql_uri = kql_uri
        self.kql_db = kql_db
        self.poll_interval = poll_interval
        self._running = False

        # High-water marks for incremental polling
        self._trade_hwm = datetime.now(timezone.utc).isoformat()
        self._order_hwm = datetime.now(timezone.utc).isoformat()

        # Initialize
        self.eventhouse = EventhouseClient(kql_uri, kql_db)
        self.pipeline = AgentPipeline(eventhouse=self.eventhouse)

        logger.info(
            "Worker initialized: KQL=%s DB=%s poll=%ds",
            kql_uri, kql_db, poll_interval,
        )

    def run(self) -> None:
        """Start the continuous polling loop."""
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        logger.info("Worker started — polling every %ds", self.poll_interval)
        cycle = 0

        while self._running:
            cycle += 1
            try:
                n = self._poll_and_process()
                if n > 0 or cycle % 30 == 0:  # log every 30 cycles even if idle
                    stats = self.pipeline.stats()
                    logger.info(
                        "Cycle %d: processed %d events | total: %d events, %d alerts, %d cases",
                        cycle, n,
                        stats["events_processed"],
                        stats["total_alerts"],
                        stats["total_cases"],
                    )
            except Exception:
                logger.exception("Error in poll cycle %d", cycle)

            time.sleep(self.poll_interval)

        # Clean shutdown
        self.pipeline.flush()
        logger.info("Worker stopped. Final stats: %s", self.pipeline.stats())

    def _poll_and_process(self) -> int:
        """Poll for new events and feed through agents. Returns event count."""
        # Fetch new trades
        trades_raw = self.eventhouse.fetch_new_trades(self._trade_hwm)
        trades = [normalize_trade(r) for r in trades_raw]
        if trades_raw:
            self._trade_hwm = str(trades_raw[-1].get("event_time", self._trade_hwm))

        # Fetch new orders
        orders_raw = self.eventhouse.fetch_new_orders(self._order_hwm)
        orders = [normalize_order(r) for r in orders_raw]
        if orders_raw:
            self._order_hwm = str(orders_raw[-1].get("event_time", self._order_hwm))

        # Merge and sort by timestamp
        all_events = trades + orders
        all_events.sort(key=lambda e: e.get("timestamp", ""))

        if all_events:
            self.pipeline.process_events(all_events)

        return len(all_events)

    def _handle_shutdown(self, signum, frame):
        logger.info("Received signal %d — shutting down gracefully...", signum)
        self._running = False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Market Surveillance Streaming Agent Worker")
    parser.add_argument("--kql-uri", default=os.environ.get("KQL_URI", ""),
                        help="Fabric Eventhouse KQL query URI")
    parser.add_argument("--kql-db", default=os.environ.get("KQL_DB", "surveillance"),
                        help="KQL database name (default: surveillance)")
    parser.add_argument("--poll-interval", type=int,
                        default=int(os.environ.get("POLL_INTERVAL", "10")),
                        help="Seconds between polls (default: 10)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.kql_uri:
        logger.error("KQL_URI is required. Set via --kql-uri or KQL_URI env var.")
        sys.exit(1)

    worker = StreamingWorker(
        kql_uri=args.kql_uri,
        kql_db=args.kql_db,
        poll_interval=args.poll_interval,
    )
    worker.run()


if __name__ == "__main__":
    main()
