#!/usr/bin/env bash
# =============================================================================
# Configure Fabric Eventstreams for Market Surveillance
# =============================================================================
#
# Fabric Eventstreams replace standalone Azure Event Hubs as the ingestion
# pathway from the simulator to the Eventhouse.
#
# Eventstreams are configured in the Fabric portal. This script documents the
# manual steps and validates that the resources exist via the Fabric REST API.
#
# Prerequisites:
#   - Azure CLI authenticated (az login)
#   - Fabric workspace already created (see setup-fabric-workspace.sh)
#   - Eventstreams already created (trades-stream, orderbook-stream)
# =============================================================================
set -euo pipefail

WORKSPACE_ID="${WORKSPACE_ID:-56f1c8c1-3395-43a5-8bab-74244c643306}"
TRADES_STREAM_ID="${TRADES_STREAM_ID:-42a08b09-23f8-4baa-8873-bbad95bc2d62}"
ORDERBOOK_STREAM_ID="${ORDERBOOK_STREAM_ID:-2c9995de-0b50-4b07-b170-2d9c651c055c}"
FABRIC_API="https://api.fabric.microsoft.com/v1"

echo "═══════════════════════════════════════════════════════════════"
echo "  Fabric Eventstream Configuration for Market Surveillance"
echo "═══════════════════════════════════════════════════════════════"

# ── Get Fabric API token ──────────────────────────────────────────
echo ""
echo "[1/3] Obtaining Fabric API access token..."
TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
echo "  ✓ Token acquired"

# ── Validate Eventstream resources ─────────────────────────────────
echo ""
echo "[2/3] Validating Eventstream resources..."

for STREAM_NAME_AND_ID in "trades-stream:${TRADES_STREAM_ID}" "orderbook-stream:${ORDERBOOK_STREAM_ID}"; do
  STREAM_NAME="${STREAM_NAME_AND_ID%%:*}"
  STREAM_ID="${STREAM_NAME_AND_ID##*:}"

  echo "  Checking ${STREAM_NAME} (${STREAM_ID})..."
  RESPONSE=$(curl -s -w "\n%{http_code}" \
    "${FABRIC_API}/workspaces/${WORKSPACE_ID}/eventstreams/${STREAM_ID}" \
    -H "Authorization: Bearer ${TOKEN}")

  HTTP_CODE=$(echo "${RESPONSE}" | tail -1)
  BODY=$(echo "${RESPONSE}" | sed '$d')

  if [[ "${HTTP_CODE}" == "200" ]]; then
    DISPLAY_NAME=$(echo "${BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('displayName','unknown'))" 2>/dev/null || echo "unknown")
    echo "  ✓ ${DISPLAY_NAME} exists (HTTP ${HTTP_CODE})"
  else
    echo "  ⚠ ${STREAM_NAME}: HTTP ${HTTP_CODE} — resource may need creation in Fabric portal"
  fi
done

# ── Document manual configuration steps ────────────────────────────
echo ""
echo "[3/3] Manual Configuration Steps"
echo ""
cat <<'STEPS'
┌─────────────────────────────────────────────────────────────────┐
│  Fabric Eventstream Custom App Source Configuration              │
│                                                                 │
│  Each Eventstream needs a "Custom App" source to accept data    │
│  from external applications (the simulator). This is configured │
│  via the Fabric portal — the REST API does not expose a direct  │
│  push endpoint.                                                 │
│                                                                 │
│  Steps (repeat for trades-stream and orderbook-stream):         │
│                                                                 │
│  1. Open the Fabric portal:                                     │
│     https://app.fabric.microsoft.com                            │
│                                                                 │
│  2. Navigate to workspace:                                      │
│     mktsurveil-surveillance-dev                                 │
│                                                                 │
│  3. Open the Eventstream (e.g., trades-stream)                  │
│                                                                 │
│  4. Click "+ Add source" → "Custom App"                         │
│     - Source name: simulator-input                              │
│     - This generates an Event Hub-compatible connection string  │
│                                                                 │
│  5. Copy the connection string from the Custom App source       │
│     - It looks like an Event Hub connection string              │
│     - Format: Endpoint=sb://<ns>.servicebus.windows.net/;...    │
│                                                                 │
│  6. Add a destination → "Eventhouse"                            │
│     - Select the 'surveillance' KQL database                    │
│     - Map to the appropriate table:                             │
│       • trades-stream    → TRADES                               │
│       • orderbook-stream → ORDER_BOOK_EVENTS                   │
│                                                                 │
│  7. Set the connection strings as environment variables:        │
│     export TRADES_STREAM_CONN_STR="Endpoint=sb://..."           │
│     export ORDERBOOK_STREAM_CONN_STR="Endpoint=sb://..."        │
│                                                                 │
│  NOTE: For programmatic ingestion without Eventstream setup,    │
│  use the KQL inline ingestion approach:                         │
│                                                                 │
│    python scripts/ingest-to-eventhouse.py \                     │
│      --exchanges SGX HKEX --duration 120                        │
│                                                                 │
│  This uses .ingest inline KQL commands via the Kusto REST API   │
│  and does not require Eventstream configuration.                │
└─────────────────────────────────────────────────────────────────┘
STEPS

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Configuration check complete"
echo "═══════════════════════════════════════════════════════════════"
