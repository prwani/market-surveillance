#!/usr/bin/env bash
# Deploy Data Activator Reflex triggers via REST API
set -euo pipefail

WS_ID="${1:?Usage: deploy-activator.sh <workspace-id>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

# Build the Reflex definition from our trigger JSON
REFLEX_PAYLOAD=$(python3 -c "
import json, base64

# Read our trigger definitions
with open('${SCRIPT_DIR}/../data_activator/reflex_triggers.json') as f:
    triggers = json.load(f)

# Build the ReflexEntities definition
reflex_def = {
    'version': '1.0',
    'dataSource': {
        'type': 'KustoQuery',
        'kqlDatabaseId': '',  # Will be configured post-creation
        'description': 'Market surveillance KQL detection functions',
    },
    'triggers': triggers.get('triggers', triggers) if isinstance(triggers, dict) else triggers,
}

platform = {
    'schemaVersion': '1.0',
    'metadata': {
        'type': 'Reflex',
        'displayName': 'Surveillance Alerts',
    }
}

payload = {
    'displayName': 'Surveillance Alerts',
    'description': 'Real-time market manipulation alerts via KQL detection functions',
    'definition': {
        'parts': [
            {
                'path': '.platform',
                'payload': base64.b64encode(json.dumps(platform).encode()).decode(),
                'payloadType': 'InlineBase64',
            },
            {
                'path': 'ReflexEntities.json',
                'payload': base64.b64encode(json.dumps(reflex_def).encode()).decode(),
                'payloadType': 'InlineBase64',
            },
        ]
    }
}
print(json.dumps(payload))
")

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
  echo "⚠ Reflex creation response (HTTP $HTTP_CODE): $BODY"
  echo "  Note: Data Activator rules may need manual configuration in the Fabric portal."
  echo "  See docs/data-activator-setup.md for step-by-step instructions."
fi
