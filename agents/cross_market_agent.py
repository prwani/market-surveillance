"""
Cross-Market Agent
==================
Detects coordinated manipulation across multiple exchanges by computing
lead-lag price correlations between related instruments (e.g. dual-listed
securities) and identifying synchronised volume spikes.

The agent mirrors the Spark / Direct Lake logic described in the README
(Section 5.2 – Cross-Market Agent) but runs entirely in Python so it can
be used against the exchange_data_simulator output without a Fabric cluster.

Algorithm
---------
1. Maintain per-symbol, per-exchange rolling 1-minute VWAP buckets (same
   structure as AnomalyDetectionAgent but stored for comparison).
2. When two exchanges share a symbol (or a configured symbol alias map),
   compute the Pearson correlation between their 1-minute VWAP series.
3. If |correlation| > ``correlation_threshold`` with a lag of 0-2 buckets,
   raise a COORDINATED_MANIPULATION alert.
4. Additionally flag cross-exchange volume synchronisation: if both exchanges
   show volume spikes within the same 1-minute window.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from .base_agent import Alert, AlertSeverity, BaseAgent, _utcnow_iso


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
HISTORY_BUCKETS = 30          # 30 one-minute buckets for correlation calc
CORRELATION_THRESHOLD = 0.85  # flag if |corr| exceeds this value
VOLUME_SYNC_RATIO = 2.0       # both exchanges must show > 2× their mean volume
BUCKET_SIZE_SECONDS = 60
MIN_BUCKETS_FOR_CORR = 10     # minimum history before correlation fires


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pearson(xs: List[float], ys: List[float]) -> float:
    """Compute Pearson correlation coefficient for two equal-length lists."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


@dataclass
class _VWAPRecord:
    bucket_id: int
    vwap: float
    volume: float


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class CrossMarketAgent(BaseAgent):
    """
    Cross-exchange lead-lag correlation detector.

    Parameters
    ----------
    symbol_aliases : dict, optional
        Mapping from a canonical symbol name to per-exchange ticker.
        Example: ``{"TENCENT": {"HKEX": "0700.HK", "SGX": "TCEHY"}}``.
        When provided the agent compares cross-listed instruments.
        If omitted the agent compares identical symbol strings across exchanges.
    correlation_threshold : float
        Pearson |r| above which a cross-market manipulation alert is raised.
    history_buckets : int
        Number of 1-minute VWAP buckets to retain per (exchange, symbol).
    """

    name = "CrossMarketAgent"

    def __init__(
        self,
        symbol_aliases: Optional[Dict[str, Dict[str, str]]] = None,
        correlation_threshold: float = CORRELATION_THRESHOLD,
        volume_sync_ratio: float = VOLUME_SYNC_RATIO,
        history_buckets: int = HISTORY_BUCKETS,
        bucket_size_seconds: int = BUCKET_SIZE_SECONDS,
    ) -> None:
        super().__init__()
        self._symbol_aliases = symbol_aliases or {}
        self._corr_threshold = correlation_threshold
        self._vol_sync_ratio = volume_sync_ratio
        self._history_buckets = history_buckets
        self._bucket_size = bucket_size_seconds

        # (exchange, symbol) → deque of _VWAPRecord
        self._vwap_history: Dict[Tuple[str, str], Deque[_VWAPRecord]] = defaultdict(
            lambda: deque(maxlen=self._history_buckets)
        )
        # (exchange, symbol) → current open _MinuteBucket
        self._open_buckets: Dict[Tuple[str, str], _OpenBucket] = {}
        # Throttle: (symbol_pair) → last alerted bucket_id
        self._last_alerted: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process_event(self, event: Dict[str, Any]) -> None:
        if event.get("event_type") != "TRADE":
            return
        self._ingest(event)

    def flush(self) -> None:
        """Finalise all open buckets and trigger cross-market evaluation."""
        for key, bucket in list(self._open_buckets.items()):
            if bucket.trade_count > 0:
                self._finalise_bucket(key, bucket)
        self._open_buckets.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_epoch(self, ts: str) -> float:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return 0.0

    def _canonical_symbol(self, exchange_id: str, symbol: str) -> str:
        """Return the canonical symbol name for cross-exchange comparison."""
        for canonical, ex_map in self._symbol_aliases.items():
            if ex_map.get(exchange_id) == symbol:
                return canonical
        return symbol  # use the ticker itself as canonical name

    def _ingest(self, event: Dict[str, Any]) -> None:
        exchange_id = event.get("exchange_id", "")
        symbol = event.get("symbol", "")
        price = float(event.get("price", 0))
        qty = int(event.get("quantity", 0))
        ts_epoch = self._parse_epoch(event.get("timestamp", ""))
        bucket_id = int(ts_epoch // self._bucket_size)

        key = (exchange_id, symbol)
        current = self._open_buckets.get(key)

        if current is None or current.bucket_id != bucket_id:
            if current is not None and current.trade_count > 0:
                self._finalise_bucket(key, current)
            self._open_buckets[key] = _OpenBucket(bucket_id=bucket_id)
            current = self._open_buckets[key]

        current.add(price, qty)

    def _finalise_bucket(
        self, key: Tuple[str, str], bucket: "_OpenBucket"
    ) -> None:
        exchange_id, symbol = key
        canonical = self._canonical_symbol(exchange_id, symbol)

        record = _VWAPRecord(
            bucket_id=bucket.bucket_id,
            vwap=bucket.vwap,
            volume=bucket.volume,
        )
        self._vwap_history[key].append(record)

        # Find all other exchanges that share the same canonical symbol
        partner_exchanges = [
            ex for (ex, sym) in self._vwap_history.keys()
            if ex != exchange_id and self._canonical_symbol(ex, sym) == canonical
        ]

        for partner_exchange in partner_exchanges:
            partner_symbol = self._get_symbol(partner_exchange, canonical)
            partner_key = (partner_exchange, partner_symbol)
            self._compare_pair(
                key, partner_key,
                exchange_id, symbol,
                partner_exchange, partner_symbol,
                canonical,
            )

    def _get_symbol(self, exchange_id: str, canonical: str) -> str:
        """Reverse-lookup: canonical → per-exchange ticker."""
        ex_map = self._symbol_aliases.get(canonical, {})
        return ex_map.get(exchange_id, canonical)

    def _compare_pair(
        self,
        key_a: Tuple[str, str],
        key_b: Tuple[str, str],
        exchange_a: str,
        symbol_a: str,
        exchange_b: str,
        symbol_b: str,
        canonical: str,
    ) -> None:
        hist_a = list(self._vwap_history[key_a])
        hist_b = list(self._vwap_history[key_b])

        if len(hist_a) < MIN_BUCKETS_FOR_CORR or len(hist_b) < MIN_BUCKETS_FOR_CORR:
            return

        # Align by bucket_id
        ids_a = {r.bucket_id: r for r in hist_a}
        ids_b = {r.bucket_id: r for r in hist_b}
        common_ids = sorted(set(ids_a) & set(ids_b))

        if len(common_ids) < MIN_BUCKETS_FOR_CORR:
            return

        vwaps_a = [ids_a[i].vwap for i in common_ids]
        vwaps_b = [ids_b[i].vwap for i in common_ids]
        vols_a = [ids_a[i].volume for i in common_ids]
        vols_b = [ids_b[i].volume for i in common_ids]

        corr = _pearson(vwaps_a, vwaps_b)

        # Check volume synchronisation
        mean_vol_a = sum(vols_a) / len(vols_a) if vols_a else 1
        mean_vol_b = sum(vols_b) / len(vols_b) if vols_b else 1
        last_vol_a = vols_a[-1] if vols_a else 0
        last_vol_b = vols_b[-1] if vols_b else 0
        vol_synced = (
            last_vol_a > mean_vol_a * self._vol_sync_ratio
            and last_vol_b > mean_vol_b * self._vol_sync_ratio
        )

        pair_key = f"{canonical}:{min(exchange_a, exchange_b)}:{max(exchange_a, exchange_b)}"
        last_alerted_bucket = self._last_alerted.get(pair_key, -1)
        latest_bucket = common_ids[-1]

        if abs(corr) >= self._corr_threshold and latest_bucket != last_alerted_bucket:
            self._last_alerted[pair_key] = latest_bucket
            self._emit_alert(Alert(
                alert_id=f"CROSS-{uuid.uuid4().hex[:8].upper()}",
                agent_name=self.name,
                alert_type="COORDINATED_MANIPULATION",
                severity=AlertSeverity.CRITICAL if vol_synced else AlertSeverity.HIGH,
                exchange_id=exchange_a,
                symbol=symbol_a,
                detected_at=_utcnow_iso(),
                description=(
                    f"Cross-market correlation detected for {canonical}: "
                    f"{exchange_a}/{symbol_a} and {exchange_b}/{symbol_b} "
                    f"show Pearson r={corr:.3f} over {len(common_ids)} minutes"
                    + (" with synchronised volume spikes." if vol_synced else ".")
                ),
                confidence_score=min(1.0, abs(corr)),
                involved_entities=[exchange_a, exchange_b],
                evidence={
                    "canonical_symbol": canonical,
                    "exchange_a": exchange_a,
                    "symbol_a": symbol_a,
                    "exchange_b": exchange_b,
                    "symbol_b": symbol_b,
                    "pearson_r": round(corr, 4),
                    "common_buckets": len(common_ids),
                    "volume_synchronised": vol_synced,
                },
                is_cross_market=True,
                related_exchanges=[exchange_a, exchange_b],
            ))


# ---------------------------------------------------------------------------
# Minimal open-bucket helper (avoids importing from anomaly agent)
# ---------------------------------------------------------------------------

class _OpenBucket:
    def __init__(self, bucket_id: int) -> None:
        self.bucket_id = bucket_id
        self._sum_price_qty = 0.0
        self._sum_qty = 0.0
        self.trade_count = 0

    def add(self, price: float, qty: int) -> None:
        self._sum_price_qty += price * qty
        self._sum_qty += qty
        self.trade_count += 1

    @property
    def vwap(self) -> float:
        return self._sum_price_qty / self._sum_qty if self._sum_qty > 0 else 0.0

    @property
    def volume(self) -> float:
        return self._sum_qty
