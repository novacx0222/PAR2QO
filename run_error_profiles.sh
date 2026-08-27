#!/usr/bin/env bash
set -Eeuo pipefail

# Usage:
#   ./run_error_profiles.sh dry-run
#   ./run_error_profiles.sh smoke
#   ./run_error_profiles.sh full
#
# Override defaults with environment variables, for example:
#   PGUSER=postgres WORKLOAD=17-0_cardinality ./run_error_profiles.sh smoke

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-dry-run}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
QUERY_ROOT="${QUERY_ROOT:-/opt/sqls/imdb-error-profile-0612}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${REPO_ROOT}/output/error-profiles}"
WORKLOAD="${WORKLOAD:-17-0_cardinality}"
SAMPLE_SIZE="${SAMPLE_SIZE:-50}"

export PGHOST="${PGHOST:-/tmp}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-imdbloadbase}"
export PGUSER="${PGUSER:-$(id -un)}"

BUILD=(
  "${PYTHON_BIN}" "${REPO_ROOT}/code/build_error_profiles.py"
  "${QUERY_ROOT}"
  -n "${SAMPLE_SIZE}"
  --output-root "${OUTPUT_ROOT}"
)

if [[ ! -d "${QUERY_ROOT}" ]]; then
  echo "Query root does not exist: ${QUERY_ROOT}" >&2
  exit 2
fi

case "${MODE}" in
  dry-run)
    "${BUILD[@]}" --include "${WORKLOAD}" --dry-run
    ;;

  smoke|full)
    if ! "${PYTHON_BIN}" -c 'import psycopg2, pandas, numpy, matplotlib, tqdm' 2>/dev/null; then
      echo "Missing Python dependencies." >&2
      echo "Install them with:" >&2
      echo "  ${PYTHON_BIN} -m pip install psycopg2-binary pandas numpy matplotlib tqdm" >&2
      exit 2
    fi

    if command -v pg_isready >/dev/null 2>&1; then
      if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -d "${PGDATABASE}"; then
        echo "PostgreSQL is not ready. Check PGHOST/PGPORT/PGDATABASE/PGUSER." >&2
        exit 2
      fi
    fi

    echo "Input:    ${QUERY_ROOT}"
    echo "Output:   ${OUTPUT_ROOT}"
    echo "Database: ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"

    if [[ "${MODE}" == "smoke" ]]; then
      "${BUILD[@]}" --include "${WORKLOAD}"
    else
      echo "Full mode may need the instrumented PostgreSQL to build missing querylet metadata."
      "${BUILD[@]}"
    fi
    ;;

  *)
    echo "Usage: $0 {dry-run|smoke|full}" >&2
    exit 2
    ;;
esac
