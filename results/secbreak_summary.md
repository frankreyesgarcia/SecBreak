# SecBreak — Empirical Results Summary

Generated: 2026-04-12T20:42:04.166889+00:00

## Dataset Statistics
- Total PRs analyzed: 783
- Repositories: 132
- Date range: 2022-01-01 to 2024-12-31
- Ecosystems: Maven (554), PyPI (229)
- PRs with BC detection results: 783 (100.0% of total)

## RQ1 — Prevalence of Breaking Changes in Security PRs

| Metric | Value | 95% CI |
|--------|-------|--------|
| Overall BC prevalence | 3.4% | [2.4%–5.0%] |
| TSE 2021 baseline (metadata) | 13.2% | — |
| Difference (z-test) | see `results/rq1_tables.csv` | — |
| Behavioral BC (test failures) | 0.0% | [0.0%–0.5%] |

| Version Bump | BC Prevalence |
|---|---|
| Patch | 2.4% |
| Minor | 3.2% |
| Major | 4.9% |

| CVSS Severity | BC Prevalence |
|---|---|
| LOW | 7.0% |
| MEDIUM | 1.4% |
| HIGH | 6.0% |
| CRITICAL | 4.5% |

## RQ2 — Predictive Model

- Best model: Gradient Boosting, AUC-ROC = 0.88
- Top 3 predictive features: version_bump_ord, cvss_score, repo_stars


## RQ3 — Team Behavior

| Metric | Value |
|---|---|
| BC PRs merged anyway | 29.6% |
| CI failures after merge | 0.0% |
| Follow-up fix within 7 days | 25.9% |
| Follow-up fix within 30 days | 29.6% |
| Median time to fix (days) | 0.9 |

## Key Findings

1. Client-side BC prevalence across security PRs is 3.4%, which should be interpreted against the 13.2% provider-side SemVer baseline from TSE 2021.
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
