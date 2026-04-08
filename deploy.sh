#!/usr/bin/env bash
# Deploy Market Surveillance infrastructure to Azure
# Architecture: Fabric Eventhouse (KQL) + Eventstreams + Container Apps (dashboard)
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
echo "[1/8] Setting Azure subscription..."
az account set --subscription "${SUBSCRIPTION_ID}"

# ── Create resource group ─────────────────────────────────
echo "[2/8] Creating resource group ${RESOURCE_GROUP}..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --tags project="${PROJECT}" environment="${ENV}" managedBy=bicep system=market-surveillance \
  --output none

# ── Deploy Bicep template ─────────────────────────────────
echo "[3/8] Deploying infrastructure (Fabric F8 + ACR + Container Apps)..."
DEPLOY_NAME="surveillance-${ENV}-$(date +%Y%m%d%H%M%S)"
DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${SCRIPT_DIR}/infra/main.bicep" \
  --parameters "${SCRIPT_DIR}/infra/parameters/${ENV}.bicepparam" \
  --name "${DEPLOY_NAME}" \
  --output json)

# Parse outputs
FABRIC_CAPACITY=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.fabricCapacityName.value')
FABRIC_CAPACITY_ID=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.fabricCapacityId.value')
KV_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.keyVaultName.value')
STORAGE_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.storageAccountName.value')
CA_ENV=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppEnvironment.value')
CA_NAME=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.containerAppName.value')
ACR_LOGIN=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.acrLoginServer.value')
DASHBOARD_URL=$(echo "${DEPLOY_OUTPUT}" | jq -r '.properties.outputs.dashboardUrl.value')
ACR_NAME="${ACR_LOGIN%%.*}"

# Worker names are per-exchange (shortened to fit ACA 32-char limit)
EXCHANGE_WORKERS=("SGX" "HKEX" "NSE" "cross-market")
WORKER_NAMES=()
for EX in "${EXCHANGE_WORKERS[@]}"; do
  if [[ "${EX}" == "cross-market" ]]; then
    WORKER_NAMES+=("${PROJECT}-wk-crossmkt-${ENV}")
  else
    WORKER_NAMES+=("${PROJECT}-wk-${EX,,}-${ENV}")
  fi
done

# ── Build and push Docker images ──────────────────────────
echo "[4/9] Building and pushing Docker images..."
echo "  Dashboard..."
az acr build \
  --registry "${ACR_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --image market-surveillance:latest \
  --file "${SCRIPT_DIR}/Dockerfile" \
  "${SCRIPT_DIR}" \
  --output none

echo "  Worker..."
az acr build \
  --registry "${ACR_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --image market-surveillance-worker:latest \
  --file "${SCRIPT_DIR}/Dockerfile.worker" \
  "${SCRIPT_DIR}" \
  --output none

# ── Set up Fabric workspace + Eventhouse + KQL DB ─────────
echo "[5/9] Setting up Fabric workspace and Eventhouse..."
if [[ -f "${SCRIPT_DIR}/scripts/setup-fabric-workspace.sh" ]]; then
  bash "${SCRIPT_DIR}/scripts/setup-fabric-workspace.sh" "${FABRIC_CAPACITY_ID}" "${PROJECT}" "${ENV}"
fi

# Discover Fabric Eventhouse KQL URI
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
echo "[6/9] Storing secrets in Key Vault..."
az keyvault secret set --vault-name "${KV_NAME}" --name "kql-cluster-uri" --value "${KQL_URI}" --output none 2>/dev/null || true
az keyvault secret set --vault-name "${KV_NAME}" --name "kql-database-name" --value "surveillance" --output none 2>/dev/null || true
az keyvault secret set --vault-name "${KV_NAME}" --name "storage-account-name" --value "${STORAGE_NAME}" --output none 2>/dev/null || true

# ── Initialize KQL tables in Fabric Eventhouse ────────────
echo "[7/9] Initializing KQL tables in Fabric Eventhouse..."
if [[ -n "${KQL_URI}" && -f "${SCRIPT_DIR}/scripts/init-kql-tables.sh" ]]; then
  bash "${SCRIPT_DIR}/scripts/init-kql-tables.sh" "${KQL_URI}" "surveillance"
else
  echo "  ⚠ Skipping table init — run scripts/init-kql-tables.sh manually"
fi

# ── Configure dashboard and workers with KQL endpoint ─────
echo "[8/9] Configuring dashboard and workers..."
if [[ -n "${KQL_URI}" ]]; then
  az containerapp update \
    --name "${CA_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --set-env-vars "KQL_URI=${KQL_URI}" "KQL_DB=surveillance" \
    --output none 2>/dev/null || true

  for i in "${!EXCHANGE_WORKERS[@]}"; do
    WN="${WORKER_NAMES[$i]}"
    EX="${EXCHANGE_WORKERS[$i]}"
    az containerapp update \
      --name "${WN}" \
      --resource-group "${RESOURCE_GROUP}" \
      --set-env-vars "KQL_URI=${KQL_URI}" "KQL_DB=surveillance" "POLL_INTERVAL=10" "EXCHANGE_FILTER=${EX}" "WARMUP_MINUTES=60" \
      --output none 2>/dev/null || true
  done
fi

# Grant dashboard and all worker identities KQL database access
echo "[9/9] Granting KQL database permissions..."
KUSTO_TOKEN=$(az account get-access-token --resource "https://kusto.kusto.windows.net" --query accessToken -o tsv)
ALL_APPS=("${CA_NAME}" "${WORKER_NAMES[@]}")
for APP_NAME in "${ALL_APPS[@]}"; do
  PRINCIPAL=$(az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" --query "identity.principalId" -o tsv 2>/dev/null)
  if [[ -n "${PRINCIPAL}" ]]; then
    APP_ID=$(az ad sp show --id "${PRINCIPAL}" --query "appId" -o tsv 2>/dev/null)
    if [[ -n "${APP_ID}" && -n "${KQL_URI}" ]]; then
      curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
        -H "Authorization: Bearer ${KUSTO_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"db\":\"surveillance\",\"csl\":\".add database surveillance viewers ('aadapp=${APP_ID}')\"}" > /dev/null
      curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
        -H "Authorization: Bearer ${KUSTO_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"db\":\"surveillance\",\"csl\":\".add database surveillance ingestors ('aadapp=${APP_ID}')\"}" > /dev/null
      echo "  ✓ ${APP_NAME} granted viewer+ingestor on surveillance DB"
    fi
  fi
done

# ── Print summary ─────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Deployment Complete"
echo "═══════════════════════════════════════════════════════"
echo " Resource Group    : ${RESOURCE_GROUP}"
echo " Fabric Capacity   : ${FABRIC_CAPACITY} (F8)"
echo " Fabric Workspace  : ${WORKSPACE_NAME}"
echo " Eventhouse KQL URI: ${KQL_URI}"
echo " Container Registry: ${ACR_LOGIN}"
echo " Key Vault         : ${KV_NAME}"
echo " Storage Account   : ${STORAGE_NAME}"
echo ""
echo " Workers (per-exchange):"
for WN in "${WORKER_NAMES[@]}"; do
  echo "   • ${WN}"
done
echo ""
echo " ╔═══════════════════════════════════════════════════╗"
echo " ║  Dashboard: ${DASHBOARD_URL}"
echo " ╚═══════════════════════════════════════════════════╝"
echo "═══════════════════════════════════════════════════════"
