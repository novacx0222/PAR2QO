#!/usr/bin/env python3
"""Compare rebuilt error profiles with an existing baseline workload."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


GENERATED_SUFFIX_RE = re.compile(r"-q\d+-t\d+-\d+$")
JOIN_SUFFIXES = ("_both", "_l", "_r")


def read_profiles(directory: Path) -> dict[str, list[str]]:
    if not directory.is_dir():
        raise ValueError(f"profile directory does not exist: {directory}")
    result: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.txt")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError(f"empty profile: {path}")
        for number, line in enumerate(lines, start=1):
            fields = line.split()
            if len(fields) != 2:
                raise ValueError(f"{path}:{number}: expected two columns")
            try:
                float(fields[0])
                float(fields[1])
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: invalid numeric row") from exc
        result[path.stem] = lines
    if not result:
        raise ValueError(f"no *.txt profiles under {directory}")
    return result


def canonical_generated_name(name: str, baseline_names: set[str]) -> str | None:
    internal = GENERATED_SUFFIX_RE.sub("", name)
    if internal in baseline_names:
        return internal

    relation = internal
    for suffix in JOIN_SUFFIXES:
        if relation.endswith(suffix):
            relation = relation[: -len(suffix)]
            break

    for baseline in baseline_names:
        aliases = baseline.split("=")
        if len(aliases) != 2:
            continue
        left, right = aliases
        if relation in (f"{left}_{right}", f"{right}_{left}"):
            return baseline
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_workload", type=Path)
    parser.add_argument("rebuilt_workload", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also require identical filenames, row order, and bytes",
    )
    args = parser.parse_args()

    baseline_dir = args.baseline_workload / "error_profile"
    rebuilt_dir = args.rebuilt_workload / "error_profile"
    try:
        baseline = read_profiles(baseline_dir)
        rebuilt = read_profiles(rebuilt_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    exact_filenames = set(baseline) == set(rebuilt)
    mapped: dict[str, tuple[str, list[str]]] = {}
    unresolved: list[str] = []
    for generated_name, rows in rebuilt.items():
        canonical = canonical_generated_name(generated_name, set(baseline))
        if canonical is None or canonical in mapped:
            unresolved.append(generated_name)
        else:
            mapped[canonical] = (generated_name, rows)

    missing = sorted(set(baseline) - set(mapped))
    extra = sorted(unresolved)
    unordered_mismatches: list[str] = []
    ordered_mismatches: list[str] = []
    byte_mismatches: list[str] = []

    for canonical in sorted(set(baseline) & set(mapped)):
        generated_name, generated_rows = mapped[canonical]
        baseline_rows = baseline[canonical]
        if Counter(baseline_rows) != Counter(generated_rows):
            unordered_mismatches.append(canonical)
        if baseline_rows != generated_rows:
            ordered_mismatches.append(canonical)
        baseline_path = baseline_dir / f"{canonical}.txt"
        rebuilt_path = rebuilt_dir / f"{generated_name}.txt"
        if baseline_path.read_bytes() != rebuilt_path.read_bytes():
            byte_mismatches.append(canonical)

    semantic_ok = not missing and not extra and not unordered_mismatches
    strict_ok = (
        semantic_ok
        and exact_filenames
        and not ordered_mismatches
        and not byte_mismatches
    )

    print(f"Baseline: {baseline_dir}")
    print(f"Rebuilt:  {rebuilt_dir}")
    print(f"Profiles: baseline={len(baseline)}, rebuilt={len(rebuilt)}")
    print(f"Exact filenames: {'YES' if exact_filenames else 'NO'}")
    print(f"Same two-column rows, ignoring order: {'YES' if semantic_ok else 'NO'}")
    print(f"Same row order after name mapping: {'YES' if not ordered_mismatches and semantic_ok else 'NO'}")
    print(f"Byte-identical after name mapping: {'YES' if not byte_mismatches and semantic_ok else 'NO'}")
    if missing:
        print("Missing baseline profiles: " + ", ".join(missing))
    if extra:
        print("Unmapped rebuilt profiles: " + ", ".join(extra))
    if unordered_mismatches:
        print("Data mismatches: " + ", ".join(unordered_mismatches))

    if args.strict:
        return 0 if strict_ok else 1
    return 0 if semantic_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
