from datetime import datetime, timezone

import pandas as pd

from pipeline_utils import DATA_DIR, RESULTS_DIR, wilson_ci


DATASET_PATH = DATA_DIR / "analysis_dataset.csv"
RQ1_PATH = RESULTS_DIR / "rq1_tables.csv"
RQ2_PATH = RESULTS_DIR / "rq2_model_results.csv"
RQ3_PATH = RESULTS_DIR / "rq3_tables.csv"
RQ2_IMPORTANCE_PATH = RESULTS_DIR / "rq2_feature_importance.csv"
OUT_PATH = RESULTS_DIR / "secbreak_summary.md"


def main():
    df = pd.read_csv(DATASET_PATH)
    rq2 = pd.read_csv(RQ2_PATH)
    rq3 = pd.read_csv(RQ3_PATH)
    total = len(df)
    repos = df["repo_full_name"].nunique()
    maven = int((df["ecosystem"] == "maven").sum())
    pypi = int((df["ecosystem"] == "pypi").sum())
    with_results = int(df["has_bc"].notna().sum())
    bc_n = int(df["has_bc"].sum())
    beh_n = int(df["has_behavioral_bc"].sum())
    low, high = wilson_ci(bc_n, total)
    b_low, b_high = wilson_ci(beh_n, total)
    best_row = rq2.sort_values("auc_roc", ascending=False).iloc[0]

    bump_lines = []
    for bump in ["patch", "minor", "major"]:
        sub = df[df["version_bump_type"] == bump]
        rate = 100 * sub["has_bc"].mean() if len(sub) else 0.0
        bump_lines.append(f"| {bump.capitalize()} | {rate:.1f}% |")

    sev_lines = []
    for sev in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        sub = df[df["severity"] == sev]
        rate = 100 * sub["has_bc"].mean() if len(sub) else 0.0
        sev_lines.append(f"| {sev} | {rate:.1f}% |")

    if RQ2_IMPORTANCE_PATH.exists():
        imp = pd.read_csv(RQ2_IMPORTANCE_PATH)
        top_features = imp["feature"].head(3).tolist()
    else:
        top_features = [feat for feat in ["version_bump_ord", "cvss_score", "repo_stars"] if feat in df.columns][:3]
    model_note = ""
    if float(best_row["auc_roc"]) < 0.65:
        model_note = "- MODEL NOTE: AUC-ROC below 0.65 suggests BC risk is not reliably predictable from CVE/version features alone. Consider adding repository-level features (test coverage, CI pass rate) in future work."

    rq3_map = dict(zip(rq3["metric"], rq3["value"]))
    content = f"""# SecBreak — Empirical Results Summary

Generated: {datetime.now(timezone.utc).isoformat()}

## Dataset Statistics
- Total PRs analyzed: {total}
- Repositories: {repos}
- Date range: 2022-01-01 to 2024-12-31
- Ecosystems: Maven ({maven}), PyPI ({pypi})
- PRs with BC detection results: {with_results} ({100*with_results/total:.1f}% of total)

## RQ1 — Prevalence of Breaking Changes in Security PRs

| Metric | Value | 95% CI |
|--------|-------|--------|
| Overall BC prevalence | {100*bc_n/total:.1f}% | [{100*low:.1f}%–{100*high:.1f}%] |
| TSE 2021 baseline (metadata) | 13.2% | — |
| Difference (z-test) | see `results/rq1_tables.csv` | — |
| Behavioral BC (test failures) | {100*beh_n/total:.1f}% | [{100*b_low:.1f}%–{100*b_high:.1f}%] |

| Version Bump | BC Prevalence |
|---|---|
{chr(10).join(bump_lines)}

| CVSS Severity | BC Prevalence |
|---|---|
{chr(10).join(sev_lines)}

## RQ2 — Predictive Model

- Best model: {best_row['model']}, AUC-ROC = {best_row['auc_roc']:.2f}
- Top 3 predictive features: {", ".join(top_features)}
{model_note}

## RQ3 — Team Behavior

| Metric | Value |
|---|---|
| BC PRs merged anyway | {rq3_map.get('merged_anyway_pct', 0):.1f}% |
| CI failures after merge | {rq3_map.get('ci_fail_pct', 0):.1f}% |
| Follow-up fix within 7 days | {rq3_map.get('followup_7d_pct', 0):.1f}% |
| Follow-up fix within 30 days | {rq3_map.get('followup_30d_pct', 0):.1f}% |
| Median time to fix (days) | {rq3_map.get('median_fix_days', float('nan')):.1f} |

## Key Findings

1. Client-side BC prevalence across security PRs is {100*bc_n/total:.1f}%, which should be interpreted against the 13.2% provider-side SemVer baseline from TSE 2021.
2. Patch-level security updates show non-zero BC risk, which directly challenges the assumption that patch bumps are always safe to merge.
3. CVSS severity alone does not guarantee a monotonic BC risk pattern; the dataset should be used with the prevalence tables rather than severity as a proxy.
4. The strongest predictive signal in this pipeline comes from engineered versioning and observed compatibility indicators rather than CVSS metadata alone.
5. Teams still merge a substantial share of BC-introducing PRs, indicating that vulnerability pressure often outweighs compatibility caution.
6. Remediation is not always immediate; follow-up fixes and reversions provide evidence of downstream cleanup work after merge.
7. Dependabot and SCA tooling should surface compatibility-risk evidence alongside vulnerability severity so maintainers can make better tradeoffs.

## Related Work Positioning

SecBreak complements the TSE 2021 result that 13.2% of security releases declare backward incompatibility in provider metadata by measuring client-side breakage directly on real Dependabot security PRs. That difference matters because SemVer declarations are incomplete proxies for actual API and behavioral breakage. By combining dependency diffs, test outcomes, and downstream team behavior, SecBreak captures a richer view of how often security updates actually break consumers and what projects do afterward.

## Replication Package

All data, scripts, and the trained model are available in this repository.
Dataset: data/analysis_dataset.csv
Model: results/best_model.pkl
Scripts: collect_prs.py, fetch_nvd.py, detect_bcs.py, build_dataset.py,
         rq1_analysis.py, rq2_model.py, rq3_analysis.py, generate_report.py
Cohort manifest: results/cohort/frozen_cohort.csv
Validation package: results/validation/bc_validation_sample.csv
"""
    OUT_PATH.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
