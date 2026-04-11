#!/usr/bin/env python3
"""Build a Fabric ontology create payload from the repo RDF file."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ONTOLOGY_DISPLAY_NAME = "Market_Surveillance"
ONTOLOGY_DESCRIPTION = (
    "Real-time market manipulation detection with beneficial ownership resolution"
)

_NS = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
_RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
_XSD_TO_FABRIC = {
    "string": "String",
    "boolean": "Boolean",
    "dateTime": "DateTime",
    "integer": "BigInt",
    "int": "BigInt",
    "long": "BigInt",
    "decimal": "Double",
    "double": "Double",
    "float": "Double",
}


def _stable_bigint(key: str) -> str:
    raw = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    value = raw & ((1 << 63) - 1)
    return str(value or 1)


def _local_name(uri: str) -> str:
    value = uri.rstrip("/#")
    if "#" in value:
        return value.rsplit("#", 1)[-1]
    return value.rsplit("/", 1)[-1]


def _valid_name(raw_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", raw_name or "")
    if not cleaned:
        cleaned = "Value"
    if not cleaned[0].isalpha():
        cleaned = f"N{cleaned}"
    return cleaned[:128]


def _fabric_type(range_uri: str | None) -> str:
    if not range_uri:
        return "String"
    xsd_name = _local_name(range_uri)
    return _XSD_TO_FABRIC.get(xsd_name, "String")


def _encode_part(payload: object) -> str:
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")


def _entity_parts(entity_uris: list[str], root: ET.Element) -> list[dict[str, object]]:
    entity_index: dict[str, dict[str, object]] = {}
    for entity_uri in entity_uris:
        entity_index[entity_uri] = {
            "id": _stable_bigint(f"entity:{entity_uri}"),
            "name": _valid_name(_local_name(entity_uri)),
            "properties": [],
        }

    for prop in root.findall(".//owl:DatatypeProperty", _NS):
        prop_uri = prop.get(_RDF_ABOUT)
        domain = prop.find("rdfs:domain", _NS)
        if not prop_uri or domain is None:
            continue

        domain_uri = domain.get(_RDF_RESOURCE)
        if not domain_uri or domain_uri not in entity_index:
            continue

        range_el = prop.find("rdfs:range", _NS)
        identifier_el = prop.find(
            "{http://example.org/ontology/market-surveillance/}isIdentifier"
        )
        entity_index[domain_uri]["properties"].append(
            {
                "id": _stable_bigint(f"property:{domain_uri}:{prop_uri}"),
                "name": _valid_name(_local_name(prop_uri)),
                "valueType": _fabric_type(
                    range_el.get(_RDF_RESOURCE) if range_el is not None else None
                ),
                "isIdentifier": (
                    identifier_el is not None
                    and (identifier_el.text or "").strip().lower() == "true"
                ),
            }
        )

    parts: list[dict[str, object]] = []
    for entity_uri in entity_uris:
        entity = entity_index[entity_uri]
        properties = entity["properties"]  # type: ignore[assignment]
        identifier_ids = [prop["id"] for prop in properties if prop["isIdentifier"]]
        display_name_id = next(
            (
                prop["id"]
                for prop in properties
                if prop["name"].lower() == "name"
                or prop["name"].lower().endswith("name")
            ),
            identifier_ids[0] if identifier_ids else properties[0]["id"],
        )
        entity_definition = {
            "id": entity["id"],
            "namespace": "usertypes",
            "baseEntityTypeId": None,
            "name": entity["name"],
            "entityIdParts": identifier_ids or [display_name_id],
            "displayNamePropertyId": display_name_id,
            "namespaceType": "Custom",
            "visibility": "Visible",
            "properties": [
                {
                    "id": prop["id"],
                    "name": prop["name"],
                    "redefines": None,
                    "baseTypeNamespaceType": None,
                    "valueType": prop["valueType"],
                }
                for prop in properties
            ],
        }
        parts.append(
            {
                "path": f"EntityTypes/{entity['id']}/definition.json",
                "payload": _encode_part(entity_definition),
                "payloadType": "InlineBase64",
            }
        )

    return parts


def _relationship_parts(
    entity_uris: list[str], root: ET.Element
) -> list[dict[str, object]]:
    entity_ids = {
        entity_uri: _stable_bigint(f"entity:{entity_uri}") for entity_uri in entity_uris
    }

    parts: list[dict[str, object]] = []
    seen_relationships: set[str] = set()
    for relation in root.findall(".//owl:ObjectProperty", _NS):
        relation_uri = relation.get(_RDF_ABOUT)
        domain = relation.find("rdfs:domain", _NS)
        range_el = relation.find("rdfs:range", _NS)
        if not relation_uri or domain is None or range_el is None:
            continue

        domain_uri = domain.get(_RDF_RESOURCE)
        range_uri = range_el.get(_RDF_RESOURCE)
        if (
            not domain_uri
            or not range_uri
            or domain_uri not in entity_ids
            or range_uri not in entity_ids
            or relation_uri in seen_relationships
        ):
            continue

        seen_relationships.add(relation_uri)
        relationship_id = _stable_bigint(f"relationship:{relation_uri}")
        relationship_definition = {
            "id": relationship_id,
            "namespace": "usertypes",
            "name": _valid_name(_local_name(relation_uri)),
            "namespaceType": "Custom",
            "source": {"entityTypeId": entity_ids[domain_uri]},
            "target": {"entityTypeId": entity_ids[range_uri]},
        }
        parts.append(
            {
                "path": f"RelationshipTypes/{relationship_id}/definition.json",
                "payload": _encode_part(relationship_definition),
                "payloadType": "InlineBase64",
            }
        )

    return parts


def build_create_request(
    rdf_path: Path,
    display_name: str = ONTOLOGY_DISPLAY_NAME,
    description: str = ONTOLOGY_DESCRIPTION,
) -> dict[str, object]:
    tree = ET.parse(rdf_path)
    root = tree.getroot()

    entity_uris = sorted(
        {
            class_el.get(_RDF_ABOUT)
            for class_el in root.findall(".//owl:Class", _NS)
            if class_el.get(_RDF_ABOUT)
        },
        key=lambda uri: _valid_name(_local_name(uri)),
    )

    parts: list[dict[str, object]] = [
        {
            "path": ".platform",
            "payload": _encode_part(
                {"metadata": {"type": "Ontology", "displayName": display_name}}
            ),
            "payloadType": "InlineBase64",
        },
        {
            "path": "definition.json",
            "payload": _encode_part({}),
            "payloadType": "InlineBase64",
        },
    ]
    parts.extend(_entity_parts(entity_uris, root))
    parts.extend(_relationship_parts(entity_uris, root))

    return {
        "displayName": display_name,
        "description": description,
        "definition": {"parts": parts},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rdf", required=True, type=Path)
    parser.add_argument("--display-name", default=ONTOLOGY_DISPLAY_NAME)
    parser.add_argument("--description", default=ONTOLOGY_DESCRIPTION)
    args = parser.parse_args()

    payload = build_create_request(
        rdf_path=args.rdf,
        display_name=args.display_name,
        description=args.description,
    )
    print(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
