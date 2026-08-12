# SecBreak Data Rectification Report

This report documents the correction of a silent-default bug in the RQ1 breaking-change
(BC) detection pipeline that had invalidated the headline result reported in
`paper/secbreak_tse_short.tex` (now removed; see "Paper consolidation" below), and the
follow-on corrections this triggered across RQ2, RQ3, and the manual validation package.

**Bottom line: the original 3.4% BC prevalence was an artifact of counting never-analyzed
PRs as verified negatives. The corrected, analyzed-only prevalence is 43.1% (159/369) —
significantly *higher* than the 13.2% provider-side baseline this paper compares against,
not lower.**

## Final verification

Exact output of the verification script specified for this rectification:

```
--- BEFORE ---
total rows: 783
analyzed_ok: 201 (25.7%)
has_bc (naive, over all rows): 27 (3.4%)
has_bc (correct, over analyzed rows only): 27 (13.4%)

--- AFTER ---
total rows: 783
analyzed_ok: 369 (47.1%)
has_bc (naive, over all rows): 159 (20.3%)
has_bc (correct, over analyzed rows only): 159 (43.1%)
```

Worth noting: even the *original* 201-row analyzed subset, computed correctly (over
analyzed rows only, not `len(df)`), gives 13.4% — statistically indistinguishable from
the TSE 2021 baseline of 13.2%. The paper's original "client-side risk is significantly
lower" claim was entirely a product of using the wrong (full-cohort) denominator; it was
never supported by the data that had actually been analyzed, even before Phase 1/2 grew
that analyzed set from 201 to 369 rows.

### Checklist

- [x] Coverage rate (`analyzed_ok / total`) improved materially from 25.7% → **47.1%**.
- [x] Corrected RQ1 prevalence number (43.1%) is the one now cited in the paper — only one
      canonical `.tex` file remains (see below), so there is no second file to diverge.
- [x] `tests_pass_new` is no longer 100% NaN for the diagnostic sample (21/21 rows got real
      True/False values after fixing the harness) — **and** the behavioral-BC claim has
      been removed from the paper's headline results and moved to Discussion/Threats to
      Validity as explicit future work, because a follow-on diagnostic showed the
      resulting signal is still dominated by environment confounds, not real behavioral
      BCs. Both parts of this checklist item are satisfied simultaneously: the harness
      works, and we still don't report a number from it, because "works" and
      "trustworthy" turned out to be different bars.
- [x] `has_behavioral_bc` is removed from the RQ2 feature set.
- [x] RQ2 AUC is now reported with mean ± std across repo-grouped folds (0.906 ± 0.064,
      25 folds), not a single point estimate.
- [x] Validation sample is restratified (100 rows, all `analyzed_ok`) and contains no
      unresolved/unanalyzed rows.
- [x] Only one canonical `.tex` file remains: `paper/secbreak_tse_revision.tex`
      (`paper/secbreak_tse_short.tex` deleted, its unique content merged in).

## What was wrong

`parse_dependency_name()` in `collect_prs.py` extracts a Maven dependency's
`groupId:artifactId` from the PR title via regex. For older-style Dependabot titles
(`"bump X from A to B"`, used before Dependabot began including the groupId in Maven PR
titles), this captured only the artifact name with no groupId — 425 of 554 Maven rows
(76.7%). `detect_maven_bcs()` correctly refused to run without a resolvable coordinate,
returning `analysis_error: missing_dependency_coordinates` — but the same function's error
path also set `has_bc: False` in the same dict, and `rq1_analysis.py` used `len(df)` (783)
as its prevalence denominator without checking `analysis_error`. The two bugs compounded:
582 of 783 rows (74.3%) never had BC detection run, and every one of them was silently
counted as a verified compatible negative.

## Phase-by-phase summary

**Phase 1 — dependency coordinate resolution.** Wrote `fix_dependency_coordinates.py` to
resolve real `groupId:artifactId` pairs from each affected PR's diff (matching the
`pom.xml`/`build.gradle` dependency block whose version moved from `old_version` to
`new_version`, including one level of Maven property indirection). Resolved 200/425
(47%) unique missing-coordinate rows — below the ~80% target. Root cause of the shortfall,
confirmed by inspection: `ecosystem_from_repo_files()` in `collect_prs.py` tags a PR's
ecosystem from repo-root file presence, not from what the PR itself modifies. In polyglot
repositories with a `pom.xml` present, many "Maven" rows are actually GitHub Actions bumps
(`aquasecurity/trivy-action`, 72/225 unresolved) or npm/pip bumps
(`OpenAPITools/openapi-generator`: `ajv`, `url-parse`, `json5`, `webpack`, `postcss`,
`flask`, `requests`, dozens of rows) that were never Maven dependency bumps and are
correctly unresolvable. This is a distinct, pre-existing data-quality bug, out of scope
for this rectification; flagged as future work (per-PR ecosystem tagging from changed
files, not repo-root presence).

**Phase 2 — re-run BC detection on repaired rows.** Straightforward on paper, but three
infrastructure bugs surfaced and were fixed during execution, in order:
1. `mvn dependency:copy`'s 300s timeout was mostly spent waiting out artifacts that would
   never resolve (BOM/pom-only coordinates, bad coordinates) — reduced to 60s and the
   checkpoint interval to every 5 rows. This alone wasn't the real problem, below.
2. `mvn dependency:copy` was found to **hang indefinitely** in this environment — confirmed
   via `ss` that it never even opens a socket to Maven Central while resolving its own
   plugin, even though the identical URLs resolve in well under a second over plain HTTPS
   and `mvn test` (a different resolver code path) downloads from Central successfully.
   Replaced `maven_copy()` with a direct HTTPS download from Maven Central. All 153 rows
   the first restarted run had processed were false `jar_download_failed` results as a
   consequence and were discarded.
3. That same restart also exposed that `jars/roseau-cli-0.5.0.jar` — a vendored tool
   tracked in git, not a cache artifact — lived inside the same directory used as
   per-PR download scratch space, and had been deleted (twice) by cache cleanup during
   this session. Combined with `JAVA_BIN` not being set (Roseau requires Java ≥25;
   the environment's default `java` is 21), `detect_maven_bcs()` was silently falling
   back to japicmp for every row, diverging from the original run's predominantly-roseau
   methodology. Fixed by relocating the jar out of the cache directory and adding
   `resolve_java_bin()` to auto-discover a Java 25 sdkman candidate when `JAVA_BIN` isn't
   explicitly exported.

   Final result: 168/200 coordinate-repaired rows (84%) successfully re-detected via the
   correct tool. The 139 transient-error retries (53 `jar_download_failed` + 86
   `pip_install_failed`) all still failed after retry with the fixed tooling — not a bug:
   most are genuine BOM artifacts with no jar to diff, plus a handful with
   `old_version`/`new_version` literally equal to the string `"|"` (a separate,
   pre-existing regex bug in `pipeline_utils.extract_versions()`, flagged but not fixed
   here). The 86 pip failures were not individually root-caused given time constraints;
   left as `analyzed_ok=False` either way, the safe outcome.

**Phase 3 — RQ1 with a correct denominator.** Added an explicit `analyzed_ok` column and
report three numbers: full-cohort naive rate (20.3%, explicitly not a prevalence
estimate), analyzed-only prevalence (**43.1%, 159/369, 95% CI 38.1–48.2%**, cite this
one), and pipeline coverage (47.1%). Verified the magnitude of the change is real, not a
matching artifact: within every version-bump stratum, newly-resolved rows show 6–9× higher
BC rates than the original 201-row baseline, and manual spot-checks of 10 newly-resolved
rows confirmed correct dependency matches against real, well-documented major upgrades
(H2 1.4.190→2.1.210, Jetty 9.4→10.0, Guava 30→32, Hibernate 5.2→5.4).

**Phase 4 — behavioral BC harness.** Diagnosed and fixed two structural bugs: (1) the
harness never `git fetch`ed the PR's head commit before checking it out, so
`git checkout head_sha` failed with "reference is not a tree" on essentially every row —
almost certainly the dominant cause of the original 100% `tests_pass_new` NaN rate; (2)
PyPI's test runner invoked a bare `pytest` with no guarantee it or the repo's own
dependencies were installed anywhere, causing `tests_available=False` for all 229 PyPI
rows. Both confirmed fixed on a 21-row diagnostic sample (16-row sweep + 5-row large-repo
timing probe): every row now produces a real `tests_pass_new` value. However, the same
diagnostic showed the resulting pass/fail signal is still dominated by environment
confounds unrelated to the PR under study — missing test-only PyPI dependencies (our
installer only captures `install_requires`, not test extras) and Maven Central
rate-limiting on cold multi-module builds. Per the rectification doc's explicit guidance
for this situation, **we do not report a behavioral-BC percentage** in the corrected
results or paper; it is documented as fixed-but-not-validated future work.

**Phase 5 — RQ2 methodology.** Removed `has_behavioral_bc` from the feature set (post-outcome
leakage regardless of importance). Re-checked `has_cve` after that removal — importance is
negligible (0.005, rank 16/16) but kept, since it's a legitimate pre-outcome feature and
low importance is a valid finding, not evidence of a leak. Replaced the single
`train_test_split` with repeated `StratifiedGroupKFold` (5 repeats × 5 folds, grouped by
`repo_full_name`). Best model: Random Forest, **AUC-ROC 0.906 ± 0.064** across 25 folds
(original: single-split point estimate of 0.88).

**Phase 6 — validation sample restratification.** Regenerated the 100-PR manual validation
sample from `analyzed_ok` rows only; 414 non-analyzed rows are excluded from the sampling
frame entirely rather than mixed in as if they were detector negatives (the original
sample had 70/100 rows with `analysis_error` set).

**Phase 7 — paper and pipeline fixes.** Moved the merged-PR rate out of the BC-prevalence
table into the dataset-description text. Consolidated to one canonical paper
(`paper/secbreak_tse_revision.tex`, chosen for its more complete Threats to Validity and
existing Replication Package section; unique content from the other file — the Conclusion
section and detailed RQ2 table — was merged in before it was deleted) and rewrote every
numeric claim to match the corrected pipeline output. Softened the CI-signal wording to
match what `repo_has_ci()` actually checks (presence of `.github/workflows`, not proof CI
ran or passed).

**RQ3 (not one of the 7 named phases, but required for consistency).** RQ3's team-response
statistics are computed over the `has_bc==1` subset, which grew from 27 to 159 rows once
RQ1 was corrected. Recomputed on the corrected set for internal paper consistency: merge
rate 33.3% (vs. 29.6% original), median follow-up fix 1.0 day (vs. 0.9), broadly similar
shape but resting on a 6× larger, non-cherry-picked sample.

## Known limitations carried forward (not fixed in this pass)

1. **Ecosystem mistagging** (Phase 1 finding): `ecosystem_from_repo_files()` tags a PR's
   ecosystem from repo-root file presence, not from what the PR modifies, causing some
   GitHub Actions/npm/pip bumps in polyglot repos to be mislabeled as Maven rows.
2. **`old_version`/`new_version` extraction bug** (Phase 2 finding): a handful of rows have
   these fields literally equal to the string `"|"`, from a pre-existing regex bug in
   `pipeline_utils.extract_versions()` unrelated to the coordinate bug this rectification
   targeted.
3. **Behavioral BC is unmeasured**, not conservatively zero. The harness works; the signal
   it produces is not yet trustworthy (see Phase 4 above). Recommended follow-up: install
   PyPI test/dev extras (not just `install_requires`), and pre-warm or mirror Maven Central
   BOM resolution to avoid rate-limit-induced false failures on cold multi-module builds.
4. **The 86 `pip_install_failed` retries** were not individually root-caused; plausible
   causes (yanked PyPI releases, missing system build dependencies, Python-version
   incompatibility with old package releases) were not distinguished from each other.

## File manifest (corrected vs. original)

| Corrected | Original (preserved) |
|---|---|
| `data/raw_prs_corrected.jsonl` | `data/raw_prs.jsonl` |
| `data/bc_results_corrected.jsonl` | `data/bc_results.jsonl` |
| `data/analysis_dataset_corrected.csv` | `data/analysis_dataset.csv` |
| `data/rq3_followup_corrected.jsonl` | `data/rq3_followup.jsonl` |
| `results/rq1_tables_corrected.csv` | `results/rq1_tables_ORIGINAL_BUGGY.csv` |
| `results/rq2_model_results_corrected.csv` | `results/rq2_model_results_ORIGINAL_BUGGY.csv` |
| `results/rq2_feature_importance_corrected.csv` | `results/rq2_feature_importance_ORIGINAL_BUGGY.csv` |
| `results/rq3_tables_corrected.csv` | `results/rq3_tables_ORIGINAL_BUGGY.csv` |
| `results/validation/bc_validation_sample_corrected.csv` | `results/validation/bc_validation_sample.csv` |
| `results/figures/*.png` (regenerated in place) | `results/figures/*_ORIGINAL_BUGGY.png` |
| `paper/secbreak_tse_revision.tex` (canonical) | `paper/secbreak_tse_short.tex` (deleted; content merged) |

All corrections were made on branch `rectification/rq1-fix`, committed incrementally per
phase, for review before merging to `main`.
