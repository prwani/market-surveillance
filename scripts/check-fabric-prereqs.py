#!/usr/bin/env python3
"""Validate Fabric tenant settings before azd provisioning starts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fabric_tenant_settings import (  # noqa: E402
    evaluate_required_settings,
    format_missing_settings_message,
    get_missing_required_settings,
    parse_tenant_settings_payload,
)


FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
TENANT_SETTINGS_URL = f"{FABRIC_RESOURCE}/v1/admin/tenantsettings"


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(stderr or "command failed")
    return result.stdout.strip()


def get_fabric_access_token() -> str:
    return _run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            FABRIC_RESOURCE,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ]
    )


def fetch_tenant_settings(access_token: str) -> str:
    request = Request(
        TENANT_SETTINGS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body.replace("\n", " ")[:400]
        raise RuntimeError(
            f"HTTP {exc.code} from {TENANT_SETTINGS_URL}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Failed to reach {TENANT_SETTINGS_URL}: {exc.reason}"
        ) from exc


def main() -> int:
    print("Checking Fabric tenant settings required for deployment...")
    try:
        access_token = get_fabric_access_token()
        payload = fetch_tenant_settings(access_token)
        settings = parse_tenant_settings_payload(payload)
    except (OSError, RuntimeError, ValueError) as exc:
        print("✗ Unable to verify Fabric tenant settings before provisioning.")
        print(
            "  This precheck calls GET /v1/admin/tenantsettings and requires a"
        )
        print(
            "  Fabric admin account (or another identity with Tenant.Read.All)."
        )
        print("  Sign in with an eligible account, then rerun `azd up`.")
        print(f"  Details: {exc}")
        return 1

    checks = evaluate_required_settings(settings)
    missing = get_missing_required_settings(checks)
    if missing:
        print(f"✗ {format_missing_settings_message(missing)}")
        print("")
        print(
            "This deployment stops early so preview-setting propagation happens"
        )
        print("before Azure resources are provisioned.")
        return 1

    print("✓ Required Fabric tenant settings are enabled:")
    for check in checks:
        print(f"  - {check.requirement.title}")
    print(
        "  - Eventhouse Python plugin still must be enabled manually later if"
    )
    print("    you plan to create anomaly detector items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
