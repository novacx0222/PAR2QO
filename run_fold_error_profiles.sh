#!/usr/bin/env bash
set -Eeuo pipefail

# Build the two ownership-based IMDb error-profile workloads.
#
# Typical usage:
#   ./run_fold_error_profiles.sh samples
#   ./run_fold_error_profiles.sh metadata
#   ./run_fold_error_profiles.sh profiles
#   ./run_fold_error_profiles.sh sanity
#
# Useful overrides:
#   FOLDS="1" ./run_fold_error_profiles.sh samples
#   FOLDS="1" WORKLOAD="1-0_cardinality" ./run_fold_error_profiles.sh metadata
#   REFRESH_METADATA=1 FOLDS="1" WORKLOAD="1-0_cardinality" ./run_fold_error_profiles.sh metadata
#   FOLDS="1" WORKLOAD="17-0_cardinality" ./run_fold_error_profiles.sh profiles
#   PGUSER=postgres PGDATABASE=imdbloadbase ./run_fold_error_profiles.sh profiles

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND="${1:-help}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SOURCE_ROOT="${SOURCE_ROOT:-/data/robdp/imdb-separate-ep-0826}"
REFERENCE_ROOT="${REFERENCE_ROOT:-/data/robdp/imdb-error-profile-0612}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-/data/robdp/imdb-separate-ep-0826}"
SAMPLE_SIZE="${SAMPLE_SIZE:-50}"
FOLDS="${FOLDS:-1 2}"
WORKLOAD="${WORKLOAD:-*}"

read -r -a FOLD_ARRAY <<< "${FOLDS}"

COMMON_ARGS=(
  --source-root "${SOURCE_ROOT}"
  --reference-root "${REFERENCE_ROOT}"
  --output-prefix "${OUTPUT_PREFIX}"
  --sample-label "${SAMPLE_SIZE}"
  --folds "${FOLD_ARRAY[@]}"
)

check_samples() {
  "${PYTHON_BIN}" "${REPO_ROOT}/code/fold_error_profile_inputs.py" \
    check-samples "${COMMON_ARGS[@]}"
}

check_profiles() {
  "${PYTHON_BIN}" "${REPO_ROOT}/code/fold_error_profile_inputs.py" \
    check-profiles "${COMMON_ARGS[@]}" --include "${WORKLOAD}"
}

metadata_root() {
  echo "${OUTPUT_PREFIX}-${FOLD_ARRAY[0]}"
}

check_metadata() {
  QUERY_ROOT="$(metadata_root)" \
  OUTPUT_ROOT="$(metadata_root)" \
  SAMPLE_SIZE="${SAMPLE_SIZE}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  WORKLOAD="${WORKLOAD}" \
    "${REPO_ROOT}/run_error_profiles.sh" check-metadata
}

run_metadata() {
  check_samples
  echo "Building shared querylet metadata from fold ${FOLD_ARRAY[0]}"
  QUERY_ROOT="$(metadata_root)" \
  OUTPUT_ROOT="$(metadata_root)" \
  SAMPLE_SIZE="${SAMPLE_SIZE}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  WORKLOAD="${WORKLOAD}" \
    "${REPO_ROOT}/run_error_profiles.sh" metadata
}

run_profiles() {
  check_samples
  check_metadata
  for fold_id in "${FOLD_ARRAY[@]}"; do
    fold_root="${OUTPUT_PREFIX}-${fold_id}"
    echo "Building error profiles for fold ${fold_id}: ${fold_root}"
    if [[ "${WORKLOAD}" == "*" ]]; then
      QUERY_ROOT="${fold_root}" \
      OUTPUT_ROOT="${fold_root}" \
      SAMPLE_SIZE="${SAMPLE_SIZE}" \
      PYTHON_BIN="${PYTHON_BIN}" \
      REQUIRE_METADATA=1 \
        "${REPO_ROOT}/run_error_profiles.sh" full
    else
      QUERY_ROOT="${fold_root}" \
      OUTPUT_ROOT="${fold_root}" \
      SAMPLE_SIZE="${SAMPLE_SIZE}" \
      PYTHON_BIN="${PYTHON_BIN}" \
      WORKLOAD="${WORKLOAD}" \
      REQUIRE_METADATA=1 \
        "${REPO_ROOT}/run_error_profiles.sh" smoke
    fi
  done
  check_profiles
}

case "${COMMAND}" in
  samples)
    "${PYTHON_BIN}" "${REPO_ROOT}/code/fold_error_profile_inputs.py" \
      samples "${COMMON_ARGS[@]}"
    ;;
  check-samples)
    check_samples
    ;;
  metadata)
    run_metadata
    ;;
  check-metadata)
    check_metadata
    ;;
  profiles)
    run_profiles
    ;;
  check-profiles)
    check_profiles
    ;;
  sanity)
    check_samples
    check_metadata
    check_profiles
    ;;
  all)
    "${PYTHON_BIN}" "${REPO_ROOT}/code/fold_error_profile_inputs.py" \
      samples "${COMMON_ARGS[@]}"
    run_metadata
    run_profiles
    ;;
  dry-run-profiles)
    check_samples
    for fold_id in "${FOLD_ARRAY[@]}"; do
      QUERY_ROOT="${OUTPUT_PREFIX}-${fold_id}" \
      OUTPUT_ROOT="${OUTPUT_PREFIX}-${fold_id}" \
      SAMPLE_SIZE="${SAMPLE_SIZE}" \
      PYTHON_BIN="${PYTHON_BIN}" \
      WORKLOAD="${WORKLOAD}" \
        "${REPO_ROOT}/run_error_profiles.sh" dry-run
    done
    ;;
  help|-h|--help)
    sed -n '3,13p' "$0"
    ;;
  *)
    echo "Usage: $0 {samples|check-samples|metadata|check-metadata|profiles|check-profiles|sanity|all|dry-run-profiles}" >&2
    exit 2
    ;;
esac
