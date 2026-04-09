"""
Intervention Agent
==================
Receives confirmed alerts from upstream detection agents and takes
autonomous intervention actions:

    1. ``halt_trading``      – POST a trade-halt request to the exchange API.
    2. ``notify_regulator``  – Send a structured alert to the relevant
                               regulatory authority (MAS / SFC / SEBI).
    3. ``suspend_broker``    – Request temporary broker account suspension.

In this implementation all exchange and regulator API calls are **simulated**
(they log the request and return a structured mock response).  In production
these would call the real endpoints described in the README, Section 5.2.

Every action is recorded in an immutable ``InterventionCase`` object that
forms the beginning of the audit trail later consumed by the
``EvidenceCollectionAgent``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .base_agent import Alert, AlertSeverity, BaseAgent, _utcnow_iso


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map exchange ID → regulatory authority
REGULATOR_MAP: Dict[str, str] = {
    "SGX": "MAS",    # Monetary Authority of Singapore
    "HKEX": "SFC",   # Securities and Futures Commission, Hong Kong
    "NSE": "SEBI",   # Securities and Exchange Board of India
}

# Confidence threshold above which the agent acts autonomously
AUTO_INTERVENTION_THRESHOLD = 0.85

# Simulated exchange halt API endpoints (for documentation purposes)
EXCHANGE_HALT_APIS: Dict[str, str] = {
    "SGX":  "https://api.sgx.com/v1/surveillance/halt",
    "HKEX": "https://api.hkex.com/v2/market/halt",
    "NSE":  "https://api.nseindia.com/v1/trading/halt",
}


# ---------------------------------------------------------------------------
# Case model
# ---------------------------------------------------------------------------

class CaseStatus(str, Enum):
    OPEN = "OPEN"
    HALTED = "HALTED"
    NOTIFIED = "NOTIFIED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


@dataclass
class InterventionCase:
    """Immutable record of a detected manipulation event and all actions taken."""

    case_id: str
    alert: Alert
    created_at: str = field(default_factory=_utcnow_iso)
    status: CaseStatus = CaseStatus.OPEN
    actions: List[Dict[str, Any]] = field(default_factory=list)
    halt_response: Optional[Dict[str, Any]] = None
    regulator_notified: bool = False
    broker_suspended: bool = False

    def add_action(self, action_type: str, details: Dict[str, Any]) -> None:
        self.actions.append({
            "action_type": action_type,
            "timestamp": _utcnow_iso(),
            **details,
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "alert": self.alert.to_dict(),
            "actions": self.actions,
            "halt_response": self.halt_response,
            "regulator_notified": self.regulator_notified,
            "broker_suspended": self.broker_suspended,
        }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class InterventionAgent(BaseAgent):
    """
    Autonomous intervention agent.

    Listens for ``Alert`` objects via ``handle_alert``.  When the alert's
    confidence score exceeds ``auto_intervention_threshold`` it immediately:

        1. Calls ``halt_trading`` on the relevant exchange.
        2. Notifies the regulatory authority.
        3. Optionally suspends involved broker accounts.

    All simulated API calls can be replaced with real HTTP clients by
    injecting a custom ``http_client`` callable.
    """

    name = "InterventionAgent"

    def __init__(
        self,
        auto_intervention_threshold: float = AUTO_INTERVENTION_THRESHOLD,
        http_client: Optional[Callable[[str, Dict], Dict]] = None,
        dry_run: bool = True,
    ) -> None:
        super().__init__()
        self._threshold = auto_intervention_threshold
        self._http_client = http_client or self._simulated_http_post
        self._dry_run = dry_run
        self._cases: Dict[str, InterventionCase] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def handle_alert(self, alert: Alert) -> Optional[InterventionCase]:
        """
        Entry point: evaluate an alert and intervene if threshold is met.

        Returns the ``InterventionCase`` (new or updated) or ``None`` if the
        alert was below the intervention threshold.
        """
        if alert.confidence_score < self._threshold:
            logger.info(
                "[%s] Alert %s confidence %.2f below threshold %.2f — skipping.",
                self.name, alert.alert_id, alert.confidence_score, self._threshold,
            )
            return None

        case_id = alert.case_id or f"CASE-{uuid.uuid4().hex[:10].upper()}"
        alert.case_id = case_id

        case = InterventionCase(case_id=case_id, alert=alert)
        self._cases[case_id] = case

        logger.info(
            "[%s] Opening case %s for %s/%s — %s (confidence=%.2f)",
            self.name, case_id, alert.exchange_id, alert.symbol,
            alert.alert_type, alert.confidence_score,
        )

        # Step 1: Halt trading
        self.halt_trading(case)

        # Step 2: Notify regulator
        self.notify_regulator(case)

        # Step 3: Suspend involved brokers (for CRITICAL alerts)
        if alert.severity == AlertSeverity.CRITICAL and alert.involved_entities:
            for entity in alert.involved_entities:
                self.suspend_broker(case, entity)

        return case

    def halt_trading(self, case: InterventionCase) -> Dict[str, Any]:
        """Send a trade-halt request to the exchange API."""
        alert = case.alert
        endpoint = EXCHANGE_HALT_APIS.get(alert.exchange_id, "https://api.unknown/halt")

        payload = {
            "symbol": alert.symbol,
            "reason": "REGULATORY_SURVEILLANCE",
            "case_id": case.case_id,
            "halted_by": "fabric-surveillance-agent",
            "alert_type": alert.alert_type,
            "confidence_score": alert.confidence_score,
        }

        response = self._http_client(endpoint, payload)
        case.halt_response = response
        case.status = CaseStatus.HALTED
        case.add_action("HALT_TRADING", {
            "endpoint": endpoint,
            "payload": payload,
            "response": response,
            "dry_run": self._dry_run,
        })

        logger.info(
            "[%s] Case %s: HALT sent to %s for %s/%s — response: %s",
            self.name, case.case_id, alert.exchange_id,
            alert.exchange_id, alert.symbol, response.get("status"),
        )
        return response

    def notify_regulator(self, case: InterventionCase) -> Dict[str, Any]:
        """Send a structured alert to the relevant regulatory authority."""
        alert = case.alert
        regulator = REGULATOR_MAP.get(alert.exchange_id, "UNKNOWN_REGULATOR")
        notification = {
            "regulator": regulator,
            "case_id": case.case_id,
            "exchange_id": alert.exchange_id,
            "symbol": alert.symbol,
            "manipulation_type": alert.alert_type,
            "confidence_score": alert.confidence_score,
            "detected_at": alert.detected_at,
            "involved_entities": alert.involved_entities,
            "preliminary_evidence": alert.evidence,
            "notification_sent_at": _utcnow_iso(),
        }

        response = self._http_client(
            f"https://regulatory-portal.{regulator.lower()}.gov/api/alerts",
            notification,
        )
        case.regulator_notified = True
        case.status = CaseStatus.NOTIFIED
        case.add_action("NOTIFY_REGULATOR", {
            "regulator": regulator,
            "notification": notification,
            "response": response,
            "dry_run": self._dry_run,
        })

        logger.info(
            "[%s] Case %s: Notified %s — response: %s",
            self.name, case.case_id, regulator, response.get("status"),
        )
        return response

    def suspend_broker(self, case: InterventionCase, broker_id: str) -> Dict[str, Any]:
        """Request suspension of a broker account."""
        alert = case.alert
        payload = {
            "broker_id": broker_id,
            "case_id": case.case_id,
            "reason": f"Suspected {alert.alert_type}",
            "suspended_by": "fabric-surveillance-agent",
        }

        response = self._http_client(
            EXCHANGE_HALT_APIS.get(alert.exchange_id, "").replace("/halt", "/suspend"),
            payload,
        )
        case.broker_suspended = True
        case.add_action("SUSPEND_BROKER", {
            "broker_id": broker_id,
            "response": response,
            "dry_run": self._dry_run,
        })

        logger.info(
            "[%s] Case %s: Broker %s suspended — response: %s",
            self.name, case.case_id, broker_id, response.get("status"),
        )
        return response

    def get_case(self, case_id: str) -> Optional[InterventionCase]:
        return self._cases.get(case_id)

    def list_cases(self) -> List[InterventionCase]:
        return list(self._cases.values())

    # ------------------------------------------------------------------
    # BaseAgent.process_event not used (alert-driven, not event-driven)
    # ------------------------------------------------------------------

    def process_event(self, event: Dict[str, Any]) -> None:
        pass  # InterventionAgent is alert-driven, not event-driven

    # ------------------------------------------------------------------
    # Simulated HTTP client
    # ------------------------------------------------------------------

    @staticmethod
    def _simulated_http_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulated HTTP POST — logs the request and returns a mock 200 response.
        Replace with a real HTTP client (e.g. ``requests.post``) in production.
        """
        logger.info("[SimulatedHTTP] POST %s payload_keys=%s", endpoint, list(payload.keys()))
        return {
            "status": "accepted",
            "endpoint": endpoint,
            "timestamp": _utcnow_iso(),
            "simulated": True,
        }
