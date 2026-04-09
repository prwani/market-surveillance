# Getting Started — Verifying Your Deployment

After running `azd up`, follow these steps to verify each component is working.

## 1. Open the Dashboard

Your dashboard URL was shown at the end of `azd up`:
```
Endpoint: https://mktsurveil-agent-dev.xxxxxx.southeastasia.azurecontainerapps.io/
```

Open it in your browser. You should see the Market Surveillance home page with navigation to Simulate, Alerts, Cases, and KQL.

## 2. Run Your First Simulation

1. Click **Simulate** in the navigation bar
2. Select exchanges: ✅ SGX, ✅ HKEX
3. Set duration: 120 seconds
4. Enable manipulation types: ✅ Spoofing, ✅ Layering, ✅ Wash Trading
5. Click **Run Simulation**
6. Wait ~5 seconds — you should see results:
   - Events generated: ~10,000+
   - Alerts: 30-80
   - Cases: 5-30

## 3. Review Alerts

Click **Alerts** to see detected manipulation patterns:
- **SPOOFING** (🔴 CRITICAL) — broker placed large orders then cancelled >80% within 500ms
- **LAYERING** (🟠 HIGH) — multiple price levels with mass cancellation
- **WASH_TRADING** (🟠 HIGH) — same beneficial owner on both sides

## 4. Review Intervention Cases

Click **Cases** to see automated interventions:
- Each case shows: trade halt, regulator notification, broker suspension
- Status: NOTIFIED (regulator was alerted)

## 5. Try KQL Queries

Click **KQL** and try these queries:

### Count all data
```kusto
TRADES | count
```

### Find spoofing brokers
```kusto
ORDER_BOOK_EVENTS
| where action in ("add", "cancel")
| summarize added=countif(action=="add"), cancelled=countif(action=="cancel")
    by broker_id, symbol
| where added > 0 and cancelled*1.0/added > 0.80
| order by cancelled desc
```

### Resolve a broker's beneficial owner (ontology graph)
```kusto
resolve_ubo("BROKER_SGX_001")
```
This shows the 3-hop ownership chain: Broker → Fund → Holding Company → Person

### Find applicable regulations
```kusto
get_regulations("SGX", "SPOOFING")
```

### Run all detection functions at once
```kusto
detect_spoofing()
detect_layering()
detect_wash_trading()
detect_anomalies()
```

## 6. Verify Fabric Artifacts (Azure Portal)

1. Go to [Fabric Portal](https://app.fabric.microsoft.com)
2. Open workspace: `mktsurveil-surveillance-dev`
3. Verify:
   - ✅ Eventhouse: `surveillance-eh`
   - ✅ KQL Database: `surveillance`
   - ✅ Tables: TRADES, ORDER_BOOK_EVENTS, ENTITIES, RELATIONSHIPS
   - ✅ Stored Functions: detect_spoofing, detect_layering, etc.

## 7. Import the Ontology and Use FabricIQ NL Queries

The ontology enables **natural language queries** in the Fabric portal —
ask questions in plain English instead of writing KQL.

### Import the Ontology

1. Open [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Navigate to workspace: `mktsurveil-surveillance-dev`
3. Go to **Settings** → **Ontology** (or **IQ** → **Ontology**)
4. Click **Import ontology** → upload `ontology/market-surveillance.rdf`
5. Map entity types to Eventhouse tables (see
   [Ontology Playground Guide](ontology-playground-guide.md#step-5-import-into-fabriciq-schema--data-mapping)
   for the full mapping table)
6. Save the mapping

### Ask Natural Language Questions

After importing, open **Copilot for Fabric** (or the IQ query bar) in the
Fabric portal and try these sample questions:

**Beneficial Ownership & Entity Resolution:**
- "Who is the ultimate beneficial owner of BROKER_SGX_001?"
- "Which brokers share a beneficial owner?"
- "Show me the ownership chain for Alpha Fund Singapore"
- "List all brokers under the same holding company as BROKER_HKEX_001"

**Trade Surveillance:**
- "Show me all trades on SGX for OCBC in the last hour"
- "Which brokers have the highest trade volume today?"
- "Find trades where the buyer and seller are under the same holding company"
- "What is the average trade price for DBS on SGX?"

**Manipulation Detection:**
- "Which brokers have a cancel rate above 80%?"
- "Find brokers who placed orders at 5 or more price levels then cancelled them"
- "Are there any wash trades between related accounts?"
- "Show me price anomalies across all exchanges"

**Regulatory:**
- "Which regulations apply to spoofing on SGX?"
- "What is the regulatory body for HKEX?"
- "List all regulations enforced by MAS"

> **Note:** FabricIQ translates these natural language questions into KQL
> queries using the ontology as a guide. The ontology tells FabricIQ that
> "beneficial owner" means traversing the `parent_entity → beneficial_owner`
> relationship chain in the RELATIONSHIPS table — the user doesn't need to
> know KQL or the table structure.

For a detailed guide on ontology design and the schema-to-data relationship,
see [Ontology Playground Guide](ontology-playground-guide.md).

## 8. Set Up Data Activator (Optional)

For autonomous real-time alerting without the dashboard:
See [Data Activator Setup Guide](data-activator-setup.md)

## Architecture Overview

```
Exchange Simulator
        │
        ▼
  Fabric Eventhouse (KQL DB)
  ┌─────────────────────────────────────┐
  │  TRADES, ORDER_BOOK_EVENTS          │
  │  ENTITIES, RELATIONSHIPS (ontology) │
  │                                     │
  │  KQL Stored Functions:              │
  │  • detect_spoofing()                │
  │  • detect_layering()                │
  │  • detect_wash_trading() + UBO      │
  │  • detect_anomalies()               │
  │  • resolve_ubo()                    │
  │  • get_regulations()                │
  └───────────┬─────────────────────────┘
              │
    ┌─────────┼──────────┐
    ▼                    ▼
Data Activator      Dashboard (ACA)
(Reflex triggers)   (FastAPI UI)
    │
    ▼
Trade Halt / Regulator Alert / Teams Notification
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Dashboard shows 0 alerts | Run a simulation first (Simulate page) |
| KQL page says "not configured" | `KQL_URI` env var not set — re-run `azd provision` |
| Fabric capacity paused | Resume: `az fabric capacity resume --capacity-name mktsurveilfabricdev --resource-group rg-dev` |
| `azd up` fails at Key Vault | Purge soft-deleted KV: `az keyvault purge --name mktsurveil-kv-dev` then retry |
