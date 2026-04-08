# Market Surveillance — Scaling Guide

## Overview

This guide documents how the agent worker architecture scales from a demo deployment
(12 symbols on a single exchange) to production workloads monitoring 1,000+ symbols
across multiple exchanges simultaneously.

The surveillance pipeline is CPU-light and memory-moderate: each agent maintains
compact sliding-window state per (exchange, symbol) pair. The primary scaling
challenge is not raw compute but **partitioning** — ensuring every symbol is
processed by exactly one worker to avoid duplicate alerts and keeping per-worker
memory bounded.

Two deployment models are covered:

1. **Azure Container Apps (ACA)** — the current approach, suitable for dev and
   small-to-medium deployments (up to ~200 symbols).
2. **Azure Kubernetes Service (AKS)** — the recommended production approach for
   large-scale deployments (200–5,000+ symbols).

---

## Agent Memory Model

All five surveillance agents maintain per-(exchange, symbol) state using sliding
windows or rolling buckets. Understanding memory consumption is key to capacity
planning.

### Per-agent window sizes

| Agent | Window / History | Data Structure |
|-------|-----------------|----------------|
| **PatternDetection** — spoofing | 60 s | Deque of `_OrderRecord` per (exchange, symbol) |
| **PatternDetection** — layering | 120 s | Same deque (shared with spoofing, trimmed to 120 s) |
| **PatternDetection** — wash trading | 600 s | Deque of `_TradeRecord` per (exchange, symbol) |
| **AnomalyDetection** | 60 one-minute VWAP/volume buckets (1 hour) | `_RollingStats` deque per (exchange, symbol) |
| **CrossMarket** | 30 one-minute VWAP buckets per exchange pair | `_VWAPRecord` deque per (exchange, symbol) |
| **Intervention** | Stateless (evaluates each alert independently) | — |
| **Evidence** | Bounded event buffer | Circular buffer per case |

### Memory estimates

- **Per symbol (all agents combined):** ~200 KB
  - PatternDetection dominates: the 600 s wash-trading window can hold hundreds
    of `_TradeRecord` objects for active symbols.
  - AnomalyDetection: 60 floats × 2 (VWAP + volume) ≈ negligible.
  - CrossMarket: 30 `_VWAPRecord` objects × number of exchange pairings.
- **12 symbols (demo):** ~2.4 MB
- **36 symbols (dev — 12 per exchange × 3 exchanges):** ~7.2 MB
- **1,000 symbols:** ~200 MB total in-memory state
- **5,000 symbols:** ~1 GB total in-memory state

> Memory grows linearly with symbol count. There is no cross-symbol state except
> in the CrossMarket agent, which only tracks explicitly dual-listed pairs.

---

## Current Architecture: ACA Partitioned Workers

### Deployment topology

The current `deploy.sh` provisions a single worker Container App
(`mktsurveil-worker-dev`) as defined in `infra/modules/worker-app.bicep`. For
multi-exchange isolation, the recommended ACA topology deploys one worker per
exchange plus one cross-market worker:

```
mktsurveil-worker-sgx-dev          → SGX symbols only
mktsurveil-worker-hkex-dev         → HKEX symbols only
mktsurveil-worker-nse-dev          → NSE symbols only
mktsurveil-worker-cross-market-dev → Cross-exchange correlation only
```

### How partitioning works

- Each worker sets an `EXCHANGE_FILTER` environment variable (e.g.,
  `EXCHANGE_FILTER=SGX`).
- On each poll cycle, the worker appends a `| where exchange_id == '{filter}'`
  clause to its KQL query, so it only retrieves events for its assigned exchange.
- **Isolation:** a crash or restart of the SGX worker does not affect HKEX or NSE
  processing — each Container App is an independent unit.
- **Auto-restart:** ACA automatically restarts crashed containers with exponential
  back-off, so transient failures self-heal.

### Cold start and warm-up

The worker follows this startup sequence:

1. **Historical backfill** — on startup, queries the Fabric Eventhouse for the
   last 60 minutes of historical trade and order-book events (controlled by
   `WARMUP_MINUTES`, default 60).
2. **Replay through agents** — feeds historical events through
   `PatternDetectionAgent`, `AnomalyDetectionAgent`, and `CrossMarketAgent` to
   populate their sliding windows and rolling statistics.
3. **Set high-water mark** — records the timestamp of the most recent replayed
   event as the starting point for incremental polling.
4. **Enter normal loop** — switches to the standard `_poll_and_process()` cycle,
   fetching only events newer than the high-water mark.

- **Warm-up time:** ~10–30 seconds depending on data volume for the 60-minute
  window.
- During warm-up, the agent suppresses alert emission to avoid firing on stale
  patterns that have already been processed.

### Scaling the ACA approach

Within the ACA model, you can scale in two ways:

1. **Vertical** — increase the CPU/memory allocation in `worker-app.bicep`
   (currently 0.5 CPU, 1 Gi memory). Suitable for exchanges with many symbols.
2. **Horizontal (per exchange)** — deploy additional Container Apps, each
   filtering to a different exchange via `EXCHANGE_FILTER`.

### Limitations of the ACA approach

| Limitation | Impact |
|-----------|--------|
| **Static partitioning** | One Container App per exchange — cannot split a high-volume exchange across multiple workers. |
| **Manual scaling** | Adding a new exchange or splitting a partition requires deploying a new Container App via Bicep. |
| **No dynamic rebalancing** | If one exchange suddenly gets 10× more traffic, you cannot automatically redistribute symbols. |
| **No hash-based sharding** | All symbols for an exchange go to a single worker — potential hot-spot if one exchange has thousands of symbols. |
| **Limited observability** | ACA provides basic container logs but lacks Prometheus-native metrics or Grafana integration out of the box. |

These limitations become significant at approximately 200+ symbols or when
sub-5-second detection latency is required.

---

## Production Architecture: AKS with StatefulSets

### Why AKS?

Move from ACA to AKS when any of the following apply:

- Monitoring **more than 200 symbols** across all exchanges.
- Detection latency requirement drops below **5 seconds**.
- You need **automatic horizontal scaling** based on event lag or throughput.
- You require **fine-grained observability** (Prometheus metrics, Grafana
  dashboards, per-pod resource monitoring).
- Compliance or governance requires **stable pod identity** for audit trails.

AKS provides StatefulSets with stable ordinals, Horizontal Pod Autoscaler (HPA),
and native Prometheus/Grafana integration — all critical for production-grade
surveillance.

### Deployment topology

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: surveillance-workers
  namespace: market-surveillance
spec:
  serviceName: surveillance-workers
  replicas: 8  # adjust based on symbol count
  selector:
    matchLabels:
      app: surveillance-worker
  template:
    metadata:
      labels:
        app: surveillance-worker
    spec:
      containers:
      - name: worker
        image: <acr-login-server>/market-surveillance-worker:latest
        env:
        - name: TOTAL_REPLICAS
          value: "8"
        - name: POD_ORDINAL
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['apps.kubernetes.io/pod-index']
        - name: KQL_URI
          valueFrom:
            secretKeyRef:
              name: surveillance-secrets
              key: kql-uri
        - name: KQL_DB
          value: surveillance
        - name: POLL_INTERVAL
          value: "5"
        - name: WARMUP_MINUTES
          value: "60"
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1"
            memory: "1Gi"
```

### Symbol-based hash partitioning

Instead of filtering by exchange, AKS workers use **hash-based symbol
partitioning** so symbols are evenly distributed regardless of exchange:

```python
import hashlib

def get_partition(exchange_id: str, symbol: str, total_replicas: int) -> int:
    """Deterministic partition assignment for a symbol."""
    key = f"{exchange_id}:{symbol}"
    hash_val = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return hash_val % total_replicas
```

Each pod computes its partition assignments at startup:

1. Pod reads its ordinal from `POD_ORDINAL` (0, 1, 2, …) and `TOTAL_REPLICAS`.
2. On each poll, the worker fetches all new events from Eventhouse.
3. For each event, it computes `partition = hash(exchange_id + symbol) % total_replicas`.
4. If `partition == pod_ordinal`, the event is processed; otherwise it is skipped.
5. **Adding replicas** automatically redistributes symbols — no configuration
   changes needed.

**Example:** 1,000 symbols / 8 pods = ~125 symbols per pod (uniformly distributed
by the hash function).

### Cross-market worker as a separate Deployment

The CrossMarket agent requires visibility into multiple exchanges for the same
symbol, so it cannot use per-exchange or hash-based partitioning. Deploy it as a
standard Kubernetes Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: surveillance-cross-market
  namespace: market-surveillance
spec:
  replicas: 1  # scale if >50 dual-listed symbols
  selector:
    matchLabels:
      app: surveillance-cross-market
  template:
    metadata:
      labels:
        app: surveillance-cross-market
    spec:
      containers:
      - name: cross-market
        image: <acr-login-server>/market-surveillance-worker:latest
        env:
        - name: AGENT_MODE
          value: cross-market-only
        - name: KQL_URI
          valueFrom:
            secretKeyRef:
              name: surveillance-secrets
              key: kql-uri
        resources:
          requests:
            cpu: "250m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
```

- Runs as a **Deployment** (not StatefulSet) since it does not need stable identity.
- Processes only dual-listed symbols (~20–50 symbols typically).
- Can scale horizontally by partitioning on canonical symbol if needed.

### Horizontal Pod Autoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: surveillance-workers-hpa
  namespace: market-surveillance
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: surveillance-workers
  minReplicas: 4
  maxReplicas: 16
  metrics:
  - type: External
    external:
      metric:
        name: eventhub_lag  # or custom metric from Eventhouse query latency
      target:
        type: AverageValue
        averageValue: "1000"  # scale up if >1000 unprocessed events per pod
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 75  # scale up if memory pressure from symbol state
```

The HPA evaluates two signals:

1. **Event lag** — the number of unprocessed events in the Eventhouse (exposed as
   a custom Prometheus metric by the worker). If each pod has more than 1,000
   events queued, new pods are added.
2. **Memory utilization** — as more symbols are assigned per pod, memory grows.
   Scaling out reduces per-pod symbol count and memory pressure.

### State recovery on pod restart

Because all agent state is in-memory (no persistent volumes), pods must rebuild
their sliding windows on restart:

1. Pod starts and reads `WARMUP_MINUTES` (default: 60) from environment.
2. Queries Eventhouse for the last `WARMUP_MINUTES` of trade and order-book events
   matching its hash partition.
3. Replays events through all agents to rebuild sliding windows and rolling
   statistics.
4. Sets the high-water mark to the timestamp of the most recent replayed event.
5. Enters normal polling loop.
6. **Total recovery time:** <60 seconds for up to ~125 symbols.

No persistent volume is needed — Eventhouse is the durable store and source of
truth. This keeps the deployment simple and avoids PVC management overhead.

### Monitoring and observability

The worker exposes Prometheus metrics at `/metrics` (or via the Prometheus client
library push gateway):

| Metric | Type | Description |
|--------|------|-------------|
| `surveillance_events_processed_total` | Counter | Total events processed by this pod |
| `surveillance_alerts_raised_total` | Counter | Total alerts raised, by type |
| `surveillance_poll_latency_seconds` | Histogram | Time to complete each poll cycle |
| `surveillance_active_symbols` | Gauge | Number of symbols assigned to this pod |
| `surveillance_warmup_duration_seconds` | Histogram | Time to complete warm-up replay |

**Grafana dashboard** panels:

- Per-pod event throughput (events/second).
- Per-pod memory and CPU utilization.
- Alert rate by type (spoofing, layering, wash trading, price anomaly).
- Poll latency P50/P95/P99.
- Symbol distribution across pods (detect hot-spots).

**Alerting rules** (Prometheus Alertmanager):

- `poll_latency > 5s` sustained for 2 minutes → page on-call.
- `pod restarts > 3/hour` → investigate OOM or crash loop.
- `alert_rate` anomaly (sudden spike or drop) → possible data pipeline issue.

---

## Performance Estimates

| Scenario | Symbols | Events/sec | Workers | Memory | Detection Latency |
|----------|---------|-----------|---------|--------|-------------------|
| Demo | 12 | ~50 | 1 | 50 MB | ≤10 s |
| Dev (current) | 12 × 3 | ~150 | 4 (ACA) | 200 MB | ≤10 s |
| Production (small) | 200 | ~5,000 | 4 (AKS) | 500 MB | ≤5 s |
| Production (medium) | 1,000 | ~25,000 | 8 (AKS) | 2 GB | ≤3 s |
| Production (large) | 5,000 | ~100,000 | 16 (AKS) | 8 GB | ≤2 s |

**Key assumptions:**

- ~5 events/second per symbol (mix of trades and order-book updates).
- Detection latency = time from event ingestion in Eventhouse to alert emission.
- Latency improves with more workers because each pod processes fewer symbols and
  completes poll cycles faster.
- Memory estimates include Python runtime overhead (~50 MB base) plus agent state.

---

## Cost Implications

### ACA (current)

| Component | Specification | Monthly Cost |
|-----------|--------------|-------------|
| 4 workers | 0.5 CPU × 1 Gi each | ~$60 (consumption plan) |
| ACR (Basic) | Container image storage | ~$5 |
| Log Analytics | Container logs | ~$10 |
| **Total** | | **~$75/month** |

ACA consumption plan billing is based on vCPU-seconds and GiB-seconds of active
usage. The worker runs continuously, so costs are predictable.

### AKS (production)

| Component | Specification | Monthly Cost |
|-----------|--------------|-------------|
| Node pool | 4× Standard_D4s_v5 (4 vCPU, 16 GB each) | ~$500 |
| Managed Prometheus | Metrics ingestion and storage | ~$50 |
| Managed Grafana | Dashboard hosting | ~$30 |
| Load Balancer | Internal (for metrics scraping) | ~$20 |
| ACR (Standard) | Container image storage | ~$20 |
| **Total** | | **~$620/month** |

**Recommended for:** production deployments monitoring >200 symbols where
detection latency, auto-scaling, and observability justify the cost increase.

### Break-even analysis

| | ACA | AKS |
|--|-----|-----|
| Best for | ≤200 symbols, ≤10 s latency OK | >200 symbols, ≤5 s latency needed |
| Operational overhead | Low (serverless-like) | Medium (cluster management) |
| Auto-scaling | Manual (deploy new Container Apps) | Automatic (HPA) |
| Observability | Basic (Log Analytics) | Full (Prometheus + Grafana) |
| Monthly cost | ~$75 | ~$620 |

---

## Migration Path: ACA → AKS

### When to migrate

Migrate when you observe any of:

- [ ] Monitoring more than 200 symbols total.
- [ ] Detection latency exceeding 5 seconds during peak trading hours.
- [ ] Need to split a single exchange across multiple workers.
- [ ] Compliance requires per-pod audit trails with stable identifiers.
- [ ] Team needs Prometheus/Grafana-level observability.

### Step-by-step migration

1. **Provision AKS cluster**
   ```bash
   az aks create \
     --resource-group rg-market-surveillance-prod \
     --name aks-surveillance-prod \
     --node-count 4 \
     --node-vm-size Standard_D4s_v5 \
     --enable-managed-identity \
     --attach-acr <acr-name>
   ```

2. **Deploy secrets**
   ```bash
   kubectl create namespace market-surveillance
   kubectl create secret generic surveillance-secrets \
     --namespace market-surveillance \
     --from-literal=kql-uri="<your-kql-uri>"
   ```

3. **Deploy StatefulSet workers**
   Apply the StatefulSet manifest from the [Deployment topology](#deployment-topology-1)
   section. Start with `replicas: 4` and adjust based on symbol count.

4. **Deploy cross-market worker**
   Apply the Deployment manifest from the
   [Cross-market worker](#cross-market-worker-as-a-separate-deployment) section.

5. **Configure HPA**
   Apply the HPA manifest. Install the Prometheus adapter or KEDA for custom
   metric scaling.

6. **Set up monitoring**
   - Enable Azure Managed Prometheus on the AKS cluster.
   - Deploy Grafana dashboards for per-pod throughput and alert rates.
   - Configure Alertmanager rules for latency and restart thresholds.

7. **Validate**
   - Confirm all symbols are covered: query the worker logs for symbol assignment
     counts — total across all pods should equal your monitored symbol count.
   - Run a test simulation and verify alerts appear with expected latency.
   - Monitor for 24 hours before decommissioning ACA workers.

8. **Decommission ACA workers**
   ```bash
   az containerapp delete --name mktsurveil-worker-sgx-dev \
     --resource-group rg-market-surveillance-dev --yes
   # Repeat for each ACA worker
   ```

### Rollback

If issues arise during migration:

- ACA workers can be redeployed in minutes via `deploy.sh`.
- Both ACA and AKS workers can run in parallel (processing different partitions)
  during the transition period — they read from the same Eventhouse and write
  alerts independently.

---

## Summary

| Aspect | ACA (current) | AKS (production) |
|--------|--------------|-------------------|
| Partitioning | Per-exchange (`EXCHANGE_FILTER`) | Hash-based (`hash(exchange:symbol) % replicas`) |
| Scaling | Manual (new Container Apps) | Automatic (HPA + StatefulSet replicas) |
| State recovery | Query last 60 min from Eventhouse | Same — Eventhouse is source of truth |
| Cross-market | Dedicated Container App | Dedicated Deployment |
| Monitoring | Log Analytics | Prometheus + Grafana |
| Best for | Dev, demo, ≤200 symbols | Production, 200–5,000+ symbols |
