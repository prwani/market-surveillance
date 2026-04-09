#!/usr/bin/env bash
# Set up ontology graph tables (ENTITIES + RELATIONSHIPS) and populate with
# broker ownership chains, instrument listings, and regulatory data.
set -euo pipefail

KQL_URI="${1:?Usage: setup-ontology.sh <kql-uri> [database-name]}"
KQL_DB="${2:-surveillance}"

echo "Setting up ontology graph in ${KQL_DB}..."
echo "  KQL URI: ${KQL_URI}"

TOKEN=$(az account get-access-token --resource "https://kusto.kusto.windows.net" --query accessToken -o tsv)

run_kql() {
  local name="$1"
  local query="$2"
  echo "  ${name}..."
  RESPONSE=$(curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"db\":\"${KQL_DB}\",\"csl\":$(echo "$query" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    -w "\n%{http_code}")
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "    ✗ Failed (HTTP ${HTTP_CODE})" >&2
    echo "    $(echo "$RESPONSE" | head -1)" >&2
    return 1
  fi
  echo "    ✓ OK"
}

# ── Create tables ─────────────────────────────────────────────────────────────
echo ""
echo "Creating ontology tables..."

run_kql "ENTITIES table" \
  ".create-merge table ENTITIES (entity_id: string, entity_type: string, display_name: string, properties: dynamic, created_at: datetime)"

run_kql "RELATIONSHIPS table" \
  ".create-merge table RELATIONSHIPS (source_id: string, target_id: string, relationship_type: string, properties: dynamic, created_at: datetime)"

# ── Ingestion mappings ────────────────────────────────────────────────────────
echo ""
echo "Creating ingestion mappings..."

run_kql "ENTITIES mapping" \
  ".create-or-alter table ENTITIES ingestion json mapping 'entities_json_mapping' '[{\"column\":\"entity_id\",\"path\":\"$.entity_id\"},{\"column\":\"entity_type\",\"path\":\"$.entity_type\"},{\"column\":\"display_name\",\"path\":\"$.display_name\"},{\"column\":\"properties\",\"path\":\"$.properties\"},{\"column\":\"created_at\",\"path\":\"$.created_at\"}]'"

run_kql "RELATIONSHIPS mapping" \
  ".create-or-alter table RELATIONSHIPS ingestion json mapping 'relationships_json_mapping' '[{\"column\":\"source_id\",\"path\":\"$.source_id\"},{\"column\":\"target_id\",\"path\":\"$.target_id\"},{\"column\":\"relationship_type\",\"path\":\"$.relationship_type\"},{\"column\":\"properties\",\"path\":\"$.properties\"},{\"column\":\"created_at\",\"path\":\"$.created_at\"}]'"

# ── Populate entities ─────────────────────────────────────────────────────────
echo ""
echo "Populating ENTITIES..."

TS="2026-04-09T00:00:00Z"

# SGX Brokers (10)
run_kql "SGX brokers" ".ingest inline into table ENTITIES <|
BROKER_SGX_001	broker	SGX Broker 001	{}	${TS}
BROKER_SGX_002	broker	SGX Broker 002	{}	${TS}
BROKER_SGX_003	broker	SGX Broker 003	{}	${TS}
BROKER_SGX_004	broker	SGX Broker 004	{}	${TS}
BROKER_SGX_005	broker	SGX Broker 005	{}	${TS}
BROKER_SGX_006	broker	SGX Broker 006	{}	${TS}
BROKER_SGX_007	broker	SGX Broker 007	{}	${TS}
BROKER_SGX_008	broker	SGX Broker 008	{}	${TS}
BROKER_SGX_009	broker	SGX Broker 009	{}	${TS}
BROKER_SGX_010	broker	SGX Broker 010	{}	${TS}"

# HKEX Brokers (10)
run_kql "HKEX brokers" ".ingest inline into table ENTITIES <|
BROKER_HKEX_001	broker	HKEX Broker 001	{}	${TS}
BROKER_HKEX_002	broker	HKEX Broker 002	{}	${TS}
BROKER_HKEX_003	broker	HKEX Broker 003	{}	${TS}
BROKER_HKEX_004	broker	HKEX Broker 004	{}	${TS}
BROKER_HKEX_005	broker	HKEX Broker 005	{}	${TS}
BROKER_HKEX_006	broker	HKEX Broker 006	{}	${TS}
BROKER_HKEX_007	broker	HKEX Broker 007	{}	${TS}
BROKER_HKEX_008	broker	HKEX Broker 008	{}	${TS}
BROKER_HKEX_009	broker	HKEX Broker 009	{}	${TS}
BROKER_HKEX_010	broker	HKEX Broker 010	{}	${TS}"

# NSE Brokers (10)
run_kql "NSE brokers" ".ingest inline into table ENTITIES <|
BROKER_NSE_001	broker	NSE Broker 001	{}	${TS}
BROKER_NSE_002	broker	NSE Broker 002	{}	${TS}
BROKER_NSE_003	broker	NSE Broker 003	{}	${TS}
BROKER_NSE_004	broker	NSE Broker 004	{}	${TS}
BROKER_NSE_005	broker	NSE Broker 005	{}	${TS}
BROKER_NSE_006	broker	NSE Broker 006	{}	${TS}
BROKER_NSE_007	broker	NSE Broker 007	{}	${TS}
BROKER_NSE_008	broker	NSE Broker 008	{}	${TS}
BROKER_NSE_009	broker	NSE Broker 009	{}	${TS}
BROKER_NSE_010	broker	NSE Broker 010	{}	${TS}"

# Funds (5)
run_kql "Funds" ".ingest inline into table ENTITIES <|
FUND_ALPHA_SG	fund	Alpha Fund Singapore	{\"jurisdiction\":\"SG\"}	${TS}
FUND_BETA_HK	fund	Beta Capital Hong Kong	{\"jurisdiction\":\"HK\"}	${TS}
FUND_GAMMA_IN	fund	Gamma Investments India	{\"jurisdiction\":\"IN\"}	${TS}
FUND_DELTA_GLOBAL	fund	Delta Global Partners	{\"jurisdiction\":\"SG\"}	${TS}
FUND_EPSILON_ASIA	fund	Epsilon Asia Fund	{\"jurisdiction\":\"HK\"}	${TS}"

# Holding companies (3)
run_kql "Holding companies" ".ingest inline into table ENTITIES <|
HOLDING_ASIA_LTD	holding	Asia Holdings Ltd	{\"jurisdiction\":\"SG\",\"incorporation\":\"2015\"}	${TS}
HOLDING_PACIFIC_GRP	holding	Pacific Group Holdings	{\"jurisdiction\":\"HK\",\"incorporation\":\"2012\"}	${TS}
HOLDING_ORIENT_CORP	holding	Orient Corporation	{\"jurisdiction\":\"IN\",\"incorporation\":\"2018\"}	${TS}"

# UBOs (3 persons who control brokers across exchanges)
run_kql "UBOs" ".ingest inline into table ENTITIES <|
UBO_SMITH_001	person	John Smith	{\"nationality\":\"SG\",\"pep\":false}	${TS}
UBO_CHEN_002	person	Wei Chen	{\"nationality\":\"HK\",\"pep\":false}	${TS}
UBO_PATEL_003	person	Rajesh Patel	{\"nationality\":\"IN\",\"pep\":false}	${TS}"

# Exchanges (3)
run_kql "Exchanges" ".ingest inline into table ENTITIES <|
SGX	exchange	Singapore Exchange	{\"timezone\":\"Asia/Singapore\",\"currency\":\"SGD\"}	${TS}
HKEX	exchange	Hong Kong Exchange	{\"timezone\":\"Asia/Hong_Kong\",\"currency\":\"HKD\"}	${TS}
NSE	exchange	National Stock Exchange of India	{\"timezone\":\"Asia/Kolkata\",\"currency\":\"INR\"}	${TS}"

# Instruments
run_kql "Instruments" ".ingest inline into table ENTITIES <|
OCBC	instrument	OCBC Bank	{\"isin\":\"SG1S04926220\",\"sector\":\"Finance\"}	${TS}
DBS	instrument	DBS Group Holdings	{\"isin\":\"SG1L01001701\",\"sector\":\"Finance\"}	${TS}
UOB	instrument	United Overseas Bank	{\"isin\":\"SG1M31001969\",\"sector\":\"Finance\"}	${TS}
0700.HK	instrument	Tencent Holdings	{\"isin\":\"KYG875721634\",\"sector\":\"Technology\"}	${TS}
9988.HK	instrument	Alibaba Group	{\"isin\":\"KYG017191142\",\"sector\":\"Technology\"}	${TS}
0005.HK	instrument	HSBC Holdings	{\"isin\":\"GB0005405286\",\"sector\":\"Finance\"}	${TS}
RELIANCE	instrument	Reliance Industries	{\"isin\":\"INE002A01018\",\"sector\":\"Energy\"}	${TS}
TCS	instrument	Tata Consultancy Services	{\"isin\":\"INE467B01029\",\"sector\":\"Technology\"}	${TS}
INFY	instrument	Infosys Limited	{\"isin\":\"INE009A01021\",\"sector\":\"Technology\"}	${TS}"

# Regulators
run_kql "Regulators" ".ingest inline into table ENTITIES <|
MAS	regulator	Monetary Authority of Singapore	{\"country\":\"SG\"}	${TS}
SFC	regulator	Securities and Futures Commission	{\"country\":\"HK\"}	${TS}
SEBI	regulator	Securities and Exchange Board of India	{\"country\":\"IN\"}	${TS}"

# Regulations
run_kql "Regulations" ".ingest inline into table ENTITIES <|
REG_MAS_SPOOFING	regulation	MAS Notice on Market Manipulation (Spoofing)	{\"alert_types\":[\"SPOOFING\"],\"penalty\":\"up to SGD 250,000\"}	${TS}
REG_MAS_LAYERING	regulation	MAS Notice on Market Manipulation (Layering)	{\"alert_types\":[\"LAYERING\"],\"penalty\":\"up to SGD 250,000\"}	${TS}
REG_MAS_WASH	regulation	MAS Securities Act s197 (Wash Trading)	{\"alert_types\":[\"WASH_TRADING\"],\"penalty\":\"up to SGD 250,000 or 7 years\"}	${TS}
REG_SFC_SPOOFING	regulation	SFC Code s274 (Spoofing)	{\"alert_types\":[\"SPOOFING\"],\"penalty\":\"up to HKD 10M\"}	${TS}
REG_SFC_LAYERING	regulation	SFC Code s274 (Layering)	{\"alert_types\":[\"LAYERING\"],\"penalty\":\"up to HKD 10M\"}	${TS}
REG_SFC_WASH	regulation	SFC Securities Ordinance s295 (Wash Trading)	{\"alert_types\":[\"WASH_TRADING\"],\"penalty\":\"up to HKD 10M or 10 years\"}	${TS}
REG_SEBI_SPOOFING	regulation	SEBI PFUTP Reg 4(2)(a) (Spoofing)	{\"alert_types\":[\"SPOOFING\"],\"penalty\":\"up to INR 25 crore\"}	${TS}
REG_SEBI_LAYERING	regulation	SEBI PFUTP Reg 4(2)(a) (Layering)	{\"alert_types\":[\"LAYERING\"],\"penalty\":\"up to INR 25 crore\"}	${TS}
REG_SEBI_WASH	regulation	SEBI PFUTP Reg 4(2)(b) (Wash Trading)	{\"alert_types\":[\"WASH_TRADING\"],\"penalty\":\"up to INR 25 crore\"}	${TS}"


# ── Populate relationships ────────────────────────────────────────────────────
echo ""
echo "Populating RELATIONSHIPS..."

# Broker → Fund (parent_entity): each fund has 2-4 brokers across exchanges
run_kql "Broker→Fund links" ".ingest inline into table RELATIONSHIPS <|
BROKER_SGX_001	FUND_ALPHA_SG	parent_entity	{}	${TS}
BROKER_SGX_002	FUND_ALPHA_SG	parent_entity	{}	${TS}
BROKER_HKEX_001	FUND_ALPHA_SG	parent_entity	{}	${TS}
BROKER_SGX_003	FUND_BETA_HK	parent_entity	{}	${TS}
BROKER_HKEX_002	FUND_BETA_HK	parent_entity	{}	${TS}
BROKER_HKEX_003	FUND_BETA_HK	parent_entity	{}	${TS}
BROKER_NSE_001	FUND_GAMMA_IN	parent_entity	{}	${TS}
BROKER_NSE_002	FUND_GAMMA_IN	parent_entity	{}	${TS}
BROKER_SGX_004	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_HKEX_004	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_NSE_003	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_SGX_005	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_HKEX_005	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_NSE_004	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_SGX_006	FUND_ALPHA_SG	parent_entity	{}	${TS}
BROKER_HKEX_006	FUND_BETA_HK	parent_entity	{}	${TS}
BROKER_NSE_005	FUND_GAMMA_IN	parent_entity	{}	${TS}
BROKER_SGX_007	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_HKEX_007	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_NSE_006	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}"

# Fund → Holding (parent_entity)
run_kql "Fund→Holding links" ".ingest inline into table RELATIONSHIPS <|
FUND_ALPHA_SG	HOLDING_ASIA_LTD	parent_entity	{}	${TS}
FUND_BETA_HK	HOLDING_PACIFIC_GRP	parent_entity	{}	${TS}
FUND_GAMMA_IN	HOLDING_ORIENT_CORP	parent_entity	{}	${TS}
FUND_DELTA_GLOBAL	HOLDING_ASIA_LTD	parent_entity	{}	${TS}
FUND_EPSILON_ASIA	HOLDING_PACIFIC_GRP	parent_entity	{}	${TS}"

# Holding → UBO (beneficial_owner)
# Key: UBO_SMITH_001 controls HOLDING_ASIA_LTD → controls brokers on SGX+HKEX+NSE
# Key: UBO_CHEN_002 controls HOLDING_PACIFIC_GRP → controls brokers on HKEX+SGX
# Key: UBO_PATEL_003 controls HOLDING_ORIENT_CORP → controls brokers on NSE
run_kql "Holding→UBO links" ".ingest inline into table RELATIONSHIPS <|
HOLDING_ASIA_LTD	UBO_SMITH_001	beneficial_owner	{\"ownership_pct\":85}	${TS}
HOLDING_PACIFIC_GRP	UBO_CHEN_002	beneficial_owner	{\"ownership_pct\":72}	${TS}
HOLDING_ORIENT_CORP	UBO_PATEL_003	beneficial_owner	{\"ownership_pct\":91}	${TS}"

# Instrument → Exchange (listed_on)
run_kql "Instrument listings" ".ingest inline into table RELATIONSHIPS <|
OCBC	SGX	listed_on	{}	${TS}
DBS	SGX	listed_on	{}	${TS}
UOB	SGX	listed_on	{}	${TS}
0700.HK	HKEX	listed_on	{}	${TS}
9988.HK	HKEX	listed_on	{}	${TS}
0005.HK	HKEX	listed_on	{}	${TS}
RELIANCE	NSE	listed_on	{}	${TS}
TCS	NSE	listed_on	{}	${TS}
INFY	NSE	listed_on	{}	${TS}"

# Regulator → Exchange (regulates)
run_kql "Regulatory links" ".ingest inline into table RELATIONSHIPS <|
MAS	SGX	regulates	{}	${TS}
SFC	HKEX	regulates	{}	${TS}
SEBI	NSE	regulates	{}	${TS}"

# Regulator → Regulation (enforces)
run_kql "Regulation enforcement" ".ingest inline into table RELATIONSHIPS <|
MAS	REG_MAS_SPOOFING	enforces	{}	${TS}
MAS	REG_MAS_LAYERING	enforces	{}	${TS}
MAS	REG_MAS_WASH	enforces	{}	${TS}
SFC	REG_SFC_SPOOFING	enforces	{}	${TS}
SFC	REG_SFC_LAYERING	enforces	{}	${TS}
SFC	REG_SFC_WASH	enforces	{}	${TS}
SEBI	REG_SEBI_SPOOFING	enforces	{}	${TS}
SEBI	REG_SEBI_LAYERING	enforces	{}	${TS}
SEBI	REG_SEBI_WASH	enforces	{}	${TS}"

# Remaining brokers without fund assignments (direct UBO links for simpler chains)
run_kql "Direct broker links" ".ingest inline into table RELATIONSHIPS <|
BROKER_SGX_008	FUND_ALPHA_SG	parent_entity	{}	${TS}
BROKER_SGX_009	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_SGX_010	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_HKEX_008	FUND_BETA_HK	parent_entity	{}	${TS}
BROKER_HKEX_009	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_HKEX_010	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_NSE_007	FUND_GAMMA_IN	parent_entity	{}	${TS}
BROKER_NSE_008	FUND_DELTA_GLOBAL	parent_entity	{}	${TS}
BROKER_NSE_009	FUND_EPSILON_ASIA	parent_entity	{}	${TS}
BROKER_NSE_010	FUND_ALPHA_SG	parent_entity	{}	${TS}"


# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo " Ontology Graph Setup Complete"
echo "═══════════════════════════════════════════════════════"
echo " ENTITIES table:"
echo "   30 brokers (10 per exchange: SGX, HKEX, NSE)"
echo "    5 funds"
echo "    3 holding companies"
echo "    3 UBOs (persons)"
echo "    3 exchanges"
echo "    9 instruments"
echo "    3 regulators"
echo "    9 regulations"
echo ""
echo " RELATIONSHIPS table:"
echo "   30 broker → fund (parent_entity)"
echo "    5 fund → holding (parent_entity)"
echo "    3 holding → UBO (beneficial_owner)"
echo "    9 instrument → exchange (listed_on)"
echo "    3 regulator → exchange (regulates)"
echo "    9 regulator → regulation (enforces)"
echo ""
echo " Cross-market UBO chains:"
echo "   UBO_SMITH_001 → HOLDING_ASIA_LTD → FUND_ALPHA_SG → SGX/HKEX/NSE brokers"
echo "   UBO_SMITH_001 → HOLDING_ASIA_LTD → FUND_DELTA_GLOBAL → SGX/HKEX/NSE brokers"
echo "   UBO_CHEN_002  → HOLDING_PACIFIC_GRP → FUND_BETA_HK → SGX/HKEX brokers"
echo "   UBO_CHEN_002  → HOLDING_PACIFIC_GRP → FUND_EPSILON_ASIA → SGX/HKEX/NSE brokers"
echo "   UBO_PATEL_003 → HOLDING_ORIENT_CORP → FUND_GAMMA_IN → NSE brokers"
echo "═══════════════════════════════════════════════════════"
