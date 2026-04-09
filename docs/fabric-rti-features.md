# Fabric RTI Native Features

This solution leverages two Fabric Real-Time Intelligence preview features for
enhanced detection and operational monitoring.

## 1. Anomaly Detection Models

### What They Provide
Fabric RTI includes 12 built-in anomaly detection models that go far beyond
basic Z-score detection:

| Model | Best For | Market Surveillance Use Case |
|-------|---------|---------------------------|
| **Signal Watcher (Seasonal)** | Patterns with intraday cycles | Detecting price manipulation that respects market open/close patterns |
| **Change Spike Detector** | Sharp local changes | Flash crashes, sudden spoofing-induced price moves |
| **Rolling Change Tracker** | Gradual shifts | Slow layering that builds over minutes |
| **Pattern Proximity (KNN)** | Local pattern shifts | Unusual order flow patterns compared to recent history |
| **Core Pattern Finder (PCA)** | Hidden patterns | Coordinated cross-market manipulation |
| **Robust Outlier Radar (Seasonal)** | Noisy data with recurring patterns | Volume spikes during volatile trading sessions |

### How to Set Up

1. Navigate to your Eventhouse in the Fabric workspace
2. Enable the **Python language extension** (Plugins → Python 3.11.7 DL)
3. Select the `TRADES` table → **Create Anomaly Detector**
4. Configure:
   - **Value to watch:** `price`
   - **Group by:** `symbol`, `exchange_id`
   - **Timestamp:** `event_time`
5. Click **Run Analysis** (takes ~4 minutes)
6. Review recommended models — **Signal Watcher (Seasonal)** is recommended for trading data
7. Adjust sensitivity (start with Medium, tune based on false positive rate)
8. **Publish** to Real-Time Hub for continuous monitoring
9. Configure **alert action** → Data Activator for automated intervention

### Integration with Our Detection Pipeline

```
Anomaly Detection Models (continuous, Fabric-managed)
        ↓ publishes to Real-Time Hub
Data Activator (triggers on anomaly events)
        ↓
Trade Halt / Teams Notification
```

The anomaly detector runs continuously alongside our KQL stored functions.
It provides a complementary ML-based detection layer that catches patterns
the rule-based KQL functions might miss.

### Limitations
- Requires Python plugin enabled on Eventhouse
- Max 8 concurrent queries per Eventhouse
- One model configuration per anomaly detector item
- Sufficient historical data improves accuracy (minimum: a few days at 1-second granularity)
- Preview feature — subject to changes

### Setup Automation

Add to `scripts/postprovision.sh` (after KQL table creation):
```bash
# Enable Python plugin on Eventhouse (required for anomaly detection models)
echo "Enabling Python plugin on Eventhouse..."
# Note: Python plugin enablement currently requires Fabric portal UI.
# Automated enablement via REST API is not yet available.
```

## 2. Operations Agent (Advisory Layer)

### What It Provides
An AI-powered agent that continuously monitors your Eventhouse data,
understands business goals, and recommends actions via Microsoft Teams.

### Why It's a Secondary Layer (Not Primary Detection)

| Aspect | Data Activator (Primary) | Operations Agent (Advisory) |
|--------|--------------------------|----------------------------|
| **Polling interval** | Configurable (30s) | Fixed 5 minutes |
| **Decision logic** | Deterministic KQL rules | Probabilistic LLM |
| **Detection latency** | <60 seconds ✅ | ~5 minutes ❌ |
| **Best for** | Autonomous trade halts | Contextual insights, deeper investigation |
| **Reliability** | Deterministic — same input = same output | LLM-based — may vary |

**The 5-minute polling interval and probabilistic LLM decisions make Operations
Agent unsuitable for autonomous trade halts** (which require ≤60s and
deterministic logic). However, it excels at providing contextual analysis that
humans can act on.

### Recommended Configuration

**Business Goals:**
```
Detect and investigate potential market manipulation across SGX, HKEX,
and NSE exchanges. Focus on spoofing, layering, wash trading, and
coordinated cross-market manipulation. Prioritize high-confidence
alerts and provide beneficial ownership context.
```

**Instructions:**
```
Operational Rules:
1. Alert when detect_spoofing() returns results with cancel_rate > 0.90
2. Alert when detect_wash_trading() finds trades between entities sharing a UBO
3. Alert when detect_anomalies() finds price deviations > 3 standard deviations
4. When alerting on wash trading, include the UBO chain from resolve_ubo()
5. When alerting on spoofing, include the regulatory context from get_regulations()

Semantic Information:
1. Trade data is in the TRADES table, identified by trade_id
2. Order flow data is in ORDER_BOOK_EVENTS table, identified by event_id
3. Broker ownership chains are in ENTITIES and RELATIONSHIPS tables
4. A broker's UBO can be found using: resolve_ubo("BROKER_ID")
5. Applicable regulations can be found using: get_regulations("EXCHANGE", "TYPE")
6. Cancel rate above 80% with cancel latency under 500ms indicates spoofing
7. Trades where buyer and seller share the same UBO indicate wash trading
```

**Data Source:** `surveillance` KQL database in `surveillance-eh` Eventhouse

**Actions:**
| Action | Description | Connected To |
|--------|-------------|-------------|
| Escalate to Compliance | Send detailed alert with UBO chain to compliance officer | Teams channel |
| Request Investigation | Flag case for manual review with full evidence | Teams message |
| Generate Report | Trigger evidence notebook for regulatory report | Data Activator → Fabric Pipeline |

### Architecture: Two-Layer Detection

```
Layer 1 — Deterministic (Primary, <60s):
  Eventhouse → KQL stored functions → Data Activator
  → Autonomous: trade halt, regulator notification, broker suspension
  
Layer 2 — AI Advisory (Secondary, ~5min):
  Eventhouse → Operations Agent (LLM-powered)
  → Advisory: contextual analysis, UBO investigation, compliance escalation
  → Human reviews recommendation → approves/rejects in Teams
```

### Limitations
- **5-minute polling interval** (cannot meet 60s SLA for autonomous actions)
- **LLM-based** — decisions are probabilistic, not deterministic
- **English only** for instructions and goals
- **Creator's identity** used for all queries
- **3-day auto-cancel** on unresponded recommendations
- **Throttling** possible under heavy usage
- Preview feature

### Setup Steps (Manual — Fabric Portal)

1. In workspace, select **Create** → **Operations Agent**
2. Name: `Surveillance Advisor`
3. Enter business goals and instructions (copy from above)
4. Select data source: `surveillance` KQL database
5. Create actions: Escalate to Compliance, Request Investigation
6. Connect actions to Data Activator or Teams
7. Activate the agent

> **Note:** Operations Agent creation is not yet available via REST API.
> This step must be performed manually in the Fabric portal after `azd up`.
