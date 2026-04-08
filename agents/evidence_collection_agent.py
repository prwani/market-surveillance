"""
Evidence Collection Agent
=========================
Compiles audit trails and generates regulatory-ready case reports for
confirmed manipulation events (Section 5.2 of the architecture README).

Responsibilities
----------------
1. Collect all order book and trade events that are causally related to a
   detected manipulation case (within a configurable evidence window).
2. Compute summary statistics (involved brokers, price impact, volume).
3. Generate a structured case report dictionary suitable for:
   - Regulatory portal submission (MAS / SFC / SEBI)
   - Internal audit log storage in Eventhouse (OneLake)
   - Optional GenAI narrative generation (GPT-4o prompt template included)

GenAI integration
-----------------
When an ``openai_client`` is provided (or when the ``OPENAI_API_KEY``
environment variable is set), ``generate_narrative`` calls the OpenAI Chat
Completions API using the prompt template from README Section 5.2.
Otherwise a structured plain-text narrative is assembled locally without
any external dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base_agent import Alert, BaseAgent, _utcnow_iso
from .intervention_agent import InterventionCase, REGULATOR_MAP


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence window (seconds before and after the detected event)
# ---------------------------------------------------------------------------
DEFAULT_EVIDENCE_WINDOW_SECONDS = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Prompt template (mirrors README Section 5.2)
# ---------------------------------------------------------------------------

_EVIDENCE_PROMPT_TEMPLATE = """\
You are a financial market surveillance expert. Analyze the following trading \
data and produce a formal regulatory evidence report.

CASE ID: {case_id}
EXCHANGE: {exchange_id}
SYMBOL: {symbol}
DETECTED MANIPULATION TYPE: {manipulation_type}
TIME WINDOW: {start_time} to {end_time}

ORDER BOOK EVENTS (chronological):
{order_book_events}

TRADE EVENTS:
{trade_events}

ML DETECTION SCORES:
- Spoofing Score: {spoofing_score:.3f}
- Layering Score: {layering_score:.3f}
- Anomaly Score: {anomaly_score:.3f}

INVOLVED ENTITIES:
{involved_entities}

Produce:
1. Executive Summary (2 paragraphs, suitable for senior regulator)
2. Timeline of Events (bullet points, chronological)
3. Evidence of Intent (explain why this is likely intentional manipulation)
4. Market Impact Analysis (estimated price distortion, affected investors)
5. Recommended Regulatory Action
6. Supporting Data References (cite specific orders/trades by ID)

Regulatory jurisdiction: {regulatory_body}
Language: {language}
"""


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

@dataclass
class CaseReport:
    """Structured case report produced by the Evidence Collection Agent."""

    report_id: str
    case_id: str
    generated_at: str
    exchange_id: str
    symbol: str
    manipulation_type: str
    regulatory_body: str
    involved_entities: List[str]
    evidence_window_start: str
    evidence_window_end: str
    # Event summary
    related_order_events: List[Dict[str, Any]] = field(default_factory=list)
    related_trade_events: List[Dict[str, Any]] = field(default_factory=list)
    # Statistics
    price_impact_pct: float = 0.0
    total_volume_affected: int = 0
    estimated_gain: float = 0.0
    # Detection scores
    spoofing_score: float = 0.0
    layering_score: float = 0.0
    anomaly_score: float = 0.0
    # Narrative
    narrative: str = ""
    # Intervention reference
    intervention_actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class EvidenceCollectionAgent(BaseAgent):
    """
    Compiles evidence and generates regulatory case reports.

    Parameters
    ----------
    evidence_window_seconds : int
        How many seconds before and after detection to include in evidence.
    openai_client : callable, optional
        A callable ``(prompt: str) -> str`` that calls the GenAI API.
        If ``None`` and ``OPENAI_API_KEY`` is set, the agent will attempt to
        import ``openai`` and call ``gpt-4o``.  Otherwise a template-based
        narrative is generated locally.
    language : str
        Language for the GenAI narrative (English | Simplified Chinese |
        Traditional Chinese | Hindi | Tamil).
    """

    name = "EvidenceCollectionAgent"

    def __init__(
        self,
        evidence_window_seconds: int = DEFAULT_EVIDENCE_WINDOW_SECONDS,
        openai_client: Optional[Any] = None,
        language: str = "English",
    ) -> None:
        super().__init__()
        self._window = evidence_window_seconds
        self._openai_client = openai_client
        self._language = language
        # Buffer of all processed events (keyed by (exchange, symbol))
        self._event_buffer: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def process_event(self, event: Dict[str, Any]) -> None:
        """Buffer events for later evidence retrieval."""
        self._event_buffer.append(event)

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def compile_case(
        self,
        case: InterventionCase,
        all_events: Optional[List[Dict[str, Any]]] = None,
    ) -> CaseReport:
        """
        Build a ``CaseReport`` for the given intervention case.

        Parameters
        ----------
        case : InterventionCase
            The intervention case to document.
        all_events : list, optional
            Full event stream.  If ``None`` the internal buffer is used.
        """
        alert = case.alert
        events = all_events if all_events is not None else self._event_buffer

        # Determine evidence window
        detected_epoch = self._parse_epoch(alert.detected_at)
        window_start_epoch = detected_epoch - self._window
        window_end_epoch = detected_epoch + self._window
        window_start = self._epoch_to_iso(window_start_epoch)
        window_end = self._epoch_to_iso(window_end_epoch)

        # Filter events to the evidence window and matching symbol/exchange
        related_orders = []
        related_trades = []
        for ev in events:
            if (
                ev.get("exchange_id") == alert.exchange_id
                and ev.get("symbol") == alert.symbol
            ):
                ts_epoch = self._parse_epoch(ev.get("timestamp", ""))
                if window_start_epoch <= ts_epoch <= window_end_epoch:
                    if ev.get("event_type") == "ORDER_BOOK":
                        related_orders.append(ev)
                    elif ev.get("event_type") == "TRADE":
                        related_trades.append(ev)

        # Sort chronologically
        related_orders.sort(key=lambda e: e.get("timestamp", ""))
        related_trades.sort(key=lambda e: e.get("timestamp", ""))

        # Compute basic statistics
        prices = [float(t.get("price", 0)) for t in related_trades]
        volumes = [int(t.get("quantity", 0)) for t in related_trades]
        price_impact_pct = 0.0
        if len(prices) >= 2:
            price_impact_pct = abs((prices[-1] - prices[0]) / prices[0] * 100)
        total_volume = sum(volumes)

        # Infer detection scores from alert evidence
        evidence = alert.evidence
        spoofing_score = 0.0
        layering_score = 0.0
        anomaly_score = 0.0
        if alert.alert_type == "SPOOFING":
            spoofing_score = alert.confidence_score
        elif alert.alert_type == "LAYERING":
            layering_score = alert.confidence_score
        elif alert.alert_type in ("PRICE_ANOMALY", "VOLUME_SPIKE"):
            anomaly_score = alert.confidence_score

        regulatory_body = REGULATOR_MAP.get(alert.exchange_id, "UNKNOWN")

        report = CaseReport(
            report_id=f"RPT-{uuid.uuid4().hex[:10].upper()}",
            case_id=case.case_id,
            generated_at=_utcnow_iso(),
            exchange_id=alert.exchange_id,
            symbol=alert.symbol,
            manipulation_type=alert.alert_type,
            regulatory_body=regulatory_body,
            involved_entities=alert.involved_entities,
            evidence_window_start=window_start,
            evidence_window_end=window_end,
            related_order_events=related_orders,
            related_trade_events=related_trades,
            price_impact_pct=round(price_impact_pct, 4),
            total_volume_affected=total_volume,
            estimated_gain=float(evidence.get("estimated_gain", 0.0)),
            spoofing_score=spoofing_score,
            layering_score=layering_score,
            anomaly_score=anomaly_score,
            intervention_actions=case.actions,
        )

        report.narrative = self.generate_narrative(report)
        logger.info(
            "[%s] Compiled report %s for case %s (%d orders, %d trades)",
            self.name, report.report_id, case.case_id,
            len(related_orders), len(related_trades),
        )
        return report

    def generate_narrative(self, report: CaseReport) -> str:
        """
        Generate a plain-text (or GenAI-powered) narrative for the case.

        Uses the GPT-4o prompt template from the README when an OpenAI
        client is available, otherwise assembles a structured template
        locally.
        """
        if self._openai_client is not None:
            return self._genai_narrative(report)

        # Check environment for OpenAI key
        if os.environ.get("OPENAI_API_KEY"):
            try:
                return self._openai_narrative(report)
            except Exception as exc:
                logger.warning(
                    "[%s] OpenAI narrative failed (%s) — using template fallback.",
                    self.name, exc,
                )

        return self._template_narrative(report)

    # ------------------------------------------------------------------
    # Narrative helpers
    # ------------------------------------------------------------------

    def _template_narrative(self, report: CaseReport) -> str:
        """Build a structured narrative without any external API call."""
        lines = [
            f"CASE REPORT — {report.manipulation_type}",
            f"Case ID: {report.case_id}",
            f"Report ID: {report.report_id}",
            f"Generated: {report.generated_at}",
            "",
            "EXECUTIVE SUMMARY",
            f"A {report.manipulation_type} pattern was detected on "
            f"{report.exchange_id}/{report.symbol} between "
            f"{report.evidence_window_start} and {report.evidence_window_end}. "
            f"The detection agent assigned a confidence score of "
            f"{max(report.spoofing_score, report.layering_score, report.anomaly_score):.2f}.",
            "",
            "INVOLVED ENTITIES",
        ]
        for entity in report.involved_entities:
            lines.append(f"  • {entity}")

        lines += [
            "",
            "MARKET IMPACT",
            f"  Price movement:      {report.price_impact_pct:.2f}%",
            f"  Total volume:        {report.total_volume_affected:,} shares",
            f"  Estimated gain:      {report.estimated_gain:,.2f}",
            "",
            "DETECTION SCORES",
            f"  Spoofing score:      {report.spoofing_score:.3f}",
            f"  Layering score:      {report.layering_score:.3f}",
            f"  Anomaly score:       {report.anomaly_score:.3f}",
            "",
            "REGULATORY BODY",
            f"  {report.regulatory_body}",
            "",
            "EVIDENCE REFERENCES",
            f"  Order book events:   {len(report.related_order_events)}",
            f"  Trade events:        {len(report.related_trade_events)}",
            "",
            "RECOMMENDED ACTION",
            f"  Refer case {report.case_id} to {report.regulatory_body} "
            "Enforcement Division for investigation.",
        ]
        return "\n".join(lines)

    def _genai_narrative(self, report: CaseReport) -> str:
        """Call the injected OpenAI client callable."""
        prompt = self._build_prompt(report)
        return self._openai_client(prompt)

    def _openai_narrative(self, report: CaseReport) -> str:
        """Call OpenAI API directly using the ``openai`` package."""
        import openai  # type: ignore  # optional dependency
        prompt = self._build_prompt(report)
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    def _build_prompt(self, report: CaseReport) -> str:
        """Render the GenAI prompt template from the README."""
        order_summary = json.dumps(
            [
                {k: v for k, v in e.items() if k in
                 ("event_id", "timestamp", "action", "side", "price", "quantity", "broker_id")}
                for e in report.related_order_events[:50]  # cap at 50 events
            ],
            indent=2,
        )
        trade_summary = json.dumps(
            [
                {k: v for k, v in e.items() if k in
                 ("event_id", "timestamp", "price", "quantity", "buyer_id", "seller_id")}
                for e in report.related_trade_events[:50]
            ],
            indent=2,
        )
        return _EVIDENCE_PROMPT_TEMPLATE.format(
            case_id=report.case_id,
            exchange_id=report.exchange_id,
            symbol=report.symbol,
            manipulation_type=report.manipulation_type,
            start_time=report.evidence_window_start,
            end_time=report.evidence_window_end,
            order_book_events=order_summary,
            trade_events=trade_summary,
            spoofing_score=report.spoofing_score,
            layering_score=report.layering_score,
            anomaly_score=report.anomaly_score,
            involved_entities="\n".join(f"  • {e}" for e in report.involved_entities),
            regulatory_body=report.regulatory_body,
            language=self._language,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_epoch(ts: str) -> float:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _epoch_to_iso(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
