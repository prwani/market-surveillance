#!/usr/bin/env python
"""
End-to-end demo of the Market Surveillance pipeline.

Generates simulated exchange data with all manipulation types injected,
feeds events through all detection and response agents, and prints a
summary of alerts, intervention cases, and evidence reports.

Usage:
    python run_demo.py
"""

import dataclasses
import os
import random
import sys

# Add src/ to path for local development
_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
_sim = os.path.join(_src, "simulator")
for _p in (_src, _sim):
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


def main() -> None:
    random.seed(42)

    # --- 1. Generate events with all manipulation types ---
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

    # Convert dataclass instances to plain dicts (enum values → strings)
    events = [
        {
            k: (v.value if hasattr(v, "value") else v)
            for k, v in dataclasses.asdict(e).items()
        }
        for e in raw_events
    ]

    print("=" * 60)
    print("  Market Surveillance — End-to-End Demo")
    print("=" * 60)
    print(f"\nSimulated {stats['total_events']} events "
          f"({stats['trade_events']} trades, "
          f"{stats['order_book_events']} order-book updates)")
    print(f"Manipulation events injected: {stats['manipulation_events']} "
          f"({stats['manipulation_rate_pct']:.1f}%)")
    print(f"Breakdown: {stats['manipulation_breakdown']}")

    # --- 2. Instantiate agents ---
    pattern_agent = PatternDetectionAgent()
    anomaly_agent = AnomalyDetectionAgent(price_history_buckets=30)
    cross_market_agent = CrossMarketAgent(
        symbol_aliases={
            "DBS_GROUP": {"SGX": "DBS", "HKEX": "0005.HK"},
        },
        correlation_threshold=0.80,
    )
    intervention_agent = InterventionAgent(
        auto_intervention_threshold=0.70,
        dry_run=True,
    )
    evidence_agent = EvidenceCollectionAgent()

    # --- 3. Wire alert handlers ---
    alerts: list[Alert] = []
    cases = []

    def on_alert(alert: Alert) -> None:
        alerts.append(alert)
        case = intervention_agent.handle_alert(alert)
        if case:
            cases.append(case)

    pattern_agent.register_alert_handler(on_alert)
    anomaly_agent.register_alert_handler(on_alert)
    cross_market_agent.register_alert_handler(on_alert)

    # --- 4. Feed events through agents ---
    for ev in events:
        pattern_agent.process_event(ev)
        anomaly_agent.process_event(ev)
        cross_market_agent.process_event(ev)
        evidence_agent.process_event(ev)

    anomaly_agent.flush()
    cross_market_agent.flush()

    # --- 5. Compile evidence reports ---
    reports = []
    for case in cases:
        report = evidence_agent.compile_case(case)
        if report:
            reports.append(report)

    # --- 6. Print summary ---
    print("\n" + "-" * 60)
    print("  Pipeline Results")
    print("-" * 60)
    print(f"  Alerts raised       : {len(alerts)}")
    print(f"  Intervention cases  : {len(cases)}")
    print(f"  Evidence reports    : {len(reports)}")

    if alerts:
        severity_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for a in alerts:
            sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            type_counts[a.alert_type] = type_counts.get(a.alert_type, 0) + 1
        print(f"\n  Alerts by severity  : {severity_counts}")
        print(f"  Alerts by type      : {type_counts}")

    if reports:
        print(f"\n  Sample report (case {reports[0].case_id}):")
        narrative_preview = reports[0].narrative[:200]
        print(f"    {narrative_preview}...")

    print("\n" + "=" * 60)
    print("  Demo complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
