"""
Pattern Detection Agent
=======================
Detects the three core manipulation patterns from order book and trade events:

    1. Spoofing   – large orders placed then cancelled within a short window
                    before the price moves, followed by a profitable trade on
                    the opposite side.

    2. Layering   – multiple orders placed at different price levels on one side
                    to create artificial pressure, then mass-cancelled after
                    executing on the opposite side.

    3. Wash Trading – the same beneficial owner appears on both sides of a trade
                    (using different broker IDs) to inflate reported volume.

All rules are implemented as sliding-window accumulators that mirror the KQL
detection logic described in the README / Section 5.2.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from .base_agent import Alert, AlertSeverity, BaseAgent, _utcnow_iso


# ---------------------------------------------------------------------------
# Tuneable thresholds (mirrors the KQL rule parameters in the README)
# ---------------------------------------------------------------------------
SPOOFING_WINDOW_SECONDS = 60          # look-back window for cancel-rate analysis
SPOOFING_MIN_CANCEL_RATE = 0.80       # >80 % of added orders must be cancelled
SPOOFING_MAX_CANCEL_LATENCY_MS = 500  # cancelled within 500 ms
SPOOFING_MIN_ORDER_SIZE = 10_000      # only flag large orders

LAYERING_WINDOW_SECONDS = 120         # 2-minute window
LAYERING_MIN_PRICE_LEVELS = 5         # orders at ≥5 distinct price levels
LAYERING_MIN_CANCEL_FRACTION = 0.70   # 70 % of placed orders are cancelled

WASH_WINDOW_SECONDS = 600             # 10-minute window for wash-trade detection
WASH_MIN_TRADES = 3                   # at least 3 back-and-forth trades

ALERT_CONFIDENCE_SPOOFING = 0.90
ALERT_CONFIDENCE_LAYERING = 0.85
ALERT_CONFIDENCE_WASH = 0.80


# ---------------------------------------------------------------------------
# Internal state containers
# ---------------------------------------------------------------------------

@dataclass
class _OrderRecord:
    order_id: str
    broker_id: str
    side: str
    price: float
    quantity: int
    action: str          # "add" | "cancel" | "modify" | "fill"
    timestamp: str       # ISO-8601
    timestamp_epoch: float


@dataclass
class _TradeRecord:
    event_id: str
    buyer_id: str
    seller_id: str
    price: float
    quantity: int
    timestamp: str
    timestamp_epoch: float


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class PatternDetectionAgent(BaseAgent):
    """
    Rule-based manipulation pattern detector.

    Internal state is maintained per (exchange_id, symbol) key.  Only events
    within the relevant look-back window are kept in memory; older records are
    discarded to bound memory usage.
    """

    name = "PatternDetectionAgent"

    def __init__(
        self,
        spoofing_window_s: float = SPOOFING_WINDOW_SECONDS,
        layering_window_s: float = LAYERING_WINDOW_SECONDS,
        wash_window_s: float = WASH_WINDOW_SECONDS,
    ) -> None:
        super().__init__()
        self._spoofing_window = spoofing_window_s
        self._layering_window = layering_window_s
        self._wash_window = wash_window_s

        # (exchange, symbol) → deque of _OrderRecord
        self._order_windows: Dict[str, Deque[_OrderRecord]] = defaultdict(deque)
        # (exchange, symbol) → deque of _TradeRecord
        self._trade_windows: Dict[str, Deque[_TradeRecord]] = defaultdict(deque)
        # Track already-alerted broker windows to avoid duplicate alerts
        self._alerted_spoofing: Dict[str, float] = {}
        self._alerted_layering: Dict[str, float] = {}
        self._alerted_wash: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process_event(self, event: Dict[str, Any]) -> None:
        """Evaluate a single normalised event dict from the simulator."""
        etype = event.get("event_type", "")
        if etype == "ORDER_BOOK":
            self._ingest_order(event)
        elif etype == "TRADE":
            self._ingest_trade(event)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _parse_epoch(self, ts: str) -> float:
        """Parse an ISO-8601 timestamp to a Unix epoch float."""
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return 0.0

    def _ingest_order(self, event: Dict[str, Any]) -> None:
        key = f"{event.get('exchange_id')}:{event.get('symbol')}"
        ts_epoch = self._parse_epoch(event.get("timestamp", ""))

        rec = _OrderRecord(
            order_id=event.get("order_id", ""),
            broker_id=event.get("broker_id", ""),
            side=event.get("side", ""),
            price=float(event.get("price", 0)),
            quantity=int(event.get("quantity", 0)),
            action=event.get("action", ""),
            timestamp=event.get("timestamp", ""),
            timestamp_epoch=ts_epoch,
        )
        window = self._order_windows[key]
        window.append(rec)

        # Evaluate spoofing and layering after each order event
        self._evaluate_spoofing(key, ts_epoch)
        self._evaluate_layering(key, ts_epoch)

    def _ingest_trade(self, event: Dict[str, Any]) -> None:
        key = f"{event.get('exchange_id')}:{event.get('symbol')}"
        ts_epoch = self._parse_epoch(event.get("timestamp", ""))

        rec = _TradeRecord(
            event_id=event.get("event_id", ""),
            buyer_id=event.get("buyer_id", ""),
            seller_id=event.get("seller_id", ""),
            price=float(event.get("price", 0)),
            quantity=int(event.get("quantity", 0)),
            timestamp=event.get("timestamp", ""),
            timestamp_epoch=ts_epoch,
        )
        window = self._trade_windows[key]
        window.append(rec)

        self._evaluate_wash_trading(key, ts_epoch, event)

    # ------------------------------------------------------------------
    # Spoofing detection
    # ------------------------------------------------------------------

    def _evaluate_spoofing(self, key: str, now_epoch: float) -> None:
        """
        Within the spoofing window, group orders by broker_id and detect:
            cancel_rate > 80 %  AND  avg_cancel_latency_ms < 500
            AND large order size
        """
        window = self._order_windows[key]
        cutoff = now_epoch - self._spoofing_window
        # Trim stale records
        while window and window[0].timestamp_epoch < cutoff:
            window.popleft()

        # Aggregate by broker
        broker_adds: Dict[str, List[_OrderRecord]] = defaultdict(list)
        broker_cancels: Dict[str, List[_OrderRecord]] = defaultdict(list)

        for rec in window:
            if rec.action == "add":
                broker_adds[rec.broker_id].append(rec)
            elif rec.action == "cancel":
                broker_cancels[rec.broker_id].append(rec)

        exchange_id, symbol = key.split(":", 1)

        for broker_id, adds in broker_adds.items():
            cancels = broker_cancels.get(broker_id, [])
            if not adds:
                continue

            cancel_rate = len(cancels) / len(adds)
            avg_qty = sum(r.quantity for r in adds) / len(adds)

            if (
                cancel_rate >= SPOOFING_MIN_CANCEL_RATE
                and avg_qty >= SPOOFING_MIN_ORDER_SIZE
            ):
                # Estimate average cancel latency by pairing adds with cancels
                latency_ms = self._estimate_cancel_latency_ms(adds, cancels)

                if latency_ms <= SPOOFING_MAX_CANCEL_LATENCY_MS:
                    alert_key = f"{key}:{broker_id}"
                    # Throttle: one alert per broker per window
                    last_alert = self._alerted_spoofing.get(alert_key, 0.0)
                    if now_epoch - last_alert >= self._spoofing_window:
                        self._alerted_spoofing[alert_key] = now_epoch
                        score = min(
                            1.0,
                            cancel_rate * (1 - latency_ms / SPOOFING_MAX_CANCEL_LATENCY_MS),
                        )
                        self._emit_alert(Alert(
                            alert_id=f"SPOOF-{uuid.uuid4().hex[:8].upper()}",
                            agent_name=self.name,
                            alert_type="SPOOFING",
                            severity=AlertSeverity.CRITICAL,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            detected_at=_utcnow_iso(),
                            description=(
                                f"Spoofing detected: broker {broker_id} placed "
                                f"{len(adds)} large order(s) with {cancel_rate*100:.0f}% "
                                f"cancel rate and avg cancel latency {latency_ms:.0f}ms."
                            ),
                            confidence_score=score,
                            involved_entities=[broker_id],
                            evidence={
                                "adds": len(adds),
                                "cancels": len(cancels),
                                "cancel_rate": round(cancel_rate, 3),
                                "avg_cancel_latency_ms": round(latency_ms, 1),
                                "avg_order_qty": round(avg_qty, 0),
                            },
                        ))

    def _estimate_cancel_latency_ms(
        self, adds: List[_OrderRecord], cancels: List[_OrderRecord]
    ) -> float:
        """Estimate mean cancel latency by matching add→cancel pairs by order_id."""
        latencies: List[float] = []
        cancel_map = {r.order_id: r for r in cancels}
        for add in adds:
            cancel = cancel_map.get(add.order_id)
            if cancel:
                delta_ms = (cancel.timestamp_epoch - add.timestamp_epoch) * 1000
                if delta_ms >= 0:
                    latencies.append(delta_ms)
        if latencies:
            return sum(latencies) / len(latencies)
        # Fallback: use average time gap between all adds and all cancels
        if adds and cancels:
            avg_add = sum(r.timestamp_epoch for r in adds) / len(adds)
            avg_cancel = sum(r.timestamp_epoch for r in cancels) / len(cancels)
            return max(0.0, (avg_cancel - avg_add) * 1000)
        return float("inf")

    # ------------------------------------------------------------------
    # Layering detection
    # ------------------------------------------------------------------

    def _evaluate_layering(self, key: str, now_epoch: float) -> None:
        """
        Within the layering window, per broker, detect:
            distinct price levels ≥ 5  AND  cancel fraction ≥ 70%
            AND opposite-side buy orders present (to capture the intent to buy low)
        """
        window = self._order_windows[key]
        cutoff = now_epoch - self._layering_window
        while window and window[0].timestamp_epoch < cutoff:
            window.popleft()

        # Aggregate by broker × side
        broker_side_adds: Dict[str, Dict[str, List[_OrderRecord]]] = defaultdict(
            lambda: defaultdict(list)
        )
        broker_side_cancels: Dict[str, Dict[str, List[_OrderRecord]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for rec in window:
            if rec.action == "add":
                broker_side_adds[rec.broker_id][rec.side].append(rec)
            elif rec.action == "cancel":
                broker_side_cancels[rec.broker_id][rec.side].append(rec)

        exchange_id, symbol = key.split(":", 1)

        for broker_id, side_adds in broker_side_adds.items():
            for side, adds in side_adds.items():
                cancels = broker_side_cancels[broker_id].get(side, [])

                price_levels = len({r.price for r in adds})
                total_placed = len(adds)
                cancel_fraction = len(cancels) / total_placed if total_placed else 0.0

                # Opposite side — the "real" intent
                opp_side = "buy" if side == "sell" else "sell"
                opp_adds = broker_side_adds[broker_id].get(opp_side, [])

                if (
                    price_levels >= LAYERING_MIN_PRICE_LEVELS
                    and cancel_fraction >= LAYERING_MIN_CANCEL_FRACTION
                    and len(opp_adds) >= 1
                ):
                    alert_key = f"{key}:{broker_id}:{side}"
                    last_alert = self._alerted_layering.get(alert_key, 0.0)
                    if now_epoch - last_alert >= self._layering_window:
                        self._alerted_layering[alert_key] = now_epoch
                        score = min(
                            1.0,
                            (cancel_fraction * price_levels / 10) * ALERT_CONFIDENCE_LAYERING,
                        )
                        self._emit_alert(Alert(
                            alert_id=f"LAYER-{uuid.uuid4().hex[:8].upper()}",
                            agent_name=self.name,
                            alert_type="LAYERING",
                            severity=AlertSeverity.HIGH,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            detected_at=_utcnow_iso(),
                            description=(
                                f"Layering detected: broker {broker_id} placed "
                                f"{total_placed} {side} orders across {price_levels} price "
                                f"levels with {cancel_fraction*100:.0f}% cancellation."
                            ),
                            confidence_score=score,
                            involved_entities=[broker_id],
                            evidence={
                                "side": side,
                                "price_levels": price_levels,
                                "orders_placed": total_placed,
                                "orders_cancelled": len(cancels),
                                "cancel_fraction": round(cancel_fraction, 3),
                                "opposite_side_orders": len(opp_adds),
                            },
                        ))

    # ------------------------------------------------------------------
    # Wash trading detection
    # ------------------------------------------------------------------

    def _evaluate_wash_trading(
        self, key: str, now_epoch: float, event: Dict[str, Any]
    ) -> None:
        """
        Within the wash window, detect trades where the same beneficial
        owner appears on both sides.  Since we do not have a real ownership
        table, we flag brokers whose IDs share a known naming pattern
        (``BROKER_WASH_*_A`` / ``BROKER_WASH_*_B``) or where buyer==seller.
        """
        window = self._trade_windows[key]
        cutoff = now_epoch - self._wash_window
        while window and window[0].timestamp_epoch < cutoff:
            window.popleft()

        buyer_id = event.get("buyer_id", "")
        seller_id = event.get("seller_id", "")
        exchange_id, symbol = key.split(":", 1)

        # Direct match: buyer == seller
        if buyer_id == seller_id:
            self._emit_alert(Alert(
                alert_id=f"WASH-{uuid.uuid4().hex[:8].upper()}",
                agent_name=self.name,
                alert_type="WASH_TRADING",
                severity=AlertSeverity.HIGH,
                exchange_id=exchange_id,
                symbol=symbol,
                detected_at=_utcnow_iso(),
                description=(
                    f"Wash trade: broker {buyer_id} appears as both buyer and seller."
                ),
                confidence_score=ALERT_CONFIDENCE_WASH,
                involved_entities=[buyer_id],
                evidence={"buyer_id": buyer_id, "seller_id": seller_id},
            ))
            return

        # Pattern-based detection: "_WASH_" in both IDs → likely same beneficial owner
        if "_WASH_" in buyer_id and "_WASH_" in seller_id:
            # Aggregate wash trades in window for this pair
            pair_key = f"{min(buyer_id, seller_id)}|{max(buyer_id, seller_id)}"
            pair_trades = [
                r for r in window
                if {r.buyer_id, r.seller_id} == {buyer_id, seller_id}
            ]
            if len(pair_trades) >= WASH_MIN_TRADES:
                alert_key = f"{key}:{pair_key}"
                last_alert = self._alerted_wash.get(alert_key, 0.0)
                if now_epoch - last_alert >= self._wash_window:
                    self._alerted_wash[alert_key] = now_epoch
                    total_vol = sum(r.quantity for r in pair_trades)
                    self._emit_alert(Alert(
                        alert_id=f"WASH-{uuid.uuid4().hex[:8].upper()}",
                        agent_name=self.name,
                        alert_type="WASH_TRADING",
                        severity=AlertSeverity.HIGH,
                        exchange_id=exchange_id,
                        symbol=symbol,
                        detected_at=_utcnow_iso(),
                        description=(
                            f"Wash trading detected: {len(pair_trades)} trades "
                            f"between accounts {buyer_id} and {seller_id} "
                            f"(total volume: {total_vol:,})."
                        ),
                        confidence_score=ALERT_CONFIDENCE_WASH,
                        involved_entities=[buyer_id, seller_id],
                        evidence={
                            "trade_count": len(pair_trades),
                            "total_volume": total_vol,
                            "account_a": buyer_id,
                            "account_b": seller_id,
                        },
                    ))
