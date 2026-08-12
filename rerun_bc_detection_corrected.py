"""Phase 2: re-run syntactic BC detection on rows repaired by Phase 1.

Targets two groups from data/bc_results.jsonl:
  1. Rows with analysis_error == "missing_dependency_coordinates" whose
     dependency_name was resolved by fix_dependency_coordinates.py
     (data/raw_prs_corrected.jsonl, coordinate_source in {pr_diff_pom, pr_diff_gradle}).
  2. Rows with analysis_error in {"jar_download_failed", "pip_install_failed"} —
     retried once in case the original failure was transient.

Behavioral-check fields (tests_available/tests_pass_old/tests_pass_new/...) are
carried over unchanged from the original run; behavioral_check() doesn't depend
on dependency_name, and the harness itself is fixed separately in Phase 4.

Original data/bc_results.jsonl is never modified; output goes to
data/bc_results_corrected.jsonl.
"""

import json

from detect_bcs import detect_maven_bcs, detect_python_bcs
from pipeline_utils import DATA_DIR, ensure_layout, load_jsonl, read_json, setup_logger, write_json, LOGS_DIR

RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
RAW_PRS_CORRECTED_PATH = DATA_DIR / "raw_prs_corrected.jsonl"
BC_RESULTS_PATH = DATA_DIR / "bc_results.jsonl"
BC_RESULTS_CORRECTED_PATH = DATA_DIR / "bc_results_corrected.jsonl"
CHECKPOINT_PATH = DATA_DIR / "progress_rerun_bcs.json"
ERROR_LOG = LOGS_DIR / "rerun_bc_detection_errors.log"

RETRY_ERRORS = {"jar_download_failed", "pip_install_failed"}


def main():
    ensure_layout()
    logger = setup_logger("rerun_bc_detection", ERROR_LOG)

    original_rows = load_jsonl(BC_RESULTS_PATH)
    if RAW_PRS_CORRECTED_PATH.exists():
        raw_rows = load_jsonl(RAW_PRS_CORRECTED_PATH)
    else:
        raw_rows = load_jsonl(RAW_PRS_PATH)
    raw_by_key = {(r["repo_full_name"], r["pr_number"]): r for r in raw_rows}

    checkpoint = read_json(CHECKPOINT_PATH, {})

    coord_resolved = 0
    coord_still_bc_bug = 0
    retry_success = 0
    retry_still_failed = 0
    unchanged = 0

    out_rows = []
    total = len(original_rows)
    for idx, row in enumerate(original_rows, start=1):
        key = (row["repo_full_name"], row["pr_number"])
        ck_key = f"{key[0]}#{key[1]}"
        raw_row = raw_by_key.get(key)
        error = row.get("analysis_error")

        needs_rerun = False
        rerun_row = {}
        if error == "missing_dependency_coordinates" and raw_row is not None:
            source = raw_row.get("coordinate_source")
            if source in {"pr_diff_pom", "pr_diff_gradle"}:
                needs_rerun = True
                rerun_row = dict(raw_row)
        elif error in RETRY_ERRORS:
            needs_rerun = True
            rerun_row = dict(raw_row) if raw_row is not None else dict(row)

        if not needs_rerun:
            out_rows.append(row)
            unchanged += 1
            continue

        if ck_key in checkpoint:
            new_syntactic = checkpoint[ck_key]
        else:
            if rerun_row.get("ecosystem") == "maven":
                new_syntactic = detect_maven_bcs(rerun_row, logger)
            else:
                new_syntactic = detect_python_bcs(rerun_row, logger)
            checkpoint[ck_key] = new_syntactic
            if idx % 20 == 0 or idx == total:
                write_json(CHECKPOINT_PATH, checkpoint)
                print(f"  progress: {idx}/{total}")

        merged = dict(row)
        merged["has_bc"] = new_syntactic["has_bc"]
        merged["bc_types"] = new_syntactic["bc_types"]
        merged["bc_count"] = new_syntactic["bc_count"]
        merged["tool_used"] = new_syntactic.get("tool_used")
        merged["analysis_error_original"] = error
        merged["analysis_error"] = new_syntactic.get("analysis_error")
        merged["rectified_in_phase2"] = True
        out_rows.append(merged)

        if error == "missing_dependency_coordinates":
            if merged["analysis_error"] is None:
                coord_resolved += 1
            else:
                coord_still_bc_bug += 1
        else:
            if merged["analysis_error"] is None:
                retry_success += 1
            else:
                retry_still_failed += 1

    write_json(CHECKPOINT_PATH, checkpoint)

    with BC_RESULTS_CORRECTED_PATH.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    before_ok = sum(1 for r in original_rows if r.get("analysis_error") is None)
    after_ok = sum(1 for r in out_rows if r.get("analysis_error") is None)

    print("[rerun_bc_detection_corrected] summary")
    print(f"  coordinate-repaired rows re-detected successfully: {coord_resolved}")
    print(f"  coordinate-repaired rows still failing:            {coord_still_bc_bug}")
    print(f"  transient-error retries succeeded:                 {retry_success}")
    print(f"  transient-error retries still failing:              {retry_still_failed}")
    print(f"  rows unchanged (not a rerun target):                {unchanged}")
    print()
    print(f"  Phase 0 baseline analyzed_ok: {before_ok}/{total} ({100*before_ok/total:.1f}%)")
    print(f"  After Phase 2 analyzed_ok:    {after_ok}/{total} ({100*after_ok/total:.1f}%)")
    print(f"  wrote: {BC_RESULTS_CORRECTED_PATH}")
    changed = coord_resolved + coord_still_bc_bug + retry_success + retry_still_failed
    print(f"[DONE] rerun_bc_detection_corrected — {total} records processed, {changed} changed")


if __name__ == "__main__":
    main()
