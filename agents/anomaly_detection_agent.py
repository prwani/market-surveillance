"""
Anomaly Detection Agent
=======================
Detects unusual price movements and volume spikes in trade event streams
using lightweight statistical methods (Z-score / rolling mean-std) that
mirror the KQL ``series_decompose_anomalies`` approach described in the
README / Section 5.2.

Two sub-detectors are implemented:

    PriceAnomalyDetector  – flags 1-minute VWAP values that deviate more
                            than ``price_z_threshold`` standard deviations
                            from the rolling mean.

    VolumeAnomalyDetector – flags 1-minute trade volume that exceeds
                            ``volume_z_threshold`` standard deviations above
                            the rolling mean.

Both operate per (exchange_id, symbol) key and maintain a configurable
rolling window of historical 1-minute buckets.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from .base_agent import Alert, AlertSeverity, BaseAgent, _utcnow_iso


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PRICE_HISTORY_BUCKETS = 60     # 60 one-minute buckets (1 hour of history)
VOLUME_HISTORY_BUCKETS = 60
PRICE_Z_THRESHOLD = 2.5        # flag if VWAP deviates > 2.5 std-devs
VOLUME_Z_THRESHOLD = 3.0       # flag if volume exceeds mean + 3.0 std-devs
BUCKET_SIZE_SECONDS = 60       # 1-minute aggregation


# ---------------------------------------------------------------------------
# Rolling statistics helper
# ---------------------------------------------------------------------------

class _RollingStats:
    """Maintains a fixed-length deque of floats and exposes mean / std."""

    def __init__(self, maxlen: int) -> None:
        self._data: Deque[float] = deque(maxlen=maxlen)

    def push(self, value: float) -> None:
        self._data.append(value)

    def mean(self) -> float:
        if not self._data:
            return 0.0
        return sum(self._data) / len(self._data)

    def std(self) -> float:
        if len(self._data) < 2:
            return 0.0
        m = self.mean()
        variance = sum((x - m) ** 2 for x in self._data) / (len(self._data) - 1)
        return math.sqrt(variance)

    def z_score(self, value: float) -> float:
        s = self.std()
        if s == 0.0:
            return 0.0
        return (value - self.mean()) / s

    def __len__(self) -> int:
        return len(self._data)


# ---------------------------------------------------------------------------
# Per-symbol bucket accumulators
# ---------------------------------------------------------------------------

@dataclass
class _MinuteBucket:
    bucket_id: int          # epoch // BUCKET_SIZE_SECONDS
    sum_price_qty: float = 0.0
    sum_qty: float = 0.0
    trade_count: int = 0
    first_price: float = 0.0
    last_price: float = 0.0

    def add_trade(self, price: float, qty: int) -> None:
        self.sum_price_qty += price * qty
        self.sum_qty += qty
        self.trade_count += 1
        if self.first_price == 0.0:
            self.first_price = price
        self.last_price = price

    @property
    def vwap(self) -> float:
        return self.sum_price_qty / self.sum_qty if self.sum_qty > 0 else 0.0

    @property
    def volume(self) -> float:
        return self.sum_qty


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AnomalyDetectionAgent(BaseAgent):
    """
    Statistical price and volume anomaly detector.

    Aggregates trade events into 1-minute VWAP buckets, then applies
    Z-score anomaly detection using a rolling history of completed buckets.
    """

    name = "AnomalyDetectionAgent"

    def __init__(
        self,
        price_history_buckets: int = PRICE_HISTORY_BUCKETS,
        volume_history_buckets: int = VOLUME_HISTORY_BUCKETS,
        price_z_threshold: float = PRICE_Z_THRESHOLD,
        volume_z_threshold: float = VOLUME_Z_THRESHOLD,
        bucket_size_seconds: int = BUCKET_SIZE_SECONDS,
    ) -> None:
        super().__init__()
        self._price_history_buckets = price_history_buckets
        self._volume_history_buckets = volume_history_buckets
        self._price_z_threshold = price_z_threshold
        self._volume_z_threshold = volume_z_threshold
        self._bucket_size = bucket_size_seconds

        # Per (exchange, symbol) current open bucket
        self._current_bucket: Dict[str, _MinuteBucket] = {}
        # Per (exchange, symbol) rolling stats
        self._price_stats: Dict[str, _RollingStats] = defaultdict(
            lambda: _RollingStats(self._price_history_buckets)
        )
        self._volume_stats: Dict[str, _RollingStats] = defaultdict(
            lambda: _RollingStats(self._volume_history_buckets)
        )
        # Per (exchange, symbol) last alerted bucket to avoid duplicates
        self._last_alerted_bucket: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process_event(self, event: Dict[str, Any]) -> None:
        if event.get("event_type") != "TRADE":
            return  # only trade events carry price/volume information
        self._ingest_trade(event)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_epoch(self, ts: str) -> float:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return 0.0

    def _ingest_trade(self, event: Dict[str, Any]) -> None:
        exchange_id = event.get("exchange_id", "")
        symbol = event.get("symbol", "")
        key = f"{exchange_id}:{symbol}"
        price = float(event.get("price", 0))
        qty = int(event.get("quantity", 0))
        ts_epoch = self._parse_epoch(event.get("timestamp", ""))
        bucket_id = int(ts_epoch // self._bucket_size)

        current = self._current_bucket.get(key)

        if current is None or current.bucket_id != bucket_id:
            # Finalise the previous bucket (if any) and evaluate anomalies
            if current is not None and current.trade_count > 0:
                self._finalise_bucket(key, current, exchange_id, symbol)
            # Open a new bucket
            self._current_bucket[key] = _MinuteBucket(bucket_id=bucket_id)
            current = self._current_bucket[key]

        current.add_trade(price, qty)

    def _finalise_bucket(
        self,
        key: str,
        bucket: _MinuteBucket,
        exchange_id: str,
        symbol: str,
    ) -> None:
        """Push completed bucket into rolling stats and check for anomalies."""
        vwap = bucket.vwap
        volume = bucket.volume

        price_stats = self._price_stats[key]
        volume_stats = self._volume_stats[key]

        # Need at least a few history points before we start alerting
        if len(price_stats) >= 5:
            price_z = price_stats.z_score(vwap)
            volume_z = volume_stats.z_score(volume)
            last = self._last_alerted_bucket.get(key, -1)

            if abs(price_z) >= self._price_z_threshold and bucket.bucket_id != last:
                self._last_alerted_bucket[key] = bucket.bucket_id
                direction = "spike" if price_z > 0 else "crash"
                magnitude_pct = abs((vwap - price_stats.mean()) / price_stats.mean() * 100)
                self._emit_alert(Alert(
                    alert_id=f"ANOM-PRICE-{uuid.uuid4().hex[:8].upper()}",
                    agent_name=self.name,
                    alert_type="PRICE_ANOMALY",
                    severity=(
                        AlertSeverity.CRITICAL
                        if abs(price_z) >= self._price_z_threshold * 1.5
                        else AlertSeverity.HIGH
                    ),
                    exchange_id=exchange_id,
                    symbol=symbol,
                    detected_at=_utcnow_iso(),
                    description=(
                        f"Price {direction}: VWAP {vwap:.4f} deviates "
                        f"{abs(price_z):.1f} std-devs from rolling mean "
                        f"({price_stats.mean():.4f}). "
                        f"Magnitude: {magnitude_pct:.2f}%."
                    ),
                    confidence_score=min(1.0, abs(price_z) / (self._price_z_threshold * 2)),
                    evidence={
                        "vwap": round(vwap, 4),
                        "rolling_mean": round(price_stats.mean(), 4),
                        "rolling_std": round(price_stats.std(), 4),
                        "z_score": round(price_z, 2),
                        "magnitude_pct": round(magnitude_pct, 2),
                        "direction": direction,
                        "bucket_id": bucket.bucket_id,
                        "trade_count": bucket.trade_count,
                    },
                ))

            if volume_z >= self._volume_z_threshold and bucket.bucket_id != last:
                self._last_alerted_bucket[key] = bucket.bucket_id
                self._emit_alert(Alert(
                    alert_id=f"ANOM-VOL-{uuid.uuid4().hex[:8].upper()}",
                    agent_name=self.name,
                    alert_type="VOLUME_SPIKE",
                    severity=AlertSeverity.MEDIUM,
                    exchange_id=exchange_id,
                    symbol=symbol,
                    detected_at=_utcnow_iso(),
                    description=(
                        f"Volume spike: {volume:,.0f} shares in 1 minute "
                        f"({volume_z:.1f} std-devs above rolling mean "
                        f"{volume_stats.mean():,.0f})."
                    ),
                    confidence_score=min(1.0, volume_z / (self._volume_z_threshold * 2)),
                    evidence={
                        "volume": volume,
                        "rolling_mean_volume": round(volume_stats.mean(), 0),
                        "rolling_std_volume": round(volume_stats.std(), 0),
                        "z_score": round(volume_z, 2),
                        "bucket_id": bucket.bucket_id,
                        "trade_count": bucket.trade_count,
                    },
                ))

        # Commit bucket values to rolling history
        price_stats.push(vwap)
        volume_stats.push(volume)

    def flush(self) -> None:
        """
        Finalise all open buckets.  Call this after feeding all events to
        ensure the last (possibly partial) bucket is evaluated.
        """
        for key, bucket in list(self._current_bucket.items()):
            if bucket.trade_count > 0:
                exchange_id, symbol = key.split(":", 1)
                self._finalise_bucket(key, bucket, exchange_id, symbol)
        self._current_bucket.clear()
