"""HTML template functions for the market surveillance dashboard."""

from typing import Any, Dict, List, Optional


_NAV_ITEMS = [
    ("/", "Dashboard"),
    ("/simulate", "Simulate"),
    ("/alerts", "Alerts"),
    ("/cases", "Cases"),
    ("/kql", "KQL"),
]

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; }
a { color: #7f8fff; text-decoration: none; }
a:hover { text-decoration: underline; }
nav { background: #16213e; padding: 12px 24px; display: flex; gap: 24px; align-items: center; border-bottom: 1px solid #0f3460; }
nav .brand { font-weight: 700; font-size: 1.1rem; color: #e94560; margin-right: 16px; }
nav a { color: #a0a8d0; font-size: 0.95rem; }
nav a:hover { color: #fff; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { font-size: 1.6rem; margin-bottom: 16px; }
h2 { font-size: 1.2rem; margin-bottom: 12px; color: #a0a8d0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 20px; }
.card .label { font-size: 0.85rem; color: #888; text-transform: uppercase; }
.card .value { font-size: 2rem; font-weight: 700; font-family: 'Courier New', monospace; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-family: 'Courier New', monospace; font-size: 0.9rem; }
th { background: #16213e; padding: 10px 12px; text-align: left; border-bottom: 2px solid #0f3460; font-size: 0.8rem; text-transform: uppercase; color: #888; }
td { padding: 10px 12px; border-bottom: 1px solid #0f3460; }
tr:hover { background: rgba(127,143,255,0.06); }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.78rem; font-weight: 600; }
.badge-critical { background: #e94560; color: #fff; }
.badge-high { background: #e07020; color: #fff; }
.badge-medium { background: #c0a020; color: #1a1a2e; }
.badge-low { background: #2ecc71; color: #1a1a2e; }
.badge-open { background: #3498db; color: #fff; }
.badge-halted { background: #e94560; color: #fff; }
.badge-notified { background: #e07020; color: #fff; }
.badge-closed { background: #2ecc71; color: #1a1a2e; }
.badge-escalated { background: #9b59b6; color: #fff; }
form { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 24px; max-width: 600px; }
label { display: block; margin-bottom: 4px; font-size: 0.9rem; color: #a0a8d0; }
input[type=number], input[type=text], textarea, select { background: #1a1a2e; color: #e0e0e0; border: 1px solid #0f3460; border-radius: 4px; padding: 8px 12px; width: 100%; font-family: 'Courier New', monospace; font-size: 0.9rem; margin-bottom: 12px; }
textarea { resize: vertical; min-height: 120px; }
input[type=checkbox] { margin-right: 6px; }
.checkbox-group { margin-bottom: 12px; }
.checkbox-group label { display: inline-flex; align-items: center; margin-right: 18px; cursor: pointer; }
button, .btn { background: #e94560; color: #fff; border: none; border-radius: 4px; padding: 10px 24px; font-size: 0.95rem; cursor: pointer; font-weight: 600; }
button:hover, .btn:hover { background: #c73a52; }
button:disabled { background: #555; cursor: not-allowed; }
.section { margin-bottom: 32px; }
pre { background: #0d1117; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; font-family: 'Courier New', monospace; }
.result-area { margin-top: 16px; }
.info { color: #888; font-style: italic; }
"""


def _severity_badge(severity: str) -> str:
    s = severity.upper() if severity else "LOW"
    return f'<span class="badge badge-{s.lower()}">{s}</span>'


def _status_badge(status: str) -> str:
    s = status.upper() if status else "OPEN"
    return f'<span class="badge badge-{s.lower()}">{s}</span>'


def _esc(text: Any) -> str:
    """Basic HTML escaping."""
    s = str(text) if text is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _base(title: str, body: str) -> str:
    nav_links = "".join(
        f'<a href="{href}">{label}</a>' for href, label in _NAV_ITEMS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} — Market Surveillance</title>
<style>{_CSS}</style>
</head>
<body>
<nav>
<span class="brand">&#x1F6E1; Market Surveillance</span>
{nav_links}
</nav>
<div class="container">
{body}
</div>
</body>
</html>"""


def dashboard_html(stats: Dict[str, Any]) -> str:
    cards = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div></div>'
        for label, value in [
            ("Total Events", stats.get("total_events", 0)),
            ("Active Alerts", stats.get("total_alerts", 0)),
            ("Open Cases", stats.get("total_cases", 0)),
            ("Reports Generated", stats.get("total_reports", 0)),
        ]
    )
    return _base("Dashboard", f"""
<h1>Dashboard</h1>
<div class="cards">{cards}</div>
<div class="section">
<h2>Quick Actions</h2>
<p><a href="/simulate" class="btn" style="display:inline-block;margin-right:12px;">Run Simulation</a>
<a href="/alerts" class="btn" style="background:#3498db;display:inline-block;margin-right:12px;">View Alerts</a>
<a href="/cases" class="btn" style="background:#2ecc71;display:inline-block;margin-right:12px;">View Cases</a>
<a href="/kql" class="btn" style="background:#9b59b6;display:inline-block;">KQL Query</a></p>
</div>
""")


def simulate_html() -> str:
    return _base("Simulate", """
<h1>Run Simulation</h1>
<form id="simForm">
<label for="exchanges">Exchanges (comma-separated)</label>
<input type="text" id="exchanges" value="SGX" placeholder="SGX, NYSE, LSE">

<label for="duration">Duration (seconds)</label>
<input type="number" id="duration" value="120" min="10" max="600">

<div class="checkbox-group">
<label><input type="checkbox" id="spoofing" checked> Inject Spoofing</label>
<label><input type="checkbox" id="layering" checked> Inject Layering</label>
<label><input type="checkbox" id="wash_trading" checked> Inject Wash Trading</label>
<label><input type="checkbox" id="price_anomaly"> Inject Price Anomaly</label>
</div>

<button type="submit" id="runBtn">&#9654; Run Simulation</button>
</form>
<div id="result" class="result-area"></div>
<script>
document.getElementById('simForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const btn = document.getElementById('runBtn');
    btn.disabled = true; btn.textContent = 'Running...';
    const exch = document.getElementById('exchanges').value.split(',').map(s=>s.trim()).filter(Boolean);
    const body = {
        exchanges: exch,
        duration: parseInt(document.getElementById('duration').value),
        inject_spoofing: document.getElementById('spoofing').checked,
        inject_layering: document.getElementById('layering').checked,
        inject_wash_trading: document.getElementById('wash_trading').checked,
        inject_price_anomaly: document.getElementById('price_anomaly').checked,
    };
    try {
        const resp = await fetch('/api/simulate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const data = await resp.json();
        document.getElementById('result').innerHTML = '<h2>Results</h2><pre>'+JSON.stringify(data, null, 2)+'</pre>' +
            '<p style="margin-top:12px"><a href="/alerts">View Alerts &rarr;</a> | <a href="/cases">View Cases &rarr;</a></p>';
    } catch(err) {
        document.getElementById('result').innerHTML = '<pre style="color:#e94560;">Error: '+err.message+'</pre>';
    }
    btn.disabled = false; btn.textContent = '\\u25B6 Run Simulation';
});
</script>
""")


def alerts_table_html(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        rows = '<tr><td colspan="7" class="info">No alerts yet. <a href="/simulate">Run a simulation</a> first.</td></tr>'
    else:
        rows = ""
        for a in alerts:
            rows += f"""<tr>
<td>{_esc(a.get('alert_id','')[:12])}</td>
<td>{_esc(a.get('alert_type',''))}</td>
<td>{_severity_badge(a.get('severity',''))}</td>
<td>{_esc(a.get('exchange_id',''))}</td>
<td>{_esc(a.get('symbol',''))}</td>
<td>{_esc(f"{a.get('confidence_score',0):.1%}")}</td>
<td>{_esc(a.get('detected_at',''))}</td>
</tr>"""
    return _base("Alerts", f"""
<h1>Detected Alerts <span style="font-size:0.9rem;color:#888;">({len(alerts)})</span></h1>
<table>
<thead><tr><th>ID</th><th>Type</th><th>Severity</th><th>Exchange</th><th>Symbol</th><th>Confidence</th><th>Time</th></tr></thead>
<tbody>{rows}</tbody>
</table>
""")


def cases_table_html(cases: List[Dict[str, Any]]) -> str:
    if not cases:
        rows = '<tr><td colspan="6" class="info">No cases yet. <a href="/simulate">Run a simulation</a> first.</td></tr>'
    else:
        rows = ""
        for c in cases:
            alert = c.get("alert", {})
            actions = c.get("actions", [])
            action_str = ", ".join(a.get("action", "") for a in actions) if actions else "—"
            rows += f"""<tr>
<td><a href="/reports/{_esc(c.get('case_id',''))}">{_esc(c.get('case_id','')[:12])}</a></td>
<td>{_status_badge(c.get('status',''))}</td>
<td>{_esc(alert.get('alert_type',''))}</td>
<td>{_esc(alert.get('exchange_id',''))}</td>
<td>{_esc(alert.get('symbol',''))}</td>
<td>{_esc(action_str)}</td>
</tr>"""
    return _base("Cases", f"""
<h1>Intervention Cases <span style="font-size:0.9rem;color:#888;">({len(cases)})</span></h1>
<table>
<thead><tr><th>Case ID</th><th>Status</th><th>Alert Type</th><th>Exchange</th><th>Symbol</th><th>Actions</th></tr></thead>
<tbody>{rows}</tbody>
</table>
""")


def report_html(report: Optional[Dict[str, Any]]) -> str:
    if not report:
        return _base("Report Not Found", '<h1>Report Not Found</h1><p class="info">No report found for this case. <a href="/cases">Back to cases</a></p>')

    stats_cards = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div><div class="value">{_esc(value)}</div></div>'
        for label, value in [
            ("Price Impact", f"{report.get('price_impact_pct', 0):.2f}%"),
            ("Volume Affected", f"{report.get('total_volume_affected', 0):,}"),
            ("Estimated Gain", f"${report.get('estimated_gain', 0):,.2f}"),
            ("Spoofing Score", f"{report.get('spoofing_score', 0):.2f}"),
            ("Layering Score", f"{report.get('layering_score', 0):.2f}"),
            ("Anomaly Score", f"{report.get('anomaly_score', 0):.2f}"),
        ]
    )
    entities = ", ".join(report.get("involved_entities", [])) or "—"
    narrative = _esc(report.get("narrative", "No narrative generated."))

    return _base(f"Report — {report.get('case_id', '')[:12]}", f"""
<h1>Evidence Report</h1>
<p style="margin-bottom:16px;color:#888;">
Report ID: {_esc(report.get('report_id',''))} &bull;
Case: {_esc(report.get('case_id',''))} &bull;
Generated: {_esc(report.get('generated_at',''))}
</p>

<div class="section">
<h2>Overview</h2>
<table>
<tr><td style="width:160px;color:#888;">Exchange</td><td>{_esc(report.get('exchange_id',''))}</td></tr>
<tr><td style="color:#888;">Symbol</td><td>{_esc(report.get('symbol',''))}</td></tr>
<tr><td style="color:#888;">Manipulation Type</td><td>{_esc(report.get('manipulation_type',''))}</td></tr>
<tr><td style="color:#888;">Regulatory Body</td><td>{_esc(report.get('regulatory_body',''))}</td></tr>
<tr><td style="color:#888;">Involved Entities</td><td>{_esc(entities)}</td></tr>
<tr><td style="color:#888;">Evidence Window</td><td>{_esc(report.get('evidence_window_start',''))} — {_esc(report.get('evidence_window_end',''))}</td></tr>
</table>
</div>

<div class="section">
<h2>Statistics</h2>
<div class="cards">{stats_cards}</div>
</div>

<div class="section">
<h2>Narrative</h2>
<pre>{narrative}</pre>
</div>

<p><a href="/cases">&larr; Back to Cases</a></p>
""")


def kql_html(query: str = "", results: Optional[List[Dict[str, Any]]] = None, error: str = "") -> str:
    result_html = ""
    if error:
        result_html = f'<pre style="color:#e94560;">{_esc(error)}</pre>'
    elif results is not None:
        if not results:
            result_html = '<p class="info">Query returned no results.</p>'
        else:
            headers = list(results[0].keys())
            th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
            rows = ""
            for row in results:
                rows += "<tr>" + "".join(f"<td>{_esc(row.get(h, ''))}</td>" for h in headers) + "</tr>"
            result_html = f'<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>'

    return _base("KQL Query", f"""
<h1>KQL Query Runner</h1>
<form id="kqlForm">
<label for="query">KQL Query</label>
<textarea id="query" placeholder="StockEvents | take 100">{_esc(query)}</textarea>
<button type="submit" id="kqlBtn">&#9654; Execute</button>
</form>
<div id="kqlResult" class="result-area">{result_html}</div>
<script>
document.getElementById('kqlForm').addEventListener('submit', async function(e) {{
    e.preventDefault();
    const btn = document.getElementById('kqlBtn');
    btn.disabled = true; btn.textContent = 'Running...';
    const q = document.getElementById('query').value;
    try {{
        const resp = await fetch('/api/kql', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{query: q}})}});
        const data = await resp.json();
        if (data.error) {{
            document.getElementById('kqlResult').innerHTML = '<pre style="color:#e94560;">'+data.error+'</pre>';
        }} else if (data.results && data.results.length > 0) {{
            let headers = Object.keys(data.results[0]);
            let html = '<table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>';
            data.results.forEach(row => {{
                html += '<tr>'+headers.map(h=>'<td>'+(row[h]!=null?row[h]:'')+'</td>').join('')+'</tr>';
            }});
            html += '</tbody></table>';
            document.getElementById('kqlResult').innerHTML = html;
        }} else {{
            document.getElementById('kqlResult').innerHTML = '<p class="info">Query returned no results.</p>';
        }}
    }} catch(err) {{
        document.getElementById('kqlResult').innerHTML = '<pre style="color:#e94560;">Error: '+err.message+'</pre>';
    }}
    btn.disabled = false; btn.textContent = '\\u25B6 Execute';
}});
</script>
""")
