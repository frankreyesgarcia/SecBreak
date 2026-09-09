# SecBreak — Rectification Handoff: Execution Summary

Date: 2026-09-08 · Branch: `paper-strengthening/v2` · Target: IEEE TSE

This summarizes execution of the pasted rectification handoff. **Read
`AUDIT_INITIAL.md` first** — it maps every handoff step to the repo state. The short
version: Steps 1–6 and 9 were already done by two prior passes
(`results/RECTIFICATION_REPORT.md`, `results/STRENGTHENING_REPORT.md`); this pass did
the genuinely outstanding parts (Steps 7, 8, 10) and did **not** re-run completed work
or make destructive changes.

---

## 1. The six bug-class steps (1–6): already fixed before this pass

| # | Handoff claim | Actual state | Value before → after |
|---|---|---|---|
| 1 | RQ1 denominator = `len(df)`=783 instead of analyzed rows | Fixed in `rectification/rq1-fix`; `analyzed_ok` flag added; coverage re-runs since grew analyzed set 201→369→**380** | Prevalence **3.4 % (buggy) → 42.1 % (160/380)**, 95 % Wilson CI [37.2, 47.1]. Reported with explicit 48.5 % coverage + Manski bounds [20.4 %, 71.9 %] + model-imputed 38.0 %. |
| 2 | `tests_pass_new` NaN in every row → "0 % behavioral BC" is non-measurement | Fixed: `phase4_diagnose_behavioral.py` found + fixed two structural bugs (no `git fetch` of PR head; bare `pytest`). Harness now yields real values on a 21-row diagnostic. Signal still env-confounded. | Paper **reports no behavioral-BC %**; documents harness-fixed-but-unvalidated in Threats to Validity — exactly handoff §2.6–2.7. |
| 3 | `has_behavioral_bc` used as RQ2 feature = leakage | Removed from feature set in `rq2_model_corrected.py`; paper RQ2 explains the exclusion on principle. `has_cve` re-checked (kept, importance 0.005). | RF AUC single-split 0.88 → grouped-CV **0.894 ± 0.069**. |
| 4 | RQ2 CV not grouped by repo; no CIs | `StratifiedGroupKFold` by `repo_full_name`, 5×5 repeats; AUC as mean ± std; `DummyClassifier` baseline row (0.500); `statsmodels` logit coefficients with 95 % CIs. | **Partial gap:** per-metric *bootstrap* CIs (1000 iters) for AUC/F1/precision/recall not reported — only mean ± std across 25 folds. Author call whether that suffices for TSE. |
| 5 | RQ3 manual validation 30/100, need Cohen's κ | **N/A as written.** This paper's RQ3 = team remediation response (merge rate, follow-up-fix time), not adoption-strategy coding. Recomputed on corrected 160-PR BC set with a strict relatedness filter (`rq3_analysis_strict.py`). | Merge rate 33.1 %; strict median fix **3.5 d** (naive keyword-only 1.0 d, 68.4 % of naive candidates unrelated). |
| 6 | Unify two diverged LaTeX drafts | Already done: one canonical file `paper/secbreak_tse_revision.tex`; `secbreak_tse_short.tex` deleted, unique content merged. | — |

**Deliberate deviation:** the handoff's Step 6 also says to rename the file to
`secbreak_tse_main.tex` and move originals to `archive/`. Not done — `secbreak_tse_revision.tex`
is already the single canonical file and is referenced by name in both prior reports and
the Replication Package section. Renaming now would break those references for no benefit.

---

## 2. Step 7 — six Related Work citations with explicit differentiation (DONE this pass)

All six now appear with a differentiation clause, not a drive-by cite. Two were newly
added; four were already cited and had their differentiation sharpened. Every key was
verified against a real source (web search / arXiv fetch), not carried from notes.

| Citation | Status | Where | Differentiation clause (extract) |
|---|---|---|---|
| **BreakGuard** — Raj, Baudry, Costa, arXiv 2608.20167, 2026 (`breakguard2026`) | **NEW** | Related Work, "Detection tooling…" | "…a general-purpose detector, not a prevalence study, and is not scoped to security PRs." (verified: reports 30.3 % detection on BUMP; better on crash-type than behavioral BCs — the handoff's "0.7 %" figure could not be confirmed and was **not** used.) |
| **Venturini et al.** — TOSEM 2023, arXiv 2301.04563 (`venturini2023`) | **NEW** | Related Work, "Breaking changes and SemVer…" | "…their signal is behavioral (test-based) and their population is general npm updates, whereas we measure syntactic API-level BCs via static diffing in Maven/PyPI security PRs specifically." (verified: ~12 % of dependent packages, 14 % of releases.) |
| **Alfadel et al.** — MSR 2021 (`alfadel2021`) | sharpened | Related Work, "Dependabot security PR management" | "…'breaking build' appears there as one maintainer-stated reason among several for closing a PR without merging — a self-reported signal over the rejected subset, not an API-level compatibility measurement over the merged population, and not for Maven." (Kept measured: the handoff's exact "3.2 % / 4,440 of 15,243 / eight reasons" figures could not be verified and were not asserted.) |
| **Rebatchi et al.** — EMSE 2024 (`rebatchi2024`) | sharpened | same bucket | "…at much larger scale, again without API-level breaking-change analysis." |
| **Mohayeji et al.** — MSR 2023 / EMSE 2025 (`mohayeji2023`, `mohayeji2025`) | already present | same bucket | "…they explain how security PRs are handled, whereas our contribution is to measure the client-side compatibility risk of the proposed security fix itself." |
| **Rombaut et al.** — arXiv 2403.09012, 2024 (`rombaut2024`, was `cogo2024`) | fixed + moved | **Introduction** (as RQ2 motivation) + Related Work | Intro: "…cannot be computed for 83 % of dependency updates for lack of crowd data… That gap motivates RQ2." (Bibitem authorship corrected: was "F. Côgo and A. E. Hassan"; real first author is B. Rombaut.) |

---

## 3. Step 8 — NVD affected-version metadata validation (DONE this pass)

- New script `nvd_metadata_validation.py` (adapted to this dataset's real columns:
  `dependency_name`, `old_version`, `new_version`, `cve_ids`, `has_bc`, `analyzed_ok`).
- Random sample (`random_state=42`) of **100** CVE-linked Maven PRs from the analyzed set.
  For each, HEAD-checks the claimed-vulnerable (`old_version`) **and** fixed
  (`new_version`) coordinate against Maven Central.
- **Result: mismatch rate 0.0 %.** All 100/100 `old_version` and 100/100 `new_version`
  coordinates resolve to real published artifacts. Output: `data/nvd_metadata_validation.csv`.
- Interpretation (now a Threats-to-Validity paragraph, `\cite{nvdquality2026}` =
  Nong et al., arXiv 2609.01503, 2026, verified): this rules out the "phantom version"
  failure mode for the measured subset — every reported BC is diffed between two
  artifacts that demonstrably exist. It is expected to be clean here because the
  coordinates come from the concrete `bump X from A to B` pair in each Dependabot PR, not
  from an NVD version range. It does **not** verify CVE severity/affected-range semantics,
  which remain un-audited (stated as such).

---

## 4. Step 10 — final verification

| Check | Result |
|---|---|
| `pdflatex` compile (×2) | exit 0, **6 pages**, `Output written … (6 pages)` |
| Undefined citations / references | **none** (`grep -i undefined` on `.log` is empty) |
| Multiply-defined labels | none |
| All 6 handoff citations present with keys | BreakGuard/`breakguard2026`, Venturini/`venturini2023`, Alfadel/`alfadel2021`, Rebatchi/`rebatchi2024`, Mohayeji/`mohayeji2025`, Rombaut/`rombaut2024` — all YES |
| Stale `cogo2024` key | fully renamed, 0 remaining |
| Overfull hboxes | 10 (pre-existing, cosmetic) |
| `latexmk` | not installed; used `pdflatex` directly |

**On the handoff's "grep must return empty for 3.4 % / 783":** it does not, and should
not. "3.4 %" appears once, deliberately, as historical contrast ("far above the original
buggy 3.4 %"). "783" appears 10× as the cohort size. These are correct, not stale claims.
The paper's numbers are the corrected ones throughout (42.1 %, 380, 160, 3.5 d, AUC 0.894).

---

## 5. What was intentionally NOT done (and why)

| Handoff item | Why skipped |
|---|---|
| Re-run BC-detection / RQ pipelines on the full cohort | Already run twice; outputs are the `*_corrected` files the paper cites. A fresh run would overwrite **uncommitted** working-tree changes to `data/analysis_dataset_corrected.csv` et al. of unclear provenance, and costs 8 h+. If a re-run is wanted, commit or stash the working tree first. |
| Rename tex → `secbreak_tse_main.tex`, move originals to `archive/` | Consolidation already done; one canonical file; renaming breaks references in both prior reports + Replication Package. |
| Commit the large uncommitted `data/*` + `detect_bcs.py` + `pipeline_utils.py` diffs | Provenance not fully clear from the tree (in-progress coverage re-run + presubmission work). Author's call. |
| RQ3 adoption-strategy coding + Cohen's κ (Step 5) | Targets a different RQ3 design than this paper has. |

---

## 6. Decisions still required from the author before TSE submission

1. **Maven-only vs. dual-ecosystem scoping.** Both variants are fully generated
   (`results/MAVEN_ONLY_COMPARISON.md`). The paper reports dual-ecosystem with a
   `PENDING AUTHOR DECISION` comment at the top of Results. RQ1 prevalence is 42.1 %
   (dual) vs 65.6 % (Maven-only); RQ2 best AUC 0.894 vs 0.785. Must be resolved and the
   paper made internally consistent to one choice.
2. **Manual BC-detector validation.** `results/validation/bc_validation_sample_corrected.csv`
   is restratified (100 rows, all `analyzed_ok`) but **0/100 adjudicated**. Pre-fetched
   review context is in `results/validation/review_context.jsonl`. The presubmission gate
   wants ≥ 20–30 adjudicated rows with a reported precision/recall before submission.
3. **RQ2 metric CIs.** Currently mean ± std across 25 grouped folds. Handoff Step 4 asks
   for bootstrap 95 % CIs (1000 iters) on AUC/F1/precision/recall. Decide whether to add.
4. **Behavioral-BC harness.** Fixed but unvalidated; paper reports no number. Decide
   whether to invest in the follow-up (install PyPI test extras; pre-warm Maven BOM
   resolution) or ship it as future work as currently written.
5. **Pre-existing internal inconsistencies flagged during audit** (see `AUDIT_INITIAL.md`
   §"Known inconsistencies"): RQ3 merged share 53/33.1 % (paper) vs 54/33.8 %
   (`presubmission_supporting_metrics.csv`); BC-kind mix 83.3/20.5/9.1 % (paper) vs
   79.0/11.6/9.4 % (metrics — different denominator); `generate_presubmission_artifacts.py`
   prints bounds ×100. **RESOLVED** in the claim-trace pass (commit `fix: resolve
   RQ3/BC-kind denominator inconsistencies (item 5)`): paper now cites 54/160 (33.8 %) —
   `merged_at`-non-null is the RQ3 scripts' own `merged` definition, so the CSV was right
   and the paper's 53 was a stray copy of the naive follow-up-fix count; BC-kind mix now
   79.0/11.6/9.4 % everywhere (mutually-exclusive prefix over 135{,}437 method/type/field
   events, footnoted in the paper), the old 83.3/20.5/9.1 % came from overlapping substring
   matching that summed to 112.9 %; `fmt_pct_value()` added so bounds/imputed print as
   [20.4 %, 71.9 %] / 38.0 %. The uncommitted BC-detection re-run (407 analyzed / 173 BC)
   that had partially landed in the working tree was moved to `git stash` (item 6).
6. **Uncommitted working tree.** Review and commit (or discard) the `data/*` / pipeline
   diffs before submission so the replication package is a clean, reproducible state.

---

## 7. Files produced this pass

| File | Purpose |
|---|---|
| `AUDIT_INITIAL.md` | Step 0 — full inventory + handoff-step-to-state map |
| `nvd_metadata_validation.py` | Step 8 — NVD affected-version check script |
| `data/nvd_metadata_validation.csv` | Step 8 — 100-row result (0 % mismatch) |
| `RECTIFICATION_SUMMARY.md` | this file |
| `paper/secbreak_tse_revision.tex` | edited: Intro (Rombaut/RQ2 motivation), Related Work (BreakGuard + Venturini added; Alfadel/Rebatchi/Rombaut sharpened), Threats to Validity (NVD paragraph), bibliography (+3 bibitems, `cogo2024`→`rombaut2024`), Replication Package list |
| `paper/secbreak_tse_revision.pdf` | recompiled, 6 pages, no undefined refs |

`[DONE] SecBreak rectification handoff executed — prior passes covered Steps 1–6/9; this pass added Steps 7–8, verified Step 10. See §6 for open author decisions.`
