#!/usr/bin/env bash
# Deploy all KQL stored functions to the surveillance database
set -euo pipefail

KQL_URI="${1:?Usage: deploy-stored-functions.sh <kql-uri> [database-name]}"
KQL_DB="${2:-surveillance}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KQL_FILE="${SCRIPT_DIR}/../kql/stored_functions.kql"

echo "Deploying KQL stored functions to ${KQL_DB}..."
echo "  KQL URI: ${KQL_URI}"

TOKEN=$(az account get-access-token --resource "https://kusto.kusto.windows.net" --query accessToken -o tsv)

run_kql() {
  local name="$1"
  local query="$2"
  echo "  Deploying: ${name}..."
  RESPONSE=$(curl -s -X POST "${KQL_URI}/v1/rest/mgmt" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"db\":\"${KQL_DB}\",\"csl\":$(echo "$query" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    -w "\n%{http_code}")
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  BODY=$(echo "$RESPONSE" | head -1)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "    ✗ Failed (HTTP ${HTTP_CODE}): ${BODY}" >&2
    return 1
  fi
  echo "    ✓ OK"
}

# Parse stored_functions.kql — extract each .create-or-alter function block
echo "Parsing ${KQL_FILE}..."

# Use Python to extract function blocks from the KQL file
python3 - "${KQL_FILE}" <<'PYEOF'
import sys, re, json

with open(sys.argv[1]) as f:
    content = f.read()

# Split on .create-or-alter function boundaries
pattern = r'(\.create-or-alter\s+function\s+\w+\([^)]*\)\s*\{)'
parts = re.split(pattern, content)

functions = []
i = 1
while i < len(parts):
    header = parts[i].strip()
    body_and_rest = parts[i+1] if i+1 < len(parts) else ""
    # Find matching closing brace (track nesting)
    depth = 1
    pos = 0
    for pos, ch in enumerate(body_and_rest):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                break
    body = body_and_rest[:pos+1]
    full = header + body
    # Extract function name
    m = re.search(r'function\s+(\w+)', header)
    name = m.group(1) if m else f"function_{len(functions)}"
    functions.append((name, full))
    i += 2

# Output as JSON for the shell script to consume
print(json.dumps(functions))
PYEOF

FUNCTIONS_JSON=$(python3 - "${KQL_FILE}" <<'PYEOF'
import sys, re, json

with open(sys.argv[1]) as f:
    content = f.read()

pattern = r'(\.create-or-alter\s+function\s+\w+\([^)]*\)\s*\{)'
parts = re.split(pattern, content)

functions = []
i = 1
while i < len(parts):
    header = parts[i].strip()
    body_and_rest = parts[i+1] if i+1 < len(parts) else ""
    depth = 1
    for pos, ch in enumerate(body_and_rest):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                break
    body = body_and_rest[:pos+1]
    full = header + body
    m = re.search(r'function\s+(\w+)', header)
    name = m.group(1) if m else f"function_{len(functions)}"
    functions.append((name, full))
    i += 2

print(json.dumps(functions))
PYEOF
)

COUNT=$(echo "$FUNCTIONS_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
echo "Found ${COUNT} functions to deploy"

echo "$FUNCTIONS_JSON" | python3 -c "
import json, sys, subprocess, os

functions = json.load(sys.stdin)
kql_uri = os.environ['KQL_URI']
kql_db = os.environ['KQL_DB']
token = os.environ['TOKEN']

success = 0
failed = 0
for name, body in functions:
    print(f'  Deploying: {name}...')
    payload = json.dumps({'db': kql_db, 'csl': body})
    result = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{kql_uri}/v1/rest/mgmt',
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Content-Type: application/json',
         '-d', payload,
         '-w', '\n%{http_code}'],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split('\n')
    http_code = lines[-1] if lines else '0'
    if http_code == '200':
        print(f'    ✓ OK')
        success += 1
    else:
        print(f'    ✗ Failed (HTTP {http_code}): {lines[0] if lines else \"unknown\"}')
        failed += 1

print()
print(f'✓ Deployed {success}/{success+failed} functions successfully')
if failed > 0:
    print(f'✗ {failed} function(s) failed')
    sys.exit(1)
" KQL_URI="$KQL_URI" KQL_DB="$KQL_DB" TOKEN="$TOKEN"

echo ""
echo "✓ All stored functions deployed"
