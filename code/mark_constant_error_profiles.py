#!/usr/bin/env python3
"""Mark constant error-profile files by prefixing their names with DEL_.

A profile is constant when the set of its non-empty, stripped lines has
cardinality one.  The default mode is a dry run; pass --apply to rename files.
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


def normalized_lines(path: Path) -> list[str]:
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise ProfileError(f"profile is not UTF-8 text: {path}") from exc


def is_constant_profile(path: Path) -> tuple[bool, int, int]:
    lines = normalized_lines(path)
    unique_count = len(set(lines))
    return bool(lines) and unique_count == 1, len(lines), unique_count


def mark_profiles(root: Path, include: str, prefix: str, apply: bool) -> int:
    directories = [
        path
        for path in profile_directories(root)
        if fnmatch.fnmatch(workload_name(path), include)
    ]
    if not directories:
        raise ProfileError(f"no error_profile directories matched {include!r} under {root}")

    scanned = 0
    constant = 0
    renamed = 0
    empty = 0
    for directory in directories:
        for source in sorted(directory.glob("*.txt")):
            if source.name.startswith(prefix):
                continue
            scanned += 1
            qualifies, line_count, unique_count = is_constant_profile(source)
            if line_count == 0:
                empty += 1
                print(f"SKIP empty: {source}")
                continue
            if not qualifies:
                print(
                    f"KEEP: {source} "
                    f"(rows={line_count}, unique_rows={unique_count})"
                )
                continue

            constant += 1
            destination = source.with_name(prefix + source.name)
            if destination.exists():
                raise ProfileError(
                    f"cannot mark {source}: destination already exists: {destination}"
                )
            action = "RENAME" if apply else "WOULD RENAME"
            print(
                f"{action}: {source} -> {destination.name} "
                f"(rows={line_count}, unique_rows=1)"
            )
            if apply:
                source.rename(destination)
                renamed += 1

    mode = "apply" if apply else "dry-run"
    print(
        f"Summary ({mode}): directories={len(directories)}, scanned={scanned}, "
        f"constant={constant}, renamed={renamed}, empty_skipped={empty}"
    )
    return 0


def restore_profiles(root: Path, include: str, prefix: str, apply: bool) -> int:
    directories = [
        path
        for path in profile_directories(root)
        if fnmatch.fnmatch(workload_name(path), include)
    ]
    if not directories:
        raise ProfileError(f"no error_profile directories matched {include!r} under {root}")

    found = 0
    restored = 0
    for directory in directories:
        for source in sorted(directory.glob(f"{prefix}*.txt")):
            found += 1
            original_name = source.name[len(prefix) :]
            if not original_name:
                raise ProfileError(f"invalid marked filename: {source}")
            destination = source.with_name(original_name)
            if destination.exists():
                raise ProfileError(
                    f"cannot restore {source}: destination already exists: {destination}"
                )
            action = "RESTORE" if apply else "WOULD RESTORE"
            print(f"{action}: {source} -> {destination.name}")
            if apply:
                source.rename(destination)
                restored += 1

    mode = "apply" if apply else "dry-run"
    print(
        f"Restore summary ({mode}): directories={len(directories)}, "
        f"marked={found}, restored={restored}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        help="workload root, one workload directory, or one error_profile directory",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.prefix or "/" in args.prefix:
        print("ERROR: prefix must be a non-empty filename prefix", file=sys.stderr)
        return 2
    try:
        if args.restore:
            return restore_profiles(
                args.root, args.include, args.prefix, args.apply
            )
        return mark_profiles(args.root, args.include, args.prefix, args.apply)
    except (OSError, ProfileError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
