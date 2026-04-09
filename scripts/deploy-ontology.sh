#!/usr/bin/env bash
# Deploy ontology to FabricIQ via REST API
set -euo pipefail

WS_ID="${1:?Usage: deploy-ontology.sh <workspace-id>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)

# Convert RDF to Fabric ontology JSON definition
# The Fabric API expects a specific JSON structure, not RDF/OWL
DEFINITION_JSON=$(python3 -c "
import json, base64, xml.etree.ElementTree as ET

# Parse the RDF
tree = ET.parse('${SCRIPT_DIR}/../ontology/market-surveillance.rdf')
root = tree.getroot()
ns = {
    'owl': 'http://www.w3.org/2002/07/owl#',
    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'ont': 'http://example.org/ontology/market-surveillance/',
    'xsd': 'http://www.w3.org/2001/XMLSchema#',
}

# Extract entity types
entity_types = []
for cls in root.findall('.//owl:Class', ns):
    about = cls.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '')
    label_el = cls.find('rdfs:label', ns)
    comment_el = cls.find('rdfs:comment', ns)
    icon_el = cls.find('ont:icon', ns)
    color_el = cls.find('ont:color', ns)

    name = label_el.text if label_el is not None else about.split('/')[-1]
    entity_types.append({
        'name': name,
        'description': comment_el.text if comment_el is not None else '',
        'icon': icon_el.text if icon_el is not None else '',
        'color': color_el.text if color_el is not None else '#0078D4',
        'properties': [],
    })

# Extract data properties and attach to entity types
entity_map = {e['name']: e for e in entity_types}
for prop in root.findall('.//owl:DatatypeProperty', ns):
    label_el = prop.find('rdfs:label', ns)
    domain_el = prop.find('rdfs:domain', ns)
    prop_type_el = prop.find('ont:propertyType', ns)
    is_id_el = prop.find('ont:isIdentifier', ns)

    if label_el is not None and domain_el is not None:
        domain_ref = domain_el.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
        entity_name = domain_ref.split('/')[-1]
        if entity_name in entity_map:
            entity_map[entity_name]['properties'].append({
                'name': label_el.text,
                'type': prop_type_el.text if prop_type_el is not None else 'string',
                'isIdentifier': is_id_el is not None and is_id_el.text == 'true',
            })

# Extract relationships
relationships = []
for prop in root.findall('.//owl:ObjectProperty', ns):
    label_el = prop.find('rdfs:label', ns)
    domain_el = prop.find('rdfs:domain', ns)
    range_el = prop.find('rdfs:range', ns)

    if label_el is not None and domain_el is not None and range_el is not None:
        domain_ref = domain_el.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
        range_ref = range_el.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
        relationships.append({
            'name': label_el.text,
            'fromEntityType': domain_ref.split('/')[-1],
            'toEntityType': range_ref.split('/')[-1],
        })

# Build Fabric ontology definition
ontology_def = {
    'entityTypes': entity_types,
    'relationships': relationships,
}

# Platform part
platform = {
    'schemaVersion': '1.0',
    'metadata': {
        'type': 'Ontology',
        'displayName': 'Market Surveillance',
    }
}

# Build the API payload
payload = {
    'displayName': 'Market Surveillance',
    'description': 'Real-time market manipulation detection with beneficial ownership resolution',
    'definition': {
        'parts': [
            {
                'path': '.platform',
                'payload': base64.b64encode(json.dumps(platform).encode()).decode(),
                'payloadType': 'InlineBase64',
            },
            {
                'path': 'definition.json',
                'payload': base64.b64encode(json.dumps(ontology_def).encode()).decode(),
                'payloadType': 'InlineBase64',
            },
        ]
    }
}

print(json.dumps(payload))
")

echo "Creating FabricIQ ontology..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "https://api.fabric.microsoft.com/v1/workspaces/${WS_ID}/ontologies" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${DEFINITION_JSON}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "202" ]]; then
  echo "✓ Ontology created"
elif echo "$BODY" | grep -q "AlreadyInUse\|already exists"; then
  echo "✓ Ontology already exists"
else
  echo "⚠ Ontology creation response (HTTP $HTTP_CODE): $BODY"
  echo "  This may require manual import via Fabric portal if the API is not yet available in this tenant."
fi
