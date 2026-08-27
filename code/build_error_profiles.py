#!/usr/bin/env python3
"""Thin batch runner for the repository's original error-profile generator."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMS_FILE = HERE / "cached_info/gen_real_error_params.json"
ROBUST_PARAMS_FILE = HERE / "cached_info/gen_real_error_params_rob.json"
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


def cached_robust_params(key: str) -> dict | None:
    """Reuse robust-workload metadata when it is identical across DB instances."""
    candidates = [
        value
        for name, value in read_params(ROBUST_PARAMS_FILE).items()
        if name.startswith(key + "-")
    ]
    if candidates and all(value == candidates[0] for value in candidates[1:]):
        return candidates[0]
    return None


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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

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

        # The old modules use relative paths such as cached_info/ and cardinality/.
        os.chdir(HERE)
        import gen_real_error_pqo as generator

        key = f"{q}-{t}"
        if key not in params:
            reused = cached_robust_params(key)
            if reused is not None:
                print(f"  reuse cached querylet metadata: {key}")
                params[key] = reused
        if args.refresh_meta or key not in params:
            PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not PARAMS_FILE.exists():
                PARAMS_FILE.write_text("{}\n", encoding="utf-8")
            print(f"  build metadata: {key}")
            generator.parse_query(first_query(path, q, t, args.n), q, t)
            params = read_params()

        for name, spec in params[key].items():
            print(f"  build querylet {name}")
            generator.cache_right = {}
            generator.gen_real_error(
                "imdb", q, t, args.n, *spec,
                workload=workload,
                base_path=str(root) + os.sep,
                output_path=str(output_root) + os.sep,
            )


if __name__ == "__main__":
    main()
