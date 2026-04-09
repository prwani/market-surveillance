#!/usr/bin/env bash
# =============================================================================
# Full Eventhouse setup: create Eventhouse + KQL DB, tables, ontology, functions
# =============================================================================
# Usage:
#   scripts/setup-eventhouse.sh
#
# Prerequisites:
#   - Fabric F8 capacity is Active
#   - Workspace mktsurveil-surveillance-dev exists
#   - az CLI logged in with Fabric access
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WS_ID="${WS_ID:-56f1c8c1-3395-43a5-8bab-74244c643306}"
KQL_DB="${KQL_DB:-surveillance}"

FABRIC_API="https://api.fabric.microsoft.com/v1"

echo "═══════════════════════════════════════════════════════"
echo " Eventhouse Full Setup"
echo "═══════════════════════════════════════════════════════"

# ── Step 1: Get tokens ────────────────────────────────────────────────────────
echo "[1/5] Obtaining access tokens..."
FABRIC_TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

# ── Step 2: Create or find Eventhouse ─────────────────────────────────────────
echo "[2/5] Creating Eventhouse..."

EH_RESPONSE=$(curl -s -X POST "${FABRIC_API}/workspaces/${WS_ID}/eventhouses" \
  -H "Authorization: Bearer ${FABRIC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"displayName":"surveillance-eh","description":"Market surveillance KQL database"}')

EH_ID=$(echo "${EH_RESPONSE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

if [[ -z "${EH_ID}" ]]; then
  echo "  Eventhouse creation response: ${EH_RESPONSE}"
  echo "  Trying to find existing Eventhouse..."
  EH_ID=$(curl -s "${FABRIC_API}/workspaces/${WS_ID}/eventhouses" \
    -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
    python3 -c "import json,sys; items=json.load(sys.stdin).get('value',[]); print(items[0]['id'] if items else '')" 2>/dev/null)

  if [[ -z "${EH_ID}" ]]; then
    echo "  ⚠ Could not create or find Eventhouse via API."
    echo "  → Create 'surveillance-eh' manually in the Fabric portal:"
    echo "    https://app.fabric.microsoft.com/groups/${WS_ID}"
    echo "  → Then re-run this script."
    echo ""
    echo "  Alternatively, if you already have the KQL URI, run:"
    echo "    KQL_URI=<uri> ${0}"
    if [[ -z "${KQL_URI:-}" ]]; then
      exit 1
    fi
  fi
fi

if [[ -n "${EH_ID}" ]]; then
  echo "  ✓ Eventhouse ID: ${EH_ID}"

  # ── Step 2b: Create KQL Database ────────────────────────────────────────────
  echo "  Creating KQL Database..."
  sleep 5
  DB_RESPONSE=$(curl -s -X POST "${FABRIC_API}/workspaces/${WS_ID}/kqlDatabases" \
    -H "Authorization: Bearer ${FABRIC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"displayName\":\"${KQL_DB}\",\"creationPayload\":{\"databaseType\":\"ReadWrite\",\"parentEventhouseItemId\":\"${EH_ID}\"}}")

  DB_ID=$(echo "${DB_RESPONSE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  if [[ -z "${DB_ID}" ]]; then
    echo "  DB response: ${DB_RESPONSE}"
    DB_ID=$(curl -s "${FABRIC_API}/workspaces/${WS_ID}/kqlDatabases" \
      -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
      python3 -c "import json,sys; items=json.load(sys.stdin).get('value',[]); [print(i['id']) for i in items if i.get('displayName')=='${KQL_DB}']" 2>/dev/null | head -1)
  fi

  if [[ -n "${DB_ID}" ]]; then
    echo "  ✓ KQL Database ID: ${DB_ID}"
    sleep 10
    KQL_URI=$(curl -s "${FABRIC_API}/workspaces/${WS_ID}/kqlDatabases/${DB_ID}" \
      -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
      python3 -c "import json,sys; print(json.load(sys.stdin).get('properties',{}).get('queryServiceUri',''))" 2>/dev/null)
    echo "  ✓ KQL URI: ${KQL_URI}"
  fi
fi

if [[ -z "${KQL_URI:-}" ]]; then
  echo "  ✗ Could not determine KQL URI"
  exit 1
fi

export KQL_URI

# ── Step 3: Create base tables ────────────────────────────────────────────────
echo ""
echo "[3/5] Creating base tables + ontology tables..."
bash "${SCRIPT_DIR}/init-kql-tables.sh" "${KQL_URI}" "${KQL_DB}"

# ── Step 4: Populate ontology graph ───────────────────────────────────────────
echo ""
echo "[4/5] Populating ontology graph..."
bash "${SCRIPT_DIR}/setup-ontology.sh" "${KQL_URI}" "${KQL_DB}"

# ── Step 5: Deploy stored functions ──────────────────────────────────────────
echo ""
echo "[5/5] Deploying KQL stored functions..."
bash "${SCRIPT_DIR}/deploy-stored-functions.sh" "${KQL_URI}" "${KQL_DB}"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Eventhouse Setup Complete"
echo "═══════════════════════════════════════════════════════"
echo " Eventhouse  : surveillance-eh (${EH_ID:-manual})"
echo " KQL Database: ${KQL_DB}"
echo " KQL URI     : ${KQL_URI}"
echo ""
echo " Tables: TRADES, ORDER_BOOK_EVENTS, BROKER_OWNERSHIP,"
echo "         ML_SCORES, INTERVENTIONS, ENTITIES, RELATIONSHIPS"
echo ""
echo " Functions: detect_spoofing(), detect_layering(),"
echo "            detect_wash_trading(), detect_anomalies(),"
echo "            detect_all(), resolve_ubo(), get_regulations()"
echo ""
echo " Next: Ingest test data with:"
echo "   PYTHONPATH=src:src/simulator python3 scripts/ingest-to-eventhouse.py \\"
echo "     --exchanges SGX HKEX NSE --duration 60 --kql-uri '${KQL_URI}'"
echo "═══════════════════════════════════════════════════════"
