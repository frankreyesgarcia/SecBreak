import json
import re
from pathlib import Path

from detect_bcs import detect_maven_bcs, detect_python_bcs
from pipeline_utils import DATA_DIR, LOGS_DIR, load_jsonl, setup_logger


RAW_PATH = DATA_DIR / "raw_prs_corrected.jsonl"
BC_PATH = DATA_DIR / "bc_results_corrected.jsonl"
ERROR_LOG = LOGS_DIR / "improve_corrected_results.log"

PLACEHOLDER_DEPS = {"name", "to", "existing"}


def parse_table_triplet(body: str):
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        package_cell = cells[0]
        old_version = cells[-2].strip("` ")
        new_version = cells[-1].strip("` ")
        if not old_version or not new_version:
            continue
        if old_version.lower() in {"from", "---"} or new_version.lower() in {"to", "---"}:
            continue
        if not (re.search(r"\d", old_version) and re.search(r"\d", new_version)):
            continue
        link_match = re.search(r"\[([^\]]+)\]\([^)]+\)", package_cell)
        dep = link_match.group(1).strip() if link_match else package_cell.strip("` ")
        return dep, old_version, new_version
    return None, None, None


def should_replace_dep(row, candidate_dep: str) -> bool:
    if not candidate_dep:
        return False
    current_dep = row.get("dependency_name")
    if not current_dep:
        return True
    if current_dep in PLACEHOLDER_DEPS:
        return True
    if row.get("ecosystem") == "maven" and ":" not in str(current_dep) and ":" in candidate_dep:
        return True
    return False


def repair_raw_rows(rows):
    repaired = []
    changed_keys = set()
    dep_changes = 0
    version_changes = 0
    for row in rows:
        updated = dict(row)
        table_dep, table_old, table_new = parse_table_triplet(row.get("pr_body") or "")
        changed = False

        if updated.get("old_version") in {None, "|"} and table_old:
            updated["old_version"] = table_old
            version_changes += 1
            changed = True
        if updated.get("new_version") in {None, "|"} and table_new:
            updated["new_version"] = table_new
            version_changes += 1
            changed = True
        if should_replace_dep(updated, table_dep):
            updated["dependency_name"] = table_dep
            dep_changes += 1
            changed = True

        if changed:
            updated["metadata_repaired_in_improve"] = True
            changed_keys.add((updated["repo_full_name"], updated["pr_number"]))
        repaired.append(updated)
    return repaired, changed_keys, dep_changes, version_changes


def rerun_rows(raw_rows, bc_rows, changed_keys, logger):
    raw_by_key = {(row["repo_full_name"], row["pr_number"]): row for row in raw_rows}
    rerun_errors = {"source_extraction_failed"}
    out_rows = []
    rerun_count = 0
    improved_count = 0
    for row in bc_rows:
        key = (row["repo_full_name"], row["pr_number"])
        should_rerun = key in changed_keys or row.get("analysis_error") in rerun_errors
        if not should_rerun:
            out_rows.append(row)
            continue

        raw_row = raw_by_key.get(key)
        if raw_row is None:
            out_rows.append(row)
            continue

        rerun_count += 1
        if raw_row.get("ecosystem") == "maven":
            rerun_result = detect_maven_bcs(raw_row, logger)
        else:
            rerun_result = detect_python_bcs(raw_row, logger)

        merged = dict(row)
        merged["has_bc"] = rerun_result["has_bc"]
        merged["bc_types"] = rerun_result["bc_types"]
        merged["bc_count"] = rerun_result["bc_count"]
        merged["tool_used"] = rerun_result.get("tool_used")
        merged["analysis_error_previous"] = row.get("analysis_error")
        merged["analysis_error"] = rerun_result.get("analysis_error")
        merged["rectified_in_improve"] = True
        if row.get("analysis_error") is not None and merged.get("analysis_error") is None:
            improved_count += 1
        out_rows.append(merged)
    return out_rows, rerun_count, improved_count


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    logger = setup_logger("improve_corrected_results", ERROR_LOG)
    raw_rows = load_jsonl(RAW_PATH)
    bc_rows = load_jsonl(BC_PATH)
    if not raw_rows or not bc_rows:
        raise SystemExit("Expected raw_prs_corrected.jsonl and bc_results_corrected.jsonl")

    repaired_raw, changed_keys, dep_changes, version_changes = repair_raw_rows(raw_rows)
    repaired_bc, rerun_count, improved_count = rerun_rows(repaired_raw, bc_rows, changed_keys, logger)

    write_jsonl(RAW_PATH, repaired_raw)
    write_jsonl(BC_PATH, repaired_bc)

    print("[improve_corrected_results] summary")
    print(f"  raw rows touched:           {len(changed_keys)} unique PRs")
    print(f"  dependency repairs:        {dep_changes}")
    print(f"  version repairs:           {version_changes}")
    print(f"  BC rows rerun:             {rerun_count}")
    print(f"  reruns now analyzed_ok:    {improved_count}")
    print(f"  wrote: {RAW_PATH}")
    print(f"  wrote: {BC_PATH}")


if __name__ == "__main__":
    main()
