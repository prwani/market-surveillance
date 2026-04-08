# Deployment Guide

Step-by-step instructions for deploying the Market Surveillance Agent System to Azure
with Microsoft Fabric.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Step 1 — Clone and Configure](#step-1--clone-and-configure)
- [Step 2 — Deploy Azure Infrastructure](#step-2--deploy-azure-infrastructure)
- [Step 3 — Configure Eventstreams in Fabric Portal](#step-3--configure-eventstreams-in-fabric-portal)
- [Step 4 — Initialize KQL Tables](#step-4--initialize-kql-tables)
- [Step 5 — Verify the Deployment](#step-5--verify-the-deployment)
- [Step 6 — Run the Dashboard](#step-6--run-the-dashboard)
- [Teardown](#teardown)
- [Cost Breakdown](#cost-breakdown)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure CLI** | v2.55+ — [Install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) |
| **Azure Subscription** | With permissions to create resource groups and deploy resources |
| **Microsoft Fabric** | Fabric-enabled tenant with capacity provisioning rights |
| **Python** | 3.10 or later |
| **jq** | JSON processor — used by deployment scripts |
| **Docker** (optional) | For building the container image locally |

Ensure you are logged in to Azure CLI:

```bash
az login
az account set --subscription "<your-subscription-id>"
```

## Architecture Overview

The deployment creates the following resources:

```
Azure Resource Group
├── Microsoft Fabric Capacity (F8)
│   └── Fabric Workspace
│       ├── Eventhouse → KQL Database ("surveillance")
│       └── Eventstreams (ingestion pipeline)
├── Key Vault (secrets: KQL URI, storage keys)
├── Container Apps Environment
│   └── Container App (FastAPI dashboard)
├── Storage Account (outputs + checkpoints)
└── Log Analytics Workspace (monitoring)
```

**Key design decision:** The KQL database runs inside **Fabric Eventhouse**, and event
ingestion uses **Fabric Eventstreams**. This eliminates the need for standalone Azure Data
Explorer (~$600/mo) and Event Hubs (~$250/mo) resources, saving approximately **$850/month**
compared to a traditional architecture.

## Step 1 — Clone and Configure

```bash
git clone <repository-url>
cd market-surveillance
pip install -r requirements.txt
```

### Edit Deployment Parameters

Update `infra/parameters/dev.bicepparam` with your values:

- `fabricAdminUpn` — your Azure AD UPN (e.g., `admin@contoso.com`)
- `projectName` — short project prefix (3–15 chars, e.g., `mktsurveil`)
- `fabricSku` — Fabric SKU (default: `F8`; use `F2` for lower-cost testing)

### Edit deploy.sh

Update `deploy.sh` with your Azure subscription ID:

```bash
SUBSCRIPTION_ID="your-subscription-id-here"
```

## Step 2 — Deploy Azure Infrastructure

Run the one-command deployment:

```bash
./deploy.sh dev
```

The script executes six stages:

1. **Set subscription** — targets your Azure subscription
2. **Create resource group** — `rg-market-surveillance-dev` in `southeastasia`
3. **Deploy Bicep** — provisions Fabric capacity, Key Vault, Container Apps, and Storage
4. **Set up Fabric workspace** — creates workspace, Eventhouse, and KQL database via Fabric REST API
5. **Store secrets** — saves KQL URI and storage connection strings in Key Vault
6. **Initialize KQL tables** — creates the `TRADES`, `ORDER_BOOK_EVENTS`, and `BROKER_OWNERSHIP` tables

The deployment typically takes 5–10 minutes. On completion, you'll see a summary:

```
═══════════════════════════════════════════════════════════
 Deployment Summary
═══════════════════════════════════════════════════════════
 Resource Group      : rg-market-surveillance-dev
 Fabric Capacity     : mktsurveil-fabric-dev (F8)
 Fabric Workspace    : mktsurveil-surveillance-dev
 Eventhouse KQL URI  : https://<region>.kusto.fabric.microsoft.com
 Key Vault           : mktsurveil-kv-dev
 Storage Account     : mktsurveilstdev
 Container App Env   : mktsurveil-cae-dev
 Container App       : mktsurveil-ca-dev
═══════════════════════════════════════════════════════════
```

## Step 3 — Configure Eventstreams in Fabric Portal

After the automated deployment, configure the Eventstream ingestion pipeline in the
Fabric portal:

1. Navigate to [app.fabric.microsoft.com](https://app.fabric.microsoft.com)
2. Open the workspace created by the deployment (e.g., `mktsurveil-surveillance-dev`)
3. Click **+ New** → **Eventstream**
4. Name it `surveillance-ingest`
5. **Add source:**
   - For the simulator: choose **Custom App** and note the connection string
   - For production: configure your exchange data feed as the source
6. **Add destination:**
   - Select **Eventhouse** → choose the `surveillance` KQL database
   - Map the incoming fields to the `TRADES` and `ORDER_BOOK_EVENTS` tables
7. Click **Publish** to activate the stream

> **Note:** The `scripts/setup-fabric-workspace.sh` script creates the Eventstream
> artifact via the Fabric REST API, but the source/destination routing must be configured
> in the portal UI.

## Step 4 — Initialize KQL Tables

If the deployment script did not automatically initialize the KQL tables (e.g., if the
Eventhouse was not yet ready), run the initialization manually:

```bash
KQL_URI="https://<your-region>.kusto.fabric.microsoft.com"
bash scripts/init-kql-tables.sh "$KQL_URI" "surveillance"
```

This creates the following tables in the `surveillance` database:

| Table | Description |
|---|---|
| `TRADES` | Trade execution events |
| `ORDER_BOOK_EVENTS` | Order placement, modification, and cancellation events |
| `BROKER_OWNERSHIP` | Broker/entity ownership mappings for wash trade detection |

## Step 5 — Verify the Deployment

### Check Azure Resources

```bash
az resource list --resource-group rg-market-surveillance-dev --output table
```

### Check Fabric Workspace

```bash
FABRIC_TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

# List workspaces
curl -s "https://api.fabric.microsoft.com/v1/workspaces" \
  -H "Authorization: Bearer $FABRIC_TOKEN" | jq '.value[] | {displayName, id}'

# List KQL databases in the workspace
WORKSPACE_ID="<workspace-id-from-above>"
curl -s "https://api.fabric.microsoft.com/v1/workspaces/$WORKSPACE_ID/kqlDatabases" \
  -H "Authorization: Bearer $FABRIC_TOKEN" | jq '.value[] | {displayName, properties}'
```

### Test KQL Connectivity

```bash
# Quick test from the dashboard
curl -X POST http://localhost:8080/api/kql \
  -H "Content-Type: application/json" \
  -d '{"query": ".show tables"}'
```

## Step 6 — Run the Dashboard

### Option A: Local (development)

```bash
export KQL_URI="https://<your-region>.kusto.fabric.microsoft.com"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Open [http://localhost:8080](http://localhost:8080).

### Option B: Container App (production)

The Container App is deployed automatically by `deploy.sh`. Get its URL:

```bash
az containerapp show \
  --name mktsurveil-ca-dev \
  --resource-group rg-market-surveillance-dev \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

The dashboard will be available at `https://<container-app-fqdn>`.

### Option C: Docker (local container)

```bash
docker build -t market-surveillance .
docker run -p 8080:8080 -e KQL_URI="$KQL_URI" market-surveillance
```

## Teardown

Remove all deployed resources:

```bash
bash scripts/teardown.sh dev
```

Or manually delete the resource group:

```bash
az group delete --name rg-market-surveillance-dev --yes --no-wait
```

> **Warning:** This deletes all resources including the Fabric capacity. The Fabric
> workspace and its contents (Eventhouse, Eventstreams) will also be removed once the
> capacity is deleted.

## Cost Breakdown

Estimated monthly costs for the `dev` environment (Southeast Asia region):

| Resource | SKU / Tier | Est. Monthly Cost |
|---|---|---|
| Fabric Capacity | F8 | ~$1,049 |
| Container Apps | Consumption (0.25 vCPU, 0.5 GiB) | ~$10–30 |
| Key Vault | Standard | ~$1 |
| Storage Account | Standard LRS | ~$1–5 |
| Log Analytics | Per-GB (30-day retention) | ~$5–15 |
| **Total** | | **~$1,070–$1,100/mo** |

### Cost Optimization Tips

- **Use F2 for development/testing** — the smallest Fabric SKU (~$263/mo) supports
  Eventhouse and Eventstreams; use F8 only for production workloads
- **Pause Fabric capacity** — in the Azure portal, pause the Fabric capacity when not in
  use to stop billing (Eventhouse data is retained)
- **Use `python run_demo.py`** for development — no Azure resources needed for local
  testing of the agent pipeline
- **Scale Container Apps to zero** — Container Apps on the Consumption plan scale to
  zero when idle, minimizing compute costs

## Troubleshooting

### `deploy.sh` fails at Bicep deployment

**Symptom:** `The subscription is not registered to use namespace 'Microsoft.Fabric'`

**Fix:** Register the provider:
```bash
az provider register --namespace Microsoft.Fabric
az provider show --namespace Microsoft.Fabric --query "registrationState"
# Wait until it shows "Registered"
```

### Fabric workspace creation fails

**Symptom:** `setup-fabric-workspace.sh` reports 401 or 403 errors

**Fix:** Ensure your account has Fabric admin rights and the capacity is active:
```bash
# Check capacity state
az resource show \
  --resource-group rg-market-surveillance-dev \
  --resource-type "Microsoft.Fabric/capacities" \
  --name "mktsurveil-fabric-dev" \
  --query "properties.state"
```
The capacity must be in `Active` state. If paused, resume it in the Azure portal.

### KQL tables not created

**Symptom:** Queries return "table not found" errors

**Fix:** Run the table initialization manually:
```bash
KQL_URI=$(az keyvault secret show --vault-name mktsurveil-kv-dev --name kql-cluster-uri --query value -o tsv)
bash scripts/init-kql-tables.sh "$KQL_URI" "surveillance"
```

### Dashboard shows "KQL not configured"

**Symptom:** The KQL explorer page returns 501 errors

**Fix:** Set the `KQL_URI` environment variable:
```bash
# For local development
export KQL_URI=$(az keyvault secret show --vault-name mktsurveil-kv-dev --name kql-cluster-uri --query value -o tsv)
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

For the Container App, the URI is injected via Key Vault references configured in
`infra/modules/container-app.bicep`.

### Container App not reachable

**Symptom:** The Container App URL returns 502 or connection timeout

**Fix:** Check the Container App logs:
```bash
az containerapp logs show \
  --name mktsurveil-ca-dev \
  --resource-group rg-market-surveillance-dev \
  --follow
```

Common causes:
- The container image hasn't been pushed yet — build and push via ACR
- The `KQL_URI` secret is missing in Key Vault
- The Container App's managed identity doesn't have Key Vault access (should be
  configured by the Bicep deployment)

### Eventstream not receiving data

**Symptom:** KQL queries return empty results even though the simulator is running

**Fix:**
1. In the Fabric portal, open the Eventstream and check the **Metrics** tab
2. Verify the source connection string matches what the simulator is using
3. Ensure the Eventstream destination is mapped to the correct KQL tables
4. Check that the Fabric capacity is not paused

---

For the original architectural whitepaper with detailed design decisions, see
[architecture-whitepaper.md](architecture-whitepaper.md).
