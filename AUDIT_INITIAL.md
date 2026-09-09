# SecBreak — Initial Audit (Step 0 of the rectification handoff)

Date: 2026-09-08
Branch: `paper-strengthening/v2`
Working dir: `/mnt/ssd3/frank/SecBreak` (handoff said `/mnt/ssd3/frank/secbreak`; actual path is capitalised)

## TL;DR

**Most of the pasted handoff (Steps 1–6, 9) was already completed by two prior passes**
recorded in `results/RECTIFICATION_REPORT.md` (branch `rectification/rq1-fix`) and
`results/STRENGTHENING_REPORT.md` (branch `paper-strengthening/v2`, current). The handoff
appears to have been written against an earlier repo state. The genuinely outstanding
work is:

- **Step 7** — six named citations with explicit differentiation. Partially present:
  Alfadel, Rebatchi, Mohayeji, and the Dependabot-compatibility-score paper are already
  cited. **BreakGuard (arXiv 2608.20167) and Venturini et al. (TOSEM 2023) are missing**,
  and the differentiation sentences for the ones present are lighter than the handoff asks.
- **Step 8** — NVD affected-version metadata validation. **Not done.** No
  `nvd_metadata_validation.csv`, no Threats-to-Validity paragraph on it.
- **Step 10** — final compile / grep checks.

Steps that do **not** apply as written: Step 5 (RQ3 adoption-strategy coding + Cohen's
Kappa) targets a different RQ3 design; this paper's RQ3 is team remediation response
(merge rate, follow-up-fix time), already recomputed on the corrected BC set with a
strict relatedness filter. Step 6 (unify two LaTeX drafts) is already done — there is
one canonical file.

## File inventory (relevant paths, verified to exist)

### Paper
| Path | Role |
|---|---|
| `paper/secbreak_tse_revision.tex` | **canonical manuscript** (279 lines, `\documentclass[10pt,journal]{IEEEtran}`). `secbreak_tse_short.tex` was deleted in a prior pass, content merged. |
| `paper/tables/selection_bias.tex` | Phase-2 selection-bias table snippet |
| `paper/IEEEtran.cls`, `paper/secbreak_tse_revision.{aux,log,pdf}` | build artifacts (untracked) |
| `bib.json` | 109 KB — covers an unrelated PR-bots literature set, **not** this paper's bibliography (paper uses an inline `thebibliography`) |

### RQ1 (prevalence)
| Path | Role |
|---|---|
| `rq1_analysis_corrected.py` | corrected RQ1, `analyzed_ok` denominator, `--maven-only` flag |
| `rq1_analysis.py` | original (buggy `len(df)` denominator) |
| `rq1_bounds.py` | Phase-3 Manski bounds + model-imputed prevalence |
| `results/rq1_tables_corrected.csv` / `_ORIGINAL_BUGGY.csv` / `_mavenonly.csv` | outputs |
| `results/rq1_bounds.json` | bounds output |

### RQ2 (prediction)
| Path | Role |
|---|---|
| `rq2_model_corrected.py` | leakage-removed feature set, `StratifiedGroupKFold` by `repo_full_name`, `--maven-only` |
| `rq2_model_extras.py` | Phase-4 dummy baseline + `statsmodels` logit coefficients w/ 95% CI |
| `rq2_model.py` | original (single split, `has_behavioral_bc` in features) |
| `results/rq2_model_results_corrected.csv`, `results/rq2_feature_importance_corrected.csv`, `results/rq2_logit_coefficients_converged.csv` | outputs |

### RQ3 (team response)
| Path | Role |
|---|---|
| `rq3_analysis_strict.py` | Phase-1 relatedness-filtered follow-up-fix detection |
| `rq3_analysis_corrected.py` | corrected BC population, keyword-only follow-up match |
| `rq3_analysis.py` | original |
| `data/rq3_followup_strict.jsonl`, `results/rq3_tables_strict.csv` | outputs |

### Dataset / pipeline
| Path | Role |
|---|---|
| `data/analysis_dataset_corrected.csv` | analysis dataset, 783 unique PRs, `analyzed_ok` flag. Columns: `dependency_name`, `old_version`, `new_version`, `cve_ids`, `has_bc`, `analysis_error`, `analyzed_ok`, `tests_pass_new`, … (58 cols) |
| `data/analysis_dataset.csv` | pre-rectification |
| `collect_prs.py` | PR collection + (buggy) title-regex coordinate parsing |
| `fix_dependency_coordinates.py` | Phase-1 coordinate resolution from PR diff |
| `detect_bcs.py` | BC detection harness (Roseau/japicmp for Maven, signature diff for PyPI) |
| `rerun_bc_detection_corrected.py`, `improve_corrected_results.py`, `push_coverage_corrected.py` | coverage-improvement re-runs |
| `build_dataset_corrected.py`, `pipeline_utils.py` | dataset assembly + shared helpers |
| `phase4_diagnose_behavioral.py` | behavioural-BC harness diagnosis (Step 2 of handoff) |
| `analyze_selection_bias.py`, `rq1_bounds.py`, `rq2_model_extras.py`, `prepare_validation_review.py` | strengthening-phase scripts |
| `generate_presubmission_artifacts.py` | claim-trace generator (untracked; has a ×100 %-format bug in bounds rows) |

### Reports
- `results/RECTIFICATION_REPORT.md` — the RQ1 denominator fix + follow-ons
- `results/STRENGTHENING_REPORT.md` — 8-phase strengthening pass
- `results/MAVEN_ONLY_COMPARISON.md` — dual-ecosystem vs Maven-only side-by-side
- `docs/secbreak_paper_strengthening_tasks.md`, `docs/paper_positioning_instructions.md`
- `secbreak_presubmission_analysis_checklist.md`

## Handoff step → current state

| Handoff step | State | Evidence |
|---|---|---|
| 0 — audit | **this file** | — |
| 1 — RQ1 denominator (n≈201 not 783) | **done, and superseded** | `analyzed_ok` flag added; denominator now 380 (coverage re-runs grew 201→369→380). Prevalence **42.1 % (160/380)**, 95 % Wilson CI [37.2, 47.1]. Reported with explicit coverage + Manski bounds [20.4, 71.9] + imputed 38.0 %. Not ~13.4 %/35.6 % as the handoff predicted — those were the pre-coverage-push numbers. |
| 2 — `tests_pass_new` all NaN | **done** | `phase4_diagnose_behavioral.py`: two structural bugs fixed (missing `git fetch` of PR head; bare `pytest`). Harness now produces real values on a 21-row diagnostic, but signal is env-confounded, so the paper **reports no behavioural-BC %** and documents it as future work in TtV — matches handoff §2.6–2.7. |
| 3 — RQ2 leakage (`has_behavioral_bc`) | **done** | removed from feature set; paper RQ2 explains the exclusion on principle. `has_cve` re-checked, kept, importance 0.005. |
| 4 — RQ2 repo-grouped CV + CIs | **mostly done** | `StratifiedGroupKFold` by `repo_full_name`, 5×5 repeats, AUC reported as mean±std (RF 0.894±0.069) + dummy baseline row. Logit coeffs have 95 % CIs. **Gap vs handoff:** per-metric *bootstrap* CIs (1000 iters) for AUC/F1/precision/recall are not reported — only mean±std across folds. |
| 5 — RQ3 manual validation 70/100 + Kappa | **N/A as written** | This paper's RQ3 = team remediation response, not adoption-strategy coding. RQ3 recomputed on corrected 160-PR BC set with strict relatedness filter (`rq3_analysis_strict.py`): merge rate 33.1 %, strict median fix 3.5 d (naive 1.0 d). The 100-row *BC-detector* validation sample (`results/validation/bc_validation_sample_corrected.csv`) is restratified but still 0/100 adjudicated — flagged for the author in `STRENGTHENING_REPORT.md`. |
| 6 — unify two LaTeX drafts | **done** | one canonical file; `secbreak_tse_short.tex` deleted, content merged. |
| 7 — six Related Work citations w/ differentiation | **partial → in progress this pass** | Alfadel/Rebatchi/Mohayeji/Rombaut-Cogo-Hassan already cited; **BreakGuard + Venturini being added now**; differentiation sentences being sharpened. |
| 8 — NVD affected-version validation | **not done → doing this pass** | new `nvd_metadata_validation.py` + `data/nvd_metadata_validation.csv` + TtV paragraph. |
| 9 — recompute Abstract/Discussion/Conclusion | **done** | all three rewritten to corrected numbers. Note: "3.4 %" and "0.0 % behavioral" still appear **deliberately** as historical contrast ("far above the original buggy 3.4 %"); "783" appears throughout as the cohort size. The Step-9/10 greps therefore legitimately return matches. |
| 10 — final compile + checklist | **doing this pass** | `pdflatex` present; `latexmk` absent. |

## Uncommitted working tree (do not clobber)

Large uncommitted diffs in `data/analysis_dataset_corrected.csv`,
`data/bc_results_corrected.jsonl`, `data/raw_prs_corrected.jsonl`, `detect_bcs.py`,
`pipeline_utils.py`, `improve_corrected_results.py`, several `results/*` — from an
in-progress coverage re-run + presubmission-artifact work. `paper/secbreak_tse_revision.tex`
has a 1-line uncommitted edit (369→380). Untracked: `generate_presubmission_artifacts.py`,
`push_coverage_corrected.py`, `results/presubmission_*.csv`, `data/progress_push_coverage.json`.
Provenance of the data-file changes is not fully clear from the tree alone — left for the
author to review/commit. This pass adds only new files + targeted paper edits on top.

## Known inconsistencies noticed during audit (for the presubmission pass, not fixed here)

1. `generate_presubmission_artifacts.py` prints Manski bounds / imputed prevalence ×100
   (`[2043.4%, 7190.3%]`, `3796.5%`) — a formatting bug in that script, not in `rq1_bounds.json`.
2. RQ3 merged share: `results/presubmission_supporting_metrics.csv` says 54/160 (33.8 %);
   paper says 53 (33.1 %).
3. BC-kind mix: paper says method 83.3 % / type 20.5 % / field 9.1 %; supporting metrics
   say 79.0 % / 11.6 % / 9.4 %. Different denominators (per-PR-any vs per-event) — needs a
   single consistent definition.
4. Paper still `[...,journal]{IEEEtran}`; TSE is a journal so this is fine (the strengthening
   report's SANER note about `conference` mode does not apply to a TSE submission).
