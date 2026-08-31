#!/usr/bin/env python3
"""Inventory and safely rename generated error-profile files.

The generated profiles use querylet-oriented names such as
``mi_idx_it_both.txt``.  The original workload uses canonical relation names
such as ``it=mi_idx.txt``.  This tool creates an auditable CSV mapping and can
then apply only the rows explicitly marked as rename operations.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path


WORKLOAD_RE = re.compile(r"\d+-\d+_cardinality")
PROFILE_SUFFIX_RE = re.compile(r"_(both|pure|l|r|l_\d+|r_\d+)$")
CSV_FIELDS = [
    "target_root",
    "workload",
    "source_filename",
    "target_filename",
    "status",
    "reason",
    "reference_exists",
    "source_exists",
    "collision_sources",
]
RENAME_STATUSES = {"rename", "rename_collision_winner"}


def profile_files(root: Path, workload: str) -> set[str]:
    directory = root / workload / "error_profile"
    if not directory.is_dir():
        return set()
    return {path.name for path in directory.glob("*.txt") if path.is_file()}


def workload_names(root: Path) -> set[str]:
    if not root.is_dir():
        raise ValueError(f"directory does not exist: {root}")
    return {
        path.name
        for path in root.iterdir()
        if path.is_dir() and WORKLOAD_RE.fullmatch(path.name)
    }


def relation_aliases(reference_root: Path, workloads: set[str]) -> set[str]:
    aliases: set[str] = set()
    for workload in workloads:
        for filename in profile_files(reference_root, workload):
            stem = Path(filename).stem
            aliases.update(stem.split("="))
    return aliases


def canonical_name(
    filename: str,
    aliases: set[str],
    reference_names: set[str],
) -> tuple[str | None, str]:
    """Return the old-style filename and a short mapping explanation."""
    if filename in reference_names:
        return filename, "already uses the reference filename"

    stem = Path(filename).stem
    if stem in aliases:
        return filename, "single-table profile"

    context = ""
    if "__" in stem:
        pair_part, context = stem.split("__", 1)
        join_kind = "context"
    else:
        match = PROFILE_SUFFIX_RE.search(stem)
        if not match:
            return None, "unrecognized generated filename"
        join_kind = match.group(1)
        pair_part = stem[: match.start()]

    matches = [
        (left, right)
        for left in aliases
        for right in aliases
        if left != right and f"{left}_{right}" == pair_part
    ]
    if len(matches) != 1:
        detail = "no alias pair" if not matches else f"{len(matches)} alias pairs"
        return None, f"cannot parse {pair_part!r}: {detail}"

    left, right = matches[0]
    target = "=".join(sorted((left, right))) + ".txt"
    reason = f"{join_kind} querylet for {left}/{right}"
    if context:
        reason += f"; ignored context __{context}"
    return target, reason


def collision_rank(filename: str) -> tuple[int, str]:
    stem = Path(filename).stem
    if stem.endswith("_both"):
        return 3, filename
    if re.search(r"_(l|r)(?:_\d+)?$", stem):
        return 2, filename
    if stem.endswith("_pure"):
        return 1, filename
    return 0, filename


def inventory(reference_root: Path, target_roots: list[Path]) -> list[dict[str, str]]:
    reference_workloads = workload_names(reference_root)
    all_workloads = set(reference_workloads)
    for root in target_roots:
        all_workloads.update(workload_names(root))
    aliases = relation_aliases(reference_root, reference_workloads)

    rows: list[dict[str, str]] = []
    for root in target_roots:
        for workload in sorted(all_workloads, key=workload_sort_key):
            reference_names = profile_files(reference_root, workload)
            source_names = profile_files(root, workload)
            mapped: dict[str, tuple[str | None, str]] = {
                source: canonical_name(source, aliases, reference_names)
                for source in source_names
            }
            by_target: dict[str, list[str]] = defaultdict(list)
            for source, (target, _) in mapped.items():
                if target is not None:
                    by_target[target].append(source)

            covered_reference: set[str] = set()
            for source in sorted(source_names):
                target, reason = mapped[source]
                status: str
                collisions: list[str] = []
                if target is None:
                    status = "unparseable"
                elif target not in reference_names:
                    status = "unexpected_target"
                    reason += "; canonical target is absent from reference workload"
                else:
                    collisions = sorted(by_target[target])
                    if len(collisions) == 1:
                        status = "unchanged" if source == target else "rename"
                        covered_reference.add(target)
                    else:
                        ranked = sorted(
                            collisions,
                            key=lambda name: collision_rank(name),
                            reverse=True,
                        )
                        top_rank = collision_rank(ranked[0])[0]
                        winners = [
                            name for name in ranked if collision_rank(name)[0] == top_rank
                        ]
                        if len(winners) == 1 and source == winners[0]:
                            status = "rename_collision_winner"
                            reason += "; selected highest-priority _both variant"
                            covered_reference.add(target)
                        else:
                            status = "collision_extra_kept"
                            reason += "; kept under generated name to avoid data loss"

                rows.append(
                    {
                        "target_root": str(root),
                        "workload": workload,
                        "source_filename": source,
                        "target_filename": target or "",
                        "status": status,
                        "reason": reason,
                        "reference_exists": str(bool(target and target in reference_names)).lower(),
                        "source_exists": "true",
                        "collision_sources": "|".join(collisions),
                    }
                )

            for missing in sorted(reference_names - covered_reference):
                rows.append(
                    {
                        "target_root": str(root),
                        "workload": workload,
                        "source_filename": "",
                        "target_filename": missing,
                        "status": "missing_from_target",
                        "reason": "reference profile has no corresponding generated file",
                        "reference_exists": "true",
                        "source_exists": "false",
                        "collision_sources": "",
                    }
                )
    return rows


def workload_sort_key(name: str) -> tuple[int, int, str]:
    prefix = name.removesuffix("_cardinality")
    query, template = prefix.split("-", 1)
    return int(query), int(template), name


def write_mapping(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_mapping(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(
                f"unexpected CSV columns in {path}: {reader.fieldnames}; "
                f"expected {CSV_FIELDS}"
            )
        return list(reader)


def print_summary(rows: list[dict[str, str]]) -> None:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[row["target_root"]][row["status"]] += 1
    for root in sorted(grouped):
        counts = grouped[root]
        print(root)
        for status in sorted(counts):
            print(f"  {status}: {counts[status]}")


def verify_against_reference(reference_root: Path, target_roots: list[Path]) -> bool:
    reference_workloads = workload_names(reference_root)
    reference_total = sum(
        len(profile_files(reference_root, workload))
        for workload in reference_workloads
    )
    clean = True
    for root in target_roots:
        target_workloads = workload_names(root)
        included = 0
        missing_rows: list[tuple[str, str]] = []
        extra_rows: list[tuple[str, str]] = []
        for workload in sorted(reference_workloads | target_workloads, key=workload_sort_key):
            reference_names = profile_files(reference_root, workload)
            target_names = profile_files(root, workload)
            included += len(reference_names & target_names)
            missing_rows.extend((workload, name) for name in sorted(reference_names - target_names))
            extra_rows.extend((workload, name) for name in sorted(target_names - reference_names))
        print(root)
        print(f"  reference profiles included: {included}/{reference_total}")
        print(f"  missing: {len(missing_rows)}")
        for workload, filename in missing_rows:
            print(f"    missing {workload}/error_profile/{filename}")
        print(f"  extra: {len(extra_rows)}")
        for workload, filename in extra_rows:
            print(f"    extra {workload}/error_profile/{filename}")
        clean = clean and not missing_rows and not extra_rows
    return clean


def safe_profile_path(root: Path, workload: str, filename: str) -> Path:
    if not WORKLOAD_RE.fullmatch(workload):
        raise ValueError(f"unsafe workload in mapping: {workload!r}")
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise ValueError(f"unsafe filename in mapping: {filename!r}")
    path = root / workload / "error_profile" / filename
    if not path.resolve(strict=False).is_relative_to(root.resolve()):
        raise ValueError(f"mapping escapes target root: {path}")
    return path


def rename_from_mapping(
    rows: list[dict[str, str]],
    target_roots: list[Path],
    apply: bool,
    backup_suffix: str | None,
    verbose: bool,
) -> None:
    allowed_roots = {str(path.resolve()): path.resolve() for path in target_roots}
    operations: list[tuple[Path, Path]] = []
    for row in rows:
        if row["status"] not in RENAME_STATUSES:
            continue
        row_root = str(Path(row["target_root"]).resolve())
        if row_root not in allowed_roots:
            continue
        root = allowed_roots[row_root]
        source = safe_profile_path(root, row["workload"], row["source_filename"])
        target = safe_profile_path(root, row["workload"], row["target_filename"])
        if source == target:
            continue
        operations.append((source, target))

    destinations = Counter(target for _, target in operations)
    duplicate_destinations = [str(path) for path, count in destinations.items() if count > 1]
    if duplicate_destinations:
        raise ValueError(
            "mapping contains duplicate rename destinations: "
            + ", ".join(duplicate_destinations)
        )
    for source, target in operations:
        if not source.is_file():
            raise FileNotFoundError(f"rename source does not exist: {source}")
        if target.exists():
            raise FileExistsError(f"rename target already exists: {target}")

    print(f"rename operations: {len(operations)}")
    if verbose:
        for source, target in operations:
            print(f"  {source} -> {target}")
    if not apply:
        print("dry-run only; pass --apply to rename")
        return

    if not backup_suffix:
        raise ValueError("--apply requires --backup-suffix")
    if "/" in backup_suffix or backup_suffix in {".", ".."}:
        raise ValueError("--backup-suffix must be a simple path suffix")

    backup_paths: list[Path] = []
    for root in target_roots:
        root = root.resolve()
        backup = root.with_name(root.name + backup_suffix)
        if backup.exists():
            raise FileExistsError(f"backup target already exists: {backup}")
        backup_paths.append(backup)
    for root, backup in zip(target_roots, backup_paths):
        print(f"backup: {root.resolve()} -> {backup}")
        shutil.copytree(root.resolve(), backup, copy_function=shutil.copy2)

    staged: list[tuple[Path, Path, Path]] = []
    try:
        for source, target in operations:
            temporary = source.with_name(f".rename-{uuid.uuid4().hex}-{source.name}")
            source.rename(temporary)
            staged.append((source, temporary, target))
    except Exception:
        for source, temporary, _ in reversed(staged):
            if temporary.exists() and not source.exists():
                temporary.rename(source)
        raise

    for _, temporary, target in staged:
        temporary.rename(target)
    print(f"renamed {len(staged)} files; backups: {', '.join(map(str, backup_paths))}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory", help="compare roots and write an auditable mapping CSV"
    )
    inventory_parser.add_argument("--reference-root", required=True, type=Path)
    inventory_parser.add_argument(
        "--target-root", required=True, action="append", type=Path
    )
    inventory_parser.add_argument("--mapping-csv", required=True, type=Path)

    rename_parser = subparsers.add_parser(
        "rename", help="rename rows marked by the mapping CSV"
    )
    rename_parser.add_argument("--mapping-csv", required=True, type=Path)
    rename_parser.add_argument(
        "--target-root", required=True, action="append", type=Path
    )
    rename_parser.add_argument(
        "--apply", action="store_true", help="perform changes; default is dry-run"
    )
    rename_parser.add_argument(
        "--backup-suffix",
        help="required with --apply, e.g. .backup-before-rename-20260831",
    )
    rename_parser.add_argument(
        "--verbose", action="store_true", help="print every source/destination pair"
    )

    verify_parser = subparsers.add_parser(
        "verify", help="compare final target filenames directly with the reference"
    )
    verify_parser.add_argument("--reference-root", required=True, type=Path)
    verify_parser.add_argument(
        "--target-root", required=True, action="append", type=Path
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "inventory":
            rows = inventory(args.reference_root.resolve(), [p.resolve() for p in args.target_root])
            write_mapping(rows, args.mapping_csv.resolve())
            print(f"wrote {len(rows)} rows to {args.mapping_csv.resolve()}")
            print_summary(rows)
        elif args.command == "rename":
            rows = read_mapping(args.mapping_csv.resolve())
            print_summary(rows)
            rename_from_mapping(
                rows,
                [p.resolve() for p in args.target_root],
                args.apply,
                args.backup_suffix,
                args.verbose,
            )
        else:
            verify_against_reference(
                args.reference_root.resolve(),
                [p.resolve() for p in args.target_root],
            )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
