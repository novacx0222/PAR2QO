#!/usr/bin/env python3
"""Mark constant two-column error profiles by prefixing names with ``DEL_``.

A profile qualifies when the set of its parsed ``(true, estimated)`` row
pairs has cardinality one.  Column-separating whitespace is ignored.  The
default mode is a dry run; pass ``--apply`` to perform the validated renames.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path


DEFAULT_PREFIX = "DEL_"


class ProfileError(RuntimeError):
    pass


def profile_directories(root: Path) -> list[Path]:
    if not root.exists():
        raise ProfileError(f"path does not exist: {root}")
    if root.is_file():
        raise ProfileError(f"expected a directory, got a file: {root}")
    if root.name == "error_profile":
        return [root]
    return sorted(path for path in root.rglob("error_profile") if path.is_dir())


def workload_name(profile_dir: Path) -> str:
    return profile_dir.parent.name


def parsed_rows(path: Path) -> list[tuple[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileError(f"profile is not UTF-8 text: {path}") from exc
    rows: list[tuple[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        columns = line.split()
        if len(columns) != 2:
            raise ProfileError(
                f"expected two columns at {path}:{line_number}, got {len(columns)}"
            )
        rows.append((columns[0], columns[1]))
    return rows


def is_constant_profile(path: Path) -> tuple[bool, int, int]:
    rows = parsed_rows(path)
    unique_count = len(set(rows))
    return bool(rows) and unique_count == 1, len(rows), unique_count


def selected_directories(roots: list[Path], include: str) -> list[Path]:
    directories = {
        path.resolve()
        for root in roots
        for path in profile_directories(root.resolve())
        if fnmatch.fnmatch(workload_name(path), include)
    }
    if not directories:
        joined = ", ".join(map(str, roots))
        raise ProfileError(
            f"no error_profile directories matched {include!r} under {joined}"
        )
    return sorted(directories)


def mark_profiles(
    roots: list[Path], include: str, prefix: str, apply: bool, verbose: bool
) -> int:
    directories = selected_directories(roots, include)
    scanned = 0
    constant = 0
    empty = 0
    already_marked = 0
    operations: list[tuple[Path, Path, int]] = []
    for directory in directories:
        for source in sorted(directory.glob("*.txt")):
            if source.name.startswith(prefix):
                already_marked += 1
                continue
            scanned += 1
            qualifies, line_count, unique_count = is_constant_profile(source)
            if line_count == 0:
                empty += 1
                if verbose:
                    print(f"SKIP empty: {source}")
                continue
            if not qualifies:
                if verbose:
                    print(
                        f"KEEP: {source} "
                        f"(rows={line_count}, unique_pairs={unique_count})"
                    )
                continue

            constant += 1
            destination = source.with_name(prefix + source.name)
            if destination.exists():
                raise ProfileError(
                    f"cannot mark {source}: destination already exists: {destination}"
                )
            operations.append((source, destination, line_count))

    action = "RENAME" if apply else "WOULD RENAME"
    for source, destination, line_count in operations:
        print(
            f"{action}: {source} -> {destination.name} "
            f"(rows={line_count}, unique_pairs=1)"
        )
    if apply:
        for source, destination, _ in operations:
            source.rename(destination)

    mode = "apply" if apply else "dry-run"
    print(
        f"Summary ({mode}): directories={len(directories)}, scanned={scanned}, "
        f"constant={constant}, renamed={len(operations) if apply else 0}, "
        f"already_marked={already_marked}, empty_skipped={empty}"
    )
    return 0


def restore_profiles(roots: list[Path], include: str, prefix: str, apply: bool) -> int:
    directories = selected_directories(roots, include)
    operations: list[tuple[Path, Path]] = []
    for directory in directories:
        for source in sorted(directory.glob(f"{prefix}*.txt")):
            original_name = source.name[len(prefix) :]
            if not original_name:
                raise ProfileError(f"invalid marked filename: {source}")
            destination = source.with_name(original_name)
            if destination.exists():
                raise ProfileError(
                    f"cannot restore {source}: destination already exists: {destination}"
                )
            operations.append((source, destination))

    action = "RESTORE" if apply else "WOULD RESTORE"
    for source, destination in operations:
        print(f"{action}: {source} -> {destination.name}")
    if apply:
        for source, destination in operations:
            source.rename(destination)

    mode = "apply" if apply else "dry-run"
    print(
        f"Restore summary ({mode}): directories={len(directories)}, "
        f"marked={len(operations)}, restored={len(operations) if apply else 0}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        type=Path,
        nargs="+",
        help=(
            "one or more workload roots, workload directories, or "
            "error_profile directories"
        ),
    )
    parser.add_argument(
        "--include",
        default="*",
        help="workload directory glob, for example '17-0_cardinality'",
    )
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform renames; omission means dry-run only",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="restore DEL_*.txt names instead of detecting constant profiles",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also print non-constant and empty files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.prefix or "/" in args.prefix:
        print("ERROR: prefix must be a non-empty filename prefix", file=sys.stderr)
        return 2
    try:
        if args.restore:
            return restore_profiles(
                args.roots, args.include, args.prefix, args.apply
            )
        return mark_profiles(
            args.roots, args.include, args.prefix, args.apply, args.verbose
        )
    except (OSError, ProfileError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
