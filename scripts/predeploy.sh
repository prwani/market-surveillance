#!/usr/bin/env bash
# azd hook: runs before deployment (azd deploy)
# Validates that required configuration is in place.
set -euo pipefail

echo "═══════════════════════════════════════════════════════"
echo " Pre-deploy: Validating configuration"
echo "═══════════════════════════════════════════════════════"

KQL_URI=$(azd env get-value KQL_URI 2>/dev/null || echo "")
if [[ -z "${KQL_URI}" ]]; then
  echo "⚠  KQL_URI is not set. Workers will start in poll mode."
  echo "   Run 'azd env set KQL_URI <uri>' to configure, then redeploy."
else
  echo "✓ KQL_URI: ${KQL_URI}"
fi

echo "═══════════════════════════════════════════════════════"
echo " Pre-deploy validation complete"
echo "═══════════════════════════════════════════════════════"
