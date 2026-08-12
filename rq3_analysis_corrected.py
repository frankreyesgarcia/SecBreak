"""RQ3 recomputed on the corrected has_bc labels.

Not one of the rectification doc's 7 named phases, but required for
internal consistency: RQ3's team-response numbers (merge rate, time to
follow-up fix, reversions) are computed over the has_bc==1 subset, and that
subset grew from 27 rows to 159 once Phases 1-3 fixed the dependency-
coordinate bug. Leaving RQ3 pointed at the old 27-row set while RQ1/RQ2 cite
the corrected numbers would make the paper self-contradictory.

Same logic as rq3_analysis.py, sourced from
data/analysis_dataset_corrected.csv and restricted to analyzed_ok==True
(has_bc is only meaningful there), with its own follow-up cache so the
original data/rq3_followup.jsonl (and results/rq3_tables.csv) stay untouched
for the record.
"""

import time
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import requests
import seaborn as sns
import statsmodels.api as sm

from pipeline_utils import DATA_DIR, FIGURES_DIR, RESULTS_DIR, append_jsonl, load_jsonl, pct
from rq3_analysis import gh_headers

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"
FOLLOWUP_PATH = DATA_DIR / "rq3_followup_corrected.jsonl"
TABLES_PATH = RESULTS_DIR / "rq3_tables_corrected.csv"


def gh_get(url: str, params=None):
    while True:
        resp = requests.get(url, headers=gh_headers(), params=params, timeout=30)
        if resp.status_code in {403, 429}:
            time.sleep(60)
            continue
        resp.raise_for_status()
        return resp.json()


def find_followup(repo: str, pr_number: int, merged_at: str):
    merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    issues = gh_get("https://api.github.com/search/issues", params={"q": f"repo:{repo} is:pr created:>={merged_dt.date()} sort:created-asc"})
    earliest = None
    reverted = False
    for item in issues.get("items", []):
        title = (item.get("title") or "").lower()
        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
        text = title + "\n" + (item.get("body") or "").lower()
        if any(term in text for term in ["fix", "revert", "repair", "downgrade", "rollback", f"#{pr_number}"]):
            days = (created - merged_dt).total_seconds() / 86400.0
            if days >= 0 and (earliest is None or days < earliest):
                earliest = days
            if "revert" in text or "rollback" in text:
                reverted = True
    return earliest, reverted


def default_branch_activity(repo: str, merged_at: str):
    repo_json = gh_get(f"https://api.github.com/repos/{repo}")
    branch = repo_json["default_branch"]
    merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    commits = gh_get(f"https://api.github.com/repos/{repo}/commits", params={"sha": branch, "since": merged_at, "per_page": 10})
    next_commit_days = None
    ci_fail = False
    if commits:
        commit_dt = datetime.fromisoformat(commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00"))
        next_commit_days = (commit_dt - merged_dt).total_seconds() / 86400.0
    for commit in commits:
        status = gh_get(commit["url"] + "/status")
        if status.get("state") == "failure":
            ci_fail = True
            break
    return next_commit_days, ci_fail


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
                "next_commit_days": None,
                "followup_fix_days": None,
                "ci_failed_after_merge": False,
                "reverted": False,
            }
        else:
            try:
                next_commit_days, ci_failed = default_branch_activity(row["repo_full_name"], merged)
                fix_days, reverted = find_followup(row["repo_full_name"], int(row["pr_number"]), merged)
            except Exception as exc:
                print(f"  error on {row['repo_full_name']}#{row['pr_number']}: {exc}")
                continue
            payload = {
                "repo_full_name": row["repo_full_name"],
                "pr_number": int(row["pr_number"]),
                "merged": True,
                "next_commit_days": next_commit_days,
                "followup_fix_days": fix_days,
                "ci_failed_after_merge": ci_failed,
                "reverted": reverted,
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


def main():
    sns.set_theme(style="whitegrid")
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    bc_df = df[(df["has_bc"] == 1) & (df["analyzed_ok"])].copy()
    print(f"[rq3_analysis_corrected] {len(bc_df)} BC-introducing analyzed_ok PRs")
    follow_df = collect_followup(bc_df)
    bc_df = bc_df.merge(follow_df, on=["repo_full_name", "pr_number"], how="left")

    merged_anyway = int(bc_df["merged"].fillna(False).sum())
    total = len(bc_df)
    followups = bc_df["followup_fix_days"].dropna()
    median = float(followups.median()) if not followups.empty else float("nan")
    iqr_low = float(followups.quantile(0.25)) if not followups.empty else float("nan")
    iqr_high = float(followups.quantile(0.75)) if not followups.empty else float("nan")
    within_7 = int((bc_df["followup_fix_days"] <= 7).fillna(False).sum())
    within_30 = int((bc_df["followup_fix_days"] <= 30).fillna(False).sum())
    within_90 = int((bc_df["followup_fix_days"] <= 90).fillna(False).sum())
    ci_fail = int(bc_df["ci_failed_after_merge"].fillna(False).sum())
    reverted = int(bc_df["reverted"].fillna(False).sum())

    print("=== RQ3: TEAM BEHAVIOR (corrected) ===")
    print(f"BC-introducing PRs merged anyway:     {merged_anyway}/{total} ({pct(merged_anyway, total):.1f}%)")
    print(f"Median time to follow-up fix PR:      {median:.1f} days (IQR: {iqr_low:.1f}-{iqr_high:.1f})")
    print(f"% with follow-up fix within 7 days:   {pct(within_7, total):.1f}%")
    print(f"% with follow-up fix within 30 days:  {pct(within_30, total):.1f}%")
    print(f"% with follow-up fix within 90 days:  {pct(within_90, total):.1f}%")
    print(f"% that caused CI failure after merge: {pct(ci_fail, total):.1f}%")
    print(f"% that were reverted:                 {pct(reverted, total):.1f}%")

    model_df = bc_df.copy()
    model_df["fast_remediation"] = (model_df["followup_fix_days"] <= 7).fillna(False).astype(int)
    model_df["major_bc_type"] = model_df["bc_types"].astype(str).str.extract(r"(METHOD|TYPE|FIELD)").fillna("OTHER")
    reg = pd.get_dummies(
        model_df[["cvss_score", "major_bc_type", "ecosystem", "version_bump_type", "repo_stars", "fast_remediation"]],
        columns=["major_bc_type", "ecosystem", "version_bump_type"],
        drop_first=True,
    )
    y = reg.pop("fast_remediation")
    X = sm.add_constant(reg.astype(float), has_constant="add")
    try:
        fit = sm.Logit(y, X).fit(disp=False)
        print("Significant predictors of remediation < 7 days:")
        for name, value in fit.pvalues.items():
            if name != "const" and value < 0.05:
                print(f"  {name}: coef={fit.params[name]:.4f}, p={value:.4g}")
    except Exception as exc:
        print(f"Remediation regression unavailable: {exc}")

    pd.DataFrame(
        [
            {"metric": "merged_anyway_pct", "value": pct(merged_anyway, total)},
            {"metric": "followup_7d_pct", "value": pct(within_7, total)},
            {"metric": "followup_30d_pct", "value": pct(within_30, total)},
            {"metric": "followup_90d_pct", "value": pct(within_90, total)},
            {"metric": "ci_fail_pct", "value": pct(ci_fail, total)},
            {"metric": "reverted_pct", "value": pct(reverted, total)},
            {"metric": "median_fix_days", "value": median},
            {"metric": "n_bc_prs", "value": total},
        ]
    ).to_csv(TABLES_PATH, index=False)

    plt.figure(figsize=(8, 5))
    sns.histplot(followups, bins=20)
    plt.xlabel("Days to follow-up fix PR")
    plt.title("Time to Follow-up Fix (corrected)")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq3_time_to_fix.png", dpi=200)
    plt.close()

    merge_rate = (
        bc_df.assign(severity=bc_df["severity"].fillna("UNKNOWN"))
        .groupby("severity")["merged"]
        .mean()
        .reset_index()
    )
    plt.figure(figsize=(8, 5))
    sns.barplot(data=merge_rate, x="severity", y="merged")
    plt.ylabel("Merge rate")
    plt.title("Merge Rate by CVSS Severity (corrected)")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq3_merge_rate_by_cvss.png", dpi=200)
    plt.close()

    print(f"[DONE] rq3_analysis_corrected — {len(df)} records processed, {total} BC PRs analyzed")


if __name__ == "__main__":
    main()
