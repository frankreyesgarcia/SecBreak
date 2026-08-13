# SecBreak — Paper Strengthening Task List
**For an autonomous coding agent (Claude Code), branch off `rectification/rq1-fix`
(or `main` once that's merged), new branch `paper-strengthening/v2`**

---

## CONTEXT

The RQ1 denominator bug is already fixed (branch `rectification/rq1-fix`, see
`results/RECTIFICATION_REPORT.md`). This task list makes the paper submission-ready
on its merits, independent of which venue it targets. Work through phases in order;
phases 1-4 are data/analysis work, phases 5-8 are paper content.

## GROUND RULES (same as the rectification pass)

- Never stop on an individual error. Log it, skip, continue.
- Checkpoint after every script.
- Never ask for confirmation. Log defensible decisions in
  `logs/strengthening_decisions.log`.
- Print `[DONE] step_name — details` after each step.
- Never overwrite an existing corrected/original file — write new outputs with
  clear suffixes so every stage of the pipeline stays diffable.
- English for all code, comments, commit messages, and paper text.
- Commit after each phase.

---

## PHASE 1 — Fix the RQ3 follow-up-fix relatedness bug

**Problem:** `find_followup()` in `rq3_analysis_corrected.py` counts *any* PR in the
repo created after the merge date whose title/body contains "fix", "revert",
"repair", "downgrade", or "rollback" as the BC's remediation — with no check that
it touches the same dependency or references the original PR. This almost
certainly overcounts and produces an implausibly fast median (1.0 day).

1. In `find_followup()`, tighten the match: a candidate PR only counts as a
   follow-up fix if, in addition to the existing keyword match, it does at least
   one of:
   - references the original PR number (`#{pr_number}`) in title or body, or
   - modifies the same dependency manifest file (`pom.xml`, `build.gradle`,
     `requirements.txt`, `setup.py`, `pyproject.toml` — check the PR's changed
     files via `GET /repos/{repo}/pulls/{pr_number}/files`), or
   - mentions the dependency name itself (`row["dependency_name"]`) in title/body.
2. Re-run `collect_followup()` for the 159-row corrected BC set into a new cache
   `data/rq3_followup_strict.jsonl` (don't overwrite `rq3_followup_corrected.jsonl`).
3. Report, in `results/rq3_tables_strict.csv`, both the old (keyword-only) and new
   (relatedness-filtered) numbers side by side: count of candidate fixes found by
   each method, and the resulting median/IQR time-to-fix for each. This
   before/after comparison is itself worth a sentence in the paper — quantifying
   how much naive keyword matching overcounts remediation.
4. If the strict median is still very fast (under a few days), that's a fine
   result — just make sure it survived the relatedness filter, not the raw
   keyword search.

---

## PHASE 2 — Selection-bias quantification table

**Problem:** the paper currently asserts, in prose only, that the analyzed subset
(369/783) is "not a random subsample." Back it with numbers.

1. Write `analyze_selection_bias.py`. Using `data/analysis_dataset_corrected.csv`
   with the `analyzed_ok` column, compute for `analyzed_ok=True` vs.
   `analyzed_ok=False`:
   - `repo_stars`: median, IQR, and a Mann-Whitney U test
   - `ecosystem`: proportion Maven vs. PyPI, chi-square test
   - `version_bump_type`: distribution, chi-square test
   - `merged` (derived from `merged_at` non-null): proportion, chi-square test
2. Write the result table to `results/selection_bias_table.csv` and a
   corresponding LaTeX table snippet to `paper/tables/selection_bias.tex`.
3. Expected direction (already spot-checked): analyzed rows skew toward lower
   `repo_stars` and toward `merged=False`. Confirm and report exact numbers, don't
   assume they'll match this spot check exactly on a full re-run.

---

## PHASE 3 — Partial-identification bounds + model-based imputation sensitivity check

**Goal:** turn "47.1% coverage is a limitation" into a quantified, defensible
robustness statement instead of a caveat.

1. Write `rq1_bounds.py`:
   - **Worst-case bounds (Manski bounds):** with `n_analyzed=369`, `n_bc=159`,
     `n_total=783`, compute:
     - lower bound = `n_bc / n_total` (assumes all unanalyzed rows are BC-free)
     - upper bound = `(n_bc + n_unanalyzed) / n_total` (assumes all unanalyzed
       rows have a BC)
     - Report both explicitly labeled as worst-case, not best-guess, bounds.
   - **Model-based imputed estimate:** load the RQ2 corrected Random Forest model
     (retrain on `analyzed_ok==True` rows using `rq2_model_corrected.py`'s
     `get_features()`), apply it to the 414 `analyzed_ok==False` rows using only
     their pre-outcome features (`repo_stars`, `cvss_score`,
     `version_bump_ord`, `ecosystem_bin`, `has_cve`, CWE one-hots — the same
     feature set RQ2 already uses, so no new leakage risk), and report the
     resulting **imputed full-cohort prevalence** = `(159 + sum(predicted
     probabilities over the 414 rows)) / 783`, with a bootstrap CI (resample the
     414 rows with replacement, refit is not needed, just resample the predicted
     probabilities and recompute the aggregate 1000 times).
   - Print all three numbers together: worst-case range, analyzed-only estimate
     (43.1%), and model-based imputed estimate. This triangulation is a genuine
     methodological contribution — say so explicitly in the script's output
     summary, and write it to `results/rq1_bounds.json`.
2. This does not replace the 43.1% headline number — it contextualizes it. The
   paper should still cite 43.1% as the primary result, with the bounds/imputation
   as a robustness subsection.

---

## PHASE 4 — RQ2 additions: baseline comparison + interpretable coefficients

1. In `rq2_model_corrected.py` (or a new `rq2_model_extras.py` reading its output),
   add:
   - A `DummyClassifier(strategy="most_frequent")` baseline evaluated with the
     same repeated grouped CV, reported alongside the four existing models in
     `results/rq2_model_results_corrected.csv` (add a row, don't create a new
     file) — this contextualizes AUC 0.906 against a trivial baseline.
   - Refit the Logistic Regression pipeline once on the full `analyzed_ok` set
     (not just for CV scoring) and report **coefficients with 95% CI** (via
     `statsmodels.Logit` rather than sklearn, since sklearn doesn't give CIs
     directly) for `ecosystem_bin`, `cvss_score`, `version_bump_ord`,
     `repo_stars` — write to `results/rq2_logit_coefficients.csv`.

---

## PHASE 5 — Generate a Maven-only variant of every RQ1/RQ2/RQ3 result

**Do not decide Maven-only vs. dual-ecosystem — produce both so the decision can
be made after seeing real numbers side by side.**

1. Re-run `rq1_analysis_corrected.py`, `rq2_model_corrected.py`, and the Phase 1
   strict version of `rq3_analysis_corrected.py`, each with an added
   `--maven-only` flag that filters to `ecosystem == "maven"` before any
   computation. Write outputs with a `_mavenonly` suffix
   (`results/rq1_tables_mavenonly.csv`, etc.) alongside the existing dual-ecosystem
   corrected outputs.
2. Write a short `results/MAVEN_ONLY_COMPARISON.md` summarizing, side by side:
   pipeline coverage, prevalence + CI, best model AUC, RQ3 merge rate/fix time —
   dual-ecosystem vs. Maven-only. This is what gets read to make the scoping
   decision.

---

## PHASE 6 — Tooling to speed up manual validation (do NOT perform the adjudication)

The actual manual labeling of BC/no-BC in `bc_validation_sample_corrected.csv`
must be done by a human (Frank) — an agent should not fabricate ground-truth
labels. But you can remove friction:

1. Write `prepare_validation_review.py` that, for each of the 100 rows in
   `bc_validation_sample_corrected.csv`, pre-fetches and writes to a companion
   file `results/validation/review_context.jsonl`:
   - a direct link to the PR diff (`https://github.com/{repo}/pull/{pr}/files`)
   - a direct link to the dependency's changelog/release notes if discoverable
     (try `CHANGELOG.md` at the dependency's own repo, or its GitHub releases
     page, via a best-effort lookup — log failures, don't block)
   - the raw Roseau/griffe output already stored in `bc_types`/`bc_count` for that
     row, formatted human-readably
2. This turns each row's manual review into "open one link, read one summary,
   type yes/no/unsure" instead of a cold investigation, which matters a lot given
   there are 100 of them (or however many Frank chooses to actually do, e.g. 20-30
   for a first pass — the tooling should work for any subset).
3. Leave the `manual_bc_label` / `manual_bc_confidence` / `manual_bc_notes` /
   `manual_validation_status` columns empty for Frank to fill in by hand.

---

## PHASE 7 — Insert the Related Work section

Insert the following section into `paper/secbreak_tse_revision.tex`, positioned
after the Introduction and before Study Design. **Before finalizing for
submission, verify every citation key below against real BibTeX records —
these are placeholder keys sourced from prior literature notes, not verified
bibliographic entries; do not submit with unverified citations.**

```latex
\section{Related Work}
\label{sec:related}

\textbf{Breaking changes and SemVer compliance.} Foundational work established
the source/binary/behavioral taxonomy of breaking changes and documented
widespread SemVer violations across ecosystems~\cite{dietrich2014semver,
raemaekers2017semver}. Ochoa et al. studied SemVer compliance at scale in Maven
and quantified how frequently breaking changes appear in non-major
releases~\cite{ochoa2022maven}. Jayasuriya et al. analyzed 18,415 Maven
artifacts and found that 11.6\% of dependency updates introduce breaking
changes, with roughly half occurring in non-major versions~\cite{jayasuriya2024emse}
-- the closest prior measurement of client-side syntactic BC prevalence to the
one in this paper, though for general dependency updates rather than
specifically security-motivated ones. Hora et al. mapped manifesting breaking
changes in npm and showed that a substantial share go
undocumented~\cite{hora2018tosem}.

\textbf{Security update automation.} Raemaekers et al.~\cite{raemaekers2021}
is the direct point of comparison for this paper: they found that 13.2\% of
security releases declare backward incompatibility via provider-side
versioning metadata, and explicitly identified downstream, client-side
validation as future work -- the gap this paper addresses. Kula et al. studied
the adoption of security updates more broadly~\cite{kula2018emse}. More recent
work has examined Dependabot and Renovate as interventions in the update
process~\cite{dependabotrenovate2025}, but without measuring whether the
updates these bots produce are themselves compatibility-safe.

\textbf{Positioning.} To our knowledge, no prior study measures client-side
breaking-change prevalence specifically within the population of
security-motivated automated pull requests, as opposed to dependency updates in
general. This distinction matters practically: security PRs carry an implicit
urgency (a known vulnerability) that general dependency updates do not, so the
risk/reward calculus for merging quickly is different, and it is exactly this
population that Raemaekers et al.'s provider-side metadata result leaves
unmeasured at the client side.
```

Adjust citation keys to match whatever `.bib` file the repo uses, and add the
corresponding entries. If any of the referenced works cannot be located/verified,
leave a `% TODO: verify citation` comment rather than guessing at bibliographic
details.

---

## PHASE 8 — Trim and restructure

1. Condense the current Discussion's rectification narrative (currently ~40% of
   the paper) to:
   - One paragraph in Methodology describing the bug and fix at a high level,
     pointing to `results/RECTIFICATION_REPORT.md` in the replication package for
     full detail.
   - The Phase 3 bounds/imputation numbers as a short "Robustness" subsection
     under Results (RQ1).
   - Two paragraphs in Threats to Validity: the coverage/representativeness
     limitation (now backed by the Phase 2 table and Phase 3 bounds), and the
     residual known issues (ecosystem mistagging, the `"|"` version-string bug,
     behavioral BC being unmeasured).
2. Insert the Phase 7 Related Work section.
3. Insert the Phase 4 dummy-baseline row and logit-coefficient discussion into
   RQ2 results.
4. Insert the Phase 1 strict-vs-naive RQ3 comparison into RQ3 results, with the
   strict numbers as the ones the paper cites going forward.
5. Do not resolve the Maven-only vs. dual-ecosystem question in this phase --
   leave both variants available (Phase 5) and flag clearly in a comment at the
   top of the Results section that this is a pending author decision before
   final submission.

---

## FINAL OUTPUT

Produce `results/STRENGTHENING_REPORT.md` summarizing, phase by phase, what was
added/changed, mirroring the structure of `RECTIFICATION_REPORT.md`. Include:
- the RQ3 strict-vs-naive fix comparison numbers
- the selection-bias table
- the three-number RQ1 robustness triangulation (worst-case bounds,
  analyzed-only estimate, model-based imputed estimate)
- the RQ2 baseline/coefficient additions
- the Maven-only vs. dual-ecosystem side-by-side comparison
- an explicit list of what still requires human judgment before submission:
  (1) manual validation labels, (2) Maven-only vs. dual-ecosystem decision,
  (3) citation verification, (4) venue-specific formatting.