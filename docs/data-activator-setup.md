# Data Activator (Reflex) Setup Guide

> **Note:** Data Activator is automatically deployed by `azd up`. This guide
> is only needed if you want to customize the trigger rules or if the
> automatic deployment encountered an API limitation in your tenant.

Step-by-step instructions for configuring real-time surveillance triggers in the Fabric portal. Data Activator requires portal-based configuration — this guide walks through the full setup.

## Prerequisites

- Fabric workspace **market-surveillance** with Eventhouse **surveillance-eh** deployed
- Eventhouse database **surveillance** with detection functions deployed (`stored_functions.kql`)
- Intervention Agent webhook URL (ACA or Azure Functions endpoint)
- Microsoft Teams incoming webhook URL for the surveillance desk channel

## Step 1: Create the Reflex Item

1. Navigate to your **market-surveillance** workspace in the Fabric portal
2. Click **+ New** → **Reflex**
3. Name it `MarketSurveillanceReflex`
4. Click **Create**

## Step 2: Connect to Eventhouse Data Source

1. In the Reflex editor, click **Get data**
2. Select **Eventhouse / KQL Database**
3. Choose the **surveillance-eh** Eventhouse and **surveillance** database
4. Click **Connect**

## Step 3: Create Spoofing Alert Trigger

1. Click **+ New trigger**
2. Configure:
   - **Name:** `Spoofing Alert`
   - **Source:** KQL query — paste the query from `detect_spoofing()`:
     ```kql
     ORDER_BOOK_EVENTS
     | where event_time > ago(1m)
     | where action in ("add", "cancel")
     | summarize
         orders_added = countif(action == "add"),
         orders_cancelled = countif(action == "cancel"),
         avg_size_added = avgif(quantity, action == "add"),
         avg_cancel_latency_ms = avg(iff(action == "cancel",
             datetime_diff("millisecond", event_time, prev(event_time, 1)), 0))
         by broker_id, symbol, exchange_id, bin(event_time, 1m)
     | where orders_added > 0
     | where (orders_cancelled * 1.0 / orders_added) > 0.80
     | where avg_cancel_latency_ms < 500
     | where avg_size_added > 10000
     ```
   - **Schedule:** Every **30 seconds**
   - **Condition:** Any rows returned
3. Add actions:
   - **Action 1 — HTTP Webhook:**
     - URL: `${INTERVENTION_AGENT_WEBHOOK_URL}`
     - Method: POST
     - Body: JSON with `alert_type`, `exchange_id`, `symbol`, `broker_id`, `cancel_rate`
   - **Action 2 — Teams Notification:**
     - Webhook URL: `${TEAMS_WEBHOOK_URL}`
     - Message: `🚨 SPOOFING DETECTED | {{exchange_id}} / {{symbol}} | Broker: {{broker_id}}`

## Step 4: Create Layering Alert Trigger

1. Click **+ New trigger**
2. Configure:
   - **Name:** `Layering Alert`
   - **Source:** KQL query from `detect_layering()`:
     ```kql
     ORDER_BOOK_EVENTS
     | where event_time > ago(2m)
     | summarize
         price_levels = dcount(price),
         orders_placed = countif(action == "add"),
         orders_cancelled = countif(action == "cancel")
         by broker_id, symbol, exchange_id, side, bin(event_time, 30s)
     | where price_levels >= 5
     | where orders_placed > 0
     | extend cancel_fraction = round(orders_cancelled * 1.0 / orders_placed, 3)
     | where cancel_fraction >= 0.70
     ```
   - **Schedule:** Every **60 seconds**
   - **Condition:** Any rows returned
3. Add actions:
   - **Action 1 — HTTP Webhook** (same pattern as spoofing, with `alert_type: LAYERING`)
   - **Action 2 — Teams Notification:**
     - Message: `🚨 LAYERING DETECTED | {{exchange_id}} / {{symbol}} | {{price_levels}} price levels`

## Step 5: Create Wash Trading Alert Trigger

1. Click **+ New trigger**
2. Configure:
   - **Name:** `Wash Trading Alert`
   - **Source:** KQL query from `detect_wash_trading()` (uses UBO resolution)
   - **Schedule:** Every **5 minutes**
   - **Condition:** Any rows returned (`wash_count >= 3`)
3. Add actions:
   - **Action 1 — HTTP Webhook** (with `alert_type: WASH_TRADING`)
   - **Action 2 — Teams Notification:**
     - Message: `🚨 WASH TRADING DETECTED | {{exchange_id}} / {{symbol}} | UBO: {{ultimate_owner}}`

## Step 6: Create Volume Anomaly Alert Trigger

1. Click **+ New trigger**
2. Configure:
   - **Name:** `Volume Anomaly Alert`
   - **Source:** KQL query using `series_decompose_anomalies` on TRADES volume
   - **Schedule:** Every **60 seconds**
   - **Condition:** `z_score >= 3.0`
3. Add actions:
   - **Action 1 — HTTP Webhook** (with `alert_type: VOLUME_SPIKE`)
   - **Action 2 — Teams Notification:**
     - Message: `⚠️ VOLUME SPIKE | {{exchange_id}} / {{symbol}} | Z-score: {{z_score}}`

## Step 7: Activate All Triggers

1. In the Reflex overview, verify all four triggers appear:
   | Trigger | Schedule | Status |
   |---------|----------|--------|
   | Spoofing Alert | PT30S | Ready |
   | Layering Alert | PT60S | Ready |
   | Wash Trading Alert | PT5M | Ready |
   | Volume Anomaly Alert | PT60S | Ready |
2. Click **Activate all** or toggle each trigger individually
3. Monitor the **Run history** tab for trigger executions

## Step 8: Verify End-to-End

1. Run `scripts/run_demo.py` or `run_demo.py` to generate simulated market data
2. Watch for trigger firings in the Reflex monitoring view
3. Confirm webhook delivery to the Intervention Agent
4. Confirm Teams notifications arrive at the surveillance desk channel

## Environment Variables

Set these in the Reflex configuration or Fabric workspace secrets:

| Variable | Description |
|----------|-------------|
| `KQL_URI` | Fabric Eventhouse KQL query URI |
| `INTERVENTION_AGENT_WEBHOOK_URL` | HTTP endpoint of the Intervention Agent API |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams incoming webhook URL |

## Reference

- Trigger definitions: [`data_activator/reflex_triggers.json`](../data_activator/reflex_triggers.json)
- Detection KQL functions: [`kql/stored_functions.kql`](../kql/stored_functions.kql)
- Architecture overview: [`docs/architecture-whitepaper.md`](architecture-whitepaper.md)
