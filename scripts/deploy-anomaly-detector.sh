#!/usr/bin/env bash
# Deploy a Fabric anomaly detector via REST API
set -euo pipefail

WS_ID="${1:?Usage: deploy-anomaly-detector.sh <workspace-id> <kql-db-id>}"
KQL_DB_ID="${2:?Usage: deploy-anomaly-detector.sh <workspace-id> <kql-db-id>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DETECTOR_NAME="${ANOMALY_DETECTOR_NAME:-Market Price Anomalies}"
DETECTOR_DESCRIPTION="${ANOMALY_DETECTOR_DESCRIPTION:-Fabric anomaly detector for TRADES price series grouped by symbol.}"
TABLE_NAME="${ANOMALY_DETECTOR_TABLE:-TRADES}"
TIMESTAMP_COLUMN="${ANOMALY_DETECTOR_TIMESTAMP_COLUMN:-event_time}"
INSTANCE_COLUMN="${ANOMALY_DETECTOR_INSTANCE_COLUMN:-symbol}"
ATTRIBUTE_COLUMN="${ANOMALY_DETECTOR_ATTRIBUTE_COLUMN:-price}"
CONFIDENCE="${ANOMALY_DETECTOR_CONFIDENCE:-95}"
AUTO_PUBLISH="${ANOMALY_DETECTOR_AUTO_PUBLISH:-true}"

AUTO_PUBLISH_FLAG="--auto-publish"
if [[ "${AUTO_PUBLISH,,}" != "true" ]]; then
  AUTO_PUBLISH_FLAG="--no-auto-publish"
fi

TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

PAYLOAD=$(python3 "${SCRIPT_DIR}/build_anomaly_detector_payload.py" \
  --workspace-id "${WS_ID}" \
  --artifact-id "${KQL_DB_ID}" \
  --table-name "${TABLE_NAME}" \
  --timestamp-column "${TIMESTAMP_COLUMN}" \
  --instance-column "${INSTANCE_COLUMN}" \
  --attribute-column "${ATTRIBUTE_COLUMN}" \
  --display-name "${DETECTOR_NAME}" \
  --description "${DETECTOR_DESCRIPTION}" \
  --confidence "${CONFIDENCE}" \
  ${AUTO_PUBLISH_FLAG})

echo "Creating anomaly detector (${DETECTOR_NAME})..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "https://api.fabric.microsoft.com/v1/workspaces/${WS_ID}/anomalyDetectors" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "202" ]]; then
  echo "✓ Anomaly detector created"
elif echo "$BODY" | grep -q "ItemDisplayNameAlreadyInUse\|already exists"; then
  echo "✓ Anomaly detector already exists"
else
  echo "✗ Anomaly detector creation failed (HTTP $HTTP_CODE): $BODY" >&2
  exit 1
fi
