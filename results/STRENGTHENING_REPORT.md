# SecBreak Paper Strengthening Report

Companion to `results/RECTIFICATION_REPORT.md`. That report fixed the RQ1 denominator
bug (branch `rectification/rq1-fix`); this one covers the 8-phase paper-strengthening
pass on top of it (branch `paper-strengthening/v2`), aimed at making the paper
submission-ready on its methodological merits ahead of a SANER 2027 submission.

All 8 phases completed. After commit `8b129e9` (`Update paper analysis artifacts and manuscript`),
parts of the corrected pipeline were re-run via `improve_corrected_results.py`, changing the
final dual-ecosystem numbers again. This report has therefore been regenerated from the
current artifacts on disk (`data/analysis_dataset_corrected.csv`, `results/rq1_bounds.json`,
`results/rq1_tables_corrected.csv`, `results/rq2_*`, `results/rq3_tables_strict.csv`,
`results/selection_bias_table.csv`) rather than copied from the earlier narrative.

## Reconciliation: prior report vs. current artifacts

| Metric | Prior report | Current artifacts |
|---|---|---|
| `analyzed_ok` rows | 369 | 380 |
| Unanalyzed rows | 414 | 403 |
| BC-introducing PRs | 159 | 160 |
| Analyzed-only prevalence | 43.1% (159/369) | 42.1% (160/380) |
| 95% CI | [38.1%, 48.2%] | [37.2%, 47.1%] |
| Worst-case bounds | [20.3%, 73.2%] | [20.4%, 71.9%] |
| Model-imputed estimate | 38.0% [36.6%, 39.4%] | 38.0% [36.6%, 39.2%] |
| RQ2 best AUC (Random Forest) | 0.906 ± 0.064 | 0.894 ± 0.069 |
| Strict RQ3 fixes found | 46 (28.9%) | 47 (29.4%) |
| Strict RQ3 median fix time | 3.54 days | 3.54 days |

## Phase 1: RQ3 follow-up-fix relatedness fix

The original RQ3 "follow-up fix" detection counted any PR created after the merge date
whose title/body contained "fix", "revert", "repair", "downgrade", or "rollback" — no
check that it actually related to the dependency bump. Tightened to require, in addition,
that the candidate reference the original PR number, touch the same dependency manifest
file, or mention the dependency by name.

| | Naive (keyword-only) | Strict (relatedness-filtered) |
|---|---|---|
| Candidate fix PRs found (across all 160 BC PRs) | 784 | 248 |
| Fixes attributed | 53 (33.1%) | 47 (29.4%) |
| Median time-to-fix | 0.96 days | **3.54 days** |
| IQR | 0.13–3.54 | 0.80–10.40 |
| Within 7 days | 28.1% | 20.0% |
| Within 30 days | 31.2% | 25.6% |
| Reverted | 14.4% | **8.8%** |

**68.4% of naive keyword-matched candidates were unrelated.** The strict numbers are now
cited throughout the paper (Abstract, RQ3, Conclusion) in place of the naive ones.

## Phase 2: Selection-bias quantification

Backs the paper's prose claim ("the analyzed subset is not a random subsample") with
statistics, comparing `analyzed_ok=True` (n=380) vs. `analyzed_ok=False` (n=403):

| Variable | Test | Statistic | p-value | Direction |
|---|---|---|---|---|
| `repo_stars` | Mann-Whitney U | 46,736.5 | $3.6\times10^{-21}$ | Analyzed rows skew **lower**-star (median 9,234 vs. 16,684) |
| `ecosystem` | $\chi^2$ | 18.50 | $1.7\times10^{-5}$ | Analyzed skews less-Maven (63.4% vs. 77.7%) |
| `version_bump_type` | $\chi^2$ | 1.10 | 0.78 | **Not** significantly different |
| `merged` | $\chi^2$ | 21.57 | $3.4\times10^{-6}$ | Analyzed rows skew **unmerged** (44.2% merged vs. 61.0%) |

Full table: `results/selection_bias_table.csv`; LaTeX snippet: `paper/tables/selection_bias.tex`.

## Phase 3: RQ1 robustness triangulation

Three independent ways of bounding/estimating prevalence, all reported together in the
paper's new "Robustness" subsection (RQ1):

| Method | Estimate | Interval |
|---|---|---|
| Worst-case (Manski) bounds | — | **[20.4%, 71.9%]** |
| Analyzed-only (headline, unchanged) | **42.1%** | 95% CI [37.2%, 47.1%] |
| Model-based imputed (RF on pre-outcome features, applied to the 403 unanalyzed rows, bootstrapped) | **38.0%** | bootstrap 95% CI [36.6%, 39.2%] |

All three converge on "far above the original buggy 3.4% and above the 13.2% provider-side
baseline." The imputed estimate sitting close to (slightly below) the analyzed-only estimate
is a reassuring cross-check, not a contradiction — 42.1% remains the cited primary number.
Full output: `results/rq1_bounds.json`.

## Phase 4: RQ2 baseline and interpretable coefficients

Added a `DummyClassifier(most_frequent)` baseline (AUC = 0.500, as expected) to
`results/rq2_model_results_corrected.csv`, contextualizing Random Forest's 0.894.

Fit `statsmodels.Logit` on the full `analyzed_ok` set for coefficients with 95% CIs. The
full-feature fit did not converge — diagnosed as quasi-complete separation in one rare CWE
one-hot column (`cwe_CWE_476`), **not** `ecosystem_bin` as initially suspected. A refit
excluding that single column converges cleanly with near-identical coefficients:

| Feature | Coefficient | 95% CI | p-value |
|---|---|---|---|
| `ecosystem_bin` (Maven=0, PyPI=1) | −5.26 | [−6.81, −3.70] | $3.7\times10^{-11}$ |
| `version_bump_ord` | 0.68 | [0.25, 1.11] | 0.002 |
| `cvss_score` | 0.14 | [−0.17, 0.45] | 0.36 (n.s.) |
| `repo_stars` | −1.0e-5 | [−3.3e-5, 1.2e-5] | 0.36 (n.s.) |

Ecosystem and version-bump magnitude remain strong, significant, *converged* predictors
even controlling for other covariates; CVSS score and repo stars do not reach significance
once those two are accounted for. Full outputs: `results/rq2_logit_coefficients.csv` (full,
non-converged, with `converged`/`quasi_separated` flag columns) and
`results/rq2_logit_coefficients_converged.csv` (the one to cite).

## Phase 5: Maven-only vs. dual-ecosystem

Both variants fully generated; **no scoping decision made** (that's explicitly the point).
Full comparison: `results/MAVEN_ONLY_COMPARISON.md`. Summary:

| | Dual-ecosystem | Maven-only |
|---|---|---|
| RQ1 analyzed-only prevalence | 42.1% (160/380) | 65.6% (158/241) |
| RQ2 best model AUC (Random Forest) | 0.894 ± 0.069 | 0.785 ± 0.065 |
| RQ3 strict median fix time | 3.54 days | 3.54 days (158 vs. 160 BC PRs — two are PyPI) |

RQ1 and RQ2 change substantially under Maven-only scoping (RQ2's biggest predictor,
`ecosystem_bin`, is removed by construction); RQ3 is essentially unaffected either way.

## Phase 6: Validation review tooling

`prepare_validation_review.py` pre-fetches, for all 100 validation-sample rows: a direct
PR-diff link, a best-effort dependency changelog/repo link (Maven: parsed from the Maven
Central POM's `<scm>` URL; PyPI: parsed from the PyPI JSON API's `project_urls`), and the
raw Roseau/griffe `bc_types` output formatted human-readably. Dependency link found for
65/100 rows; the other 35 are logged, not blocking. Written to
`results/validation/review_context.jsonl`. **No adjudication was performed or fabricated**
— `manual_bc_label`/`manual_bc_confidence`/`manual_bc_notes`/`manual_validation_status` in
`bc_validation_sample_corrected.csv` remain 100% empty/`pending`, verified before and after.

## Phase 7: Related Work

Inserted after the Introduction. All 7 citation keys checked against real bibliographic
sources (web search/fetch, not the repo's `bib.json`, which turned out to cover an
unrelated PR-bots/agents literature set, not this paper's SemVer/breaking-change citations):

- **Confirmed, bibitem added:** `dietrich2014semver` (Dietrich/Jezek/Brada, CSMR-WCRE
  2014 — verified this is the actual source/binary/behavioral BC taxonomy paper),
  `raemaekers2017semver` (JSS 2017), `ochoa2022maven` (EMSE 2022, authors confirmed),
  `jayasuriya2024emse` (EMSE 2024 — its measured 11.58% matches the cited 11.6% almost
  exactly), `kula2018emse` (EMSE 2018).
- **Not confirmed, no bibitem added:** `hora2018tosem` (no matching 2018 Hora et al.
  npm/TOSEM paper found), `dependabotrenovate2025` (no single paper studying both
  Dependabot and Renovate found; closest real match is a Dependabot-only 2025 EMSE paper).
  Both left as unresolved `\cite{}` with `% TODO: verify citation` comments — they will
  render as `[?]` if the paper is compiled as-is, a second, harder-to-miss signal beyond
  the comment.

## Phase 8: Restructure

Condensed the rectification narrative from 6 Discussion paragraphs (~40% of the paper) to
a short Methodology paragraph (Study Design → "Data Rectification") pointing to
`RECTIFICATION_REPORT.md`, a 2-paragraph Discussion, and a 2-paragraph Threats to
Validity restructure citing Phase 2's real selection-bias numbers and Phase 3's bounds
instead of asserting non-representativeness in prose only. Integrated the Phase 1/4
findings into RQ2/RQ3 results directly. Added an explicit "PENDING AUTHOR DECISION"
comment at the top of Results flagging the Maven-only question. LaTeX structural checks
pass (balanced environments/braces, all `\ref{}` targets resolve, exactly the 2 unverified
citations are undefined as intended).

## What still requires your judgment before submission

1. **Manual validation labels.** `results/validation/bc_validation_sample_corrected.csv`'s
   100 rows need actual adjudication — `results/validation/review_context.jsonl` has the
   pre-fetched links/context to make this fast, but the yes/no/unsure calls are yours.
2. **Maven-only vs. dual-ecosystem scoping.** Both variants are generated
   (`results/MAVEN_ONLY_COMPARISON.md` has the side-by-side); the paper currently reports
   dual-ecosystem with a pending-decision comment at the top of Results. This changes the
   RQ1/RQ2 headline numbers substantially either way.
3. **Citation verification.** 5/7 Related Work citations verified against real sources;
   2 (`hora2018tosem`, `dependabotrenovate2025`) could not be confirmed and are flagged —
   either find the correct source or drop/rewrite those sentences before submission.
4. **Venue-specific formatting.** This pass did not touch page limits, IEEE conference
   vs. journal template conformance, or SANER's specific submission requirements — the
   paper is currently in `journal` mode (`\documentclass[10pt,journal]{IEEEtran}`); SANER
   is a conference, so this likely needs `\documentclass[10pt,conference]{IEEEtran}` and a
   page-count check against the 10+2-page limit before submission. The pre-submission audit
   should treat this as an explicit verification task rather than leaving it as a note.

## File manifest (new in this pass)

| File | Purpose |
|---|---|
| `rq3_analysis_strict.py` | Phase 1: relatedness-filtered RQ3 |
| `analyze_selection_bias.py` | Phase 2: selection-bias stats |
| `rq1_bounds.py` | Phase 3: Manski bounds + imputed estimate |
| `rq2_model_extras.py` | Phase 4: dummy baseline + logit coefficients |
| `rq1_analysis_corrected.py`, `rq2_model_corrected.py`, `rq3_analysis_strict.py` | Phase 5: `--maven-only` flag added to each |
| `prepare_validation_review.py` | Phase 6: validation review context |
| `docs/secbreak_paper_strengthening_tasks.md` | the task list this report follows |

All corrections were made on branch `paper-strengthening/v2`, off `rectification/rq1-fix`,
committed incrementally per phase, for review before merging.
