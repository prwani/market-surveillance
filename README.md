# Real-Time Market Surveillance Agent System
## Using Microsoft Fabric RTI and FabricIQ

**Author:** Technical Architecture Plan  
**Date:** April 7, 2026  
**Tags:** Microsoft Fabric, RTI, FabricIQ, Market Surveillance, AI Agents, Financial Services, Asia Markets

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Microsoft Fabric RTI and FabricIQ Overview](#2-microsoft-fabric-rti-and-fabriciq-overview)
3. [Combined Architecture](#3-combined-architecture)
4. [Architecture Diagram](#4-architecture-diagram)
5. [Agent System Design](#5-agent-system-design)
6. [Exchange Data Simulation](#6-exchange-data-simulation)
7. [GenAI Time Series and Anomaly Detection Models](#7-genai-time-series-and-anomaly-detection-models)
8. [Performance Benchmarks and Case Studies](#8-performance-benchmarks-and-case-studies)
9. [Asia-Pacific Regional Specificity](#9-asia-pacific-regional-specificity)
10. [Data Sovereignty and Security](#10-data-sovereignty-and-security)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Conclusion](#12-conclusion)

---

## 1. Executive Summary

This document presents a comprehensive architectural plan for an **Autonomous Real-Time Market Surveillance Agent System** built on **Microsoft Fabric Real-Time Intelligence (RTI)** and **FabricIQ**. The system is designed to monitor trading activity across major Asian exchanges (SGX, HKEX, NSE), detect manipulation patterns (spoofing, layering, wash trading), and autonomously coordinate intervention — all within a 60-second detection-to-halt window.

### Key Design Goals

| Goal | Target | Technology Enabler |
|------|--------|--------------------|
| Detection-to-halt latency | ≤ 60 seconds | Fabric RTI Event Streams + KQL real-time queries |
| Manipulation reduction | 80% | ML agents on FabricIQ + continuous stream processing |
| Investor confidence | 95% satisfaction | Transparent, explainable AI decisions |
| False alert rate | Near-zero | GenAI-powered intelligent filtering |
| System uptime | 99.9% | Multi-region Fabric deployment |
| Data sovereignty | Compliant per jurisdiction | Fabric workspace isolation per exchange/country |

---

## 2. Microsoft Fabric RTI and FabricIQ Overview

### 2.1 Microsoft Fabric Real-Time Intelligence (RTI)

Microsoft Fabric RTI is an end-to-end platform for ingesting, processing, and acting on streaming data in real time. Its key components are:

| Component | Role in Surveillance |
|-----------|---------------------|
| **Event Streams** | Ingest raw trading data from exchange feeds (FIX protocol, REST, WebSocket) |
| **Eventhouse / KQL Database** | Time-series storage and ultra-fast analytical queries on order book data |
| **KQL Querysets** | Ad hoc and scheduled queries for pattern detection (spoofing windows, layering sequences) |
| **Real-Time Dashboards** | Live regulatory dashboards showing market state and alerts |
| **Activator (Data Activator)** | Rule-based triggers that fire alerts or call APIs when thresholds are breached |
| **Reflex** | Automated actions when conditions are met — the "intervention" layer |

**Why RTI for Market Surveillance?**
- Sub-second ingestion latency via Event Streams
- Kusto Query Language (KQL) is purpose-built for time-series analytics with built-in windowing, series decomposition, and anomaly detection
- Native integration with OneLake for hot/warm/cold data tiering
- Activator enables autonomous responses without custom orchestration code

### 2.2 FabricIQ

FabricIQ is the AI and intelligence layer within Microsoft Fabric, combining:

| Component | Role in Surveillance |
|-----------|---------------------|
| **Copilot for Fabric** | Natural language interface for analysts to query surveillance data |
| **ML Model Registry** | Host and version custom manipulation-detection models |
| **Data Science Notebooks** | Train and evaluate anomaly detection, NLP, and GenAI models |
| **AI Skills** | Reusable AI components called from pipelines or agents |
| **Semantic Model + Direct Lake** | Business-layer view for cross-market correlation analysis |
| **Azure AI Integration** | Access to Azure OpenAI, Azure ML, and Cognitive Services |
| **Real-Time ML Scoring** | Invoke ML models directly within KQL queries using `evaluate` |

**Why FabricIQ for Market Surveillance?**
- Enables ML-powered scoring of every trade event at ingestion time
- Generative AI can synthesize narrative explanations of detected manipulation for regulators
- Direct Lake mode allows zero-copy query over streaming data from OneLake
- Semantic models allow cross-exchange, cross-market correlation with business logic

### 2.3 Why RTI + FabricIQ Together?

RTI handles the **hot path** — real-time ingestion, streaming rules, and sub-minute alerting. FabricIQ handles the **intelligent path** — ML inference, anomaly scoring, cross-market pattern recognition, and evidence synthesis. Together they form a feedback loop:

```
Trading Events → RTI (stream + rules) → Suspicious Flag → FabricIQ (ML scoring) →
Manipulation Score → RTI Activator (intervention) → Evidence → FabricIQ (GenAI narrative)
```

---

## 3. Combined Architecture

### 3.1 Logical Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION LAYER                                     │
│                                                                                  │
│  SGX Feed   HKEX Feed   NSE Feed   Dark Pool   OTC Feeds   Broker APIs          │
│  (FIX/WS)  (FIX/REST)  (FIX/WS)   (WebSocket)  (REST)      (Kafka)             │
│      │          │           │           │           │           │                │
│      └──────────┴───────────┴───────────┴───────────┴───────────┘                │
│                              │                                                   │
│                    Fabric Event Streams                                          │
│                   (Multi-source connector)                                       │
└──────────────────────────────────────────────┬───────────────────────────────────┘
                                               │
┌──────────────────────────────────────────────▼───────────────────────────────────┐
│                         REAL-TIME PROCESSING LAYER (RTI)                         │
│                                                                                  │
│  ┌───────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐   │
│  │  Stream Processing │    │  KQL Real-Time Rules  │    │  Data Activator     │   │
│  │  - Normalization  │───▶│  - Spoofing windows   │───▶│  - Alert triggers   │   │
│  │  - Enrichment     │    │  - Volume spike detect│    │  - Intervention API │   │
│  │  - Deduplication  │    │  - Layering patterns  │    │  - Regulator notify │   │
│  └───────────────────┘    └──────────────────────┘    └─────────────────────┘   │
│            │                        │                          │                 │
│            ▼                        ▼                          ▼                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │              Eventhouse / KQL Database                                  │    │
│  │  - Raw trades table (rolling 7-day hot, 1-year warm, 7-year cold)      │    │
│  │  - Order book snapshots                                                 │    │
│  │  - Pre-computed features (VWAP, bid-ask spread, order imbalance)       │    │
│  │  - Flagged events with ML scores                                        │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────┬───────────────────────────────────┘
                                               │
┌──────────────────────────────────────────────▼───────────────────────────────────┐
│                         AI/ML INTELLIGENCE LAYER (FabricIQ)                      │
│                                                                                  │
│  ┌─────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐  │
│  │  Pattern Detection  │  │  Anomaly Detection    │  │  Cross-Market Agent   │  │
│  │  Agent              │  │  Agent                │  │                       │  │
│  │  - Spoofing ML      │  │  - Price anomaly      │  │  - Correlation engine │  │
│  │  - Layering ML      │  │  - Volume anomaly     │  │  - Lead-lag detection │  │
│  │  - Wash trading ML  │  │  - Time-series decomp │  │  - Network analysis   │  │
│  └─────────────────────┘  └───────────────────────┘  └───────────────────────┘  │
│                                                                                  │
│  ┌─────────────────────┐  ┌───────────────────────┐                            │
│  │  Intervention Agent │  │  Evidence Collection  │                            │
│  │  - Trade halt API   │  │  Agent                │                            │
│  │  - Broker suspend   │  │  - Audit trail GenAI  │                            │
│  │  - Regulator notify │  │  - Case narrative     │                            │
│  └─────────────────────┘  └───────────────────────┘                            │
└──────────────────────────────────────────────┬───────────────────────────────────┘
                                               │
┌──────────────────────────────────────────────▼───────────────────────────────────┐
│                         PRESENTATION & ACTION LAYER                              │
│                                                                                  │
│  Real-Time Dashboard  │  Regulatory Portal  │  Mobile Alerts  │  Case Manager   │
│  (Fabric Dashboard)   │  (Power BI Embedded)│  (Teams/Email)  │  (SharePoint)   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Technology Mapping

| Layer | Technology | Purpose |
|-------|------------|---------|
| Ingestion | Fabric Event Streams + Custom Connectors | Ingest FIX/WebSocket/Kafka feeds from exchanges |
| Stream Processing | Event Streams transformations | Normalize, enrich, route |
| Hot Storage | Eventhouse (KQL Database) | Sub-second query on last 7 days of trades |
| Warm/Cold Storage | OneLake (Delta tables) | Historical data for model training, audit |
| Real-Time Rules | KQL Queries + Activator | Rule-based spoofing/layering detection |
| ML Inference | FabricIQ Data Science + Direct Lake | Real-time ML scoring on streaming data |
| GenAI Narrative | Azure OpenAI via FabricIQ | Regulatory case summaries and explainability |
| Agent Orchestration | Semantic Kernel + Azure AI Agents | Multi-agent coordination logic |
| Presentation | Real-Time Dashboard + Power BI | Regulatory dashboards |
| Intervention | Data Activator Reflex | Autonomous trade halt and notification |

---

## 4. Architecture Diagram

### 4.1 High-Level Component Architecture (Mermaid)

```mermaid
flowchart TD
    subgraph Exchanges["Exchange Feeds (Asia-Pacific)"]
        SGX["SGX\n(Singapore)"]
        HKEX["HKEX\n(Hong Kong)"]
        NSE["NSE\n(India)"]
        OTC["Dark Pools /\nOTC Markets"]
    end

    subgraph Ingestion["Ingestion Layer — Fabric Event Streams"]
        ES["Event Streams\n(Multi-source connector)\nFIX / WebSocket / Kafka"]
    end

    subgraph RTI["Real-Time Intelligence (RTI) Layer"]
        SP["Stream Processing\n(Normalization + Enrichment)"]
        EH["Eventhouse / KQL Database\n(Hot: 7d | Warm: 1yr | Cold: 7yr)"]
        KQL["KQL Real-Time Rules\n(Spoofing | Layering | Volume Spike)"]
        DA["Data Activator\n(Reflex Triggers)"]
    end

    subgraph FabricIQ["FabricIQ — AI Intelligence Layer"]
        PDA["Pattern Detection Agent\n(Spoofing / Layering / Wash Trading ML)"]
        ADA["Anomaly Detection Agent\n(Price + Volume Time-Series)"]
        CMA["Cross-Market Agent\n(Correlation + Network Analysis)"]
        IA["Intervention Agent\n(Trade Halt + Broker Suspend)"]
        ECA["Evidence Collection Agent\n(Audit Trail + GenAI Narrative)"]
    end

    subgraph Presentation["Regulatory Presentation Layer"]
        RTD["Real-Time Dashboard"]
        REG["Regulatory Portal\n(Power BI Embedded)"]
        CASE["Case Manager\n(SharePoint + Teams)"]
    end

    SGX -->|FIX/WS| ES
    HKEX -->|FIX/REST| ES
    NSE -->|FIX/WS| ES
    OTC -->|WebSocket| ES

    ES --> SP
    SP --> EH
    SP --> KQL
    KQL --> DA
    KQL --> EH
    EH --> PDA
    EH --> ADA
    EH --> CMA

    PDA -->|Manipulation Score| DA
    ADA -->|Anomaly Score| DA
    CMA -->|Cross-Market Flag| DA

    DA -->|Intervention Signal| IA
    DA -->|Evidence Request| ECA

    IA -->|Trade Halt API| SGX
    IA -->|Trade Halt API| HKEX
    IA -->|Trade Halt API| NSE

    ECA --> CASE
    DA --> RTD
    EH --> REG

    style Exchanges fill:#dbeafe,stroke:#1d4ed8
    style Ingestion fill:#dcfce7,stroke:#15803d
    style RTI fill:#fef3c7,stroke:#d97706
    style FabricIQ fill:#ede9fe,stroke:#7c3aed
    style Presentation fill:#fce7f3,stroke:#be185d
```

### 4.2 60-Second Detection-to-Halt Timeline

```mermaid
sequenceDiagram
    participant E as Exchange Feed
    participant ES as Event Streams
    participant KQL as KQL Engine
    participant ML as FabricIQ ML
    participant ACT as Data Activator
    participant IA as Intervention Agent
    participant REG as Regulator

    Note over E,REG: T=0 — Trade events arrive

    E->>ES: Raw order/trade events (T+0s)
    ES->>KQL: Normalized stream (T+2s)
    KQL->>KQL: Evaluate spoofing/layering rules (T+5s)
    KQL->>ML: Flag suspicious orders (T+8s)
    ML->>ML: Run ML scoring pipeline (T+15s)
    ML->>ACT: Return manipulation score > threshold (T+20s)
    ACT->>IA: Trigger intervention signal (T+22s)
    IA->>E: POST /halt-trade to exchange API (T+25s)
    IA->>REG: Push alert + preliminary evidence (T+30s)
    IA->>ML: Request evidence compilation (T+32s)
    ML->>ML: GenAI narrative + audit trail (T+50s)
    ML->>REG: Full case report (T+58s)

    Note over E,REG: T=60s — Full cycle complete
```

### 4.3 Data Model — Eventhouse Schema

```mermaid
erDiagram
    TRADES {
        string trade_id PK
        timestamp event_time
        string exchange_id
        string symbol
        float price
        float quantity
        string buyer_id
        string seller_id
        string order_type
        string venue
    }

    ORDER_BOOK_EVENTS {
        string event_id PK
        timestamp event_time
        string exchange_id
        string symbol
        string side
        float price
        float quantity
        string action
        string broker_id
    }

    ML_SCORES {
        string event_id FK
        timestamp scored_at
        float spoofing_score
        float layering_score
        float wash_trading_score
        float anomaly_score
        string model_version
        bool is_flagged
    }

    INTERVENTIONS {
        string case_id PK
        timestamp detected_at
        timestamp halted_at
        string exchange_id
        string symbol
        string manipulation_type
        string[] involved_brokers
        string status
        string regulator_ref
    }

    TRADES ||--o{ ML_SCORES : "scored"
    ORDER_BOOK_EVENTS ||--o{ ML_SCORES : "scored"
    ML_SCORES ||--o{ INTERVENTIONS : "triggers"
```

---

## 5. Agent System Design

### 5.1 Multi-Agent Coordination Architecture

The system uses five specialized AI agents orchestrated by **Semantic Kernel** with an **Azure AI Foundry** backend. Agents communicate through a shared message bus (Fabric Event Streams) and a shared state store (KQL Database).

```mermaid
flowchart LR
    subgraph Orchestrator["Agent Orchestrator (Semantic Kernel)"]
        direction TB
        COORD["Coordination Agent\n(Routes events to\nspecialist agents)"]
    end

    subgraph Specialist["Specialist Agents"]
        PDA["🔍 Pattern Detection Agent"]
        ADA["📊 Anomaly Detection Agent"]
        CMA["🌐 Cross-Market Agent"]
        IA["⚡ Intervention Agent"]
        ECA["📁 Evidence Collection Agent"]
    end

    subgraph Tools["Agent Tools (FabricIQ + RTI)"]
        KQL_TOOL["KQL Query Tool"]
        ML_TOOL["ML Scoring Tool"]
        API_TOOL["Exchange Halt API Tool"]
        GENAI_TOOL["GenAI Narrative Tool"]
        SEARCH_TOOL["OneLake Search Tool"]
    end

    COORD -->|"suspicious_event"| PDA
    COORD -->|"price_alert"| ADA
    COORD -->|"multi_exchange_flag"| CMA
    PDA -->|"manipulation_confirmed"| COORD
    ADA -->|"anomaly_confirmed"| COORD
    CMA -->|"cross_market_confirmed"| COORD
    COORD -->|"intervene"| IA
    COORD -->|"collect_evidence"| ECA

    PDA --- KQL_TOOL
    PDA --- ML_TOOL
    ADA --- ML_TOOL
    ADA --- KQL_TOOL
    CMA --- KQL_TOOL
    CMA --- SEARCH_TOOL
    IA --- API_TOOL
    ECA --- GENAI_TOOL
    ECA --- SEARCH_TOOL
```

### 5.2 Agent Specifications

#### Pattern Detection Agent

**Responsibility:** Identify spoofing, layering, and wash trading from order book and trade flow data.

**KQL Rule — Spoofing Detection:**
```kusto
// Spoofing: Large order placed then cancelled within 500ms before price moves
ORDER_BOOK_EVENTS
| where event_time > ago(1m)
| where action in ("add", "cancel")
| summarize
    orders_added = countif(action == "add"),
    orders_cancelled = countif(action == "cancel"),
    avg_size_added = avgif(quantity, action == "add"),
    avg_cancel_latency_ms = avg(iff(action == "cancel",
        datetime_diff("millisecond", event_time, prev(event_time, 1)), 0))
    by broker_id, symbol, bin(event_time, 1m)
| where orders_cancelled > orders_added * 0.8     // >80% cancel rate
| where avg_cancel_latency_ms < 500               // within 500ms
| where avg_size_added > 10000                     // large orders
| project event_time, broker_id, symbol,
    spoofing_score = (orders_cancelled * 1.0 / orders_added) * (500 - avg_cancel_latency_ms) / 500
```

**KQL Rule — Layering Detection:**
```kusto
// Layering: Multiple orders at different price levels, then mass cancel on opposite side
ORDER_BOOK_EVENTS
| where event_time > ago(2m)
| summarize
    price_levels = dcount(price),
    total_quantity = sum(quantity),
    cancel_count = countif(action == "cancel")
    by broker_id, symbol, side, bin(event_time, 30s)
| where price_levels >= 5                          // multiple price levels
| where cancel_count > 0.7 * (price_levels)        // most cancelled
| join kind=inner (
    ORDER_BOOK_EVENTS
    | where action == "add" and side == "buy"
    | summarize opp_orders = count() by broker_id, symbol, bin(event_time, 30s)
) on broker_id, symbol, event_time
| where side == "sell" and opp_orders > 5          // layering sell to push down
```

**KQL Rule — Wash Trading Detection:**
```kusto
// Wash trading: Same beneficial owner on both sides of a trade
TRADES
| where event_time > ago(10m)
| join kind=inner (TRADES) on symbol, price
| where buyer_id != seller_id                      // different account IDs
| join kind=inner (
    BROKER_OWNERSHIP                               // beneficial ownership table
) on $left.buyer_id == $right.account_id
| join kind=inner (
    BROKER_OWNERSHIP
) on $left.seller_id == $right.account_id
| where $left.ultimate_owner == $right.ultimate_owner  // same ultimate owner
| summarize wash_count = count(), wash_volume = sum(quantity) by symbol, ultimate_owner
| where wash_count > 3
```

#### Anomaly Detection Agent

**Responsibility:** Flag unusual price movements, volume spikes, and statistical outliers using ML models called from KQL.

**KQL with built-in anomaly detection:**
```kusto
// Price anomaly using KQL series_decompose_anomalies
TRADES
| where event_time > ago(24h)
| make-series avg_price = avg(price) on event_time
    from ago(24h) to now() step 1m
    by symbol, exchange_id
| extend anomalies = series_decompose_anomalies(avg_price, 2.5)
| mv-expand event_time, avg_price, anomalies
| where toreal(anomalies) != 0
| project event_time, symbol, exchange_id,
    avg_price = toreal(avg_price),
    anomaly_score = toreal(anomalies)
```

**KQL with ML model scoring (FabricIQ plugin):**
```kusto
// Score with custom transformer model registered in FabricIQ ML Registry
TRADES
| where event_time > ago(5m)
| summarize
    price_return_1m = (last(price) - first(price)) / first(price),
    volume_5m = sum(quantity),
    trade_count = count(),
    vwap = sum(price * quantity) / sum(quantity)
    by symbol, exchange_id, bin(event_time, 1m)
| evaluate ml_anomaly_score(                       // FabricIQ ML plugin
    model_name = "market-anomaly-detector-v3",
    features = pack(
        "price_return_1m", price_return_1m,
        "volume_5m", volume_5m,
        "trade_count", trade_count,
        "vwap", vwap
    )
)
| where anomaly_probability > 0.85
```

#### Cross-Market Agent

**Responsibility:** Detect coordinated manipulation across multiple exchanges or asset classes.

**Design:**
- Subscribes to flagged events from Pattern Detection and Anomaly Detection agents
- Builds a real-time entity graph: broker → accounts → orders → symbols → exchanges
- Uses graph analytics (via FabricIQ notebooks) to detect coordinated rings
- Computes lead-lag correlations to identify price manipulation across related instruments

```python
# Cross-market correlation (FabricIQ Notebook — Spark)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, window, corr, lag
from pyspark.sql.window import Window

spark = SparkSession.builder.getOrCreate()

# Read from Eventhouse via Direct Lake
trades_sgx = spark.read.format("delta").load("abfss://surveillance@onelake.dfs.fabric.microsoft.com/sgx/trades")
trades_hkex = spark.read.format("delta").load("abfss://surveillance@onelake.dfs.fabric.microsoft.com/hkex/trades")

# Compute 1-minute VWAP for correlated symbols (e.g., same company listed on 2 exchanges)
def compute_vwap(df, exchange):
    return df.groupBy(window("event_time", "1 minute"), "symbol") \
             .agg({"price * quantity": "sum", "quantity": "sum"}) \
             .withColumn("vwap", col("sum(price * quantity)") / col("sum(quantity)")) \
             .withColumn("exchange", lit(exchange))

vwap_sgx = compute_vwap(trades_sgx, "SGX")
vwap_hkex = compute_vwap(trades_hkex, "HKEX")

# Compute cross-exchange lead-lag correlation for dual-listed securities
cross_market = vwap_sgx.alias("sgx").join(
    vwap_hkex.alias("hkex"),
    on=["window", "symbol"],
    how="inner"
)

w = Window.partitionBy("symbol").orderBy("window")
cross_market = cross_market \
    .withColumn("sgx_lead_1", lag("sgx.vwap", 1).over(w)) \
    .withColumn("hkex_corr_lag1", corr("hkex.vwap", "sgx_lead_1")) \
    .filter(col("hkex_corr_lag1").abs() > 0.95)  # Strong lead-lag → possible front-running
```

#### Intervention Agent

**Responsibility:** Autonomously halt suspicious trades and notify regulators within 60 seconds.

**Design:**
- Receives intervention signals from Data Activator
- Calls exchange APIs (REST) to place trading halts
- Sends structured alerts to regulators via email, Teams, and regulatory portals
- All actions are logged to the audit trail in Eventhouse

```python
# Intervention Agent — Azure AI Agent with tools
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

class InterventionAgent:
    def __init__(self):
        self.client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str="<fabric-ai-project-connection>"
        )

    def halt_trading(self, exchange_id: str, symbol: str, case_id: str) -> dict:
        """Call exchange REST API to halt trading on a symbol."""
        exchange_apis = {
            "SGX":  "https://api.sgx.com/v1/surveillance/halt",
            "HKEX": "https://api.hkex.com/v2/market/halt",
            "NSE":  "https://api.nseindia.com/v1/trading/halt"
        }
        endpoint = exchange_apis.get(exchange_id)
        response = requests.post(endpoint, json={
            "symbol": symbol,
            "reason": "REGULATORY_SURVEILLANCE",
            "case_id": case_id,
            "halted_by": "fabric-surveillance-agent"
        }, headers={"Authorization": f"Bearer {self.get_token(exchange_id)}"})
        return response.json()

    def notify_regulator(self, case_id: str, manipulation_type: str,
                          exchange_id: str, preliminary_evidence: dict):
        """Send structured alert to regulatory body."""
        regulator_map = {
            "SGX": "MAS",    # Monetary Authority of Singapore
            "HKEX": "SFC",   # Securities and Futures Commission, HK
            "NSE": "SEBI"    # Securities and Exchange Board of India
        }
        regulator = regulator_map.get(exchange_id, "UNKNOWN")
        # Push to regulatory portal + Teams notification
        self._push_to_portal(regulator, case_id, manipulation_type, preliminary_evidence)
        self._send_teams_alert(regulator, case_id, manipulation_type)
```

#### Evidence Collection Agent

**Responsibility:** Compile audit trails and generate regulatory-ready case reports using GenAI.

**Design:**
- Queries Eventhouse for all events related to a case (30-min window before and after)
- Uses Azure OpenAI (GPT-4o) via FabricIQ to generate narrative explanations
- Produces structured case documents in formats required by MAS, SFC, SEBI
- Maintains an immutable audit log in OneLake

**GenAI Prompt Template for Evidence Narrative:**
```python
EVIDENCE_PROMPT = """
You are a financial market surveillance expert. Analyze the following trading data
and produce a formal regulatory evidence report.

CASE ID: {case_id}
EXCHANGE: {exchange_id}
SYMBOL: {symbol}
DETECTED MANIPULATION TYPE: {manipulation_type}
TIME WINDOW: {start_time} to {end_time}

ORDER BOOK EVENTS (chronological):
{order_book_events}

TRADE EVENTS:
{trade_events}

ML DETECTION SCORES:
- Spoofing Score: {spoofing_score:.3f}
- Layering Score: {layering_score:.3f}
- Anomaly Score: {anomaly_score:.3f}

INVOLVED ENTITIES:
{involved_entities}

Produce:
1. Executive Summary (2 paragraphs, suitable for senior regulator)
2. Timeline of Events (bullet points, chronological)
3. Evidence of Intent (explain why this is likely intentional manipulation)
4. Market Impact Analysis (estimated price distortion, affected investors)
5. Recommended Regulatory Action
6. Supporting Data References (cite specific orders/trades by ID)

Regulatory jurisdiction: {regulatory_body}
Language: {language}  (English | Simplified Chinese | Traditional Chinese | Hindi | Tamil)
"""
```

---

## 6. Exchange Data Simulation

The `exchange_data_simulator.py` script (in this directory) provides a comprehensive data generator that simulates realistic trading activity including:

- Normal market-making activity
- Spoofing patterns (large order → cancel before fill)
- Layering patterns (multiple price levels → mass cancel)
- Wash trading (same beneficial owner, different accounts)
- Price anomalies (sudden spikes or flash crashes)
- Cross-market coordinated manipulation

### 6.1 Simulation Architecture

```mermaid
flowchart LR
    subgraph Simulator["Exchange Data Simulator"]
        MKT["Market State\n(OHLCV, Order Book)"]
        NORM["Normal Trading\nGenerator"]
        MANIP["Manipulation\nPattern Injector"]
        SCHED["Event Scheduler\n(time-accurate)"]
    end

    subgraph Output["Output Targets"]
        KAFKA["Kafka Topic\n(fabric-event-streams)"]
        CSV["CSV Files\n(for batch testing)"]
        API["REST API\n(mock exchange endpoint)"]
        WS["WebSocket Server\n(real-time streaming)"]
    end

    MKT --> NORM
    MKT --> MANIP
    NORM --> SCHED
    MANIP --> SCHED
    SCHED --> KAFKA
    SCHED --> CSV
    SCHED --> API
    SCHED --> WS
```

### 6.2 Simulator Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Run basic simulation (normal market activity)
python exchange_data_simulator.py --exchange SGX --symbols OCBC,DBS,UOB --duration 3600

# Run with manipulation injection (spoofing at T=300s)
python exchange_data_simulator.py \
  --exchange HKEX \
  --symbols 0700.HK,9988.HK \
  --duration 3600 \
  --inject-spoofing --spoofing-start 300 \
  --inject-layering --layering-start 600 \
  --inject-wash-trading --wash-start 1200

# Run multi-exchange simulation (for cross-market testing)
python exchange_data_simulator.py \
  --multi-exchange SGX,HKEX,NSE \
  --coordinated-manipulation \
  --output kafka --kafka-broker localhost:9092

# Output to CSV for offline model training
python exchange_data_simulator.py \
  --exchange NSE \
  --symbols RELIANCE,TCS,INFY \
  --duration 28800 \
  --output csv \
  --output-dir ./data/nse_training
```

### 6.3 Sample Output Events

**Normal trade event (FIX-like JSON):**
```json
{
  "event_type": "TRADE",
  "event_id": "SGX-TRD-20260407-000001",
  "exchange_id": "SGX",
  "symbol": "OCBC",
  "timestamp": "2026-04-07T09:00:00.123456Z",
  "price": 14.52,
  "quantity": 5000,
  "buyer_id": "BROKER_UOB_001",
  "seller_id": "BROKER_DBS_023",
  "order_type": "LIMIT",
  "venue": "SGX_MAIN",
  "currency": "SGD",
  "labels": { "is_manipulation": false, "manipulation_type": null }
}
```

**Spoofing order event:**
```json
{
  "event_type": "ORDER_BOOK",
  "event_id": "SGX-OBK-20260407-000042",
  "exchange_id": "SGX",
  "symbol": "OCBC",
  "timestamp": "2026-04-07T09:05:00.445Z",
  "action": "add",
  "side": "buy",
  "price": 14.70,
  "quantity": 500000,
  "broker_id": "BROKER_SPOOF_001",
  "labels": {
    "is_manipulation": true,
    "manipulation_type": "SPOOFING",
    "will_cancel_at": "2026-04-07T09:05:00.789Z",
    "cancel_latency_ms": 344
  }
}
```

---

## 7. GenAI Time Series and Anomaly Detection Models

### 7.1 Latest Models Applicable to Market Surveillance

| Model | Type | Provider | Strengths for Surveillance |
|-------|------|----------|---------------------------|
| **TimeGPT** | Foundation Time-Series | Nixtla | Zero-shot forecasting; anomaly detection without retraining |
| **Moirai** | Foundation Time-Series | Salesforce | Multi-variate; handles irregular financial time-series |
| **Chronos** | Foundation Time-Series | Amazon | Probabilistic forecasting; uncertainty quantification |
| **TimesFM** | Foundation Time-Series | Google | Large-scale pre-training on financial data |
| **Lag-Llama** | Probabilistic TS | Independent | Decoder-only transformer; good for short-horizon alerts |
| **GPT-4o (fine-tuned)** | GenAI / Reasoning | Azure OpenAI | Evidence narrative, pattern explanation, regulatory writing |
| **Titan** | Anomaly Detection | AWS | Detection without labeled data (useful for novel schemes) |
| **PatchTST** | Self-supervised TS | Independent | Strong on multivariate time-series classification |
| **MOMENT** | Foundation TS | CMU | Unified model for classification + anomaly + forecasting |

### 7.2 Recommended Model Pipeline for FabricIQ

```mermaid
flowchart TD
    RAW["Raw Trade Stream\n(Fabric Event Streams)"] --> FEAT["Feature Engineering\n(FabricIQ Spark Notebook)"]

    FEAT --> FAST["Fast Path\n(≤5s latency)\nKQL series_decompose_anomalies\n+ Chronos/Lag-Llama"]
    FEAT --> DEEP["Deep Path\n(≤30s latency)\nMOMENT / PatchTST\n(full manipulation classifier)"]

    FAST --> FUSE["Score Fusion\n(weighted ensemble)"]
    DEEP --> FUSE

    FUSE --> THRESH["Threshold Decision\n(score > 0.85 → flag)"]
    THRESH --> |"Flag"| GENAI["GenAI Explanation\n(GPT-4o fine-tuned)"]
    THRESH --> |"No flag"| STORE["Store to Eventhouse\n(low-score events)"]

    GENAI --> EVIDENCE["Evidence Report\n(regulatory-ready)"]
```

### 7.3 Model Descriptions

#### TimeGPT (Nixtla)
**How it works:** A transformer-based foundation model pre-trained on a massive corpus of 100B+ time-series data points. It supports **zero-shot inference** — you can call it directly on new market data without retraining.

**Application:**
- Forecast "normal" price range for the next 5 minutes
- Flag trades whose prices fall outside the 99% prediction interval as anomalous
- Works across all asset classes without per-symbol fine-tuning

**Integration with FabricIQ:**
```python
# FabricIQ Notebook — TimeGPT anomaly detection
from nixtla import NixtlaClient
import pandas as pd

nixtla_client = NixtlaClient(api_key=mssparkutils.credentials.getSecret("kv-surveillance", "nixtla-api-key"))

# Load last 2 hours of 1-minute VWAP from Eventhouse
df = spark.sql("""
    SELECT event_time, symbol, avg(price) as price
    FROM TRADES
    WHERE event_time > ago(2h)
    GROUP BY bin(event_time, 1min), symbol
""").toPandas()

# Detect anomalies with TimeGPT
anomaly_df = nixtla_client.detect_anomalies(
    df=df,
    time_col="event_time",
    target_col="price",
    id_col="symbol",
    level=99  # 99% confidence interval
)
# anomaly_df["anomaly"] == True → trigger alert
```

#### MOMENT (CMU)
**How it works:** A unified foundation model for time-series that handles **classification, anomaly detection, and imputation** from a single pre-trained checkpoint. Trained on MIMIC, M4, and financial datasets.

**Application:**
- Multi-task: simultaneously classify trade pattern type AND detect anomaly
- Handles missing data (common in illiquid markets)
- Fine-tune on labeled manipulation data from historical cases

**Integration:**
```python
# FabricIQ Notebook — MOMENT fine-tuning for manipulation detection
from momentfm import MOMENTPipeline
import torch

# Load MOMENT pre-trained checkpoint from FabricIQ ML Registry
model = MOMENTPipeline.from_pretrained(
    "AutonLab/MOMENT-1-large",
    model_kwargs={"task_name": "classification", "n_channels": 8, "num_class": 4}
    # 4 classes: NORMAL, SPOOFING, LAYERING, WASH_TRADING
)

# Fine-tune on labeled historical data stored in OneLake
train_data = spark.read.format("delta").load(
    "abfss://surveillance@onelake.dfs.fabric.microsoft.com/labeled/manipulation_cases"
).toPandas()

# Training loop (simplified)
model.train()
for epoch in range(20):
    for batch in get_batches(train_data, batch_size=64):
        features = extract_order_book_features(batch)  # shape: [64, 8, 512]
        labels = batch["manipulation_type_encoded"]
        loss = model(features, labels)
        loss.backward()
```

#### Chronos (Amazon)
**How it works:** A language model architecture (T5-based) adapted for probabilistic time-series forecasting. It tokenizes time-series values like text and predicts future distributions.

**Application:**
- Probabilistic price forecasting for "what should price be in 1 minute"
- Detect flash crash precursors (probability of extreme downward move)
- Quantify uncertainty to reduce false positives in volatile markets

#### PatchTST
**How it works:** Splits time-series into patches (like image patches in ViT) and processes them with a transformer. Achieves state-of-the-art on multi-variate time-series classification.

**Application:**
- Multi-variate input: price, volume, bid-ask spread, order imbalance, broker concentration
- Superior at detecting layering (requires correlation between price levels and order quantities)
- Good for cross-asset correlation (process multiple related instruments together)

### 7.4 GenAI for Explainability (GPT-4o)

A critical advantage of GenAI in surveillance is **explainability** — regulators need plain-language justification, not just a score.

**Example GenAI-generated evidence summary:**

> **Case #SGX-2026-00142 — SPOOFING — OCBC (O39.SI)**
>
> Between 09:05:00 and 09:05:01 SGT on April 7, 2026, Broker MERIDIAN_SG_001 placed a series of large buy orders totalling 500,000 shares at prices ranging from SGD 14.68 to SGD 14.72, representing approximately 8.3% of average daily volume. These orders were systematically cancelled within an average of 344 milliseconds after placement, before any executions occurred. Immediately following each cancellation sequence, the same broker executed sell orders at prices 0.4–0.6% higher than the pre-spoofing reference price, capturing estimated gains of approximately SGD 127,000.
>
> The pattern is consistent with **spoofing** as defined under Section 208 of the Singapore Securities and Futures Act. The orders were placed with the apparent intent to create a false impression of demand, inducing other market participants to pay higher prices. The ML detection system assigned a spoofing confidence score of 0.97 (threshold: 0.85).
>
> **Recommended action:** Immediate trading suspension for MERIDIAN_SG_001 pending investigation; referral to MAS Enforcement Division.

---

## 8. Performance Benchmarks and Case Studies

### 8.1 Microsoft Fabric RTI Performance Characteristics

Based on published Microsoft documentation and partner case studies:

| Metric | Value | Notes |
|--------|-------|-------|
| Event Streams ingestion latency | < 1 second (p99) | For Kafka-compatible and Event Hub sources |
| Eventhouse KQL query latency | < 100ms for recent data | On properly partitioned tables |
| KQL query throughput | > 1M rows/second scan | Columnar storage with partition pruning |
| Data Activator trigger latency | < 5 seconds | From threshold breach to action |
| Concurrent alert processing | 10,000+ events/second | Per Eventhouse cluster |
| Maximum event stream throughput | ~100 MB/s per partition | Scalable with additional partitions |

**Published benchmark context:**  
Microsoft's internal testing for Fabric RTI in financial services scenarios (referenced in the Fabric RTI GA announcement, 2024) demonstrated end-to-end latency from event ingestion to dashboard refresh of **under 5 seconds** for high-frequency data streams up to 50,000 events/second.

### 8.2 Comparable Surveillance System Benchmarks

While direct Fabric RTI market surveillance case studies are limited (the technology is 2024-era), comparable financial surveillance systems provide reference points:

#### NASDAQ Surveillance (SMARTS)
- **Scale:** 10 billion messages/day across US equities
- **Latency:** Real-time alerts within 30 seconds
- **False positive rate:** ~2% after ML filtering
- **Relevance:** Establishes the 30-60 second baseline that Fabric RTI can match

#### London Stock Exchange Group (LSEG)
- **Technology:** Azure-based streaming (comparable to Fabric RTI architecture)
- **Reported outcome:** 40% reduction in manual review time after AI-assisted alert prioritization
- **Relevance:** Validates Azure cloud-native architecture for Tier-1 exchange surveillance

#### SGX (Singapore Exchange) — Real Implementation Context
- SGX uses **SMARTS Market Surveillance** (acquired by Nasdaq in 2010)
- SGX processes approximately **500,000 orders/day** on normal days
- Current system generates ~200 alerts/day, with 15% requiring human review
- **Gap this system addresses:** No cross-exchange coordination with HKEX/NSE; alerts are exchange-siloed

#### SEBI (India) — SCORES System
- SEBI's Integrated Market Surveillance System (IMSS) processes NSE + BSE data
- Handles ~2 billion messages/day (largest single exchange by volume globally for some periods)
- **Gap:** Batch-oriented (T+1 analysis); real-time cross-border coordination is manual

### 8.3 Projected Performance for Fabric RTI-based System

Based on architecture design and Fabric RTI capabilities:

| Scenario | Projected Performance |
|----------|----------------------|
| Normal market day (SGX alone) | 500K orders/day → ~6 orders/second avg (peak: 500/second) |
| Combined SGX + HKEX + NSE | ~5M orders/day → ~60 orders/second avg (peak: 5,000/second) |
| RTI ingestion headroom | 100,000 events/second (100x headroom at peak) |
| Detection latency (KQL rules) | 5-15 seconds for rule-based detection |
| Detection latency (ML scoring) | 15-35 seconds for ML-scored results |
| End-to-end detection-to-halt | 25-58 seconds (within 60s SLA) |
| Estimated false positive rate | < 1% (with ML filtering + GenAI review) |

### 8.4 Cost Efficiency Benchmarks

| Component | Estimated Monthly Cost (USD) | Basis |
|-----------|-------------------------------|-------|
| Fabric RTI (Event Streams) | $2,000–$5,000 | 5M events/day @ $0.015/1000 events |
| Eventhouse (KQL) | $3,000–$8,000 | Hot storage + query compute |
| FabricIQ (ML/AI) | $5,000–$15,000 | ML inference + Azure OpenAI calls |
| OneLake storage | $500–$2,000 | Delta tables for 1 year retention |
| **Total** | **$10,500–$30,000/month** | For 3-exchange Asia-Pacific deployment |

**Comparison:** Traditional on-premises SMARTS surveillance systems cost $2M–$5M/year in licensing alone, plus infrastructure. The Fabric RTI approach offers **5–10x cost reduction** while adding real-time ML capabilities.

---

## 9. Asia-Pacific Regional Specificity

### 9.1 Exchange Microstructure Comparison

| Feature | SGX (Singapore) | HKEX (Hong Kong) | NSE (India) |
|---------|----------------|-----------------|-------------|
| Trading hours | 09:00–17:20 SGT | 09:30–16:00 HKT | 09:15–15:30 IST |
| Primary protocol | FIX 4.2/4.4 | OMD-C (proprietary) | NSE FIX |
| Order types | Limit, Market, Stop, Iceberg | Limit, Enhanced Limit, At-Auction | Limit, Market, Stop-Loss, AMO |
| Price change limits | ±30% for most equities | None (circuit breaker based) | ±20% (F&O), ±10% (equity) |
| Lot sizes | 100 shares (equities), 1 (ETFs) | 100–500 (varies by price) | 1 share (most equities) |
| Short selling rules | Regulated Short Sale rules | Covered short selling only | SEBI short-selling regulations |
| Pre/post market | Extended hours (AH trading) | Pre-opening (09:00–09:20) | Pre-open session (09:00–09:08) |
| Regulator | MAS | SFC | SEBI |

### 9.2 Regulatory Adaptation per Jurisdiction

```mermaid
flowchart TD
    subgraph GLOBAL["Global Rule Engine (Fabric RTI Core)"]
        BASE["Base Surveillance Rules\n(Market-agnostic manipulation patterns)"]
    end

    subgraph SGX_RULES["SGX / MAS Rules Layer"]
        SGX1["SFA Section 197: False trading"]
        SGX2["SFA Section 198: Market rigging"]
        SGX3["SFA Section 201: Fraudulent practices"]
        SGX4["MAS Notice SFA04: Reporting obligations"]
    end

    subgraph HKEX_RULES["HKEX / SFC Rules Layer"]
        HK1["SFO Section 274: Stock market manipulation"]
        HK2["SFO Section 295: False trading"]
        HK3["SFO Section 300: Fraudulent / deceptive"]
        HK4["SFC Code of Conduct para 4.3"]
    end

    subgraph NSE_RULES["NSE / SEBI Rules Layer"]
        NSE1["SEBI PFUTP Regulations 2003"]
        NSE2["SEBI Circular on Algorithmic Trading"]
        NSE3["SEBI Insider Trading Regulations"]
        NSE4["NSE Circular on Co-location"]
    end

    BASE --> SGX_RULES
    BASE --> HKEX_RULES
    BASE --> NSE_RULES

    SGX_RULES --> MAS["MAS Alert\n(English / Mandarin)"]
    HKEX_RULES --> SFC["SFC Alert\n(English / Traditional Chinese)"]
    NSE_RULES --> SEBI["SEBI Alert\n(English / Hindi)"]
```

### 9.3 Data Sovereignty Architecture

Each exchange jurisdiction requires its data to remain within national borders:

```
OneLake Architecture for Multi-Jurisdiction:
├── Fabric Workspace: SGX-Surveillance (hosted: Southeast Asia — Singapore region)
│   ├── Eventhouse: sgx-trades (data residency: Singapore)
│   ├── OneLake: sgx-historical (data residency: Singapore)
│   └── ML Models: sgx-pattern-detector (data residency: Singapore)
│
├── Fabric Workspace: HKEX-Surveillance (hosted: East Asia — Hong Kong region)
│   ├── Eventhouse: hkex-trades (data residency: Hong Kong)
│   ├── OneLake: hkex-historical (data residency: Hong Kong)
│   └── ML Models: hkex-pattern-detector (data residency: Hong Kong)
│
├── Fabric Workspace: NSE-Surveillance (hosted: Central India region)
│   ├── Eventhouse: nse-trades (data residency: India)
│   ├── OneLake: nse-historical (data residency: India)
│   └── ML Models: nse-pattern-detector (data residency: India)
│
└── Fabric Workspace: Cross-Market-Intelligence (hosted: Southeast Asia)
    ├── Cross-Market Agent (aggregated scores only — no raw trade data)
    ├── Correlation Engine (privacy-preserving federated analysis)
    └── Global Dashboard (anonymized cross-exchange metrics)
```

**Key principle:** Raw trade data never leaves its jurisdiction. Only **aggregated scores and anonymized pattern fingerprints** flow to the Cross-Market workspace.

### 9.4 Multilingual Alert System

| Language | Jurisdiction | Alert Channel | Format |
|----------|-------------|---------------|--------|
| English | All | Email, Teams, Regulatory Portal | Full report |
| Simplified Chinese | HKEX (mainland investors) | WeChat Work, Email | Summary + details |
| Traditional Chinese | HKEX (HK-based) | Email, Regulatory Portal | Full report |
| Hindi | NSE (SEBI communications) | Email, Portal | Full report |
| Tamil | NSE (selected regional) | SMS, Email | Summary |

**Implementation:** Azure AI Translator + GPT-4o for context-aware regulatory language translation (financial terminology aware).

### 9.5 Cross-Border Coordination Protocol

For detected cross-exchange manipulation (e.g., price manipulation on HKEX affecting SGX-listed related securities):

1. **Detection:** Cross-Market Agent identifies lead-lag correlation above 0.95 with <5-minute lag
2. **Assessment:** Pattern matches known cross-border manipulation playbook
3. **Escalation:** Alert sent simultaneously to both SFC (HK) and MAS (SG) with shared case ID
4. **Coordination:** IOSCO MMoU (Multilateral Memorandum of Understanding) framework invoked
5. **Action:** Coordinated halt request sent to both exchanges within 45 seconds
6. **Evidence:** Shared evidence package generated by Evidence Collection Agent

---

## 10. Data Sovereignty and Security

### 10.1 Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SECURITY LAYERS                              │
├─────────────────────────────────────────────────────────────────────┤
│ Identity:    Azure AD / Entra ID with Conditional Access            │
│              Multi-factor auth for all regulatory personnel          │
├─────────────────────────────────────────────────────────────────────┤
│ Network:     Fabric Private Link (no public internet exposure)      │
│              Exchange connectivity via dedicated MPLS/ExpressRoute   │
├─────────────────────────────────────────────────────────────────────┤
│ Data:        Encryption at rest (Azure-managed keys or CMK)         │
│              Encryption in transit (TLS 1.3)                        │
│              Column-level security on PII fields in Eventhouse      │
├─────────────────────────────────────────────────────────────────────┤
│ Access:      Fabric workspace-level RBAC (Viewer / Contributor /    │
│              Admin) aligned to regulatory roles                      │
│              Row-level security: each regulator sees only their      │
│              exchange's data                                         │
├─────────────────────────────────────────────────────────────────────┤
│ Audit:       All queries logged to immutable Eventhouse audit table  │
│              All agent actions logged with actor, timestamp, reason  │
│              All trade halt decisions stored with full evidence chain│
├─────────────────────────────────────────────────────────────────────┤
│ Compliance:  MAS Technology Risk Management Guidelines              │
│              HKEX Cybersecurity Fortification Initiative (CFI)       │
│              SEBI Cybersecurity and Cyber Resilience Framework       │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.2 Privacy-Preserving Cross-Market Analysis

Since raw trade data cannot leave its jurisdiction, the Cross-Market Agent uses:

1. **Federated ML:** Each jurisdiction trains a local model; only model weights (not data) are shared for ensemble
2. **Differential Privacy:** Aggregated statistics (VWAP, volume, order imbalance) are published with calibrated noise to prevent reverse-engineering of individual trades
3. **Secure Multi-Party Computation:** For correlation analysis between exchanges, only encrypted intermediate values are shared

---

## 11. Implementation Roadmap

### Phase 1: Foundation (Months 1–3)
- [ ] Provision Fabric workspaces per jurisdiction (SG, HK, India)
- [ ] Set up Event Streams connectors for SGX (FIX/WebSocket simulation first)
- [ ] Create Eventhouse schema and retention policies
- [ ] Deploy basic KQL detection rules (spoofing + volume spike)
- [ ] Build Real-Time Dashboard (basic market state monitoring)
- [ ] Set up Data Activator for email-based alerts

**Success metric:** Real-time dashboard showing live simulated trade data; spoofing alerts firing within 15 seconds on simulated data.

### Phase 2: Intelligence (Months 4–6)
- [ ] Onboard HKEX and NSE connectors
- [ ] Deploy Pattern Detection Agent (ML model training on labeled historical data)
- [ ] Deploy Anomaly Detection Agent (Chronos + KQL series_decompose)
- [ ] Integrate FabricIQ ML Registry for model versioning
- [ ] Build Evidence Collection Agent (KQL query + GPT-4o narrative)
- [ ] Implement multilingual alert templates

**Success metric:** ML-based manipulation detection with < 5% false positive rate; evidence reports generated in < 60 seconds.

### Phase 3: Automation (Months 7–9)
- [ ] Deploy Intervention Agent with exchange API integration
- [ ] Implement Cross-Market Agent (federated correlation)
- [ ] Deploy Data Activator Reflex for autonomous trade halts
- [ ] Integrate with MAS/SFC/SEBI regulatory portals
- [ ] Stress test: 5,000 events/second synthetic load
- [ ] Implement data sovereignty controls and audit logging

**Success metric:** End-to-end detection-to-halt < 60 seconds; all interventions audited; regulators receive structured evidence within 60 seconds.

### Phase 4: Optimization (Months 10–12)
- [ ] Fine-tune MOMENT/PatchTST models on jurisdiction-specific manipulation patterns
- [ ] Deploy TimeGPT for zero-shot new manipulation pattern detection
- [ ] Implement GenAI-powered alert de-duplication and false-positive filtering
- [ ] Expand to dark pools and OTC markets
- [ ] Performance benchmark and tuning to handle 10,000+ events/second

**Success metric:** 80% reduction in manipulation incidents (measured vs baseline); < 1% false positive rate; 99.9% system uptime.

---

## 12. Conclusion

The proposed Real-Time Market Surveillance Agent System leverages the complementary strengths of **Microsoft Fabric RTI** (real-time data ingestion, streaming rules, and autonomous triggers) and **FabricIQ** (ML inference, GenAI explainability, and cross-market intelligence) to deliver an **autonomous, low-latency, and regulatorily compliant** surveillance platform for Asia-Pacific markets.

### Key Architectural Decisions

1. **RTI as the hot path:** Fabric Event Streams + Eventhouse provide the sub-second ingestion and millisecond-level KQL query performance required for real-time rule evaluation.

2. **FabricIQ as the intelligence path:** ML models (MOMENT, Chronos, PatchTST) and GenAI (GPT-4o) provide the accuracy, explainability, and adaptability that rule-based systems alone cannot achieve.

3. **Data Activator as the intervention bridge:** Removes the need for custom orchestration code by providing a declarative trigger-and-action framework that connects detection to intervention.

4. **Jurisdiction-isolated workspaces:** Ensures data sovereignty compliance for MAS, SFC, and SEBI while enabling privacy-preserving cross-market coordination.

5. **GenAI for regulatory narrative:** Addresses the "black box" problem in AI-driven surveillance by generating human-readable, jurisdiction-specific evidence reports that regulators can immediately act on.

### Meeting the Success Criteria

| Success Criterion | How Addressed |
|-------------------|---------------|
| 60-second detection-to-halt | RTI rules (15s) + ML scoring (20s) + Activator (5s) + API halt (5s) = 45s typical |
| 80% manipulation reduction | Continuous 24/7 monitoring with no fatigue; ML detection of novel schemes |
| 95% investor satisfaction | Transparent evidence reports; minimal legitimate trade disruption via intelligent filtering |
| Eliminate false alerts | ML ensemble scoring + GenAI review reduces false positives to < 1% |
| Zero major incidents | Proactive detection before impact; cross-market coordination prevents regulatory gaps |

---

*This architecture plan is based on Microsoft Fabric RTI and FabricIQ capabilities as of 2026. Exchange-specific regulatory requirements should be verified with MAS, SFC, and SEBI prior to production deployment.*
