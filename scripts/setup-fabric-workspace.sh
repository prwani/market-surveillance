#!/usr/bin/env bash
# Create Fabric workspace, Eventhouse, and Eventstreams via Fabric REST API
set -euo pipefail

CAPACITY_ID="${1:?Usage: setup-fabric-workspace.sh <capacity-id> <project-name> <env>}"
PROJECT="${2:?Missing project name}"
ENV="${3:?Missing environment}"

WORKSPACE_NAME="${PROJECT}-surveillance-${ENV}"
FABRIC_API="https://api.fabric.microsoft.com/v1"

# Get access token for Fabric API
echo "Obtaining Fabric API access token..."
TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

fabric_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local url="${FABRIC_API}${path}"

  if [[ -n "${data}" ]]; then
    curl -s -X "${method}" "${url}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${data}"
  else
    curl -s -X "${method}" "${url}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json"
  fi
}

# ── Create Workspace ──────────────────────────────────────
echo "Creating Fabric workspace: ${WORKSPACE_NAME}..."
WORKSPACE_RESPONSE=$(fabric_api POST "/workspaces" "{
  \"displayName\": \"${WORKSPACE_NAME}\",
  \"description\": \"Market Surveillance Real-Time Intelligence workspace\",
  \"capacityId\": \"${CAPACITY_ID}\"
}")

WORKSPACE_ID=$(echo "${WORKSPACE_RESPONSE}" | jq -r '.id // empty')
if [[ -z "${WORKSPACE_ID}" ]]; then
  # Workspace may already exist — try to find it
  echo "  Workspace creation returned: ${WORKSPACE_RESPONSE}"
  echo "  Attempting to find existing workspace..."
  EXISTING=$(fabric_api GET "/workspaces" | jq -r ".value[] | select(.displayName == \"${WORKSPACE_NAME}\") | .id")
  if [[ -n "${EXISTING}" ]]; then
    WORKSPACE_ID="${EXISTING}"
    echo "  Found existing workspace: ${WORKSPACE_ID}"
  else
    echo "  ✗ Failed to create or find workspace"
    exit 1
  fi
fi
echo "  ✓ Workspace ID: ${WORKSPACE_ID}"

# ── Create Eventhouse ─────────────────────────────────────
echo "Creating Eventhouse: surveillance-eh..."
EH_RESPONSE=$(fabric_api POST "/workspaces/${WORKSPACE_ID}/eventhouses" "{
  \"displayName\": \"surveillance-eh\",
  \"description\": \"Market surveillance KQL database for real-time analytics\"
}")

EVENTHOUSE_ID=$(echo "${EH_RESPONSE}" | jq -r '.id // empty')
if [[ -z "${EVENTHOUSE_ID}" ]]; then
  echo "  Eventhouse creation returned: ${EH_RESPONSE}"
  echo "  Attempting to find existing eventhouse..."
  EXISTING_EH=$(fabric_api GET "/workspaces/${WORKSPACE_ID}/eventhouses" | jq -r '.value[] | select(.displayName == "surveillance-eh") | .id')
  if [[ -n "${EXISTING_EH}" ]]; then
    EVENTHOUSE_ID="${EXISTING_EH}"
    echo "  Found existing eventhouse: ${EVENTHOUSE_ID}"
  else
    echo "  ⚠ Could not create Eventhouse — may require manual creation in Fabric portal"
    EVENTHOUSE_ID="PENDING"
  fi
fi
echo "  ✓ Eventhouse ID: ${EVENTHOUSE_ID}"

# ── Create KQL Database ──────────────────────────────────
if [[ "${EVENTHOUSE_ID}" != "PENDING" ]]; then
  echo "Creating KQL Database: surveillance..."
  DB_RESPONSE=$(fabric_api POST "/workspaces/${WORKSPACE_ID}/kqlDatabases" "{
    \"displayName\": \"surveillance\",
    \"description\": \"Market surveillance time-series database\",
    \"creationPayload\": {
      \"databaseType\": \"ReadWrite\",
      \"parentEventhouseItemId\": \"${EVENTHOUSE_ID}\"
    }
  }")
  KQL_DB_ID=$(echo "${DB_RESPONSE}" | jq -r '.id // empty')
  if [[ -z "${KQL_DB_ID}" ]]; then
    echo "  DB creation response: ${DB_RESPONSE}"
    EXISTING_DB=$(fabric_api GET "/workspaces/${WORKSPACE_ID}/kqlDatabases" | jq -r '.value[] | select(.displayName == "surveillance") | .id')
    if [[ -n "${EXISTING_DB}" ]]; then
      KQL_DB_ID="${EXISTING_DB}"
      echo "  Found existing database: ${KQL_DB_ID}"
    else
      echo "  ⚠ Could not create KQL database"
      KQL_DB_ID="PENDING"
    fi
  fi
  echo "  ✓ KQL Database ID: ${KQL_DB_ID}"
fi

# ── Create Eventstreams ───────────────────────────────────
for STREAM_NAME in "trades-stream" "orderbook-stream"; do
  echo "Creating Eventstream: ${STREAM_NAME}..."
  ES_RESPONSE=$(fabric_api POST "/workspaces/${WORKSPACE_ID}/eventstreams" "{
    \"displayName\": \"${STREAM_NAME}\",
    \"description\": \"${STREAM_NAME} for market surveillance data ingestion\"
  }")
  ES_ID=$(echo "${ES_RESPONSE}" | jq -r '.id // empty')
  if [[ -z "${ES_ID}" ]]; then
    echo "  Eventstream creation response: ${ES_RESPONSE}"
    EXISTING_ES=$(fabric_api GET "/workspaces/${WORKSPACE_ID}/eventstreams" | jq -r ".value[] | select(.displayName == \"${STREAM_NAME}\") | .id")
    if [[ -n "${EXISTING_ES}" ]]; then
      echo "  Found existing eventstream: ${EXISTING_ES}"
    else
      echo "  ⚠ Could not create eventstream ${STREAM_NAME}"
    fi
  else
    echo "  ✓ Eventstream ID: ${ES_ID}"
  fi
done

# ── Summary ───────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Fabric Workspace Setup Summary"
echo "═══════════════════════════════════════════════════════"
echo " Workspace   : ${WORKSPACE_NAME} (${WORKSPACE_ID})"
echo " Eventhouse  : surveillance-eh (${EVENTHOUSE_ID})"
echo " KQL Database: surveillance (${KQL_DB_ID:-PENDING})"
echo " Eventstreams: trades-stream, orderbook-stream"
echo "═══════════════════════════════════════════════════════"
