# Fabric Notebook: Evidence Report Generator
# ============================================
# Compiles evidence and generates regulatory narrative for surveillance alerts.
# Uses Fabric built-in OpenAI (gpt-4.1) — no API key required.
#
# Parameters (set via Fabric pipeline or manual run):
#   - CASE_ID: Intervention case ID to compile report for
#   - KQL_URI: Eventhouse query URI
#   - KQL_DB: Database name (default: surveillance)

# %% [markdown]
# # Evidence Report Generator
# Compiles trade/order evidence for an intervention case and generates a
# regulatory narrative using Fabric's built-in OpenAI (gpt-4.1).

# %% Cell 1 — Configuration
CASE_ID = "CASE-001"  # Set via pipeline parameter
KQL_URI = "https://trd-z85435m8eppbw7fm7f.z0.kusto.fabric.microsoft.com"
KQL_DB = "surveillance"


# %% Cell 2 — Connect to Eventhouse
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

credential = DefaultAzureCredential()
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(KQL_URI, credential)
kusto = KustoClient(kcsb)


def run_kql(query):
    """Execute a KQL query and return results as a list of dicts."""
    resp = kusto.execute_query(KQL_DB, query)
    cols = [c.column_name for c in resp.primary_results[0].columns]
    return [dict(zip(cols, row)) for row in resp.primary_results[0]]


# %% Cell 3 — Fetch alert and related data

# Get the intervention case
interventions = run_kql(f"""
    INTERVENTIONS
    | where case_id == "{CASE_ID}"
    | take 1
""")
if not interventions:
    raise ValueError(f"Case {CASE_ID} not found in INTERVENTIONS table")

case = interventions[0]
exchange_id = case["exchange_id"]
symbol = case["symbol"]
manipulation_type = case["manipulation_type"]
detected_at = case["detected_at"]

# Get related trades (30 min window around detection)
trades = run_kql(f"""
    TRADES
    | where exchange_id == "{exchange_id}" and symbol == "{symbol}"
    | where event_time between (datetime({detected_at}) - 30m .. datetime({detected_at}) + 30m)
    | order by event_time asc
    | take 100
""")

# Get related order book events
orders = run_kql(f"""
    ORDER_BOOK_EVENTS
    | where exchange_id == "{exchange_id}" and symbol == "{symbol}"
    | where event_time between (datetime({detected_at}) - 30m .. datetime({detected_at}) + 30m)
    | order by event_time asc
    | take 100
""")

# Get UBO information for involved brokers
involved_brokers = case.get("involved_brokers", "[]")
ubo_info = run_kql(f"""
    resolve_ubo("{case.get('involved_brokers', '').split(',')[0] if isinstance(case.get('involved_brokers'), str) else ''}")
""")

# Get applicable regulations
regulations = run_kql(f"""
    get_regulations("{exchange_id}", "{manipulation_type}")
""")

print(f"Case: {CASE_ID}")
print(f"Exchange: {exchange_id}, Symbol: {symbol}")
print(f"Type: {manipulation_type}")
print(f"Related trades: {len(trades)}, Orders: {len(orders)}")
print(f"UBO chain: {len(ubo_info)} hops")
print(f"Regulations: {len(regulations)}")


# %% Cell 4 — Generate narrative with Fabric built-in OpenAI
from synapse.ml.fabric.credentials import get_openai_httpx_sync_client
import openai
import json

ai_client = openai.AzureOpenAI(
    http_client=get_openai_httpx_sync_client(),
    api_version="2025-04-01-preview",
)

prompt = f"""You are a financial market surveillance expert. Analyze the following trading data and produce a formal regulatory evidence report.

CASE ID: {CASE_ID}
EXCHANGE: {exchange_id}
SYMBOL: {symbol}
DETECTED MANIPULATION TYPE: {manipulation_type}

ORDER BOOK EVENTS (chronological, first 20):
{json.dumps(orders[:20], indent=2, default=str)}

TRADE EVENTS (first 20):
{json.dumps(trades[:20], indent=2, default=str)}

BENEFICIAL OWNERSHIP CHAIN:
{json.dumps(ubo_info, indent=2, default=str)}

APPLICABLE REGULATIONS:
{json.dumps(regulations, indent=2, default=str)}

Produce:
1. Executive Summary (2 paragraphs, suitable for senior regulator)
2. Timeline of Events (bullet points, chronological)
3. Evidence of Intent (explain why this is likely intentional manipulation)
4. Market Impact Analysis (estimated price distortion, affected investors)
5. Beneficial Ownership Analysis (trace the UBO chain)
6. Recommended Regulatory Action (cite specific regulations)
7. Supporting Data References (cite specific orders/trades by ID)

Regulatory jurisdiction: {regulations[0].get('regulator_name', 'UNKNOWN') if regulations else 'UNKNOWN'}
Language: English
"""

response = ai_client.chat.completions.create(
    model="gpt-4.1",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2,
)

narrative = response.choices[0].message.content
print("=== Generated Narrative ===")
print(narrative[:500] + "...")


# %% Cell 5 — Create CASE_REPORTS table and write report

# Create table if not exists
kusto.execute_mgmt(KQL_DB, """
    .create-merge table CASE_REPORTS (
        report_id: string,
        case_id: string,
        exchange_id: string,
        symbol: string,
        manipulation_type: string,
        regulatory_body: string,
        narrative: string,
        related_trades: int,
        related_orders: int,
        price_impact_pct: real,
        generated_at: datetime,
        model_used: string
    )
""")

# Compute price impact
if len(trades) >= 2:
    first_price = float(trades[0].get("price", 0))
    last_price = float(trades[-1].get("price", 0))
    price_impact = abs((last_price - first_price) / first_price * 100) if first_price > 0 else 0
else:
    price_impact = 0

import uuid
from datetime import datetime, timezone

report_id = f"RPT-{uuid.uuid4().hex[:10].upper()}"
now = datetime.now(timezone.utc).isoformat()
regulatory_body = regulations[0].get("regulator_name", "UNKNOWN") if regulations else "UNKNOWN"

# Escape narrative for KQL inline ingestion
safe_narrative = narrative.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")[:5000]

kusto.execute_mgmt(KQL_DB, f"""
    .ingest inline into table CASE_REPORTS <|
    {report_id},{CASE_ID},{exchange_id},{symbol},{manipulation_type},{regulatory_body},{safe_narrative},{len(trades)},{len(orders)},{round(price_impact, 4)},{now},gpt-4.1
""")

print(f"\n✓ Report {report_id} written to CASE_REPORTS table")
print(f"  Regulatory body: {regulatory_body}")
print(f"  Price impact: {price_impact:.2f}%")
print(f"  Model: gpt-4.1 (Fabric built-in)")
