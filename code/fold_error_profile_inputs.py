#!/usr/bin/env python3
"""Prepare and validate per-fold inputs for the IMDb error-profile builder.

The fold CSV files are ownership lists.  Every listed query belongs to that
fold; there is deliberately no train/test filtering in this script.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from pathlib import Path


HERE = Path(__file__).resolve().parent
MAPPING_FILE = HERE / "cached_info" / "query_to_local_selection_dict.json"
REQUIRED_COLUMNS = {
    "fold_id",
    "global_query_idx",
    "fold_query_idx",
    "query_group_id",
    "template_id",
    "original_query_id",
    "candidate_count",
}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def output_root(prefix: Path, fold_id: int) -> Path:
    return Path(f"{prefix}-{fold_id}")


def fold_csv(source_root: Path, fold_id: int) -> Path:
    return source_root / "folds" / f"robdp_fold_{fold_id}.csv"


def read_ownership(path: Path, expected_fold: int) -> list[dict[str, int]]:
    if not path.is_file():
        fail(f"missing ownership CSV: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fields
        if missing:
            fail(f"{path}: missing columns: {', '.join(sorted(missing))}")

        rows: list[dict[str, int]] = []
        for line_number, raw in enumerate(reader, start=2):
            try:
                row = {name: int(raw[name]) for name in REQUIRED_COLUMNS}
            except (TypeError, ValueError) as exc:
                fail(f"{path}:{line_number}: non-integer ownership field: {exc}")
            if row["fold_id"] != expected_fold:
                fail(
                    f"{path}:{line_number}: fold_id={row['fold_id']}, "
                    f"expected {expected_fold}"
                )
            if row["candidate_count"] < 1:
                fail(f"{path}:{line_number}: candidate_count must be positive")
            rows.append(row)

    if not rows:
        fail(f"empty ownership CSV: {path}")

    global_ids = [row["global_query_idx"] for row in rows]
    pairs = [(row["template_id"], row["original_query_id"]) for row in rows]
    if len(global_ids) != len(set(global_ids)):
        fail(f"{path}: duplicate global_query_idx")
    if len(pairs) != len(set(pairs)):
        fail(f"{path}: duplicate (template_id, original_query_id)")

    fold_positions = sorted(row["fold_query_idx"] for row in rows)
    if fold_positions != list(range(len(rows))):
        fail(f"{path}: fold_query_idx is not contiguous from 0")
    return rows


def validate_ownership_set(rows_by_fold: dict[int, list[dict[str, int]]]) -> None:
    seen_global: dict[int, int] = {}
    seen_pair: dict[tuple[int, int], int] = {}
    for fold_id, rows in rows_by_fold.items():
        for row in rows:
            global_id = row["global_query_idx"]
            pair = (row["template_id"], row["original_query_id"])
            if global_id in seen_global:
                fail(
                    f"global_query_idx {global_id} is owned by folds "
                    f"{seen_global[global_id]} and {fold_id}"
                )
            if pair in seen_pair:
                fail(
                    f"query {pair} is owned by folds {seen_pair[pair]} and {fold_id}"
                )
            seen_global[global_id] = fold_id
            seen_pair[pair] = fold_id


def normalize_predicate_line(
    raw: str, source: Path, line_number: int, template_id: int
) -> str:
    """Validate one legacy predicate-list line and remove its trailing comma.

    These files look like JSON, but some conditions contain unescaped double
    quotes.  Preserve the original text because the repository's converter has
    always parsed this format by splitting on the `", "` separator.
    """
    text = raw.strip()
    if text.endswith(","):
        text = text[:-1]
    if not (text.startswith('["') and text.endswith('"]')):
        fail(f"{source}:{line_number}: malformed legacy predicate list")
    elements = text[1:-1].split('", "')
    elements = [element.removeprefix('"').removesuffix('"') for element in elements]
    if not elements:
        fail(f"{source}:{line_number}: empty predicate list")

    mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    aliases = mapping.get(f"{template_id}-0")
    if aliases is None:
        fail(f"missing predicate mapping for {template_id}-0 in {MAPPING_FILE}")

    # Template 18 stores n.gender and n.name as two source fields, while the
    # historical sample CSV (and current mapping) represents them as one local
    # selection.  Reproduce that established format.
    if template_id == 18 and len(elements) == 5 and len(aliases) == 4:
        elements[3] = f"{elements[3]} and {elements[4]}"
        elements.pop()

    if len(elements) != len(aliases):
        fail(
            f"{source}:{line_number}: {len(elements)} predicates but "
            f"mapping {template_id}-0 has {len(aliases)} columns"
        )
    return '["' + '", "'.join(elements) + '"]'


def load_reference(
    reference_root: Path, template_id: int
) -> tuple[dict[str, str], list[str]]:
    workload = reference_root / f"{template_id}-0_cardinality"
    raw_dir = workload / "raw_data"
    json_path = raw_dir / f"{template_id}-0_testing.json"
    txt_path = raw_dir / f"{template_id}-0_testing.txt"
    if not json_path.is_file():
        fail(f"missing reference SQL JSON: {json_path}")
    if not txt_path.is_file():
        fail(f"missing reference predicate TXT: {txt_path}")

    try:
        sql_data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"cannot read {json_path}: {exc}")
    if not isinstance(sql_data, dict):
        fail(f"{json_path}: expected a JSON object")

    lines = txt_path.read_text(encoding="utf-8").splitlines()
    predicates = [
        normalize_predicate_line(line, txt_path, index + 1, template_id)
        for index, line in enumerate(lines)
    ]
    return sql_data, predicates


def write_predicates(path: Path, rows: list[str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index, predicate_line in enumerate(rows):
            suffix = "," if index + 1 < len(rows) else ""
            handle.write(predicate_line + suffix + "\n")


def build_sample_csv(
    fold_root: Path,
    template_id: int,
    owned_count: int,
    sample_label: int,
) -> None:
    # Reuse the repository's original predicate-to-frequency conversion logic.
    from trans_pqo_combination_to_csv import main as convert_to_sample_csv

    output = fold_root / f"{template_id}-0_cardinality" / f"sample-{sample_label}.csv"
    with redirect_stdout(io.StringIO()):
        convert_to_sample_csv(
            template_id,
            owned_count,
            0,
            "cardinality",
            str(fold_root) + "/",
            str(output),
        )


def expected_table_totals(template_id: int, owned_count: int) -> Counter[str]:
    mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    key = f"{template_id}-0"
    if key not in mapping:
        fail(f"missing predicate mapping for {key} in {MAPPING_FILE}")
    aliases = Counter(mapping[key])
    return Counter({alias: copies * owned_count for alias, copies in aliases.items()})


def validate_sample_csv(path: Path, template_id: int, owned_count: int) -> None:
    if not path.is_file():
        fail(f"missing sample CSV: {path}")
    actual = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["Table", "Condition", "Frequency"]:
            fail(f"{path}: unexpected header {reader.fieldnames}")
        row_count = 0
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            table = row.get("Table", "")
            condition = row.get("Condition", "")
            if not table or not condition:
                fail(f"{path}:{line_number}: empty table or condition")
            try:
                frequency = int(row["Frequency"])
            except (TypeError, ValueError):
                fail(f"{path}:{line_number}: invalid frequency {row.get('Frequency')!r}")
            if frequency <= 0:
                fail(f"{path}:{line_number}: frequency must be positive")
            actual[table] += frequency
    if row_count == 0:
        fail(f"{path}: no sample rows")

    expected = expected_table_totals(template_id, owned_count)
    if actual != expected:
        fail(f"{path}: table frequency totals {dict(actual)} != expected {dict(expected)}")


def group_by_template(rows: list[dict[str, int]]) -> dict[int, list[dict[str, int]]]:
    grouped: dict[int, list[dict[str, int]]] = defaultdict(list)
    for row in rows:
        grouped[row["template_id"]].append(row)
    for owned_rows in grouped.values():
        owned_rows.sort(key=lambda row: row["fold_query_idx"])
    return dict(sorted(grouped.items()))


def prepare_samples(
    source_root: Path,
    reference_root: Path,
    prefix: Path,
    folds: list[int],
    sample_label: int,
) -> None:
    rows_by_fold = {fold: read_ownership(fold_csv(source_root, fold), fold) for fold in folds}
    validate_ownership_set(rows_by_fold)

    reference_cache: dict[int, tuple[dict[str, str], list[str]]] = {}
    for fold_id, rows in rows_by_fold.items():
        destination = output_root(prefix, fold_id)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fold_csv(source_root, fold_id), destination / "ownership.csv")
        manifest_rows: list[dict[str, object]] = []

        for template_id, owned_rows in group_by_template(rows).items():
            if template_id not in reference_cache:
                reference_cache[template_id] = load_reference(reference_root, template_id)
            sql_data, predicates = reference_cache[template_id]

            selected_sql: dict[str, str] = {}
            selected_predicates: list[str] = []
            selected_ids: list[int] = []
            for row in owned_rows:
                original_id = row["original_query_id"]
                key = f"{template_id}-0_testing_{original_id}"
                if key not in sql_data:
                    fail(f"missing {key} in reference SQL JSON")
                if original_id < 0 or original_id >= len(predicates):
                    fail(
                        f"template {template_id}: predicate index {original_id} "
                        f"outside 0..{len(predicates) - 1}"
                    )
                selected_sql[key] = sql_data[key]
                selected_predicates.append(predicates[original_id])
                selected_ids.append(original_id)

            workload_dir = destination / f"{template_id}-0_cardinality"
            raw_dir = workload_dir / "raw_data"
            raw_dir.mkdir(parents=True, exist_ok=True)
            count = len(owned_rows)
            txt_name = f"{template_id}-0_{count}_training.txt"
            json_name = f"{template_id}-0_training_{sample_label}.json"
            write_predicates(raw_dir / txt_name, selected_predicates)
            (raw_dir / json_name).write_text(
                json.dumps(selected_sql, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with (raw_dir / "owned_query_ids.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["template_id", "original_query_id"])
                writer.writerows((template_id, query_id) for query_id in selected_ids)

            build_sample_csv(destination, template_id, count, sample_label)
            validate_sample_csv(
                workload_dir / f"sample-{sample_label}.csv",
                template_id,
                count,
            )
            manifest_rows.append(
                {
                    "fold_id": fold_id,
                    "template_id": template_id,
                    "workload": workload_dir.name,
                    "owned_query_count": count,
                    "sample_label": sample_label,
                    "sample_csv": f"{workload_dir.name}/sample-{sample_label}.csv",
                }
            )
            print(f"fold {fold_id} template {template_id}: {count} owned queries -> sample-{sample_label}.csv")

        manifest = destination / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = [
                "fold_id",
                "template_id",
                "workload",
                "owned_query_count",
                "sample_label",
                "sample_csv",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest_rows)
        print(f"fold {fold_id}: wrote {len(manifest_rows)} workloads under {destination}")


def read_manifest(root: Path, expected_fold: int) -> list[dict[str, str]]:
    path = root / "manifest.csv"
    if not path.is_file():
        fail(f"missing manifest: {path}; run the samples stage first")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        fail(f"empty manifest: {path}")
    for row in rows:
        if int(row["fold_id"]) != expected_fold:
            fail(f"{path}: unexpected fold_id {row['fold_id']}")
    return rows


def check_samples(
    source_root: Path,
    prefix: Path,
    folds: list[int],
    sample_label: int,
) -> None:
    rows_by_fold = {fold: read_ownership(fold_csv(source_root, fold), fold) for fold in folds}
    validate_ownership_set(rows_by_fold)

    for fold_id, ownership_rows in rows_by_fold.items():
        root = output_root(prefix, fold_id)
        manifest = read_manifest(root, fold_id)
        expected_groups = group_by_template(ownership_rows)
        if len(manifest) != len(expected_groups):
            fail(
                f"{root}/manifest.csv: {len(manifest)} workloads, "
                f"expected {len(expected_groups)}"
            )
        seen_templates: set[int] = set()
        for row in manifest:
            template_id = int(row["template_id"])
            seen_templates.add(template_id)
            if template_id not in expected_groups:
                fail(f"{root}/manifest.csv: unexpected template {template_id}")
            owned_count = len(expected_groups[template_id])
            if int(row["owned_query_count"]) != owned_count:
                fail(f"template {template_id}: manifest ownership count mismatch")
            if int(row["sample_label"]) != sample_label:
                fail(f"template {template_id}: sample label mismatch")

            workload = root / row["workload"]
            raw_dir = workload / "raw_data"
            txt_path = raw_dir / f"{template_id}-0_{owned_count}_training.txt"
            json_path = raw_dir / f"{template_id}-0_training_{sample_label}.json"
            ids_path = raw_dir / "owned_query_ids.csv"
            if not txt_path.is_file() or len(txt_path.read_text(encoding="utf-8").splitlines()) != owned_count:
                fail(f"{txt_path}: missing or wrong line count")
            if not json_path.is_file():
                fail(f"missing {json_path}")
            sql_data = json.loads(json_path.read_text(encoding="utf-8"))
            if len(sql_data) != owned_count:
                fail(f"{json_path}: {len(sql_data)} SQLs, expected {owned_count}")
            if not ids_path.is_file():
                fail(f"missing {ids_path}")
            validate_sample_csv(
                workload / f"sample-{sample_label}.csv",
                template_id,
                owned_count,
            )
        if seen_templates != set(expected_groups):
            fail(f"{root}/manifest.csv: template coverage mismatch")
        print(
            f"sample sanity OK: fold {fold_id}, {len(ownership_rows)} queries, "
            f"{len(expected_groups)} workloads"
        )


def check_profiles(
    prefix: Path,
    folds: list[int],
    include: str,
) -> None:
    for fold_id in folds:
        root = output_root(prefix, fold_id)
        manifest = read_manifest(root, fold_id)
        checked_workloads = 0
        checked_files = 0
        checked_values = 0
        for row in manifest:
            workload_name = row["workload"]
            if not fnmatch.fnmatch(workload_name, include):
                continue
            checked_workloads += 1
            profile_dir = root / workload_name / "error_profile"
            files = sorted(profile_dir.glob("*.txt")) if profile_dir.is_dir() else []
            if not files:
                fail(f"no error-profile TXT files under {profile_dir}")
            for path in files:
                lines = path.read_text(encoding="utf-8").splitlines()
                if not lines:
                    fail(f"empty error profile: {path}")
                for line_number, line in enumerate(lines, start=1):
                    fields = line.split()
                    if len(fields) != 2:
                        fail(f"{path}:{line_number}: expected two numeric columns")
                    try:
                        true_selectivity, estimated_selectivity = map(float, fields)
                    except ValueError:
                        fail(f"{path}:{line_number}: invalid numeric values")
                    if not (
                        math.isfinite(true_selectivity)
                        and math.isfinite(estimated_selectivity)
                        and true_selectivity > 0
                        and estimated_selectivity > 0
                    ):
                        fail(f"{path}:{line_number}: selectivities must be finite and positive")
                    checked_values += 1
                checked_files += 1
        if checked_workloads == 0:
            fail(f"fold {fold_id}: no workloads matched {include!r}")
        print(
            f"profile sanity OK: fold {fold_id}, {checked_workloads} workloads, "
            f"{checked_files} files, {checked_values} profile rows"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("samples", "check-samples", "check-profiles")
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/data/robdp/imdb-separate-ep-0826"),
        help="root containing folds/robdp_fold_N.csv",
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path("/data/robdp/imdb-error-profile-0826"),
        help="reference cardinality workload containing testing JSON/TXT",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("/data/robdp/imdb-separate-ep-0826"),
        help="PREFIX creates PREFIX-1 and PREFIX-2",
    )
    parser.add_argument("--folds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--sample-label", type=int, default=50)
    parser.add_argument(
        "--include", default="*", help="workload glob for profile sanity checking"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "samples":
            prepare_samples(
                args.source_root,
                args.reference_root,
                args.output_prefix,
                args.folds,
                args.sample_label,
            )
            check_samples(
                args.source_root, args.output_prefix, args.folds, args.sample_label
            )
        elif args.command == "check-samples":
            check_samples(
                args.source_root, args.output_prefix, args.folds, args.sample_label
            )
        else:
            check_profiles(args.output_prefix, args.folds, args.include)
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
