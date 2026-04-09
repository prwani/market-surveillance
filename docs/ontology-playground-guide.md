# Using Ontology Playground with FabricIQ

This guide shows how to design your ontology schema in
[Ontology Playground](https://microsoft.github.io/Ontology-Playground/),
then connect it to live Eventhouse data via FabricIQ.

## Understanding the Two Layers

| Layer | Tool | What It Contains |
|-------|------|-----------------|
| **Schema** (structure) | Ontology Playground | Entity types, properties, relationships — no data |
| **Schema + Data** (runtime) | FabricIQ | Ontology schema mapped onto live Eventhouse tables |

**Ontology Playground** is for designing and visualizing the **graph schema** —
what types of entities exist, what properties they have, and how they relate.
It works entirely with RDF/OWL files. No Azure or Fabric connection needed.

**FabricIQ** combines the schema with your **live Eventhouse data** —
enabling natural language queries like "Which brokers share a UBO?" that
traverse both the ontology graph and actual trade data.

## Step 1: Visualize the Market Surveillance Ontology

1. Open [Ontology Playground](https://microsoft.github.io/Ontology-Playground/)
2. Click **Import** (top-right)
3. Select **Import RDF/OWL file**
4. Upload `ontology/market-surveillance.rdf` from this repo
5. The graph renders immediately — you'll see:

```
                    👤 Beneficial Owner
                         ▲
                    controlledBy
                         │
            🏢 Holding Company
                 ▲          ▲
            managedBy    managedBy
                 │          │
         💼 Fund ←──────── 💼 Fund
              ▲                ▲
          ownedBy          ownedBy
              │                │
     🏛️ Broker ──linkedTo── 🏛️ Broker
         │    │                │
    executedBy │          executedBy
         │    │                │
     💳 Trade  │           💳 Trade
         │    │
  tradedInstrument
         │
     📈 Instrument ──listedOn── 🏦 Exchange ──regulatedBy── ⚖️ Regulator
                                                                  │
                                                              enforces
                                                                  │
                                                             📋 Regulation
```

6. Click any node to see its properties (e.g., click **Broker** to see
   `brokerId`, `name`, `jurisdiction`)
7. Click any edge to see cardinality (e.g., `ownedBy: many:1`)

## Step 2: Explore Entity Types

The ontology defines **11 entity types** relevant to market surveillance:

| Entity | Icon | Purpose |
|--------|------|---------|
| Broker | 🏛️ | Trading firm registered with an exchange |
| Fund | 💼 | Investment fund entity |
| HoldingCompany | 🏢 | Parent holding company |
| BeneficialOwner | 👤 | Ultimate beneficial owner (UBO) |
| Exchange | 🏦 | Securities exchange (SGX, HKEX, NSE) |
| Instrument | 📈 | Tradable security |
| Regulator | ⚖️ | Financial regulatory authority (MAS, SFC, SEBI) |
| Regulation | 📋 | Regulatory rule or statute |
| Trade | 💳 | Executed trade transaction |
| Alert | 🚨 | Surveillance alert |
| InterventionCase | 📁 | Regulatory intervention case |

## Step 3: Edit and Extend the Ontology

1. In Ontology Playground, click **Designer** (top navigation)
2. The imported ontology appears in the visual editor
3. You can:
   - **Add entity types**: e.g., `DarkPool`, `Derivative`, `MarketMaker`
   - **Add properties**: e.g., `Broker.amlRiskScore`, `Trade.venue`
   - **Add relationships**: e.g., `Instrument --hasDerivedProduct--> Instrument`
4. Changes are reflected in the live graph preview

### Example: Adding a Dark Pool entity

1. Click **+ Add Entity Type**
2. Name: `DarkPool`, Icon: 🌑, Color: `#333333`
3. Add properties: `poolId` (string, identifier), `operator` (string)
4. Add relationship: `Trade --executedOn--> DarkPool` (many:1)
5. Export the updated RDF

## Step 4: Export Updated Ontology

1. Click **Export** → **RDF/XML**
2. Save as `market-surveillance-v2.rdf`
3. This file is ready to import into FabricIQ

## Step 5: Import into FabricIQ (Schema → Data Mapping)

This is where the schema meets your live data. FabricIQ takes the RDF
ontology (entity types and relationships) and maps each class to an
Eventhouse table, enabling natural language queries over real data.

### Via Fabric Portal

1. Open [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Navigate to your workspace: `mktsurveil-surveillance-<env>`
3. Go to **Settings** → **Ontology** (or **IQ** → **Ontology**)
4. Click **Import ontology**
5. Upload `ontology/market-surveillance.rdf`
6. **Map entity types to Eventhouse tables** — this is the key step:

| OWL Class (schema) | Eventhouse Table (data) | Mapping Notes |
|---------------------|------------------------|---------------|
| `Trade` | `TRADES` | 1:1 — each row is a Trade instance |
| `Broker` | `ENTITIES` | Filter: `entity_type == "broker"` |
| `Fund` | `ENTITIES` | Filter: `entity_type == "fund"` |
| `HoldingCompany` | `ENTITIES` | Filter: `entity_type == "holding"` |
| `BeneficialOwner` | `ENTITIES` | Filter: `entity_type == "person"` |
| `Exchange` | `ENTITIES` | Filter: `entity_type == "exchange"` |
| `Instrument` | `ENTITIES` | Filter: `entity_type == "instrument"` |
| `Regulator` | `ENTITIES` | Filter: `entity_type == "regulator"` |
| `Regulation` | `ENTITIES` | Filter: `entity_type == "regulation"` |
| `Alert` | `INTERVENTIONS` | Each row is an Alert/Case |
| All relationships | `RELATIONSHIPS` | `relationship_type` column maps to OWL ObjectProperties |

7. Confirm the mapping and save

**After mapping**, FabricIQ knows that:
- A "Broker" is a row in `ENTITIES` where `entity_type == "broker"`
- The "ownedBy" relationship is a row in `RELATIONSHIPS` where `relationship_type == "parent_entity"`
- A "Trade" is a row in `TRADES`

This enables the natural language queries in the next step.

### Via Fabric Notebook

```python
# Upload ontology RDF to FabricIQ programmatically
import requests

TOKEN = ... # Fabric API token
WORKSPACE_ID = "56f1c8c1-3395-43a5-8bab-74244c643306"

with open("ontology/market-surveillance.rdf", "rb") as f:
    rdf_content = f.read()

# Use FabricIQ ontology API (when available)
# This API is currently in preview — check Fabric documentation
# for the latest endpoint
```

## Step 6: Use FabricIQ Natural Language Queries (Schema + Data)

Once the ontology is imported **and mapped to Eventhouse tables**, FabricIQ
enables natural language questions that query your **live data** using the
**ontology schema** as a guide:

| Natural Language Question | How FabricIQ Resolves It |
|--------------------------|--------------------------|
| "Which brokers share a beneficial owner?" | Traverses RELATIONSHIPS: `parent_entity → parent_entity → beneficial_owner` |
| "Show me all trades on SGX for OCBC" | Queries TRADES: `where exchange_id='SGX' and symbol='OCBC'` |
| "Which regulations apply to spoofing in Singapore?" | Joins ENTITIES + RELATIONSHIPS: `Exchange → regulates → Regulator → enforces → Regulation` |
| "Who is the UBO of BROKER_SGX_001?" | Equivalent to KQL function `resolve_ubo("BROKER_SGX_001")` |
| "Find wash trading between related brokers" | Joins TRADES with RELATIONSHIPS for UBO resolution |

**Note:** These queries hit real data in Eventhouse — they are not just schema
exploration. The ontology tells FabricIQ *how* to interpret the tables; the
Eventhouse provides the *data* to query.

## Step 7: Share Your Ontology

### Via Ontology Playground Deep Link

After importing in the Playground, copy the URL — it contains the full
ontology as a shareable link:
```
https://microsoft.github.io/Ontology-Playground/#/catalogue/...
```

### Contributing to the Catalogue

The Ontology Playground supports one-click PRs to add your ontology to the
community catalogue:

1. Sign in with GitHub in the Playground
2. Click **Submit to Catalogue**
3. Fill in metadata (name, domain: Finance, tags)
4. A PR is created automatically on the
   [Ontology-Playground repo](https://github.com/microsoft/Ontology-Playground)

## Files Reference

| File | Description |
|------|-------------|
| `ontology/market-surveillance.rdf` | RDF/OWL ontology (11 classes, 33 properties, 13 relationships) |
| `ontology/metadata.json` | Catalogue metadata (name, domain, tags) |
| `kql/ontology_tables.kql` | KQL table definitions for runtime ontology data |
| `kql/stored_functions.kql` | `resolve_ubo()` and `get_regulations()` KQL functions |

## Learn More

- [Ontology Playground](https://microsoft.github.io/Ontology-Playground/) — try it live
- [Ontology Playground GitHub](https://github.com/microsoft/Ontology-Playground) — source code and examples
- [FabricIQ Ontology Documentation](https://learn.microsoft.com/en-us/fabric/iq/ontology/overview)
- [Finance ontology example](https://github.com/microsoft/Ontology-Playground/tree/main/catalogue/official/finance) — reference pattern
