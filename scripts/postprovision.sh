#!/usr/bin/env bash
# azd hook: runs after infrastructure provisioning (azd provision)
# Sets up Fabric workspace, Eventhouse, KQL tables, and grants permissions.
set -euo pipefail

echo "═══════════════════════════════════════════════════════"
echo " Post-provision: Setting up Fabric workspace"
echo "═══════════════════════════════════════════════════════"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get outputs from Bicep deployment (set as azd env values automatically)
FABRIC_CAPACITY_ID=$(azd env get-value FABRIC_CAPACITY_ID 2>/dev/null || echo "")
KV_NAME=$(azd env get-value KEY_VAULT_NAME 2>/dev/null || echo "")
PROJECT=$(azd env get-value PROJECT_NAME 2>/dev/null || echo "mktsurveil")
ENV_NAME=$(azd env get-value AZURE_ENV_NAME 2>/dev/null || echo "dev")

# 1. Set up Fabric workspace + Eventhouse
# The Fabric API needs the capacity GUID, not the ARM resource ID.
# Capacity name follows Bicep pattern: ${PROJECT}fabric${ENV_NAME}
FABRIC_TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
CAPACITY_NAME="${PROJECT}fabric${ENV_NAME}"
CAPACITY_GUID=$(curl -s "https://api.fabric.microsoft.com/v1/capacities" \
  -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
  jq -r ".value[] | select(.displayName == \"${CAPACITY_NAME}\") | .id" 2>/dev/null || echo "")

echo "  Looking for capacity: ${CAPACITY_NAME} → ${CAPACITY_GUID:-not found}"

if [[ -n "${CAPACITY_GUID}" && -f "${SCRIPT_DIR}/setup-fabric-workspace.sh" ]]; then
  # Pass the GUID, not the ARM ID
  bash "${SCRIPT_DIR}/setup-fabric-workspace.sh" "${CAPACITY_GUID}" "${PROJECT}" "${ENV_NAME}"
else
  echo "  ⚠ Fabric capacity GUID not found — skipping workspace setup"
fi

# 2. Discover KQL URI
FABRIC_TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
WORKSPACE_NAME="${PROJECT}-surveillance-${ENV_NAME}"
WORKSPACE_ID=$(curl -s "https://api.fabric.microsoft.com/v1/workspaces" \
  -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
  jq -r ".value[] | select(.displayName == \"${WORKSPACE_NAME}\") | .id")

KQL_URI=""
if [[ -n "${WORKSPACE_ID}" ]]; then
  KQL_URI=$(curl -s "https://api.fabric.microsoft.com/v1/workspaces/${WORKSPACE_ID}/kqlDatabases" \
    -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
    jq -r '.value[] | select(.displayName == "surveillance") | .properties.queryServiceUri')
fi

# 3. Store KQL URI as azd env value for deploy phase
if [[ -n "${KQL_URI}" ]]; then
  azd env set KQL_URI "${KQL_URI}"
  echo "KQL URI: ${KQL_URI}"
fi

# 4. Initialize KQL tables
if [[ -n "${KQL_URI}" && -f "${SCRIPT_DIR}/init-kql-tables.sh" ]]; then
  bash "${SCRIPT_DIR}/init-kql-tables.sh" "${KQL_URI}" "surveillance"
fi

# 5. Grant KQL permissions to deploying user
echo "Granting KQL permissions..."
KUSTO_TOKEN=$(az account get-access-token --resource "https://kusto.kusto.windows.net" --query accessToken -o tsv)
USER_OID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")
USER_UPN=$(az ad signed-in-user show --query userPrincipalName -o tsv 2>/dev/null || echo "")
if [[ -n "${KQL_URI}" && -n "${USER_UPN}" ]]; then
  curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
    -H "Authorization: Bearer ${KUSTO_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"db\":\"surveillance\",\"csl\":\".add database surveillance admins ('aaduser=${USER_OID};${USER_UPN}')\"}" > /dev/null
  echo "✓ KQL admin access granted to ${USER_UPN}"
fi

# 6. Deploy Fabric ontology item
echo "Deploying Fabric ontology item..."
if [[ -n "${WORKSPACE_ID}" && -f "${SCRIPT_DIR}/deploy-ontology.sh" ]]; then
  bash "${SCRIPT_DIR}/deploy-ontology.sh" "${WORKSPACE_ID}"
fi

# 7. Deploy Data Activator Reflex triggers
echo "Deploying Data Activator..."
if [[ -n "${WORKSPACE_ID}" && -f "${SCRIPT_DIR}/deploy-activator.sh" ]]; then
  bash "${SCRIPT_DIR}/deploy-activator.sh" "${WORKSPACE_ID}"
fi

# 8. Enable Python plugin on Eventhouse (required for anomaly detection models)
echo "Enabling Python plugin on Eventhouse..."
# Note: Python plugin enablement currently requires Fabric portal UI.
# Automated enablement via REST API is not yet available.
echo "  ⚠ Python plugin must be enabled manually in Fabric portal"
echo "    (Eventhouse → Plugins → Python 3.11.7 DL)"

echo "═══════════════════════════════════════════════════════"
echo " Post-provision complete (8 steps)"
echo "═══════════════════════════════════════════════════════"
