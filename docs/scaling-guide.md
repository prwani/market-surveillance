# Market Surveillance — Scaling Guide

## Overview

Detection logic runs **natively in Microsoft Fabric RTI** via KQL stored functions
and Data Activator Reflex triggers. Scaling is controlled entirely by the Fabric
capacity tier — upgrade the SKU to handle more symbols, higher event throughput,
and lower detection latency.

The only Container App is the **FastAPI dashboard** (UI + simulation demos).

---

## Fabric Capacity Tiers

| SKU | CU | Symbols | Events/sec | Detection Latency | Monthly Cost |
|-----|-----|---------|-----------|-------------------|-------------|
| **F2** | 2 | ≤20 | ~100 | ≤30 s | ~$263/mo |
| **F4** | 4 | ≤50 | ~500 | ≤15 s | ~$525/mo |
| **F8** | 8 | ≤200 | ~5,000 | ≤10 s | ~$1,049/mo |
| **F16** | 16 | ≤500 | ~15,000 | ≤5 s | ~$2,098/mo |
| **F32** | 32 | ≤2,000 | ~50,000 | ≤3 s | ~$4,196/mo |
| **F64** | 64 | ≤5,000+ | ~100,000+ | ≤2 s | ~$8,392/mo |

> **F8** is the default for dev/demo. For production workloads monitoring hundreds
> of symbols across SGX, HKEX, and NSE, start with **F16** and scale up as needed.

### How to change capacity

```bash
azd env set FABRIC_SKU F16
azd provision
```

Or update `infra/main.parameters.json`:

```json
{
  "fabricSku": { "value": "F16" }
}
```

---

## KQL Query Concurrency

Fabric Eventhouse scales query concurrency with the capacity tier. Key factors:

- **Concurrent queries** — higher SKUs support more simultaneous KQL queries.
  F8 handles ~10 concurrent queries; F32 handles ~50+.
- **Query complexity** — detection functions with large time windows or many
  symbols consume more capacity units per query.
- **Materialized views** — for high-frequency detection, create materialized
  views over raw tables to reduce per-query compute. Example:

```kusto
.create materialized-view SpoofingCandidates on table ORDER_BOOK_EVENTS {
    ORDER_BOOK_EVENTS
    | where action in ("add", "cancel")
    | summarize added=countif(action=="add"), cancelled=countif(action=="cancel")
        by broker_id, symbol, bin(event_time, 5s)
    | where added > 0 and cancelled*1.0/added > 0.80
}
```

---

## Data Activator Trigger Scaling

Data Activator Reflex triggers monitor KQL function outputs and fire when
detection thresholds are breached:

| Trigger | Condition | Action |
|---------|-----------|--------|
| Spoofing alert | Cancel ratio > 80% within 5 s window | Log alert + notify compliance |
| Layering alert | ≥3 price levels with coordinated orders | Log alert + flag for review |
| Wash trading alert | Same-broker trades > 3 in 1 min | Log alert + escalate |
| Price anomaly | Deviation > 3σ from rolling VWAP | Log alert + notify risk team |

Triggers run autonomously with no polling or cold-start delays. Scaling
considerations:

- **Trigger evaluation frequency** — Data Activator evaluates conditions on a
  cadence tied to the Fabric capacity. Higher SKUs evaluate more frequently.
- **Trigger fan-out** — each trigger can fire multiple actions (Teams notification,
  Power Automate flow, trade halt). Fan-out does not consume additional CUs.
- **Trigger count** — there is no hard limit on the number of Reflex triggers;
  create separate triggers per detection type and exchange for isolation.

---

## Eventhouse Performance Tuning

### Hot Cache vs. Cold Storage

Configure the hot cache window to keep frequently queried data in memory:

```kusto
.alter database surveillance policy caching hot = 7d
```

- **7-day hot cache** (default) — keeps the last week of events in fast SSD/memory.
- **30-day hot cache** — for production with historical lookback requirements.
  Requires a higher SKU to fit more data in cache.
- **Cold data** — older data moves to cheaper storage but remains queryable
  (with higher latency).

### Table Partitioning

Partition large tables by time to improve query performance:

```kusto
.alter table ORDER_BOOK_EVENTS policy partitioning
```json
{
  "PartitionKeys": [
    {
      "ColumnName": "event_time",
      "Kind": "UniformRange",
      "Properties": {
        "Reference": "2024-01-01T00:00:00",
        "RangeSize": "1.00:00:00",
        "OverrideCreationTime": false
      }
    }
  ]
}
```

### Ingestion Batching

Eventstreams batches events before writing to Eventhouse. Tune the batching
policy for throughput vs. latency:

```kusto
.alter table TRADES policy ingestionbatching
```json
{
  "MaximumBatchingTimeSpan": "00:00:30",
  "MaximumNumberOfItems": 10000,
  "MaximumRawDataSizeMB": 100
}
```

- For **low-latency detection** (F16+): reduce `MaximumBatchingTimeSpan` to 10 s.
- For **cost-optimized dev** (F2/F4): keep the default 30 s batch window.

---

## Dashboard Container App

The FastAPI dashboard is the Container App. It serves:

- Real-time alert and case visualization (reads from Eventhouse)
- Simulation demos (uses the Python agent library locally)
- KQL explorer for ad-hoc queries

The dashboard does not run detection logic and handles only UI traffic.
Standard Container Apps autoscaling applies if needed.

---

## Cost Summary

| Component | Purpose | Monthly Cost |
|-----------|---------|-------------|
| Fabric Capacity (F8) | Eventhouse, KQL functions, Data Activator, Eventstreams | ~$1,049/mo |
| Dashboard Container App | UI and simulation demos | ~$15/mo |
| ACR, Key Vault, Storage | Image registry, secrets, outputs | ~$5/mo |
| Log Analytics | Dashboard monitoring | ~$10/mo |
| **Total (F8 dev)** | | **~$1,080/mo** |

For production, upgrade to F16 (~$2,098/mo) or F32 (~$4,196/mo) based on symbol
count and latency requirements. The dashboard cost stays the same regardless of
Fabric capacity tier.

**Pause capacity when not in use** to reduce costs to ~$20/mo (dashboard + storage only):

```bash
az fabric capacity suspend --capacity-name mktsurveilfabric<env> --resource-group rg-<env>
```

---

## Summary

- **Scale by upgrading Fabric SKU** — F2 for dev, F8 for demo, F16/F32 for production
- **KQL concurrency** scales with capacity tier; use materialized views for hot paths
- **Data Activator triggers** scale automatically within the Fabric capacity
- **Eventhouse tuning** — adjust hot cache, partitioning, and ingestion batching
- **Dashboard Container App** — UI and simulation demos
