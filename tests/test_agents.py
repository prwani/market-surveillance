"""
Tests for the surveillance agents package.

Each agent is tested independently using synthetic event dicts that
mirror the output of exchange_data_simulator.py.
"""

import os
import sys
import time
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock

_PKG_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from agents import (
    Alert,
    AlertSeverity,
    AnomalyDetectionAgent,
    CrossMarketAgent,
    EvidenceCollectionAgent,
    InterventionAgent,
    InterventionCase,
    CaseStatus,
    PatternDetectionAgent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_s: float = 0.0) -> str:
    """Return an ISO-8601 UTC timestamp offset seconds from now."""
    epoch = time.time() + offset_s
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _order(
    exchange_id: str = "SGX",
    symbol: str = "OCBC",
    broker_id: str = "BROKER_001",
    action: str = "add",
    side: str = "buy",
    price: float = 14.50,
    quantity: int = 50000,
    order_id: str = "ORD-001",
    ts_offset: float = 0.0,
) -> Dict[str, Any]:
    return {
        "event_type": "ORDER_BOOK",
        "event_id": f"OBK-{order_id}",
        "exchange_id": exchange_id,
        "symbol": symbol,
        "timestamp": _ts(ts_offset),
        "action": action,
        "side": side,
        "price": price,
        "quantity": quantity,
        "broker_id": broker_id,
        "order_id": order_id,
        "labels": {"is_manipulation": False, "manipulation_type": "NONE"},
    }


def _trade(
    exchange_id: str = "SGX",
    symbol: str = "OCBC",
    buyer_id: str = "BROKER_001",
    seller_id: str = "BROKER_002",
    price: float = 14.50,
    quantity: int = 10000,
    ts_offset: float = 0.0,
) -> Dict[str, Any]:
    return {
        "event_type": "TRADE",
        "event_id": f"TRD-{abs(hash(buyer_id+seller_id+str(ts_offset)))%100000:05d}",
        "exchange_id": exchange_id,
        "symbol": symbol,
        "timestamp": _ts(ts_offset),
        "price": price,
        "quantity": quantity,
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "order_type": "LIMIT",
        "venue": f"{exchange_id}_MAIN",
        "currency": "SGD",
        "labels": {"is_manipulation": False, "manipulation_type": "NONE"},
    }


def _collect_alerts(agent) -> List[Alert]:
    alerts: List[Alert] = []
    agent.register_alert_handler(alerts.append)
    return alerts


# ---------------------------------------------------------------------------
# PatternDetectionAgent tests
# ---------------------------------------------------------------------------

class TestPatternDetectionAgent(unittest.TestCase):

    def test_no_alert_for_normal_trading(self):
        agent = PatternDetectionAgent()
        alerts = _collect_alerts(agent)
        # Low-quantity normal order adds and cancels
        for i in range(10):
            agent.process_event(_order(action="add", quantity=100, order_id=f"N{i}"))
        for i in range(3):
            agent.process_event(_order(action="cancel", quantity=100, order_id=f"N{i}"))
        self.assertEqual(len(alerts), 0, "Normal low-volume trading should not trigger alerts")

    def test_spoofing_detected(self):
        """Large-order, high-cancel-rate, fast-cancel pattern should fire SPOOFING."""
        agent = PatternDetectionAgent(
            spoofing_window_s=120,
        )
        alerts = _collect_alerts(agent)
        broker = "BROKER_SPOOF_SGX_001"

        # Place 10 large buy orders
        order_ids = [f"SPOOF-{i:03d}" for i in range(10)]
        for i, oid in enumerate(order_ids):
            agent.process_event(_order(
                action="add",
                broker_id=broker,
                quantity=50_000,
                order_id=oid,
                ts_offset=float(i) * 0.04,  # 40ms apart
            ))

        # Cancel 9 of them within 200ms
        for i, oid in enumerate(order_ids[:9]):
            agent.process_event(_order(
                action="cancel",
                broker_id=broker,
                quantity=50_000,
                order_id=oid,
                ts_offset=float(i) * 0.04 + 0.15,  # 150ms after add
            ))

        spoofing_alerts = [a for a in alerts if a.alert_type == "SPOOFING"]
        self.assertGreater(len(spoofing_alerts), 0, "Expected SPOOFING alert")
        self.assertIn(broker, spoofing_alerts[0].involved_entities)
        self.assertGreater(spoofing_alerts[0].confidence_score, 0.5)

    def test_layering_detected(self):
        """Multi-level orders with mass cancellation should fire LAYERING."""
        agent = PatternDetectionAgent(layering_window_s=300)
        alerts = _collect_alerts(agent)
        broker = "BROKER_LAYER_SGX_002"

        # Place 6 sell orders at 6 distinct price levels
        prices = [14.50 + i * 0.05 for i in range(6)]
        order_ids = [f"LAYER-{i:03d}" for i in range(6)]
        for i, (p, oid) in enumerate(zip(prices, order_ids)):
            agent.process_event(_order(
                action="add",
                side="sell",
                broker_id=broker,
                price=p,
                quantity=10_000,
                order_id=oid,
                ts_offset=float(i) * 0.05,
            ))

        # Cancel 5 of the 6 orders (≥70%)
        for i, oid in enumerate(order_ids[:5]):
            agent.process_event(_order(
                action="cancel",
                side="sell",
                broker_id=broker,
                price=prices[i],
                quantity=10_000,
                order_id=oid,
                ts_offset=float(i) * 0.05 + 0.5,
            ))

        # Add a buy order (opposite side) to confirm intent
        agent.process_event(_order(
            action="add",
            side="buy",
            broker_id=broker,
            price=14.48,
            quantity=10_000,
            order_id="BUY-001",
            ts_offset=0.6,
        ))

        layering_alerts = [a for a in alerts if a.alert_type == "LAYERING"]
        self.assertGreater(len(layering_alerts), 0, "Expected LAYERING alert")
        self.assertIn(broker, layering_alerts[0].involved_entities)

    def test_wash_trading_detected_by_name_pattern(self):
        """Back-and-forth trades between _WASH_ accounts should fire WASH_TRADING."""
        agent = PatternDetectionAgent(wash_window_s=600)
        alerts = _collect_alerts(agent)
        acct_a = "BROKER_WASH_SGX_003"
        acct_b = "BROKER_WASH_SGX_004_ALT"

        for i in range(5):
            buyer, seller = (acct_a, acct_b) if i % 2 == 0 else (acct_b, acct_a)
            agent.process_event(_trade(
                buyer_id=buyer,
                seller_id=seller,
                quantity=50_000,
                ts_offset=float(i) * 0.3,
            ))

        wash_alerts = [a for a in alerts if a.alert_type == "WASH_TRADING"]
        self.assertGreater(len(wash_alerts), 0, "Expected WASH_TRADING alert")

    def test_wash_trading_same_entity_both_sides(self):
        """Trade where buyer_id == seller_id should fire immediately."""
        agent = PatternDetectionAgent()
        alerts = _collect_alerts(agent)
        agent.process_event(_trade(buyer_id="BROKER_SAME", seller_id="BROKER_SAME"))
        wash_alerts = [a for a in alerts if a.alert_type == "WASH_TRADING"]
        self.assertGreater(len(wash_alerts), 0, "buyer==seller should trigger WASH_TRADING")


# ---------------------------------------------------------------------------
# AnomalyDetectionAgent tests
# ---------------------------------------------------------------------------

class TestAnomalyDetectionAgent(unittest.TestCase):

    def _build_baseline(self, agent: AnomalyDetectionAgent, symbol: str = "OCBC",
                         exchange: str = "SGX", n_buckets: int = 15,
                         base_price: float = 14.50, volume: int = 100_000,
                         price_step: float = 0.0) -> float:
        """Feed n_buckets of normal trade data to establish rolling baseline.

        Parameters
        ----------
        price_step : float
            Per-bucket price increment.  Pass a small value (e.g. 0.01) to
            produce a gently trending baseline with realistic non-zero std;
            pass 0.0 (default) for a completely flat baseline that verifies
            the no-false-positive path.
        """
        now = time.time()
        for bucket in range(n_buckets):
            bucket_start = now - (n_buckets - bucket) * 65  # stagger buckets > 60s apart
            bucket_price = base_price + bucket * price_step
            for j in range(5):
                agent.process_event(_trade(
                    symbol=symbol,
                    exchange_id=exchange,
                    price=bucket_price,  # constant within bucket so VWAP is well-defined
                    quantity=volume // 5,
                    ts_offset=bucket_start - time.time() + j * 2,
                ))
        agent.flush()
        return now

    def test_no_alert_for_stable_prices(self):
        agent = AnomalyDetectionAgent(price_z_threshold=2.5)
        alerts = _collect_alerts(agent)
        self._build_baseline(agent)
        # No extreme prices injected → no alerts
        price_alerts = [a for a in alerts if a.alert_type == "PRICE_ANOMALY"]
        self.assertEqual(len(price_alerts), 0)

    def test_price_anomaly_detected(self):
        agent = AnomalyDetectionAgent(
            price_z_threshold=2.5,
            price_history_buckets=20,
        )
        alerts = _collect_alerts(agent)
        # Build a gently-trending baseline so std > 0 and z-scores are meaningful
        self._build_baseline(agent, base_price=14.50, n_buckets=20, price_step=0.02)

        # Inject a price 30% above baseline in a fresh bucket (well outside 2.5σ)
        now = time.time()
        for j in range(5):
            agent.process_event(_trade(
                price=14.50 * 1.30,   # 30% spike
                quantity=20_000,
                ts_offset=now - time.time() + 120 + j,
            ))
        agent.flush()

        price_alerts = [a for a in alerts if a.alert_type == "PRICE_ANOMALY"]
        self.assertGreater(
            len(price_alerts), 0,
            "Expected PRICE_ANOMALY alert after a 30% price spike",
        )

    def test_volume_spike_detected(self):
        agent = AnomalyDetectionAgent(
            volume_z_threshold=3.0,
            volume_history_buckets=20,
        )
        alerts = _collect_alerts(agent)
        self._build_baseline(agent, volume=1_000, n_buckets=20)

        # Inject a volume 20× the baseline in a new bucket
        now = time.time()
        for j in range(20):
            agent.process_event(_trade(
                price=14.50,
                quantity=10_000,   # 10× per-trade vs 200 in baseline → big spike
                ts_offset=now - time.time() + 180 + j,
            ))
        agent.flush()

        vol_alerts = [a for a in alerts if a.alert_type == "VOLUME_SPIKE"]
        self.assertGreater(
            len(vol_alerts), 0,
            "Expected VOLUME_SPIKE alert after a large volume increase",
        )

    def test_flush_finalises_open_bucket(self):
        agent = AnomalyDetectionAgent()
        alerts = _collect_alerts(agent)
        now = time.time()
        agent.process_event(_trade(ts_offset=now - time.time()))
        # No flush yet → no finalised buckets
        initial_count = len(alerts)
        agent.flush()
        # Bucket was finalised (may or may not produce an alert, but no error)
        self.assertGreaterEqual(len(alerts), initial_count)


# ---------------------------------------------------------------------------
# CrossMarketAgent tests
# ---------------------------------------------------------------------------

class TestCrossMarketAgent(unittest.TestCase):

    def _feed_correlated_buckets(
        self,
        agent: CrossMarketAgent,
        n: int = 15,
        exchange_a: str = "SGX",
        symbol_a: str = "OCBC",
        exchange_b: str = "HKEX",
        symbol_b: str = "OCBC",   # same canonical name for test
        correlation: float = 1.0,
    ) -> None:
        """Feed n buckets of correlated price data to two exchanges."""
        now = time.time()
        import math, random
        random.seed(99)
        base = 100.0
        for bucket in range(n):
            t = now - (n - bucket) * 65
            price_a = base + bucket * 0.5 + random.gauss(0, 0.01)
            price_b = (base + bucket * 0.5) * correlation + random.gauss(0, 0.01)
            for j in range(3):
                agent.process_event(_trade(
                    exchange_id=exchange_a, symbol=symbol_a,
                    price=price_a, quantity=50_000,
                    ts_offset=t - now + j * 5,
                ))
                agent.process_event(_trade(
                    exchange_id=exchange_b, symbol=symbol_b,
                    price=price_b, quantity=50_000,
                    ts_offset=t - now + j * 5 + 1,
                ))
        agent.flush()

    def test_highly_correlated_symbols_raise_alert(self):
        agent = CrossMarketAgent(correlation_threshold=0.80, history_buckets=20)
        alerts = _collect_alerts(agent)
        self._feed_correlated_buckets(agent, n=15, correlation=1.0)

        cross_alerts = [a for a in alerts if a.alert_type == "COORDINATED_MANIPULATION"]
        self.assertGreater(
            len(cross_alerts), 0,
            "Expected COORDINATED_MANIPULATION for identical price movements",
        )
        self.assertTrue(cross_alerts[0].is_cross_market)

    def test_uncorrelated_symbols_no_alert(self):
        agent = CrossMarketAgent(correlation_threshold=0.85, history_buckets=20)
        alerts = _collect_alerts(agent)
        self._feed_correlated_buckets(agent, n=15, correlation=0.0)
        cross_alerts = [a for a in alerts if a.alert_type == "COORDINATED_MANIPULATION"]
        self.assertEqual(len(cross_alerts), 0, "Uncorrelated symbols should not fire alerts")

    def test_single_exchange_no_cross_market_alert(self):
        agent = CrossMarketAgent(correlation_threshold=0.80)
        alerts = _collect_alerts(agent)
        now = time.time()
        for i in range(20):
            agent.process_event(_trade(ts_offset=now - time.time() - i * 65))
        agent.flush()
        cross_alerts = [a for a in alerts if a.alert_type == "COORDINATED_MANIPULATION"]
        self.assertEqual(len(cross_alerts), 0)


# ---------------------------------------------------------------------------
# InterventionAgent tests
# ---------------------------------------------------------------------------

class TestInterventionAgent(unittest.TestCase):

    def _make_alert(self, confidence: float = 0.95, alert_type: str = "SPOOFING",
                     severity: AlertSeverity = AlertSeverity.CRITICAL) -> Alert:
        return Alert(
            alert_id="SPOOF-TEST-001",
            agent_name="PatternDetectionAgent",
            alert_type=alert_type,
            severity=severity,
            exchange_id="SGX",
            symbol="OCBC",
            detected_at=_ts(),
            description="Test spoofing alert",
            confidence_score=confidence,
            involved_entities=["BROKER_SPOOF_001"],
            evidence={"cancel_rate": 0.9},
        )

    def test_high_confidence_alert_triggers_intervention(self):
        agent = InterventionAgent(auto_intervention_threshold=0.85, dry_run=True)
        alert = self._make_alert(confidence=0.95)
        case = agent.handle_alert(alert)
        self.assertIsNotNone(case)
        self.assertIsInstance(case, InterventionCase)
        self.assertIsNotNone(case.halt_response)
        self.assertTrue(case.regulator_notified)

    def test_low_confidence_alert_does_not_intervene(self):
        agent = InterventionAgent(auto_intervention_threshold=0.85, dry_run=True)
        alert = self._make_alert(confidence=0.50)
        case = agent.handle_alert(alert)
        self.assertIsNone(case)

    def test_case_status_updated_to_notified(self):
        agent = InterventionAgent(auto_intervention_threshold=0.85, dry_run=True)
        case = agent.handle_alert(self._make_alert(confidence=0.92))
        self.assertEqual(case.status, CaseStatus.NOTIFIED)

    def test_critical_alert_triggers_broker_suspension(self):
        agent = InterventionAgent(auto_intervention_threshold=0.80, dry_run=True)
        alert = self._make_alert(confidence=0.92, severity=AlertSeverity.CRITICAL)
        case = agent.handle_alert(alert)
        self.assertTrue(case.broker_suspended)

    def test_custom_http_client_is_called(self):
        mock_client = MagicMock(return_value={"status": "accepted", "simulated": False})
        agent = InterventionAgent(auto_intervention_threshold=0.80, http_client=mock_client)
        agent.handle_alert(self._make_alert(confidence=0.92))
        self.assertTrue(mock_client.called)

    def test_case_stored_in_agent(self):
        agent = InterventionAgent(auto_intervention_threshold=0.80, dry_run=True)
        case = agent.handle_alert(self._make_alert(confidence=0.92))
        self.assertIn(case.case_id, {c.case_id for c in agent.list_cases()})

    def test_process_event_is_noop(self):
        agent = InterventionAgent()
        # Should not raise
        agent.process_event({"event_type": "TRADE"})


# ---------------------------------------------------------------------------
# EvidenceCollectionAgent tests
# ---------------------------------------------------------------------------

class TestEvidenceCollectionAgent(unittest.TestCase):

    def _make_case(self) -> InterventionCase:
        alert = Alert(
            alert_id="SPOOF-EV-001",
            agent_name="PatternDetectionAgent",
            alert_type="SPOOFING",
            severity=AlertSeverity.HIGH,
            exchange_id="SGX",
            symbol="OCBC",
            detected_at=_ts(),
            description="Test spoofing for evidence",
            confidence_score=0.91,
            involved_entities=["BROKER_SPOOF_SGX_001"],
            evidence={"cancel_rate": 0.88, "estimated_gain": 127000.0},
        )
        return InterventionCase(case_id="CASE-EV-001", alert=alert)

    def _sample_events(self, n_trades: int = 20, n_orders: int = 10) -> List[Dict]:
        events = []
        now = time.time()
        for i in range(n_trades):
            events.append(_trade(ts_offset=now - time.time() - 300 + i * 10))
        for i in range(n_orders):
            events.append(_order(ts_offset=now - time.time() - 250 + i * 10))
        return events

    def test_compile_case_returns_report(self):
        agent = EvidenceCollectionAgent()
        case = self._make_case()
        events = self._sample_events()
        report = agent.compile_case(case, all_events=events)
        self.assertEqual(report.case_id, case.case_id)
        self.assertEqual(report.exchange_id, "SGX")
        self.assertEqual(report.symbol, "OCBC")

    def test_narrative_is_non_empty_string(self):
        agent = EvidenceCollectionAgent()
        case = self._make_case()
        report = agent.compile_case(case, all_events=self._sample_events())
        self.assertIsInstance(report.narrative, str)
        self.assertGreater(len(report.narrative), 50)

    def test_template_narrative_contains_key_fields(self):
        agent = EvidenceCollectionAgent()
        case = self._make_case()
        report = agent.compile_case(case, all_events=[])
        self.assertIn("CASE-EV-001", report.narrative)
        self.assertIn("SPOOFING", report.narrative)
        self.assertIn("MAS", report.narrative)

    def test_genai_client_called_when_injected(self):
        mock_genai = MagicMock(return_value="Generated narrative text")
        agent = EvidenceCollectionAgent(openai_client=mock_genai)
        case = self._make_case()
        report = agent.compile_case(case, all_events=[])
        self.assertTrue(mock_genai.called)
        self.assertEqual(report.narrative, "Generated narrative text")

    def test_report_statistics(self):
        agent = EvidenceCollectionAgent()
        case = self._make_case()
        events = self._sample_events(n_trades=10)
        report = agent.compile_case(case, all_events=events)
        self.assertGreaterEqual(report.total_volume_affected, 0)

    def test_process_event_buffers_events(self):
        agent = EvidenceCollectionAgent()
        ev = _trade()
        agent.process_event(ev)
        # Internal buffer should have the event
        self.assertEqual(len(agent._event_buffer), 1)

    def test_report_to_dict(self):
        agent = EvidenceCollectionAgent()
        case = self._make_case()
        report = agent.compile_case(case, all_events=[])
        d = report.to_dict()
        self.assertIn("report_id", d)
        self.assertIn("narrative", d)


# ---------------------------------------------------------------------------
# Integration: full pipeline test
# ---------------------------------------------------------------------------

class TestFullPipeline(unittest.TestCase):
    """
    End-to-end test: run the simulator, feed events through all agents,
    and verify that at least one intervention case is opened and a report
    is generated.
    """

    def test_pipeline_end_to_end(self):
        import random
        sys.path.insert(0, _PKG_ROOT)
        from exchange_data_simulator import SimulationEngine
        random.seed(77)

        config = {
            "exchanges": ["SGX"],
            "duration": 500,
            "events_per_second": 5,
            "inject_spoofing": True,
            "spoofing_start": 10,
            "spoofing_repeat": 2,
            "inject_wash_trading": True,
            "wash_start": 200,
            "inject_layering": False,
            "inject_price_anomaly": False,
            "coordinated_manipulation": False,
        }

        engine = SimulationEngine(config)
        sim_events = engine.generate_all_events()
        event_dicts = [
            {
                k: (v.value if hasattr(v, "value") else v)
                for k, v in __import__("dataclasses").asdict(e).items()
            }
            for e in sim_events
        ]

        # Agents
        pattern_agent = PatternDetectionAgent()
        anomaly_agent = AnomalyDetectionAgent(price_history_buckets=30)
        intervention_agent = InterventionAgent(
            auto_intervention_threshold=0.70, dry_run=True
        )
        evidence_agent = EvidenceCollectionAgent()

        # Wire up: detected alerts → intervention → evidence
        cases = []

        def on_alert(alert: Alert) -> None:
            case = intervention_agent.handle_alert(alert)
            if case:
                cases.append(case)

        pattern_agent.register_alert_handler(on_alert)
        anomaly_agent.register_alert_handler(on_alert)

        # Feed events
        for ev in event_dicts:
            pattern_agent.process_event(ev)
            anomaly_agent.process_event(ev)
            evidence_agent.process_event(ev)

        anomaly_agent.flush()

        # Assertions
        self.assertGreater(
            len(cases), 0,
            "Expected at least one intervention case from simulated spoofing/wash data",
        )

        # Compile evidence for first case
        report = evidence_agent.compile_case(cases[0])
        self.assertIsNotNone(report)
        self.assertGreater(len(report.narrative), 0)
        self.assertEqual(report.case_id, cases[0].case_id)


if __name__ == "__main__":
    unittest.main()
