# Getting Started — Verifying Your Deployment

> **Resource naming:** This guide uses `<env>` as a placeholder for your
> environment name (e.g., `dev`, `staging`, `prod`). Replace it with the
> name you used in `azd env new <env>`. For example, if you ran
> `azd env new staging`, your resource group is `rg-staging` and your
> Fabric capacity is `mktsurveilfabricstaging`.

After running `azd up`, follow these steps to verify each component is working.

## 1. Open the Dashboard

Your dashboard URL was shown at the end of `azd up`:
```
Endpoint: <your-dashboard-url>
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
2. Open workspace: `mktsurveil-surveillance-<env>`
3. Verify:
   - ✅ Eventhouse: `surveillance-eh`
   - ✅ KQL Database: `surveillance`
   - ✅ Tables: TRADES, ORDER_BOOK_EVENTS, ENTITIES, RELATIONSHIPS
   - ✅ Stored Functions: detect_spoofing, detect_layering, etc.

## 7. Explore the Ontology in FabricIQ

The ontology was automatically imported during `azd up`. To explore it:

1. Open [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Navigate to workspace: `mktsurveil-surveillance-<env>`
3. Click on **Market Surveillance** ontology item
4. You'll see the entity graph: Brokers → Funds → Holdings → Beneficial Owners

### Try Natural Language Queries

Open **Copilot for Fabric** (or the IQ query bar) in the
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

## 8. Verify Data Activator Alerts

Data Activator was automatically configured during `azd up`. To verify:

1. In the Fabric workspace, click **Surveillance Alerts** (Reflex item)
2. You'll see 4 trigger rules:
   - Spoofing Alert (runs every 30s)
   - Layering Alert (runs every 30s)
   - Wash Trading Alert (runs every 5m)
   - Volume Anomaly Alert (runs every 1m)
3. Each trigger monitors KQL detection functions and fires when patterns are found
4. Actions: HTTP webhook (intervention API) and Teams notification

> **Note:** If triggers show as inactive, click **Activate** on each one.
> Trigger activation requires data flowing through Eventhouse — run a
> simulation from the dashboard first to populate the tables.

## 9. Explore Fabric RTI Features (Optional)

Two preview features enhance the detection pipeline:

### Anomaly Detection Models
1. In the Fabric workspace, navigate to Eventhouse → `surveillance-eh`
2. Enable **Python plugin** (Plugins → Python 3.11.7 DL)
3. Select `TRADES` table → **Create Anomaly Detector**
4. Configure: Value=`price`, Group by=`symbol`, Timestamp=`event_time`
5. Run analysis → review recommended models
6. Publish to Real-Time Hub for continuous monitoring

### Operations Agent (Advisory)
1. In workspace, **Create** → **Operations Agent**
2. Name: `Surveillance Advisor`
3. Paste the business goals and instructions from [the guide](fabric-rti-features.md#recommended-configuration)
4. Connect to `surveillance` KQL database
5. The agent will start monitoring and sending Teams recommendations every 5 minutes

> **Note:** Both features are in preview and require manual portal setup.
> They complement (not replace) the automated KQL + Data Activator pipeline.

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
| Fabric capacity paused | Resume: `az fabric capacity resume --capacity-name mktsurveilfabric<env> --resource-group rg-<env>` |
| `azd up` fails at Key Vault | Purge soft-deleted KV: `az keyvault purge --name mktsurveil-kv-<env>` then retry |
