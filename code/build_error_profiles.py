#!/usr/bin/env python3
"""Thin batch runner for the repository's original error-profile generator."""

from __future__ import annotations

import argparse
import copy
import csv
import fnmatch
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMS_FILE = HERE / "cached_info/gen_real_error_params.json"
ROBUST_PARAMS_FILE = HERE / "cached_info/gen_real_error_params_rob.json"
MANUAL_PARAMS_FILE = HERE / "cached_info/gen_real_error_params_manual.json"
ERROR_PROFILE_DICT_FILE = HERE / "cached_info/error_profile_dict.json"
WORKLOAD_RE = re.compile(r"(\d+)-(\d+)_(.+)")


def workload_info(path: Path) -> tuple[int, int, str]:
    match = WORKLOAD_RE.fullmatch(path.name)
    if not match:
        raise ValueError(f"invalid workload directory: {path.name}")
    return int(match[1]), int(match[2]), match[3]


def read_params(path: Path = PARAMS_FILE) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_params(params: dict, path: Path = PARAMS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(params, indent=4) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_metadata(key: str, metadata: object) -> int:
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError(f"metadata {key} must be a non-empty object")
    for dimension, spec in metadata.items():
        if not str(dimension).isdigit():
            raise ValueError(f"metadata {key}: invalid dimension {dimension!r}")
        if not isinstance(spec, list) or len(spec) != 6:
            raise ValueError(
                f"metadata {key}/{dimension}: expected a six-field parameter list"
            )
        if not all(isinstance(value, str) for value in spec[:5]):
            raise ValueError(
                f"metadata {key}/{dimension}: first five fields must be strings"
            )
        if not spec[4].startswith("template_"):
            raise ValueError(
                f"metadata {key}/{dimension}: invalid querylet name {spec[4]!r}"
            )
        if not isinstance(spec[5], bool):
            raise ValueError(
                f"metadata {key}/{dimension}: final field must be boolean"
            )
    return len(metadata)


def validate_metadata_against_sample(
    key: str, metadata: dict, sample: Path, query_id: int
) -> None:
    with sample.open(newline="", encoding="utf-8") as handle:
        tables = {
            row["Table"]
            for row in csv.DictReader(handle)
            if row.get("Table")
        }
    allowed = tables | {"x", "mk", "akat", "cc"}
    if query_id in {11, 21, 27}:
        allowed.add("mc")

    missing: list[str] = []
    collapsed_cct: list[str] = []
    for dimension, spec in metadata.items():
        for side, sample_table in (("left", spec[0]), ("right", spec[2])):
            if sample_table not in allowed:
                missing.append(f"dimension {dimension} {side}={sample_table}")
            if sample_table in {"cct1", "cct2"}:
                if sample_table not in spec[4]:
                    collapsed_cct.append(
                        f"dimension {dimension} {side}={sample_table} "
                        f"querylet={spec[4]}"
                    )
                side_querylet = spec[1] if side == "left" else spec[3]
                if side_querylet and side_querylet != sample_table:
                    collapsed_cct.append(
                        f"dimension {dimension} {side}={sample_table} "
                        f"side-querylet={side_querylet}"
                    )
    if missing:
        raise ValueError(
            f"metadata {key} references tables absent from {sample}: "
            + ", ".join(missing)
            + "; refresh metadata from a clean PostgreSQL record delta"
        )
    if collapsed_cct:
        raise ValueError(
            f"metadata {key} collapses cct1/cct2 into cct: "
            + ", ".join(collapsed_cct)
            + "; refresh metadata after applying the cct alias fix"
        )


def normalize_legacy_cct_params(metadata: dict) -> dict:
    """Migrate cached metadata written before cct1/cct2 aliases were preserved."""
    normalized = copy.deepcopy(metadata)
    for spec in normalized.values():
        aliases = {table for table in (spec[0], spec[2]) if table in {"cct1", "cct2"}}
        if len(aliases) != 1:
            continue
        alias = aliases.pop()
        if spec[0] == alias and spec[1] == "cct":
            spec[1] = alias
        if spec[2] == alias and spec[3] == "cct":
            spec[3] = alias
        if spec[4] == "template_cct":
            spec[4] = f"template_{alias}"
        elif spec[4] == "template_cct_cc_l":
            spec[4] = f"template_{alias}_cc_l"
    return normalized


def cached_robust_params(key: str) -> dict | None:
    """Reuse robust-workload metadata when it is identical across DB instances."""
    candidates = [
        value
        for name, value in read_params(ROBUST_PARAMS_FILE).items()
        if name.startswith(key + "-")
    ]
    if candidates and all(value == candidates[0] for value in candidates[1:]):
        return normalize_legacy_cct_params(candidates[0])
    return None


def manual_params(key: str) -> dict:
    return read_params(MANUAL_PARAMS_FILE).get(key, {})


def validate_manual_params(key: str, metadata: dict) -> None:
    expected = manual_params(key)
    missing_or_different = [
        dimension
        for dimension, spec in expected.items()
        if metadata.get(dimension) != spec
    ]
    if missing_or_different:
        raise ValueError(
            f"metadata {key} is missing manual dimensions "
            f"{', '.join(sorted(missing_or_different, key=int))}; "
            "run the metadata stage to merge manual querylets"
        )


def merge_manual_params(key: str, params: dict) -> bool:
    additions = manual_params(key)
    if not additions:
        return False
    metadata = params.setdefault(key, {})
    changed = False
    for dimension, spec in additions.items():
        if metadata.get(dimension) != spec:
            metadata[dimension] = spec
            changed = True
    if not changed:
        return False

    write_params(params)
    error_profiles = read_params(ERROR_PROFILE_DICT_FILE)
    mapping = error_profiles.setdefault(key, {})
    for dimension, spec in additions.items():
        mapping[dimension] = spec[4].removeprefix("template_") + ".txt"
    write_params(error_profiles, ERROR_PROFILE_DICT_FILE)
    print(
        f"  merge manual querylet metadata: {key}, "
        f"dimensions={','.join(sorted(additions, key=int))}"
    )
    return True


def first_query(path: Path, query_id: int, template_id: int, n: int) -> str:
    source = path / "raw_data" / f"{query_id}-{template_id}_training_{n}.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    return next(iter(data.values()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build error profiles by reusing gen_real_error_pqo.py."
    )
    parser.add_argument("root", type=Path, help="Root containing q-t_workload folders")
    parser.add_argument("--include", default="*", help="Workload glob")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Write elsewhere; defaults to the input root",
    )
    parser.add_argument("-n", type=int, default=50, help="Sample size")
    parser.add_argument(
        "--refresh-meta",
        action="store_true",
        help="Regenerate querylet metadata with the instrumented PostgreSQL",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="build/reuse querylet metadata but do not generate profiles",
    )
    parser.add_argument(
        "--check-metadata",
        action="store_true",
        help="validate cached metadata without connecting to PostgreSQL",
    )
    parser.add_argument(
        "--require-metadata",
        action="store_true",
        help="fail instead of implicitly building missing metadata",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.check_metadata and (args.metadata_only or args.refresh_meta):
        parser.error("--check-metadata cannot be combined with metadata generation")
    if args.require_metadata and (args.metadata_only or args.refresh_meta):
        parser.error("--require-metadata cannot be combined with metadata generation")

    root = args.root.resolve()
    output_root = (args.output_root or root).resolve()
    workloads = [
        path
        for path in sorted(root.iterdir())
        if path.is_dir()
           and WORKLOAD_RE.fullmatch(path.name)
           and fnmatch.fnmatch(path.name, args.include)
    ]
    if not workloads:
        raise SystemExit(f"no workload matched under {root}")

    params = read_params()
    for path in workloads:
        q, t, workload = workload_info(path)
        sample = path / f"sample-{args.n}.csv"
        if not sample.exists():
            raise SystemExit(f"missing {sample}")
        print(f"{path.name}: {sample.name}")

        if args.dry_run:
            continue

        key = f"{q}-{t}"
        if args.check_metadata:
            if key not in params:
                raise SystemExit(
                    f"missing metadata {key} in {PARAMS_FILE}; run the metadata stage"
                )
            try:
                count = validate_metadata(key, params[key])
                validate_metadata_against_sample(key, params[key], sample, q)
                validate_manual_params(key, params[key])
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"  metadata sanity OK: {key}, {count} querylets")
            continue

        if key not in params:
            reused = cached_robust_params(key)
            if reused is not None:
                print(f"  reuse cached querylet metadata: {key}")
                params[key] = reused
                # Persist reuse so metadata generation and profile generation
                # are cleanly separable pipeline stages.
                write_params(params)

        if args.require_metadata and key not in params:
            raise SystemExit(
                f"missing metadata {key} in {PARAMS_FILE}; "
                "run the metadata stage first"
            )

        if args.refresh_meta or key not in params:
            # The old modules use relative paths such as cached_info/ and
            # cardinality/, and metadata extraction needs instrumented PG.
            os.chdir(HERE)
            import gen_real_error_pqo as generator

            if not PARAMS_FILE.exists():
                write_params({})
            print(f"  build metadata: {key}")
            generator.parse_query(first_query(path, q, t, args.n), q, t)
            params = read_params()

        if key not in params:
            raise SystemExit(f"metadata generation did not produce key {key}")
        if not args.require_metadata:
            merge_manual_params(key, params)
            params = read_params()
        try:
            count = validate_metadata(key, params[key])
            validate_metadata_against_sample(key, params[key], sample, q)
            validate_manual_params(key, params[key])
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"  metadata sanity OK: {key}, {count} querylets")
        if args.metadata_only:
            continue

        # The old modules use relative paths such as cached_info/ and cardinality/.
        os.chdir(HERE)
        import gen_real_error_pqo as generator

        for name, spec in params[key].items():
            print(f"{name}: {spec}")
            print(f"Building querylet {name}")
            generator.cache_right = {}
            # try:
            generator.gen_real_error(
                "imdb", q, t, args.n, *spec,
                workload=workload,
                base_path=str(root) + os.sep,
                output_path=str(output_root) + os.sep,
            )
            # except Exception as exception:
            #     print(exception)


if __name__ == "__main__":
    main()
