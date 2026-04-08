#!/usr/bin/env bash
# Tear down all Market Surveillance Azure resources
set -euo pipefail

SUBSCRIPTION_ID="23835f6b-9ad7-4c33-b0b8-55157ad0d2b5"
ENV="${1:-dev}"
RESOURCE_GROUP="rg-market-surveillance-${ENV}"

echo "═══════════════════════════════════════════════════════"
echo " Market Surveillance — Resource Teardown"
echo " Environment   : ${ENV}"
echo " Resource Group: ${RESOURCE_GROUP}"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "⚠  This will permanently delete ALL resources in ${RESOURCE_GROUP}"
read -rp "Type 'yes' to confirm: " CONFIRM

if [[ "${CONFIRM}" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

echo "Setting subscription..."
az account set --subscription "${SUBSCRIPTION_ID}"

echo "Purging Key Vault (if soft-deleted)..."
KV_NAME="mktsurveil-kv-${ENV}"
az keyvault purge --name "${KV_NAME}" 2>/dev/null || true

echo "Deleting resource group ${RESOURCE_GROUP}..."
az group delete \
  --name "${RESOURCE_GROUP}" \
  --yes \
  --no-wait

echo "✓ Resource group deletion initiated (running in background)"
echo "  Monitor with: az group show --name ${RESOURCE_GROUP} --query properties.provisioningState"
