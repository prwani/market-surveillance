#!/usr/bin/env bash
# Deploy Market Surveillance infrastructure to Azure
# KQL database runs inside Fabric Eventhouse (not standalone ADX)
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
echo "[3/6] Deploying Bicep infrastructure (Fabric F8 + Container Apps)..."
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${SCRIPT_DIR}/infra/main.bicep" \
  --parameters "${SCRIPT_DIR}/infra/parameters/${ENV}.bicepparam" \
  --name "surveillance-${ENV}-$(date +%Y%m%d%H%M%S)" \
  --output json)

# Parse outputs
FABRIC_CAPACITY=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.fabricCapacityName.value')
FABRIC_CAPACITY_ID=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.fabricCapacityId.value')
KV_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.keyVaultName.value')
STORAGE_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.storageAccountName.value')
CA_ENV=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppEnvironment.value')
CA_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppName.value')

# ── Set up Fabric workspace + Eventhouse + KQL DB ─────────
echo "[4/6] Setting up Fabric workspace and Eventhouse..."
if [[ -f "${SCRIPT_DIR}/scripts/setup-fabric-workspace.sh" ]]; then
  bash "${SCRIPT_DIR}/scripts/setup-fabric-workspace.sh" "${FABRIC_CAPACITY_ID}" "${PROJECT}" "${ENV}"
fi

# Retrieve the Fabric Eventhouse KQL URI from the workspace
echo "  Discovering Fabric Eventhouse KQL endpoint..."
FABRIC_TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
WORKSPACE_NAME="${PROJECT}-surveillance-${ENV}"
WORKSPACE_ID=$(curl -s "https://api.fabric.microsoft.com/v1/workspaces" \
  -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
  jq -r ".value[] | select(.displayName == \"${WORKSPACE_NAME}\") | .id")

KQL_URI=""
if [[ -n "${WORKSPACE_ID}" ]]; then
  KQL_URI=$(curl -s "https://api.fabric.microsoft.com/v1/workspaces/${WORKSPACE_ID}/kqlDatabases" \
    -H "Authorization: Bearer ${FABRIC_TOKEN}" | \
    jq -r '.value[] | select(.displayName == "surveillance") | .properties.queryServiceUri')
  echo "  Fabric Eventhouse KQL URI: ${KQL_URI}"
fi

# ── Store secrets in Key Vault ────────────────────────────
echo "[5/6] Storing connection strings in Key Vault..."
# Eventstream connection info is set via scripts/setup-fabric-workspace.sh
az keyvault secret set --vault-name "${KV_NAME}" --name "kql-cluster-uri" --value "${KQL_URI}" --output none
az keyvault secret set --vault-name "${KV_NAME}" --name "kql-database-name" --value "surveillance" --output none
az keyvault secret set --vault-name "${KV_NAME}" --name "storage-account-name" --value "${STORAGE_NAME}" --output none

# ── Initialize KQL tables in Fabric Eventhouse ────────────
echo "[6/6] Initializing KQL tables in Fabric Eventhouse..."
if [[ -n "${KQL_URI}" && -f "${SCRIPT_DIR}/scripts/init-kql-tables.sh" ]]; then
  bash "${SCRIPT_DIR}/scripts/init-kql-tables.sh" "${KQL_URI}" "surveillance"
else
  echo "  ⚠ Skipping table init — run scripts/init-kql-tables.sh manually"
fi

# ── Print summary ─────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Deployment Summary"
echo "═══════════════════════════════════════════════════════"
echo " Resource Group      : ${RESOURCE_GROUP}"
echo " Fabric Capacity     : ${FABRIC_CAPACITY} (F8)"
echo " Fabric Workspace    : ${WORKSPACE_NAME}"
echo " Eventhouse KQL URI  : ${KQL_URI}"
echo " Key Vault           : ${KV_NAME}"
echo " Storage Account     : ${STORAGE_NAME}"
echo " Container App Env   : ${CA_ENV}"
echo " Container App       : ${CA_NAME}"
echo "═══════════════════════════════════════════════════════"
echo ""
echo " KQL database 'surveillance' is hosted in Fabric Eventhouse"
echo " (no standalone Azure Data Explorer cluster needed)"
echo "═══════════════════════════════════════════════════════"
