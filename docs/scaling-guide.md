# Market Surveillance — Scaling Guide

## Overview

Detection logic now runs **natively in Microsoft Fabric RTI** — no worker containers
are needed. Scaling is handled by choosing the appropriate Fabric capacity tier.

The surveillance pipeline uses:

- **KQL stored functions** in Fabric Eventhouse for spoofing, layering, wash trading,
  and anomaly detection
- **Data Activator Reflex triggers** for autonomous intervention
- **Ontology graph** in Eventhouse for UBO (Ultimate Beneficial Owner) resolution

The only Container App is the **FastAPI dashboard** (UI + simulation demos).

---

## Fabric Capacity Tiers

Scaling is controlled by the Fabric capacity SKU. Upgrade the SKU to handle more
symbols, higher event throughput, and lower detection latency.

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

Update the `fabricSku` parameter in `infra/main.bicep` or pass it at deployment:

```bash
azd provision --parameter fabricSku=F16
```

Or update `infra/main.parameters.json`:

```json
{
  "fabricSku": { "value": "F16" }
}
```

---

## Detection Architecture

### KQL Stored Functions

All detection logic runs as stored functions in the Fabric Eventhouse KQL database.
These execute within the Fabric capacity — no external compute is needed.

| Function | Detection Type | Query Pattern |
|----------|---------------|--------------|
| `fn_detect_spoofing` | Order spoofing | Order placement/cancellation ratio within sliding windows |
| `fn_detect_layering` | Layering | Multiple orders at different price levels creating false depth |
| `fn_detect_wash_trading` | Wash trading | Same-entity trades on both sides of the order book |
| `fn_detect_anomaly` | Price/volume anomalies | Statistical deviation from rolling averages |
| `fn_detect_cross_market` | Cross-exchange correlation | Synchronized anomalies across SGX, HKEX, NSE |

### Data Activator Reflex Triggers

Data Activator monitors the KQL function outputs and fires Reflex triggers when
detection thresholds are breached:

| Trigger | Condition | Action |
|---------|-----------|--------|
| Spoofing alert | Cancel ratio > 80% within 5 s window | Log alert + notify compliance |
| Layering alert | ≥3 price levels with coordinated orders | Log alert + flag for review |
| Wash trading alert | Same-broker trades > 3 in 1 min | Log alert + escalate |
| Price anomaly | Deviation > 3σ from rolling VWAP | Log alert + notify risk team |

Triggers run autonomously — no polling, no worker containers, no cold-start delays.

---

## Dashboard Container App

The FastAPI dashboard is the **sole Container App**. It serves:

- Real-time alert and case visualization (reads from Eventhouse)
- Simulation demos (uses the Python agent library locally)
- KQL explorer for ad-hoc queries

The dashboard is lightweight and does not run detection logic. It scales via
standard ACA autoscaling if needed (unlikely — it handles UI traffic only).

---

## Python Agent Library

The Python agent library (`src/agents/`) is retained for:

- **Local testing** — run `python run_demo.py` to simulate the full pipeline locally
- **Simulation demos** — the dashboard uses agents in-process for interactive demos
- **Unit tests** — `tests/test_agents.py` validates agent logic

The agent library is **not deployed as workers**. Detection in production runs
via KQL stored functions and Data Activator.

---

## Cost Summary

| Component | Purpose | Monthly Cost |
|-----------|---------|-------------|
| Fabric Capacity (F8) | Eventhouse, KQL functions, Data Activator, Eventstreams | ~$1,049/mo |
| Dashboard Container App | UI and simulation demos | ~$15/mo |
| Key Vault | Secrets management | ~$1/mo |
| Storage Account | Outputs and checkpoints | ~$5/mo |
| Log Analytics | Dashboard monitoring | ~$10/mo |
| **Total (F8 dev)** | | **~$1,080/mo** |

For production, upgrade to F16 (~$2,098/mo) or F32 (~$4,196/mo) based on symbol
count and latency requirements. The dashboard cost stays the same regardless of
Fabric capacity tier.

### Comparison with previous worker-based architecture

| | Workers + Fabric (old) | Fabric-native (current) |
|--|---|---|
| Detection compute | ACA worker containers | KQL stored functions in Fabric |
| Scaling mechanism | Deploy more Container Apps | Upgrade Fabric SKU |
| Operational overhead | Manage worker containers, cold starts, partitioning | None — Fabric handles it |
| Monthly cost (dev) | ~$1,124 (Fabric + 4 workers) | ~$1,080 (Fabric + dashboard only) |
| Monthly cost (prod) | ~$1,670+ (Fabric + AKS cluster) | ~$2,108 (F16 + dashboard) |
| Detection latency | 5–10 s (polling interval) | Near real-time (Data Activator) |

---

## Summary

- **No worker containers** — detection runs in Fabric RTI natively
- **Scale by upgrading Fabric SKU** — F8 for dev, F16/F32 for production
- **Dashboard is the sole Container App** — UI and simulation demos only
- **Data Activator** provides autonomous, near-real-time intervention
- **Python agent library** retained for local testing and demos
