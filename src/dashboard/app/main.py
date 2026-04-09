"""FastAPI web dashboard for the market surveillance system."""

import dataclasses
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Allow imports from src/ for local development;
# inside Docker, agents/ and simulator/ are at /app/ level.
_app_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(os.path.dirname(_app_dir))
_sim_dir = os.path.join(_src_dir, "simulator")
for _p in (_src_dir, _sim_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from exchange_data_simulator import SimulationEngine, TradeEvent, OrderBookEvent  # noqa: E402
from agents import (  # noqa: E402
    PatternDetectionAgent,
    AnomalyDetectionAgent,
    CrossMarketAgent,
    InterventionAgent,
    EvidenceCollectionAgent,
    Alert,
)

from app.templates import (  # noqa: E402
    dashboard_html,
    simulate_html,
    alerts_table_html,
    cases_table_html,
    report_html,
    kql_html,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional KQL support
# ---------------------------------------------------------------------------
KQL_URI = os.environ.get("KQL_URI", "")
KQL_DB = os.environ.get("KQL_DB", "surveillance")
_kusto_client = None
HAS_KUSTO = False

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    HAS_KUSTO = True
    if KQL_URI:
        kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
            KQL_URI, DefaultAzureCredential()
        )
        _kusto_client = KustoClient(kcsb)
except Exception:
    _kusto_client = None

# ---------------------------------------------------------------------------
# In-memory state (demo only)
# ---------------------------------------------------------------------------
_state: Dict[str, Any] = {
    "events": [],
    "alerts": [],
    "cases": [],
    "reports": {},
    "stats": {
        "total_events": 0,
        "total_alerts": 0,
        "total_cases": 0,
        "total_reports": 0,
    },
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Market Surveillance Dashboard", version="1.0.0")


def _alert_to_dict(a: Alert) -> Dict[str, Any]:
    d = dataclasses.asdict(a)
    d["severity"] = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
    return d


def _case_to_dict(c: Any) -> Dict[str, Any]:
    d = dataclasses.asdict(c)
    if hasattr(c.status, "value"):
        d["status"] = c.status.value
    if hasattr(c.alert, "severity") and hasattr(c.alert.severity, "value"):
        d["alert"]["severity"] = c.alert.severity.value
    return d


def _report_to_dict(r: Any) -> Dict[str, Any]:
    return dataclasses.asdict(r)


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    return dashboard_html(_state["stats"])


@app.get("/simulate", response_class=HTMLResponse)
async def page_simulate():
    return simulate_html()


@app.get("/alerts", response_class=HTMLResponse)
async def page_alerts():
    return alerts_table_html(_state["alerts"])


@app.get("/cases", response_class=HTMLResponse)
async def page_cases():
    return cases_table_html(_state["cases"])


@app.get("/reports/{case_id}", response_class=HTMLResponse)
async def page_report(case_id: str):
    report = _state["reports"].get(case_id)
    return report_html(report)


@app.get("/kql", response_class=HTMLResponse)
async def page_kql():
    return kql_html()


# ---------------------------------------------------------------------------
# Eventhouse inline ingestion helper
# ---------------------------------------------------------------------------
_INGEST_BATCH_SIZE = 50


def _ingest_events_to_eventhouse(raw_events) -> int:
    """Ingest raw simulation events into Fabric Eventhouse via .ingest inline.

    Returns the total number of rows ingested.
    """
    trades = [e for e in raw_events if isinstance(e, TradeEvent)]
    orders = [e for e in raw_events if isinstance(e, OrderBookEvent)]

    def _trade_tsv(ev):
        d = dataclasses.asdict(ev)
        return "\t".join([
            str(d.get("event_id", "")),
            str(d.get("timestamp", "")),
            str(d.get("exchange_id", "")),
            str(d.get("symbol", "")),
            str(d.get("price", 0)),
            str(d.get("quantity", 0)),
            str(d.get("buyer_id", "")),
            str(d.get("seller_id", "")),
            str(d.get("order_type", "")),
            str(d.get("venue", "")),
        ])

    def _order_tsv(ev):
        d = dataclasses.asdict(ev)
        return "\t".join([
            str(d.get("event_id", "")),
            str(d.get("timestamp", "")),
            str(d.get("exchange_id", "")),
            str(d.get("symbol", "")),
            str(d.get("side", "")),
            str(d.get("price", 0)),
            str(d.get("quantity", 0)),
            str(d.get("action", "")),
            str(d.get("broker_id", "")),
        ])

    total = 0
    for i in range(0, len(trades), _INGEST_BATCH_SIZE):
        batch = trades[i : i + _INGEST_BATCH_SIZE]
        rows = "\n".join(_trade_tsv(t) for t in batch)
        cmd = f".ingest inline into table TRADES <|\n{rows}"
        _kusto_client.execute_mgmt(KQL_DB, cmd)
        total += len(batch)

    for i in range(0, len(orders), _INGEST_BATCH_SIZE):
        batch = orders[i : i + _INGEST_BATCH_SIZE]
        rows = "\n".join(_order_tsv(o) for o in batch)
        cmd = f".ingest inline into table ORDER_BOOK_EVENTS <|\n{rows}"
        _kusto_client.execute_mgmt(KQL_DB, cmd)
        total += len(batch)

    return total


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/simulate")
async def api_simulate(request: Request):
    body = await request.json()

    exchanges = body.get("exchanges", ["SGX"])
    duration = body.get("duration", 120)
    inject_spoofing = body.get("inject_spoofing", True)
    inject_layering = body.get("inject_layering", True)
    inject_wash_trading = body.get("inject_wash_trading", True)
    inject_price_anomaly = body.get("inject_price_anomaly", False)

    config = {
        "exchanges": exchanges,
        "duration": duration,
        "events_per_second": 20,
        "inject_spoofing": inject_spoofing,
        "spoofing_start": max(5, duration // 6),
        "spoofing_repeat": max(10, duration // 4),
        "inject_layering": inject_layering,
        "layering_start": max(8, duration // 5),
        "inject_wash_trading": inject_wash_trading,
        "wash_start": max(10, duration // 4),
        "inject_price_anomaly": inject_price_anomaly,
        "price_anomaly_start": max(15, duration // 3),
        "anomaly_direction": "pump",
    }

    engine = SimulationEngine(config)
    raw_events = engine.generate_all_events()

    events = []
    for ev in raw_events:
        events.append(dataclasses.asdict(ev) if dataclasses.is_dataclass(ev) else ev)

    # -- agents ---------------------------------------------------------------
    pattern_agent = PatternDetectionAgent()
    anomaly_agent = AnomalyDetectionAgent()
    cross_agent = CrossMarketAgent()
    intervention_agent = InterventionAgent(dry_run=True, auto_intervention_threshold=0.70)
    evidence_agent = EvidenceCollectionAgent()

    alerts: List[Alert] = []
    cases_list: List[Any] = []

    def _on_alert(alert: Alert):
        alerts.append(alert)
        case = intervention_agent.handle_alert(alert)
        if case is not None:
            cases_list.append(case)

    for agent in (pattern_agent, anomaly_agent, cross_agent):
        agent.register_alert_handler(_on_alert)

    for ev in events:
        pattern_agent.process_event(ev)
        anomaly_agent.process_event(ev)
        cross_agent.process_event(ev)
        evidence_agent.process_event(ev)

    anomaly_agent.flush()
    cross_agent.flush()

    # -- evidence reports -----------------------------------------------------
    reports_map: Dict[str, Dict[str, Any]] = {}
    for case in cases_list:
        try:
            report = evidence_agent.compile_case(case)
            reports_map[case.case_id] = _report_to_dict(report)
        except Exception:
            pass

    # -- store in module state ------------------------------------------------
    alert_dicts = [_alert_to_dict(a) for a in alerts]
    case_dicts = [_case_to_dict(c) for c in cases_list]

    _state["events"] = events
    _state["alerts"] = alert_dicts
    _state["cases"] = case_dicts
    _state["reports"] = reports_map
    _state["stats"] = {
        "total_events": len(events),
        "total_alerts": len(alert_dicts),
        "total_cases": len(case_dicts),
        "total_reports": len(reports_map),
    }

    # -- optionally ingest into Fabric Eventhouse ----------------------------
    eventhouse_rows = 0
    if KQL_URI and HAS_KUSTO and _kusto_client:
        try:
            eventhouse_rows = _ingest_events_to_eventhouse(raw_events)
            logger.info("Eventhouse ingestion: %d rows", eventhouse_rows)
        except Exception as e:
            logger.warning("Eventhouse ingestion failed: %s", e)

    return {
        "event_count": len(events),
        "alert_count": len(alert_dicts),
        "case_count": len(case_dicts),
        "report_count": len(reports_map),
        "eventhouse_rows": eventhouse_rows,
    }


@app.get("/api/alerts")
async def api_alerts():
    return JSONResponse(_state["alerts"])


@app.get("/api/cases")
async def api_cases():
    return JSONResponse(_state["cases"])


@app.get("/api/reports/{case_id}")
async def api_report(case_id: str):
    report = _state["reports"].get(case_id)
    if report is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return JSONResponse(report)


@app.get("/api/stats")
async def api_stats():
    return JSONResponse(_state["stats"])


@app.post("/api/kql")
async def api_kql(request: Request):
    body = await request.json()
    query = body.get("query", "")
    if not query:
        return JSONResponse({"error": "No query provided"}, status_code=400)
    if not _kusto_client:
        return JSONResponse(
            {"error": "KQL not configured. Set KQL_URI environment variable."},
            status_code=501,
        )
    try:
        response = _kusto_client.execute_query(KQL_DB, query)
        columns = [col.column_name for col in response.primary_results[0].columns]
        results = []
        for row in response.primary_results[0]:
            results.append({col: str(row[col]) for col in columns})
        return JSONResponse({"results": results})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "kql_configured": bool(KQL_URI)}
