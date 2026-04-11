"""Helpers for resolving Fabric connection settings."""

from __future__ import annotations

import os
import shutil
import subprocess
from urllib.parse import urlparse, urlunparse


def resolve_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value

    if not shutil.which("azd"):
        return ""

    try:
        result = subprocess.run(
            ["azd", "env", "get-value", name],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def derive_ingest_uri(kql_uri: str) -> str:
    parsed = urlparse(kql_uri)
    if not parsed.scheme or not parsed.netloc:
        return ""
    if parsed.netloc.startswith("ingest-"):
        return kql_uri
    return urlunparse(parsed._replace(netloc=f"ingest-{parsed.netloc}"))
