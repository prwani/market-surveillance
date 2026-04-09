#!/usr/bin/env python3
"""
Streaming Agent Worker
======================
Continuously polls the Fabric Eventhouse for new trading events and feeds
them through all 5 surveillance agents in real-time.

Architecture (Hybrid — Phase 2):
    Cold start:  Eventhouse (TRADES + ORDER_BOOK_EVENTS)
                     → Worker polls every POLL_INTERVAL seconds for warm-up
                     → Agents seeded with last WARMUP_MINUTES of history
    Live:        Eventstream (Event Hub-compatible endpoint)
                     → EventHubConsumerClient pushes events in ~1s
                     → Agents process events in real-time

The worker supports two operating modes:

    **Eventhouse-poll mode** (default / fallback):
        Polls KQL every POLL_INTERVAL seconds.  Suitable for development or
        when no Eventstream endpoint is configured.

    **Eventstream-direct mode** (Phase 2, low-latency):
        Set ``EVENTSTREAM_ENDPOINT`` (Event Hub-compatible connection string)
        to enable direct Eventstream consumption via
        ``azure.eventhub.EventHubConsumerClient``.
        Each exchange partition subscribes using its exchange name as the
        consumer group.  Cold start still uses Eventhouse for the 60-minute
        history back-fill.

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
    KQL_URI               — Fabric Eventhouse query URI (required)
    KQL_DB                — KQL database name (default: surveillance)
    POLL_INTERVAL         — seconds between polls (default: 10)
    EXCHANGE_FILTER       — exchange partition (e.g. SGX, HKEX, NSE, cross-market)
    WARMUP_MINUTES        — minutes of history to load on cold start (default: 60)
    DASHBOARD_URL         — URL of the dashboard to push state updates (optional)
    EVENTSTREAM_ENDPOINT  — Event Hub-compatible connection string for Eventstream
                            direct consumption (Phase 2).  When set, live events
                            are consumed from the Eventstream (~1s latency) and
                            Eventhouse polling is used only for warm-up.
    EVENTSTREAM_EVENTHUB  — Event Hub name within the Eventstream namespace
                            (default: surveillance-stream)
    CONSUMER_GROUP        — Consumer group for Eventstream (default: exchange name
                            or "$Default" for the all-exchanges worker)
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
for _sdk_logger in ("azure.identity", "azure.core", "azure.kusto", "msal",
                    "azure.eventhub", "uamqp"):
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
# Eventstream direct consumption (Phase 2)
# ---------------------------------------------------------------------------

try:
    from azure.eventhub import EventHubConsumerClient  # type: ignore
    HAS_EVENTHUB = True
except ImportError:
    HAS_EVENTHUB = False
    logger.warning(
        "azure-eventhub not installed — Eventstream direct mode unavailable. "
        "pip install azure-eventhub"
    )


class EventstreamConsumer:
    """
    Direct Eventstream consumer using the Event Hub-compatible endpoint.

    Consumes trade and order-book events from the Fabric Eventstream at
    approximately 1-second latency, replacing the 10-second Eventhouse
    polling loop for the live phase.

    Each partitioned worker subscribes with its exchange name as the
    consumer group so that per-exchange workers receive only their subset
    of events.

    Parameters
    ----------
    connection_string : str
        Event Hub-compatible connection string from the Fabric Eventstream
        custom app endpoint.  Set via ``EVENTSTREAM_ENDPOINT`` env var.
    eventhub_name : str
        Event Hub name within the Eventstream namespace.
        Set via ``EVENTSTREAM_EVENTHUB`` env var (default: ``surveillance-stream``).
    consumer_group : str
        Consumer group name.  Defaults to the exchange name or ``"$Default"``
        for the all-exchanges worker.
    pipeline : AgentPipeline
        The agent pipeline to push received events into.
    cross_market_only : bool
        When True only the CrossMarketAgent processes incoming events.
    """

    def __init__(
        self,
        connection_string: str,
        eventhub_name: str,
        consumer_group: str,
        pipeline: "AgentPipeline",
        cross_market_only: bool = False,
    ) -> None:
        if not HAS_EVENTHUB:
            raise RuntimeError(
                "azure-eventhub is required for Eventstream mode. "
                "pip install azure-eventhub"
            )
        self.connection_string = connection_string
        self.eventhub_name = eventhub_name
        self.consumer_group = consumer_group
        self.pipeline = pipeline
        self.cross_market_only = cross_market_only
        self._running = False

        self._client = EventHubConsumerClient.from_connection_string(
            connection_string,
            consumer_group=consumer_group,
            eventhub_name=eventhub_name,
        )
        logger.info(
            "EventstreamConsumer: connected to %s / consumer_group=%s",
            eventhub_name, consumer_group,
        )

    def start(self) -> None:
        """Start consuming events from Eventstream (blocking call)."""
        self._running = True
        logger.info("EventstreamConsumer: starting receive loop...")
        self._client.receive(
            on_event=self._on_event,
            starting_position="-1",  # latest events only (warm-up handled separately)
        )

    def stop(self) -> None:
        """Gracefully stop the consumer."""
        self._running = False
        try:
            self._client.close()
        except Exception:
            pass

    def _on_event(self, partition_context, event) -> None:
        """Callback invoked for each incoming Eventstream message."""
        try:
            body = event.body_as_str(encoding="UTF-8")
            data = json.loads(body)
            # Normalise the raw Eventstream payload into agent event format
            normalised = self._normalise_event(data)
            if normalised:
                self.pipeline.process_events([normalised],
                                             cross_market_only=self.cross_market_only)
        except Exception as exc:
            logger.warning("EventstreamConsumer: failed to process event — %s", exc)
        finally:
            partition_context.update_checkpoint(event)

    @staticmethod
    def _normalise_event(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a raw Eventstream JSON payload to the agent event format.

        The Eventstream schema matches the ``exchange_data_simulator.py``
        output, so the same normalization as Eventhouse rows is applied.
        The ``event_type`` field distinguishes TRADE from ORDER_BOOK events.

        When the payload already contains ``event_type`` and agent-friendly
        fields (i.e. simulator output forwarded directly), it is returned as-is.
        If the payload uses the Eventhouse KQL column names (``trade_id``,
        ``event_id``, ``event_time``) it is normalised via ``normalize_trade``
        or ``normalize_order``.
        """
        event_type = data.get("event_type", "")
        if event_type == "TRADE":
            # Re-normalise if the payload uses KQL column names
            return normalize_trade(data) if "trade_id" in data else data
        elif event_type == "ORDER_BOOK":
            return normalize_order(data) if "event_id" in data else data
        return None


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

HEALTHCHECK_PATH = Path("/tmp/worker-healthy")


class StreamingWorker:
    """
    Hybrid streaming worker: Eventhouse warm-up + optional Eventstream live push.

    On cold start the worker back-fills agent sliding windows by querying
    the last ``warmup_minutes`` of historical data from Eventhouse (KQL).

    After warm-up the worker switches to the most available live mode:

    1. **Eventstream-direct** (Phase 2, ~1s latency) — when
       ``EVENTSTREAM_ENDPOINT`` is configured, an ``EventstreamConsumer``
       subscribes to the Eventstream Event Hub-compatible endpoint.
    2. **Eventhouse-poll** (fallback, default 10s latency) — the traditional
       KQL polling loop for environments without an Eventstream endpoint.

    Supports per-exchange partitioning (``--exchange``) and the special
    ``cross-market`` partition that runs only the CrossMarketAgent.
    """

    def __init__(
        self,
        kql_uri: str,
        kql_db: str = "surveillance",
        poll_interval: int = 10,
        exchange: str = "",
        warmup_minutes: int = 60,
        eventstream_endpoint: str = "",
        eventstream_eventhub: str = "surveillance-stream",
        consumer_group: str = "",
    ):
        self.kql_uri = kql_uri
        self.kql_db = kql_db
        self.poll_interval = poll_interval
        self.exchange = exchange
        self.warmup_minutes = warmup_minutes
        self.eventstream_endpoint = eventstream_endpoint
        self.eventstream_eventhub = eventstream_eventhub
        # Default consumer group = exchange name or "$Default"
        self.consumer_group = consumer_group or (exchange if exchange and exchange != "cross-market" else "$Default")
        self._running = False

        # cross-market mode: fetch all exchanges but only run CrossMarketAgent
        self.cross_market_only = exchange == "cross-market"
        # For cross-market we need data from every exchange (no filter)
        self._exchange_filter = "" if self.cross_market_only else exchange

        # High-water marks for incremental polling
        self._trade_hwm = datetime.now(timezone.utc).isoformat()
        self._order_hwm = datetime.now(timezone.utc).isoformat()

        # Initialize
        self.eventhouse = EventhouseClient(kql_uri, kql_db)
        self.pipeline = AgentPipeline(eventhouse=self.eventhouse)
        self._eventstream_consumer: Optional[EventstreamConsumer] = None

        label = exchange if exchange else "all"
        logger.info(
            "Worker initialized: KQL=%s DB=%s poll=%ds exchange=%s warmup=%dm eventstream=%s",
            kql_uri, kql_db, poll_interval, label, warmup_minutes,
            "yes" if eventstream_endpoint else "no",
        )

    # ── Warm-up ───────────────────────────────────────────

    def _warmup(self) -> None:
        """Back-fill agent sliding windows with recent historical data."""
        if self.warmup_minutes <= 0:
            return

        logger.info("Warming up agents with last %d minutes of history...", self.warmup_minutes)
        warmup_since = (datetime.now(timezone.utc) - timedelta(minutes=self.warmup_minutes)).isoformat()

        trades_raw = self.eventhouse.fetch_new_trades(warmup_since, limit=50000, exchange=self._exchange_filter)
        orders_raw = self.eventhouse.fetch_new_orders(warmup_since, limit=50000, exchange=self._exchange_filter)

        trades = [normalize_trade(r) for r in trades_raw]
        orders = [normalize_order(r) for r in orders_raw]

        all_events = trades + orders
        all_events.sort(key=lambda e: e.get("timestamp", ""))

        if all_events:
            self.pipeline.process_events(all_events, cross_market_only=self.cross_market_only)

        # Set HWMs so the polling loop only fetches truly new events
        if trades_raw:
            self._trade_hwm = str(trades_raw[-1].get("event_time", self._trade_hwm))
        if orders_raw:
            self._order_hwm = str(orders_raw[-1].get("event_time", self._order_hwm))

        logger.info("Warm-up complete: processed %d events", len(all_events))

    # ── Healthcheck ───────────────────────────────────────

    @staticmethod
    def _touch_healthcheck() -> None:
        """Write healthcheck sentinel so liveness probes can verify the worker."""
        try:
            HEALTHCHECK_PATH.touch()
        except OSError:
            pass

    # ── Main loop ─────────────────────────────────────────

    def run(self) -> None:
        """
        Start the worker.

        After Eventhouse warm-up, the worker enters the best available live mode:
        - Eventstream-direct (when ``EVENTSTREAM_ENDPOINT`` is configured)
        - Eventhouse-poll fallback
        """
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        # Warm up agent windows before entering the live loop
        try:
            self._warmup()
        except Exception:
            logger.exception("Warm-up failed — starting with empty state")

        if self.eventstream_endpoint and HAS_EVENTHUB:
            self._run_eventstream()
        else:
            if self.eventstream_endpoint and not HAS_EVENTHUB:
                logger.warning(
                    "EVENTSTREAM_ENDPOINT set but azure-eventhub not installed — "
                    "falling back to Eventhouse polling."
                )
            self._run_poll_loop()

    def _run_eventstream(self) -> None:
        """Live mode: consume events directly from Eventstream (~1s latency)."""
        logger.info(
            "Worker started — Eventstream-direct mode | consumer_group=%s",
            self.consumer_group,
        )
        self._eventstream_consumer = EventstreamConsumer(
            connection_string=self.eventstream_endpoint,
            eventhub_name=self.eventstream_eventhub,
            consumer_group=self.consumer_group,
            pipeline=self.pipeline,
            cross_market_only=self.cross_market_only,
        )
        try:
            self._eventstream_consumer.start()  # blocking
        except KeyboardInterrupt:
            pass
        finally:
            self._eventstream_consumer.stop()
            self.pipeline.flush()
            logger.info("Worker stopped. Final stats: %s", self.pipeline.stats())

    def _run_poll_loop(self) -> None:
        """Live mode: poll Eventhouse every POLL_INTERVAL seconds (fallback)."""
        logger.info("Worker started — polling every %ds", self.poll_interval)
        cycle = 0

        while self._running:
            cycle += 1
            try:
                n = self._poll_and_process()
                self._touch_healthcheck()
                if n > 0 or cycle % 30 == 0:
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
        trades_raw = self.eventhouse.fetch_new_trades(self._trade_hwm, exchange=self._exchange_filter)
        trades = [normalize_trade(r) for r in trades_raw]
        if trades_raw:
            self._trade_hwm = str(trades_raw[-1].get("event_time", self._trade_hwm))

        # Fetch new orders
        orders_raw = self.eventhouse.fetch_new_orders(self._order_hwm, exchange=self._exchange_filter)
        orders = [normalize_order(r) for r in orders_raw]
        if orders_raw:
            self._order_hwm = str(orders_raw[-1].get("event_time", self._order_hwm))

        # Merge and sort by timestamp
        all_events = trades + orders
        all_events.sort(key=lambda e: e.get("timestamp", ""))

        if all_events:
            self.pipeline.process_events(all_events, cross_market_only=self.cross_market_only)

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
    parser.add_argument("--exchange",
                        default=os.environ.get("EXCHANGE_FILTER", ""),
                        help="Exchange partition filter (e.g. SGX, HKEX, NSE, cross-market)")
    parser.add_argument("--warmup-minutes", type=int,
                        default=int(os.environ.get("WARMUP_MINUTES", "60")),
                        help="Minutes of history to back-fill on cold start (default: 60)")
    parser.add_argument("--eventstream-endpoint",
                        default=os.environ.get("EVENTSTREAM_ENDPOINT", ""),
                        help="Event Hub-compatible connection string for Eventstream "
                             "direct consumption (Phase 2, ~1s latency)")
    parser.add_argument("--eventstream-eventhub",
                        default=os.environ.get("EVENTSTREAM_EVENTHUB", "surveillance-stream"),
                        help="Event Hub name within the Eventstream namespace "
                             "(default: surveillance-stream)")
    parser.add_argument("--consumer-group",
                        default=os.environ.get("CONSUMER_GROUP", ""),
                        help="Consumer group for Eventstream "
                             "(default: exchange name or '$Default')")
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
        exchange=args.exchange,
        warmup_minutes=args.warmup_minutes,
        eventstream_endpoint=args.eventstream_endpoint,
        eventstream_eventhub=args.eventstream_eventhub,
        consumer_group=args.consumer_group,
    )
    worker.run()


if __name__ == "__main__":
    main()
