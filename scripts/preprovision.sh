#!/usr/bin/env sh
# azd hook: runs before infrastructure provisioning starts
set -eu

echo "═══════════════════════════════════════════════════════"
echo " Pre-provision: Verifying Fabric tenant settings"
echo "═══════════════════════════════════════════════════════"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python3 "${SCRIPT_DIR}/check-fabric-prereqs.py"
