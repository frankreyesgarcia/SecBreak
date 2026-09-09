# SecBreak

Autonomous empirical pipeline for collecting Dependabot security PRs, detecting breaking
changes, building the analysis dataset, and generating results for RQ1–RQ3.

**Paper:** `paper/secbreak_tse_revision.tex` — *SecBreak: Client-Side Breaking-Change Risk
in Dependabot Security Pull Requests* (target: IEEE TSE).

> **Status (2026-09):** a cohort-expansion pass is in progress (`collect_prs_expanded.py`,
> window widened to 2021–2025, per-month sampling cap raised). The numbers below are for
> the frozen **783-PR** cohort and will be regenerated once the larger cohort lands.

## Headline results (783-PR cohort)

| # | Question | Result |
|---|----------|--------|
| — | Cohort | 783 unique Dependabot security PRs, 132 repositories (554 Maven / 229 PyPI), Jan 2022 – Dec 2024 |
| — | Pipeline coverage (BC detection genuinely executed) | **48.5%** (380/783) — reported explicitly, like a survey response rate |
| **RQ1** | How often do Dependabot security PRs introduce breaking changes? | **42.1%** of analyzed PRs (160/380), 95% CI [37.2%, 47.1%] — *higher* than the 13.2% provider-side metadata baseline (Raemaekers et al., TSE 2021), not lower (z = 11.4, p < 10⁻²⁹) |
| RQ1 | Robustness of the 42.1% estimate | Worst-case (Manski) bounds [20.4%, 71.9%]; model-imputed full-cohort estimate 38.0% [36.6%, 39.2%] |
| RQ1 | By ecosystem (analyzed) | Maven **65.6%** (158/241) vs PyPI **1.4%** (2/139), χ² p = 1.3×10⁻³³ |
| RQ1 | By version bump (analyzed) | patch 37.3% · minor 34.7% · major 60.6% (χ² p = 4.5×10⁻⁴) — patch security updates are *not* risk-free |
| RQ1 | CVSS severity vs BC risk | no significant monotonic association (Spearman ρ = −0.07, p = 0.16) |
| **RQ2** | Can we predict which PRs introduce BCs? | Random Forest **AUC-ROC 0.894 ± 0.069** (repository-grouped, 5×5 repeated CV; dummy baseline 0.500). Top features: repo stars, ecosystem, CVSS, bump magnitude. No target leakage. Treated as supporting triage evidence. |
| **RQ3** | How do teams react to a merged BC-introducing security PR? | **33.1%** of BC-introducing PRs merged anyway; median follow-up fix **3.5 days** (IQR 0.8–10.4) after filtering follow-up PRs to ones plausibly related to the bump (naive keyword-only match alone implies an inflated 1.0 day); reversion rate 8.8% |
| — | Behavioral (test-based) BC | **not reported** — harness bugs fixed and verified, but the resulting signal is dominated by environment confounds; documented as future work, not as "0%" |
| — | NVD metadata quality check | 100 sampled CVE-linked Maven PRs: **0% version mismatch** — every claimed-affected and fixed coordinate resolves in Maven Central |

Full traceable claim list: `results/presubmission_claim_trace.csv` and
`results/presubmission_supporting_metrics.csv`.

## Data rectification

An earlier pipeline version silently treated PRs where BC detection never ran as
verified-compatible negatives, using `len(df)` as the prevalence denominator. This
understated BC prevalence by more than an order of magnitude (reported 3.4%) and inverted
the comparison against the provider-side baseline. The fix (resolve dependency
coordinates from the PR diff, add an explicit `analyzed_ok` flag, compute prevalence only
over analyzed rows) and every downstream recomputation are documented in:

- `results/RECTIFICATION_REPORT.md` — the denominator bug and its follow-ons
- `results/STRENGTHENING_REPORT.md` — 8-phase methodological strengthening pass
- `AUDIT_INITIAL.md` / `RECTIFICATION_SUMMARY.md` — most recent verification pass
- `results/MAVEN_ONLY_COMPARISON.md` — dual-ecosystem vs Maven-only scoping (pending author decision)

Original (pre-fix) outputs are preserved under `*_ORIGINAL_BUGGY` names.

## Pipeline

| Stage | Script | Output |
|-------|--------|--------|
| 1. Collect security PRs | `collect_prs.py` (baseline) · `collect_prs_expanded.py` (2021–2025, wider cap) | `data/raw_prs.jsonl` |
| 2. Resolve dependency coordinates | `fix_dependency_coordinates.py` | `data/raw_prs_corrected.jsonl` |
| 3. Enrich CVEs from NVD | `fetch_nvd.py` | `data/cve_details.json` |
| 4. Detect breaking changes | `detect_bcs.py` · `rerun_bc_detection_corrected.py` · `improve_corrected_results.py` | `data/bc_results_corrected.jsonl` |
| 5. Build analysis dataset | `build_dataset_corrected.py` | `data/analysis_dataset_corrected.csv` |
| 6. Freeze cohort | `freeze_cohort.py` | `results/cohort/` |
| 7. RQ1 prevalence + bounds | `rq1_analysis_corrected.py`, `rq1_bounds.py` | `results/rq1_tables_corrected.csv`, `results/rq1_bounds.json` |
| 8. RQ2 model | `rq2_model_corrected.py`, `rq2_model_extras.py` | `results/rq2_model_results_corrected.csv`, `results/rq2_logit_coefficients_converged.csv` |
| 9. RQ3 team response | `rq3_analysis_strict.py` | `results/rq3_tables_strict.csv` |
| 10. Selection bias / robustness | `analyze_selection_bias.py` | `results/selection_bias_table.csv` |
| 11. NVD metadata validation | `nvd_metadata_validation.py` | `data/nvd_metadata_validation.csv` |
| 12. Pre-submission claim trace | `generate_presubmission_artifacts.py` | `results/presubmission_*.csv` |

Requires `GITHUB_TOKEN` (stages 1–2, 4) and optionally `NVD_API_KEY` (stage 3). Java 25
on `PATH` or `JAVA_BIN` for Roseau (stage 4). Python deps in `.venv`.

## Build the paper

```
cd paper && pdflatex secbreak_tse_revision.tex && pdflatex secbreak_tse_revision.tex
```
