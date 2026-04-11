#!/usr/bin/env python3
"""Build a Fabric anomaly detector create payload."""

from __future__ import annotations

import argparse
import base64
import json
import uuid
from typing import Any

DEFAULT_DISPLAY_NAME = "Market Price Anomalies"
DEFAULT_DESCRIPTION = (
    "Fabric anomaly detector for TRADES price series grouped by symbol."
)
ANOMALY_SCHEMA_ID = (
    "https://developer.microsoft.com/json-schemas/fabric/item/"
    "anomalyDetector/definition/1.0.0/schema.json"
)


def _encode_part(payload: object) -> str:
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")


def build_create_request(
    *,
    workspace_id: str,
    artifact_id: str,
    table_name: str = "TRADES",
    timestamp_column: str = "event_time",
    instance_column: str = "symbol",
    attribute_column: str = "price",
    display_name: str = DEFAULT_DISPLAY_NAME,
    description: str = DEFAULT_DESCRIPTION,
    configuration_name: str = "TRADES price by symbol",
    algorithm: str = "SR",
    model_name: str = "Spectral Residual",
    model_version: str = "1.0",
    confidence: int = 95,
    auto_publish: bool = True,
) -> dict[str, Any]:
    configuration = {
        "$id": ANOMALY_SCHEMA_ID,
        "$schema": "https://json-schema.org/draft-07/schema#",
        "univariateConfigurations": [
            {
                "configurationId": str(uuid.uuid4()),
                "configurationName": configuration_name,
                "fabricDataSource": {
                    "workspaceId": workspace_id,
                    "artifactId": artifact_id,
                    "dataSourceType": "KqlDb",
                    "tableName": table_name,
                    "timestampColumnName": timestamp_column,
                    "instanceIDColumnName": instance_column,
                    "attributeColumnName": attribute_column,
                },
                "modelOption": {
                    "modelSelection": {
                        "modelAlgorithm": algorithm,
                        "modelVersion": model_version,
                        "modelName": model_name,
                        "modelDescription": description,
                    }
                },
                "detectionSettings": {
                    "confidence": confidence,
                    "autoPublish": auto_publish,
                },
            }
        ],
    }

    return {
        "displayName": display_name,
        "description": description,
        "definition": {
            "format": "AnomalyDetectorV1",
            "parts": [
                {
                    "path": ".platform",
                    "payload": _encode_part(
                        {"metadata": {"type": "AnomalyDetector", "displayName": display_name}}
                    ),
                    "payloadType": "InlineBase64",
                },
                {
                    "path": "Configurations.json",
                    "payload": _encode_part(configuration),
                    "payloadType": "InlineBase64",
                },
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--table-name", default="TRADES")
    parser.add_argument("--timestamp-column", default="event_time")
    parser.add_argument("--instance-column", default="symbol")
    parser.add_argument("--attribute-column", default="price")
    parser.add_argument("--display-name", default=DEFAULT_DISPLAY_NAME)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--configuration-name", default="TRADES price by symbol")
    parser.add_argument("--algorithm", default="SR")
    parser.add_argument("--model-name", default="Spectral Residual")
    parser.add_argument("--model-version", default="1.0")
    parser.add_argument("--confidence", type=int, default=95)
    parser.add_argument(
        "--auto-publish",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args()

    payload = build_create_request(
        workspace_id=args.workspace_id,
        artifact_id=args.artifact_id,
        table_name=args.table_name,
        timestamp_column=args.timestamp_column,
        instance_column=args.instance_column,
        attribute_column=args.attribute_column,
        display_name=args.display_name,
        description=args.description,
        configuration_name=args.configuration_name,
        algorithm=args.algorithm,
        model_name=args.model_name,
        model_version=args.model_version,
        confidence=args.confidence,
        auto_publish=args.auto_publish,
    )
    print(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
