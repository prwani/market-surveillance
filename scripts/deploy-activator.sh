#!/usr/bin/env bash
# Deploy Data Activator Reflex triggers via REST API
set -euo pipefail

WS_ID="${1:?Usage: deploy-activator.sh <workspace-id>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
KQL_URI="$(azd env get-value KQL_URI 2>/dev/null || echo "")"
FABRIC_ADMIN_UPN="$(azd env get-value FABRIC_ADMIN_UPN 2>/dev/null || echo "")"
USER_UPN="$(az ad signed-in-user show --query userPrincipalName -o tsv 2>/dev/null || echo "")"
ALERT_RECIPIENT="${ACTIVATOR_ALERT_RECIPIENT:-${FABRIC_ADMIN_UPN:-${USER_UPN}}}"

if [[ -z "${KQL_URI}" ]]; then
  echo "⚠ KQL_URI is not set, skipping Reflex deployment"
  exit 0
fi

if [[ -z "${ALERT_RECIPIENT}" ]]; then
  echo "⚠ No alert recipient available for Reflex deployment"
  exit 0
fi

REFLEX_PAYLOAD=$(python3 "${SCRIPT_DIR}/build_reflex_payload.py" \
  --config "${SCRIPT_DIR}/../data_activator/reflex_triggers.json" \
  --workspace-id "${WS_ID}" \
  --cluster-uri "${KQL_URI}" \
  --database "surveillance" \
  --alert-recipient "${ALERT_RECIPIENT}")

echo "Creating Data Activator Reflex..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "https://api.fabric.microsoft.com/v1/workspaces/${WS_ID}/reflexes" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${REFLEX_PAYLOAD}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "202" ]]; then
  echo "✓ Data Activator Reflex created"
elif echo "$BODY" | grep -q "AlreadyInUse\|already exists"; then
  echo "✓ Reflex already exists"
else
  echo "✗ Reflex creation failed (HTTP $HTTP_CODE): $BODY" >&2
  exit 1
fi
