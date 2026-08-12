"""Phase 4 diagnostic: find out why tests_pass_new was 100% NaN across all
783 rows in the original bc_results.jsonl.

Runs behavioral_check() (now instrumented, see detect_bcs.py) against a
mixed sample of Maven and PyPI rows and logs full stdout/stderr/exit
code/elapsed time for every subprocess invocation to
logs/behavioral_check_debug.log, plus a compact JSON summary per row to
data/phase4_diagnostic_results.jsonl.

Two sub-experiments:
  1. `sample sweep` — 8 Maven + 8 PyPI rows spanning the repo_stars
     distribution (quartile-sampled), timeout=300s per test invocation,
     flaky-check enabled (reruns the old-state suite twice). This is where
     harness_error reasons (missing pytest, install failures, checkout
     failures, missing project markers) get surfaced.
  2. `large-repo timing probe` — the 3 highest-star Maven repos and 2
     highest-star PyPI repos in the cohort, single old-state run with a
     1800s timeout, to measure whether 300s (the original timeout) was
     actually too short, as the rectification doc hypothesized.

Sample size is deliberately smaller than the doc's suggested 20+20 to keep
total wall-clock bounded (bounded diagnostic, not a full-cohort run) — see
logs/rectification_decisions.log for that call.
"""

import json
import logging
import random
from pathlib import Path

from detect_bcs import behavioral_check
from pipeline_utils import DATA_DIR, LOGS_DIR, ensure_layout, load_jsonl, setup_logger

RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
OUT_PATH = DATA_DIR / "phase4_diagnostic_results.jsonl"
DEBUG_LOG = LOGS_DIR / "behavioral_check_debug.log"
ERROR_LOG = LOGS_DIR / "phase4_diagnostic_errors.log"
DECISIONS_LOG = Path("logs/rectification_decisions.log")

SWEEP_TIMEOUT = 300
PROBE_TIMEOUT = 1800
SWEEP_N_PER_ECOSYSTEM = 8
PROBE_N_MAVEN = 3
PROBE_N_PYPI = 2


def setup_debug_logger():
    ensure_layout()
    logger = logging.getLogger("behavioral_check_debug")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(DEBUG_LOG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh)
    return logger


def quartile_sample(rows, n, seed):
    rows_sorted = sorted(rows, key=lambda r: r.get("repo_stars") or 0)
    if not rows_sorted:
        return []
    buckets = [rows_sorted[i::4] for i in range(4)]
    rng = random.Random(seed)
    picked = []
    per_bucket = max(1, n // 4)
    for bucket in buckets:
        if bucket:
            picked.extend(rng.sample(bucket, min(per_bucket, len(bucket))))
    return picked[:n]


def dec_log(message: str):
    with DECISIONS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def main():
    ensure_layout()
    debug_logger = setup_debug_logger()
    err_logger = setup_logger("phase4_diagnostic_errors", ERROR_LOG)

    rows = load_jsonl(RAW_PRS_PATH)
    maven_rows = [r for r in rows if r.get("ecosystem") == "maven"]
    pypi_rows = [r for r in rows if r.get("ecosystem") == "pypi"]

    sweep_sample = quartile_sample(maven_rows, SWEEP_N_PER_ECOSYSTEM, seed=1) + quartile_sample(pypi_rows, SWEEP_N_PER_ECOSYSTEM, seed=2)
    maven_by_stars = sorted(maven_rows, key=lambda r: r.get("repo_stars") or 0, reverse=True)
    pypi_by_stars = sorted(pypi_rows, key=lambda r: r.get("repo_stars") or 0, reverse=True)
    probe_sample = maven_by_stars[:PROBE_N_MAVEN] + pypi_by_stars[:PROBE_N_PYPI]

    dec_log(
        f"Phase4 diagnostic: sweep sample n={len(sweep_sample)} (timeout={SWEEP_TIMEOUT}s, flaky-check on), "
        f"probe sample n={len(probe_sample)} (timeout={PROBE_TIMEOUT}s, single old-state run). "
        f"Scaled down from doc's suggested 20+20 to bound wall-clock; see script docstring."
    )

    results = []

    print(f"[phase4_diagnose_behavioral] sweep: {len(sweep_sample)} rows, timeout={SWEEP_TIMEOUT}s")
    for idx, row in enumerate(sweep_sample, start=1):
        print(f"  sweep {idx}/{len(sweep_sample)}: {row['repo_full_name']}#{row['pr_number']} ({row['ecosystem']}, {row.get('repo_stars')} stars)")
        try:
            out = behavioral_check(row, debug_logger, check_flaky=True, maven_timeout=SWEEP_TIMEOUT, pypi_timeout=SWEEP_TIMEOUT)
        except Exception as exc:
            err_logger.exception("sweep row failed %s#%s: %s", row["repo_full_name"], row["pr_number"], exc)
            out = {"harness_error": f"uncaught:{exc}"}
        record = {
            "experiment": "sweep",
            "repo_full_name": row["repo_full_name"],
            "pr_number": row["pr_number"],
            "ecosystem": row["ecosystem"],
            "repo_stars": row.get("repo_stars"),
            **out,
        }
        results.append(record)
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[phase4_diagnose_behavioral] probe: {len(probe_sample)} rows, timeout={PROBE_TIMEOUT}s")
    for idx, row in enumerate(probe_sample, start=1):
        print(f"  probe {idx}/{len(probe_sample)}: {row['repo_full_name']}#{row['pr_number']} ({row['ecosystem']}, {row.get('repo_stars')} stars)")
        try:
            out = behavioral_check(row, debug_logger, check_flaky=False, maven_timeout=PROBE_TIMEOUT, pypi_timeout=PROBE_TIMEOUT)
        except Exception as exc:
            err_logger.exception("probe row failed %s#%s: %s", row["repo_full_name"], row["pr_number"], exc)
            out = {"harness_error": f"uncaught:{exc}"}
        record = {
            "experiment": "large_repo_probe",
            "repo_full_name": row["repo_full_name"],
            "pr_number": row["pr_number"],
            "ecosystem": row["ecosystem"],
            "repo_stars": row.get("repo_stars"),
            **out,
        }
        results.append(record)
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- summary ---
    from collections import Counter
    sweep = [r for r in results if r["experiment"] == "sweep"]
    harness_errors = Counter(r.get("harness_error") for r in sweep)
    tests_available_n = sum(1 for r in sweep if r.get("tests_available"))
    tests_pass_new_set = sum(1 for r in sweep if r.get("tests_pass_new") is not None)
    flaky_n = sum(1 for r in sweep if r.get("flaky_old"))

    print("=== PHASE 4 DIAGNOSTIC SUMMARY ===")
    print(f"sweep sample: {len(sweep)} rows")
    print(f"  tests_available=True: {tests_available_n}/{len(sweep)}")
    print(f"  tests_pass_new is non-null: {tests_pass_new_set}/{len(sweep)}")
    print(f"  flaky_old (old suite gave different result on rerun): {flaky_n}")
    print("  harness_error breakdown:")
    for reason, count in harness_errors.most_common():
        print(f"    {reason}: {count}")

    print("large-repo timing probe:")
    for r in results:
        if r["experiment"] == "large_repo_probe":
            print(f"  {r['repo_full_name']} ({r['ecosystem']}, {r['repo_stars']} stars): "
                  f"tests_available={r.get('tests_available')} timeout={r.get('tests_timeout')} "
                  f"harness_error={r.get('harness_error')}")

    dec_log(f"Phase4 diagnostic summary: harness_error breakdown={dict(harness_errors)}, tests_available={tests_available_n}/{len(sweep)}")
    print(f"[DONE] phase4_diagnose_behavioral — {len(results)} records processed, {len(results)} changed")


if __name__ == "__main__":
    main()
