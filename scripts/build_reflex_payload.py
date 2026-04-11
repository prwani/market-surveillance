#!/usr/bin/env python3
"""Build a valid Fabric Reflex create payload from trigger configuration."""

from __future__ import annotations

import argparse
import base64
import json
import uuid
from pathlib import Path
from typing import Any

TEMPLATE_VERSION = "1.2.2"
ALLOWED_POLLING_FREQUENCIES_MINUTES = {5, 15, 60, 180, 360, 720, 1440}


def validate_polling_frequency(polling_frequency_minutes: int) -> int:
    if polling_frequency_minutes not in ALLOWED_POLLING_FREQUENCIES_MINUTES:
        allowed_values = sorted(ALLOWED_POLLING_FREQUENCIES_MINUTES)
        raise ValueError(
            f"Polling frequency must be one of {allowed_values} minutes. "
            f"Got: {polling_frequency_minutes}"
        )
    return polling_frequency_minutes * 60


def _encode_part(payload: object) -> str:
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")


def _normalize_cluster_hostname(cluster_uri: str) -> str:
    hostname = cluster_uri.replace("https://", "").replace("http://", "")
    return hostname.rstrip("/")


def _normalize_kql_query(kql_query: str) -> str:
    return " ".join(kql_query.replace("\n", " ").split())


def _generate_teams_binding(
    alert_recipient: str, headline: str, message: str
) -> dict[str, Any]:
    return {
        "name": "TeamsBinding",
        "kind": "TeamsMessage",
        "arguments": [
            {"name": "messageLocale", "type": "string", "value": ""},
            {
                "name": "recipients",
                "type": "array",
                "values": [{"type": "string", "value": alert_recipient}],
            },
            {
                "name": "headline",
                "type": "array",
                "values": [{"type": "string", "value": headline}],
            },
            {
                "name": "optionalMessage",
                "type": "array",
                "values": [{"type": "string", "value": message}],
            },
            {"name": "additionalInformation", "type": "array", "values": []},
        ],
    }


def _generate_email_binding(
    alert_recipient: str, headline: str, message: str
) -> dict[str, Any]:
    return {
        "name": "EmailBinding",
        "kind": "EmailMessage",
        "arguments": [
            {"name": "messageLocale", "type": "string", "value": ""},
            {
                "name": "sentTo",
                "type": "array",
                "values": [{"type": "string", "value": alert_recipient}],
            },
            {"name": "copyTo", "type": "array", "values": []},
            {"name": "bCCTo", "type": "array", "values": []},
            {
                "name": "subject",
                "type": "array",
                "values": [{"type": "string", "value": headline}],
            },
            {
                "name": "headline",
                "type": "array",
                "values": [{"type": "string", "value": headline}],
            },
            {
                "name": "optionalMessage",
                "type": "array",
                "values": [{"type": "string", "value": message}],
            },
            {"name": "additionalInformation", "type": "array", "values": []},
        ],
    }


def _create_container_entity(trigger_name: str) -> tuple[dict[str, Any], str]:
    container_guid = str(uuid.uuid4())
    container = {
        "uniqueIdentifier": container_guid,
        "payload": {"name": trigger_name, "type": "unconstrained"},
        "type": "container-v1",
    }
    return container, container_guid


def _create_kql_source_entity(
    trigger_name: str,
    polling_frequency_minutes: int,
    kql_query: str,
    database: str,
    cluster_hostname: str,
    container_id: str,
    workspace_id: str,
) -> tuple[dict[str, Any], str]:
    source_id = str(uuid.uuid4())
    source = {
        "uniqueIdentifier": source_id,
        "payload": {
            "name": f"{trigger_name} source",
            "runSettings": {
                "executionIntervalInSeconds": validate_polling_frequency(
                    polling_frequency_minutes
                )
            },
            "query": {"queryString": _normalize_kql_query(kql_query)},
            "eventhouseItem": {
                "databaseName": database,
                "clusterHostName": cluster_hostname,
            },
            "queryParameters": [],
            "metadata": {
                "workspaceId": workspace_id,
                "measureName": "",
                "querySetId": "",
                "queryId": "",
            },
            "parentContainer": {"targetUniqueIdentifier": container_id},
        },
        "type": "kqlSource-v1",
    }
    return source, source_id


def _create_simple_event_rule_entities(
    trigger_name: str,
    container_id: str,
    source_id: str,
    message: str,
    headline: str,
    alert_recipient: str,
    alert_type: str,
) -> list[dict[str, Any]]:
    event_entity_guid = str(uuid.uuid4())

    if alert_type.lower() == "email":
        binding = _generate_email_binding(alert_recipient, headline, message)
    else:
        binding = _generate_teams_binding(alert_recipient, headline, message)

    event_entity = {
        "uniqueIdentifier": event_entity_guid,
        "payload": {
            "name": f"{trigger_name} event",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Event",
                "instance": json.dumps(
                    {
                        "templateId": "SourceEvent",
                        "templateVersion": TEMPLATE_VERSION,
                        "steps": [
                            {
                                "name": "SourceEventStep",
                                "id": str(uuid.uuid4()),
                                "rows": [
                                    {
                                        "name": "SourceSelector",
                                        "kind": "SourceReference",
                                        "arguments": [
                                            {
                                                "name": "entityId",
                                                "type": "string",
                                                "value": source_id,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    separators=(",", ":"),
                ),
            },
        },
        "type": "timeSeriesView-v1",
    }

    rule_entity = {
        "uniqueIdentifier": str(uuid.uuid4()),
        "payload": {
            "name": f"{trigger_name} rule",
            "description": "Created by market-surveillance deployment",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Rule",
                "instance": json.dumps(
                    {
                        "templateId": "EventTrigger",
                        "templateVersion": TEMPLATE_VERSION,
                        "steps": [
                            {
                                "name": "FieldsDefaultsStep",
                                "id": str(uuid.uuid4()),
                                "rows": [
                                    {
                                        "name": "EventSelector",
                                        "kind": "Event",
                                        "arguments": [
                                            {
                                                "kind": "EventReference",
                                                "type": "complex",
                                                "arguments": [
                                                    {
                                                        "name": "entityId",
                                                        "type": "string",
                                                        "value": event_entity_guid,
                                                    }
                                                ],
                                                "name": "event",
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "name": "EventDetectStep",
                                "id": str(uuid.uuid4()),
                                "rows": [
                                    {
                                        "name": "OnEveryValue",
                                        "kind": "OnEveryValue",
                                        "arguments": [],
                                    }
                                ],
                            },
                            {
                                "name": "ActStep",
                                "id": str(uuid.uuid4()),
                                "rows": [binding],
                            },
                        ],
                    },
                    separators=(",", ":"),
                ),
                "settings": {
                    "shouldRun": True,
                    "shouldApplyRuleOnUpdate": False,
                },
            },
        },
        "type": "timeSeriesView-v1",
    }

    return [event_entity, rule_entity]


def build_create_request(
    config_path: Path,
    workspace_id: str,
    cluster_uri: str,
    database: str,
    alert_recipient: str,
) -> dict[str, Any]:
    config = json.loads(config_path.read_text())
    alert_type = config.get("alert_type", "teams")
    cluster_hostname = _normalize_cluster_hostname(cluster_uri)

    entities: list[dict[str, Any]] = []
    for trigger in config["triggers"]:
        container, container_id = _create_container_entity(trigger["name"])
        source, source_id = _create_kql_source_entity(
            trigger_name=trigger["id"],
            polling_frequency_minutes=trigger["polling_frequency_minutes"],
            kql_query=trigger["kql_query"],
            database=database,
            cluster_hostname=cluster_hostname,
            container_id=container_id,
            workspace_id=workspace_id,
        )
        event_and_rule = _create_simple_event_rule_entities(
            trigger_name=trigger["id"],
            container_id=container_id,
            source_id=source_id,
            message=trigger["message"],
            headline=trigger["headline"],
            alert_recipient=alert_recipient,
            alert_type=alert_type,
        )
        entities.extend([container, source, *event_and_rule])

    display_name = config["display_name"]
    description = config["description"]
    return {
        "displayName": display_name,
        "description": description,
        "definition": {
            "parts": [
                {
                    "path": "ReflexEntities.json",
                    "payload": _encode_part(entities),
                    "payloadType": "InlineBase64",
                },
                {
                    "path": ".platform",
                    "payload": _encode_part(
                        {"metadata": {"type": "Reflex", "displayName": display_name}}
                    ),
                    "payloadType": "InlineBase64",
                },
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--cluster-uri", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--alert-recipient", required=True)
    args = parser.parse_args()

    payload = build_create_request(
        config_path=args.config,
        workspace_id=args.workspace_id,
        cluster_uri=args.cluster_uri,
        database=args.database,
        alert_recipient=args.alert_recipient,
    )
    print(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
