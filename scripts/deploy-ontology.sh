#!/usr/bin/env bash
# Deploy ontology to Microsoft Fabric via REST API.
set -euo pipefail

WS_ID="${1:?Usage: deploy-ontology.sh <workspace-id>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RDF_PATH="${SCRIPT_DIR}/../ontology/market-surveillance.rdf"
ONTOLOGY_NAME="Market_Surveillance"

TOKEN=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv)
REQUEST_JSON=$(python3 "${SCRIPT_DIR}/build_ontology_payload.py" --rdf "${RDF_PATH}" --display-name "${ONTOLOGY_NAME}")

HEADERS_FILE=$(mktemp)
BODY_FILE=$(mktemp)

cleanup() {
  rm -f "${HEADERS_FILE}" "${BODY_FILE}"
}
trap cleanup EXIT

header_value() {
  local name="$1"
  awk -v header="${name}" 'BEGIN { IGNORECASE=1 }
    $0 ~ "^" header ":" {
      sub(/^[^:]+:[[:space:]]*/, "")
      sub(/\r$/, "")
      print
      exit
    }' "${HEADERS_FILE}"
}

http_code() {
  awk 'toupper($1) ~ /^HTTP\// { code=$2 } END { print code }' "${HEADERS_FILE}"
}

poll_operation() {
  local location="$1"
  local delay="$2"
  local attempts=0

  while (( attempts < 20 )); do
    sleep "${delay}"
    curl -sS -D "${HEADERS_FILE}" -o "${BODY_FILE}" -X GET "${location}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json"

    local status
    status=$(jq -r '.status // empty' "${BODY_FILE}")
    case "${status}" in
      Succeeded)
        return 0
        ;;
      Failed)
        echo "✗ Ontology creation operation failed: $(cat "${BODY_FILE}")" >&2
        return 1
        ;;
      Running|InProgress|NotStarted|"")
        delay=$(header_value "Retry-After")
        delay="${delay:-5}"
        ;;
      *)
        echo "  Waiting for ontology operation: ${status}"
        delay=$(header_value "Retry-After")
        delay="${delay:-5}"
        ;;
    esac
    attempts=$((attempts + 1))
  done

  echo "✗ Ontology creation operation did not complete in time" >&2
  return 1
}

echo "Creating Fabric ontology item (${ONTOLOGY_NAME})..."
curl -sS -D "${HEADERS_FILE}" -o "${BODY_FILE}" -X POST "https://api.fabric.microsoft.com/v1/workspaces/${WS_ID}/ontologies" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${REQUEST_JSON}"

HTTP_CODE=$(http_code)
BODY=$(cat "${BODY_FILE}")

case "${HTTP_CODE}" in
  201)
    echo "✓ Ontology created"
    ;;
  202)
    LOCATION=$(header_value "Location")
    RETRY_AFTER=$(header_value "Retry-After")
    RETRY_AFTER="${RETRY_AFTER:-5}"
    if [[ -z "${LOCATION}" ]]; then
      echo "✗ Ontology creation returned 202 without a Location header" >&2
      exit 1
    fi
    poll_operation "${LOCATION}" "${RETRY_AFTER}"
    echo "✓ Ontology created"
    ;;
  *)
    if echo "${BODY}" | grep -q "ItemDisplayNameAlreadyInUse\|AlreadyInUse\|already exists"; then
      echo "✓ Ontology already exists"
      exit 0
    fi
    echo "✗ Ontology creation failed (HTTP ${HTTP_CODE}): ${BODY}" >&2
    exit 1
    ;;
esac
