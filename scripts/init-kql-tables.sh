#!/usr/bin/env bash
# Initialize KQL tables in Fabric Eventhouse for the surveillance database
set -euo pipefail

KQL_URI="${1:?Usage: init-kql-tables.sh <kql-uri> <database-name>}"
KQL_DB="${2:?Missing database name}"

echo "Initializing KQL tables in ${KQL_DB} on Fabric Eventhouse..."

TOKEN=$(az account get-access-token --resource "https://kusto.kusto.windows.net" --query accessToken -o tsv)

run_kql() {
  local name="$1"
  local query="$2"
  echo "  Creating table: ${name}..."
  curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"db\":\"${KQL_DB}\",\"csl\":\"${query}\"}" \
    -o /dev/null -w ""
}

# ── TRADES table ──────────────────────────────────────────
run_kql "TRADES" ".create-merge table TRADES (trade_id: string, event_time: datetime, exchange_id: string, symbol: string, price: real, quantity: real, buyer_id: string, seller_id: string, order_type: string, venue: string)"

# ── ORDER_BOOK_EVENTS table ──────────────────────────────
run_kql "ORDER_BOOK_EVENTS" ".create-merge table ORDER_BOOK_EVENTS (event_id: string, event_time: datetime, exchange_id: string, symbol: string, side: string, price: real, quantity: real, action: string, broker_id: string)"

# ── BROKER_OWNERSHIP table ───────────────────────────────
run_kql "BROKER_OWNERSHIP" ".create-merge table BROKER_OWNERSHIP (broker_id: string, parent_entity: string, beneficial_owner: string, ownership_pct: real, jurisdiction: string, updated_at: datetime)"

# ── ML_SCORES table ──────────────────────────────────────
run_kql "ML_SCORES" ".create-merge table ML_SCORES (event_id: string, scored_at: datetime, spoofing_score: real, layering_score: real, wash_trading_score: real, anomaly_score: real, model_version: string, is_flagged: bool)"

# ── INTERVENTIONS table ──────────────────────────────────
run_kql "INTERVENTIONS" ".create-merge table INTERVENTIONS (case_id: string, detected_at: datetime, halted_at: datetime, exchange_id: string, symbol: string, manipulation_type: string, involved_brokers: dynamic, status: string, regulator_ref: string)"

# ── Ingestion mappings for Event Hub JSON ─────────────────
echo "  Creating ingestion mappings..."
run_kql "TRADES_MAPPING" ".create-or-alter table TRADES ingestion json mapping 'trades_json_mapping' '[{\"column\":\"trade_id\",\"path\":\"$.trade_id\"},{\"column\":\"event_time\",\"path\":\"$.event_time\"},{\"column\":\"exchange_id\",\"path\":\"$.exchange_id\"},{\"column\":\"symbol\",\"path\":\"$.symbol\"},{\"column\":\"price\",\"path\":\"$.price\"},{\"column\":\"quantity\",\"path\":\"$.quantity\"},{\"column\":\"buyer_id\",\"path\":\"$.buyer_id\"},{\"column\":\"seller_id\",\"path\":\"$.seller_id\"},{\"column\":\"order_type\",\"path\":\"$.order_type\"},{\"column\":\"venue\",\"path\":\"$.venue\"}]'"

run_kql "ORDER_BOOK_EVENTS_MAPPING" ".create-or-alter table ORDER_BOOK_EVENTS ingestion json mapping 'orderbook_json_mapping' '[{\"column\":\"event_id\",\"path\":\"$.event_id\"},{\"column\":\"event_time\",\"path\":\"$.event_time\"},{\"column\":\"exchange_id\",\"path\":\"$.exchange_id\"},{\"column\":\"symbol\",\"path\":\"$.symbol\"},{\"column\":\"side\",\"path\":\"$.side\"},{\"column\":\"price\",\"path\":\"$.price\"},{\"column\":\"quantity\",\"path\":\"$.quantity\"},{\"column\":\"action\",\"path\":\"$.action\"},{\"column\":\"broker_id\",\"path\":\"$.broker_id\"}]'"

echo "✓ All KQL tables initialized successfully"
