"""Phase 1 (paper strengthening): tighten RQ3's follow-up-fix relatedness check.

find_followup() in rq3_analysis_corrected.py counted *any* PR created after the
merge date whose title/body contains "fix", "revert", "repair", "downgrade", or
"rollback" as the BC's remediation, with no check that it actually relates to
the dependency bump under study. That almost certainly overcounts (a repo with
active development has many PRs with "fix" in the title for unrelated reasons)
and produces an implausibly fast median (1.0 day).

This script re-implements find_followup() with a relatedness requirement: a
keyword-matching candidate only counts if it ALSO does at least one of:
  - references the original PR number (#123) in title or body, or
  - modifies the same dependency manifest file (pom.xml, build.gradle*,
    requirements.txt, setup.py, pyproject.toml), or
  - mentions the dependency name itself in title/body.

Writes to new paths (data/rq3_followup_strict.jsonl, results/rq3_tables_strict.csv)
so rq3_analysis_corrected.py's outputs stay untouched for before/after comparison.
"""

import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from pipeline_utils import DATA_DIR, RESULTS_DIR, append_jsonl, load_jsonl, pct
from rq3_analysis import gh_headers

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"
FOLLOWUP_PATH = DATA_DIR / "rq3_followup_strict.jsonl"
NAIVE_FOLLOWUP_PATH = DATA_DIR / "rq3_followup_corrected.jsonl"
TABLES_PATH = RESULTS_DIR / "rq3_tables_strict.csv"
DECISIONS_LOG = Path("logs/strengthening_decisions.log")

MANIFEST_BASENAMES = {"pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt", "setup.py", "pyproject.toml"}


def dec_log(message: str):
    with DECISIONS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def gh_get(url: str, params=None):
    attempt = 0
    while True:
        resp = requests.get(url, headers=gh_headers(), params=params, timeout=30)
        if resp.status_code in {403, 429}:
            attempt += 1
            time.sleep(min(300, 30 * attempt))
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def pr_touches_manifest(repo: str, pr_number: int) -> bool:
    files = gh_get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files", params={"per_page": 100})
    if not files:
        return False
    for f in files:
        if Path(f.get("filename", "")).name in MANIFEST_BASENAMES:
            return True
    return False


def find_followup_strict(repo: str, pr_number: int, merged_at: str, dependency_name: str):
    merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    issues = gh_get("https://api.github.com/search/issues", params={"q": f"repo:{repo} is:pr created:>={merged_dt.date()} sort:created-asc"})
    earliest = None
    reverted = False
    naive_candidates = 0
    strict_candidates = 0
    dep_token = (dependency_name or "").split(":")[-1].lower() if dependency_name else ""
    for item in (issues or {}).get("items", []):
        title = (item.get("title") or "").lower()
        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
        body = (item.get("body") or "").lower()
        text = title + "\n" + body
        keyword_match = any(term in text for term in ["fix", "revert", "repair", "downgrade", "rollback"])
        if not keyword_match:
            continue
        naive_candidates += 1
        days = (created - merged_dt).total_seconds() / 86400.0
        if days < 0:
            continue

        related = False
        if f"#{pr_number}" in text:
            related = True
        elif dep_token and dep_token in text:
            related = True
        else:
            candidate_number = item.get("number")
            try:
                if candidate_number and pr_touches_manifest(repo, candidate_number):
                    related = True
            except Exception as exc:
                dec_log(f"manifest-check failed for {repo}#{candidate_number}: {exc}")

        if not related:
            continue
        strict_candidates += 1
        if earliest is None or days < earliest:
            earliest = days
        if "revert" in text or "rollback" in text:
            reverted = True
    return earliest, reverted, naive_candidates, strict_candidates


def collect_followup(df: pd.DataFrame) -> pd.DataFrame:
    cached = load_jsonl(FOLLOWUP_PATH)
    done = {(row["repo_full_name"], row["pr_number"]) for row in cached}
    out_rows = []
    total = len(df)
    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        key = (row["repo_full_name"], int(row["pr_number"]))
        if key in done:
            continue
        merged = row.get("merged_at")
        if not merged or pd.isna(merged):
            payload = {
                "repo_full_name": row["repo_full_name"],
                "pr_number": int(row["pr_number"]),
                "merged": False,
                "followup_fix_days": None,
                "reverted": False,
                "naive_candidates": 0,
                "strict_candidates": 0,
            }
        else:
            try:
                fix_days, reverted, naive_n, strict_n = find_followup_strict(
                    row["repo_full_name"], int(row["pr_number"]), merged, row.get("dependency_name")
                )
            except Exception as exc:
                print(f"  error on {row['repo_full_name']}#{row['pr_number']}: {exc}")
                dec_log(f"rq3_strict: error on {row['repo_full_name']}#{row['pr_number']}: {exc}")
                continue
            payload = {
                "repo_full_name": row["repo_full_name"],
                "pr_number": int(row["pr_number"]),
                "merged": True,
                "followup_fix_days": fix_days,
                "reverted": reverted,
                "naive_candidates": naive_n,
                "strict_candidates": strict_n,
            }
        out_rows.append(payload)
        if len(out_rows) >= 10:
            append_jsonl(FOLLOWUP_PATH, out_rows)
            done.update((item["repo_full_name"], item["pr_number"]) for item in out_rows)
            out_rows.clear()
            print(f"  progress: {idx}/{total}", flush=True)
    if out_rows:
        append_jsonl(FOLLOWUP_PATH, out_rows)
    return pd.DataFrame(load_jsonl(FOLLOWUP_PATH))


def summarize(bc_df, label):
    total = len(bc_df)
    followups = bc_df["followup_fix_days"].dropna()
    median = float(followups.median()) if not followups.empty else float("nan")
    iqr_low = float(followups.quantile(0.25)) if not followups.empty else float("nan")
    iqr_high = float(followups.quantile(0.75)) if not followups.empty else float("nan")
    within_7 = int((bc_df["followup_fix_days"] <= 7).fillna(False).sum())
    within_30 = int((bc_df["followup_fix_days"] <= 30).fillna(False).sum())
    n_fixed = int(followups.shape[0])
    print(f"=== {label} ===")
    print(f"  fixes found: {n_fixed}/{total} ({pct(n_fixed, total):.1f}%)")
    print(f"  median: {median:.2f} days (IQR {iqr_low:.2f}-{iqr_high:.2f})")
    print(f"  within 7d: {within_7} ({pct(within_7, total):.1f}%), within 30d: {within_30} ({pct(within_30, total):.1f}%)")
    return {
        "label": label,
        "n_bc_prs": total,
        "fixes_found": n_fixed,
        "fixes_found_pct": pct(n_fixed, total),
        "median_fix_days": median,
        "iqr_low": iqr_low,
        "iqr_high": iqr_high,
        "within_7d_pct": pct(within_7, total),
        "within_30d_pct": pct(within_30, total),
    }


def main():
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    bc_df = df[(df["has_bc"] == 1) & (df["analyzed_ok"])].copy()
    print(f"[rq3_analysis_strict] {len(bc_df)} BC-introducing analyzed_ok PRs")

    follow_df = collect_followup(bc_df)
    strict_df = bc_df.merge(follow_df, on=["repo_full_name", "pr_number"], how="left")

    naive_cache = load_jsonl(NAIVE_FOLLOWUP_PATH)
    naive_df_raw = pd.DataFrame(naive_cache) if naive_cache else pd.DataFrame(columns=["repo_full_name", "pr_number", "followup_fix_days"])
    naive_df = bc_df.merge(naive_df_raw[["repo_full_name", "pr_number", "followup_fix_days"]], on=["repo_full_name", "pr_number"], how="left")

    naive_summary = summarize(naive_df, "NAIVE (keyword-only, original corrected run)")
    strict_summary = summarize(strict_df, "STRICT (relatedness-filtered)")

    total_naive_candidates = int(follow_df["naive_candidates"].fillna(0).sum()) if "naive_candidates" in follow_df else 0
    total_strict_candidates = int(follow_df["strict_candidates"].fillna(0).sum()) if "strict_candidates" in follow_df else 0
    overcounting_pct = 100.0 * (total_naive_candidates - total_strict_candidates) / total_naive_candidates if total_naive_candidates else 0.0
    print(f"Candidate fix PRs found: naive={total_naive_candidates}, strict={total_strict_candidates} ({overcounting_pct:.1f}% of naive candidates were unrelated)")

    dec_log(
        f"rq3_analysis_strict: naive median={naive_summary['median_fix_days']:.2f}d "
        f"({naive_summary['fixes_found']}/{naive_summary['n_bc_prs']} fixes found) vs "
        f"strict median={strict_summary['median_fix_days']:.2f}d "
        f"({strict_summary['fixes_found']}/{strict_summary['n_bc_prs']} fixes found). "
        f"{total_naive_candidates} naive keyword-match candidates found across all rows, "
        f"only {total_strict_candidates} survived the relatedness filter "
        f"({overcounting_pct:.1f}% were unrelated PRs coincidentally containing a fix/revert keyword). "
        f"Decision: report strict numbers as the paper's cited RQ3 remediation-speed figures."
    )

    pd.DataFrame([naive_summary, strict_summary]).to_csv(TABLES_PATH, index=False)
    print(f"[DONE] rq3_analysis_strict — {len(bc_df)} records processed, {strict_summary['fixes_found']} strict fixes found")


if __name__ == "__main__":
    main()
