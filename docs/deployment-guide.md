# Deployment Guide

Deploy the Market Surveillance Agent System to Azure using the Azure Developer CLI (`azd`).
All detection runs natively in Fabric Eventhouse via KQL stored functions.

## Prerequisites

- Azure CLI (`az`) installed and logged in
- Azure Developer CLI (`azd`) installed
- Azure subscription with Fabric capacity rights
- Python 3.10+ (for local testing)

## Quick Deploy (azd up)

```bash
# Clone the repo
git clone https://github.com/prwani/market-surveillance.git
cd market-surveillance

# Initialize azd environment
azd init --environment dev

# Set required parameters
azd env set AZURE_LOCATION southeastasia
azd env set AZURE_SUBSCRIPTION_ID "your-subscription-id"
azd env set FABRIC_ADMIN_UPN "admin@yourtenant.onmicrosoft.com"
azd env set FABRIC_SKU F8   # or F2 for cheaper dev

# Deploy everything
azd up
```

## What `azd up` deploys

1. **Azure resources** (via Bicep):
   - Fabric F8 capacity (~$1,049/mo, pausable)
   - Container Registry (ACR)
   - Container App (dashboard)
   - Key Vault, Storage, Log Analytics
2. **Fabric artifacts** (via postprovision hook):
   - Workspace, Eventhouse, KQL database
   - Detection stored functions
   - Ontology graph tables
3. **Dashboard** (via azd deploy):
   - Builds Docker image
   - Pushes to ACR
   - Updates Container App

## After Deployment

See [Getting Started Guide](getting-started.md) for verification steps.

## Pause Fabric Capacity (save costs when not in use)

```bash
az fabric capacity suspend --capacity-name mktsurveilfabric<env> --resource-group rg-<env>
```

## Tear Down

```bash
azd down --purge
```

## Cost Summary

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| Fabric F8 | ~$1,049 | Pausable — $0 when paused |
| Container App | ~$15 | Dashboard only |
| ACR, KV, Storage | ~$5 | Minimal |
| **Total (active)** | **~$1,070** | |
| **Total (paused)** | **~$20** | Fabric paused |

## Troubleshooting

### `azd up` fails at Bicep deployment

**Symptom:** `The subscription is not registered to use namespace 'Microsoft.Fabric'`

**Fix:** Register the provider:
```bash
az provider register --namespace Microsoft.Fabric
az provider show --namespace Microsoft.Fabric --query "registrationState"
# Wait until it shows "Registered"
```

### Fabric workspace creation fails (postprovision hook)

**Symptom:** 401 or 403 errors during Fabric artifact setup

**Fix:** Ensure your account has Fabric admin rights and the capacity is active:
```bash
az resource show \
  --resource-group rg-<env> \
  --resource-type "Microsoft.Fabric/capacities" \
  --name "mktsurveilfabric<env>" \
  --query "properties.state"
```
The capacity must be in `Active` state. If paused, resume it in the Azure portal.

### Dashboard shows "KQL not configured"

**Symptom:** The KQL explorer page returns 501 errors

**Fix:** The `KQL_URI` environment variable was not injected. Re-run provisioning:
```bash
azd provision
```

### `azd up` fails at Key Vault

**Symptom:** Conflict error due to soft-deleted Key Vault

**Fix:** Purge the soft-deleted vault and retry:
```bash
az keyvault purge --name mktsurveil-kv-<env>
azd up
```

### Container App not reachable

**Symptom:** The Container App URL returns 502 or connection timeout

**Fix:** Check the Container App logs:
```bash
az containerapp logs show \
  --name mktsurveil-ca-<env> \
  --resource-group rg-<env> \
  --follow
```

---

For the original architectural whitepaper with detailed design decisions, see
[architecture-whitepaper.md](architecture-whitepaper.md).
