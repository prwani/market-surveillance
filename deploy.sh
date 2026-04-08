#!/usr/bin/env bash
# Deploy Market Surveillance infrastructure to Azure
set -euo pipefail

SUBSCRIPTION_ID="23835f6b-9ad7-4c33-b0b8-55157ad0d2b5"
ENV="${1:-dev}"
PROJECT="mktsurveil"
LOCATION="southeastasia"
RESOURCE_GROUP="rg-market-surveillance-${ENV}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "═══════════════════════════════════════════════════════"
echo " Market Surveillance — Azure Deployment"
echo " Environment : ${ENV}"
echo " Resource Group: ${RESOURCE_GROUP}"
echo " Location      : ${LOCATION}"
echo "═══════════════════════════════════════════════════════"

# ── Set subscription ──────────────────────────────────────
echo "[1/6] Setting Azure subscription..."
az account set --subscription "${SUBSCRIPTION_ID}"

# ── Create resource group ─────────────────────────────────
echo "[2/6] Creating resource group ${RESOURCE_GROUP}..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --tags project="${PROJECT}" environment="${ENV}" managedBy=bicep system=market-surveillance \
  --output none

# ── Deploy Bicep template ─────────────────────────────────
echo "[3/6] Deploying Bicep infrastructure..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${SCRIPT_DIR}/infra/main.bicep" \
  --parameters "${SCRIPT_DIR}/infra/parameters/${ENV}.bicepparam" \
  --name "surveillance-${ENV}-$(date +%Y%m%d%H%M%S)" \
  --output json)

# Parse outputs
EH_NAMESPACE=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.eventHubNamespace.value')
ADX_URI=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.adxClusterUri.value')
ADX_DB=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.adxDatabaseName.value')
KV_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.keyVaultName.value')
STORAGE_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.storageAccountName.value')
CA_ENV=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppEnvironment.value')
CA_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppName.value')

# ── Store secrets in Key Vault ────────────────────────────
echo "[4/6] Storing connection strings in Key Vault..."
EH_CONN=$(az eventhubs namespace authorization-rule keys list \
  --resource-group "${RESOURCE_GROUP}" \
  --namespace-name "${EH_NAMESPACE}" \
  --name "surveillance-app" \
  --query primaryConnectionString -o tsv)

az keyvault secret set --vault-name "${KV_NAME}" --name "eventhub-connection-string" --value "${EH_CONN}" --output none
az keyvault secret set --vault-name "${KV_NAME}" --name "adx-cluster-uri" --value "${ADX_URI}" --output none
az keyvault secret set --vault-name "${KV_NAME}" --name "adx-database-name" --value "${ADX_DB}" --output none
az keyvault secret set --vault-name "${KV_NAME}" --name "storage-account-name" --value "${STORAGE_NAME}" --output none

# ── Initialize KQL tables ────────────────────────────────
echo "[5/6] Initializing ADX tables..."
if [[ -f "${SCRIPT_DIR}/scripts/init-kql-tables.sh" ]]; then
  bash "${SCRIPT_DIR}/scripts/init-kql-tables.sh" "${ADX_URI}" "${ADX_DB}" "${RESOURCE_GROUP}"
else
  echo "  ⚠ init-kql-tables.sh not found — skipping table init"
fi

# ── Print summary ─────────────────────────────────────────
echo "[6/6] Deployment complete!"
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Deployment Summary"
echo "═══════════════════════════════════════════════════════"
echo " Resource Group      : ${RESOURCE_GROUP}"
echo " Event Hubs Namespace: ${EH_NAMESPACE}"
echo " ADX Cluster URI     : ${ADX_URI}"
echo " ADX Database        : ${ADX_DB}"
echo " Key Vault           : ${KV_NAME}"
echo " Storage Account     : ${STORAGE_NAME}"
echo " Container App Env   : ${CA_ENV}"
echo " Container App       : ${CA_NAME}"
echo "═══════════════════════════════════════════════════════"
