#!/usr/bin/env bash
set -Eeuo pipefail

# Usage: ./run_sample_csv.sh [workload]
# Example: ./run_sample_csv.sh 17-0_cardinality

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY_ROOT="${QUERY_ROOT:-/opt/sqls/imdb-error-profile-0612}"
WORKLOAD="${1:-17-0_cardinality}"
SAMPLE_SIZE="${SAMPLE_SIZE:-50}"

if [[ ! "${WORKLOAD}" =~ ^([0-9]+)-([0-9]+)_(.+)$ ]]; then
  echo "Invalid workload name: ${WORKLOAD}" >&2
  exit 2
fi

Q="${BASH_REMATCH[1]}"
T="${BASH_REMATCH[2]}"
WORKLOAD_TYPE="${BASH_REMATCH[3]}"
OUTPUT="${OUTPUT:-${REPO_ROOT}/output/samples/${WORKLOAD}/sample-${SAMPLE_SIZE}.csv}"

python3 "${REPO_ROOT}/code/trans_pqo_combination_to_csv.py" \
  --q "${Q}" \
  --t "${T}" \
  --n "${SAMPLE_SIZE}" \
  --workload "${WORKLOAD_TYPE}" \
  --base_path "${QUERY_ROOT}/" \
  --output "${OUTPUT}"

echo "Generated: ${OUTPUT}"
