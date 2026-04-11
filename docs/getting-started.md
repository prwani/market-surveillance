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

Click **Cases** to review the dashboard demo's generated intervention cases:
- Each case summarizes the alert, supporting evidence, and recommended response
- Status values come from the local demo workflow shown in the dashboard

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

## 7. Inspect the Ontology Item

The ontology item is created during `azd up` as `Market_Surveillance`. To inspect it:

1. Open [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Navigate to workspace: `mktsurveil-surveillance-<env>`
3. Click on **Market_Surveillance**
4. Verify the item shows the deployed entity model:
   - Broker, Fund, HoldingCompany, BeneficialOwner
   - Exchange, Instrument, Regulator, Regulation
   - Trade, Alert, InterventionCase
5. Verify the relationship model includes:
   - `ownedBy`, `managedBy`, `controlledBy`
   - `listedOn`, `regulatedBy`, `enforces`
   - `executedBy`, `tradedInstrument`, `triggersAlert`

> **Note:** Fabric item names created through the API must use letters,
> numbers, or `_`, so the deployed ontology item is named
> `Market_Surveillance`.

> **Important:** Fabric also creates a companion graph model item named
> `Market_Surveillance_graph_<id>`. That graph canvas stays empty until ontology
> **data bindings** are configured. The current `azd up` flow deploys the
> ontology schema, but it does not yet bind entity types to OneLake/Eventhouse
> source tables, so seeing `Nodes (0)` and `Edges (0)` there is expected.

For a detailed guide on visualizing the RDF in Ontology Playground and
manually binding the schema in another FabricIQ setup, see
[Ontology Playground Guide](ontology-playground-guide.md).

## 8. Verify Data Activator Alerts

Data Activator was automatically configured during `azd up`. To verify:

1. In the Fabric workspace, click **Surveillance Alerts** (Reflex item)
2. Verify the deployed rule set is present:
   - Spoofing Alert
   - Layering Alert
   - Wash Trading Alert
   - Price And Volume Anomaly Alert
3. Each rule runs a KQL detection function against the `surveillance` database on a
   5-minute cadence
4. The default deployment action is a Teams notification sent to
   `FABRIC_ADMIN_UPN` (or the signed-in Azure user if that variable is unset)
5. Run a simulation from the dashboard, then inspect the Reflex run history in the
   Fabric portal to confirm the rules evaluate against live Eventhouse data

> **Note:** `azd up` creates the Reflex item and rules automatically. No manual
> JSON import or portal-based authoring is required for the baseline deployment.

## 9. Explore Fabric RTI Features (Optional)

Two preview features enhance the detection pipeline:

### Anomaly Detection Models
1. In the Fabric workspace, navigate to Eventhouse → `surveillance-eh`
2. Enable **Python plugin** (Plugins → Python 3.11.7 DL)
3. Ensure a Fabric admin has enabled **Detect anomalies in Real-Time
   Intelligence (Preview)** in tenant settings
4. Select `TRADES` table → **Create Anomaly Detector**
5. Configure: Value=`price`, Group by=`symbol`, Timestamp=`event_time`
6. Run analysis → review recommended models
7. Publish to Real-Time Hub for continuous monitoring

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
(Reflex alerts)     (FastAPI UI)
    │
    ▼
Teams Notification / Alert Desk Review
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Dashboard shows 0 alerts | Run a simulation first (Simulate page) |
| KQL page says "not configured" | `KQL_URI` env var not set — re-run `azd provision` |
| Fabric capacity paused | Resume: `az fabric capacity resume --capacity-name mktsurveilfabric<env> --resource-group rg-<env>` |
| `Market_Surveillance_graph_<id>` shows `Nodes (0)` / `Edges (0)` | Expected until ontology data bindings are added. Current deployment creates the schema item, not a populated bound graph model. |
| `azd up` fails at Key Vault | Purge soft-deleted KV: `az keyvault purge --name mktsurveil-kv-<env>` then retry |
