"""Helpers for validating Fabric tenant settings required by deployment."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable


@dataclass(frozen=True)
class RequiredTenantSetting:
    setting_name: str
    title: str
    reason: str


@dataclass(frozen=True)
class TenantSettingCheck:
    requirement: RequiredTenantSetting
    found: bool
    enabled: bool
    delegate_to_capacity: bool


REQUIRED_TENANT_SETTINGS = (
    RequiredTenantSetting(
        setting_name="OntologyPreview",
        title="Users can create Ontology (preview) items",
        reason=(
            "Required because `azd up` creates the `Market_Surveillance` ontology "
            "item during postprovision."
        ),
    ),
    RequiredTenantSetting(
        setting_name="RTHAnomalyDetectionTenantSwitch",
        title="Detect anomalies in Real-Time Intelligence (Preview)",
        reason=(
            "Required so the anomaly-detection part of the solution is available "
            "immediately after deployment."
        ),
    ),
)


def parse_tenant_settings_payload(payload: str) -> dict[str, dict]:
    """Return tenant settings keyed by settingName."""
    data = json.loads(payload)
    raw_settings = data.get("tenantSettings") or data.get("value") or []
    settings: dict[str, dict] = {}
    for item in raw_settings:
        name = item.get("settingName")
        if name:
            settings[str(name)] = item
    return settings


def evaluate_required_settings(
    settings_by_name: dict[str, dict],
    required_settings: Iterable[RequiredTenantSetting] = REQUIRED_TENANT_SETTINGS,
) -> list[TenantSettingCheck]:
    checks: list[TenantSettingCheck] = []
    for requirement in required_settings:
        current = settings_by_name.get(requirement.setting_name)
        checks.append(
            TenantSettingCheck(
                requirement=requirement,
                found=current is not None,
                enabled=bool(current and current.get("enabled")),
                delegate_to_capacity=bool(current and current.get("delegateToCapacity")),
            )
        )
    return checks


def get_missing_required_settings(
    checks: Iterable[TenantSettingCheck],
) -> list[TenantSettingCheck]:
    return [check for check in checks if not check.enabled]


def format_missing_settings_message(
    missing_checks: Iterable[TenantSettingCheck],
) -> str:
    checks = list(missing_checks)
    lines = [
        "Required Fabric tenant settings are not ready for deployment.",
        "",
        "Enable these settings in the Fabric admin portal, wait up to 15 minutes",
        "for propagation, and then rerun `azd up`:",
    ]
    for check in checks:
        lines.append(
            f"- {check.requirement.title} ({check.requirement.setting_name})"
        )
        lines.append(f"  {check.requirement.reason}")
        if check.delegate_to_capacity:
            lines.append(
                "  This setting can also be delegated to capacity admins, so verify "
                "the target capacity has not overridden it if deployment still fails."
            )
    return "\n".join(lines)
