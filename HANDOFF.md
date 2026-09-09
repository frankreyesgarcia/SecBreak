# SecBreak — Handoff (2026-09-09)

Point-in-time handoff. `STATUS.md` is the lighter living version; this file is the full
picture, including one **critical unresolved issue found today**.

---

## One line

All the *pipeline / analysis bugs* from the rectification + strengthening passes are
resolved and merged to `main`. **But a load-bearing citation in the paper
(`raemaekers2021`, the "13.2% provider-side baseline") is fabricated** — it must be
removed and the paper's framing rebuilt before any submission.

---

## Git state

| Ref | SHA | Meaning |
|---|---|---|
| `origin/main` | `1672761` | fast-forwarded to the full feature branch today; nothing lost |
| `origin/paper-strengthening/v2` | `1672761` | same commit; kept alive (cohort expansion runs on it) |
| `origin/wip/bc-rerun-407-173` | `704d274` | the deferred 407-analyzed / 173-BC re-run, preserved as a branch |
| `git stash@{0}` | — | same 407/173 re-run, still stashed (belt + suspenders) |

Working tree clean except two untracked files that were never tracked:
`paper/IEEEtran.cls` (needed to compile — consider committing) and
`paper/secbreak_tse_revision.pdf` (build output).

**Push** (SSH has no key here; `token.txt` PAT works):
```bash
git push "https://$(tr -d ' \n' < token.txt)@github.com/frankreyesgarcia/SecBreak.git" HEAD:<branch>
```

---

## Bugs — RESOLVED

All identified pipeline/analysis bugs are fixed and on `main`:

| # | Bug | Resolution | Where |
|---|---|---|---|
| 1 | RQ1 prevalence denominator used `len(df)`=783, counting never-analyzed PRs as compatible | `analyzed_ok` flag; prevalence over 380 analyzed only → **42.1%** (was a buggy 3.4%) | `rectification/rq1-fix`, `build_dataset_corrected.py`, `rq1_analysis_corrected.py` |
| 2 | `tests_pass_new` NaN on every row (no `git fetch` of PR head; bare `pytest`) | harness fixed + verified on 21-row diagnostic; signal still env-confounded → **paper reports no behavioral-BC number**, documents it as future work | `phase4_diagnose_behavioral.py` |
| 3 | RQ2 used `has_behavioral_bc` (post-outcome) as a feature — target leakage | removed from feature set; explained on principle in the paper | `rq2_model_corrected.py` |
| 4 | RQ2 CV not grouped by repo; single split | `StratifiedGroupKFold` by `repo_full_name`, 5×5 repeats, mean±sd + dummy baseline + logit CIs | `rq2_model_corrected.py`, `rq2_model_extras.py` |
| 5 | RQ3 follow-up-fix match was keyword-only, overcounting (median 1.0 d) | relatedness filter (PR-number ref / same manifest / dep named) → median **3.5 d** | `rq3_analysis_strict.py` |
| 6 | RQ3 merged-share printed 33.1% (stray copy of the naive fix count) | corrected to **33.8%** (54/160), abstract + body aligned | commit `1d1942a` |
| 7 | BC-kind mix 83.3/20.5/9.1% summed to 112.9% (overlapping substring match) | mutually-exclusive prefix count → **79.0 / 11.6 / 9.4%**, footnoted | commit `1d1942a` |
| 8 | Robustness bounds/imputed printed ×100 ("2043.4%") | `fmt_pct_value()` (no ×100) → "[20.4%, 71.9%]" / "38.0%" | commit `1d1942a` |
| 9 | Related Work: mis-attributed `cogo2024`; 2 target citations missing | fixed to `rombaut2024`; **BreakGuard** + **Venturini** added, all 6 with differentiation, keys verified | commit `ade2882` |
| 10 | No NVD metadata-quality check | `nvd_metadata_validation.py`: 100 Maven CVE PRs, **0% version mismatch**; new Threats paragraph | commit `ade2882` |

Paper compiles clean (pdflatex ×2, 6 pp, no undefined refs). Claim trace:
**48 / 50 claims traced** to a script output.

---

## ⚠️ CRITICAL — NOT resolved: fabricated citation `raemaekers2021`

**Found 2026-09-09 via literature search.** There is **no** paper by Raemaekers, van
Deursen & Visser titled *"Do Security Updates Break Compatibility? An Empirical Study of
Versioning in Security Releases," IEEE TSE, 2021*. No study anywhere reports **"13.2% of
security releases declare backward incompatibility via provider-side versioning
metadata."** The 2026 systematic review of breaking-change literature does not contain
the figure or the paper. Raemaekers' real corpus: SCAM 2014, JSS 2017
(`raemaekers2017semver`, which *is* real and cited).

The fabricated claim is **load-bearing** and appears in `paper/secbreak_tse_revision.tex` at:

| Line | Context |
|---|---|
| 20 | Abstract — "13.2% provider-side baseline ... not lower" |
| 30 | Introduction — "Raemaekers *et al.* reported in TSE that 13.2% ... future work `\cite{raemaekers2021}`" |
| 63–66 | Related Work — "Provider-side security metadata" paragraph |
| 141 | RQ1 Results — "significantly higher than the 13.2% provider-side baseline from TSE `\cite{raemaekers2021}`" |
| 169 | RQ1 Robustness — "above the 13.2% provider-side baseline" |
| 236 | Conclusion — "higher than the 13.2% provider-side metadata baseline" |
| 256 | `\bibitem{raemaekers2021}` |

Also affected: the published artifact
(`https://claude.ai/code/artifact/2771dd50-6130-4f5b-9475-b8272e3a6d5f`) — the
"Provider-side metadata / Raemaekers 2021 / 13.2%" bar.

### Fix plan (not yet done)

1. Remove `raemaekers2021` and every "13.2%" / "provider-side baseline" claim from
   abstract, intro, Related Work, RQ1 results, robustness, conclusion, bibliography, and
   the artifact.
2. Re-anchor the comparison to **verifiable** numbers:
   - **Alfadel et al., MSR 2021** — npm Dependabot security PRs, manual sample:
     **3.2%** suffered build breakage; 65.4% merged. *(npm, manual/self-reported,
     mostly non-merged subset.)*
   - **Jayasuriya et al., EMSE 2024** — Maven, general updates, static API analysis:
     **11.58%** introduce client-impacting breaking changes.
   - **Venturini et al., TOSEM 2023** — npm, general non-major updates, test execution:
     ~12% packages / 14% releases.
3. Reframe novelty (see next section) — the "they measured provider-side and asked for the
   client-side follow-up" story is gone; replace with "prior work measured general
   updates, or npm security PRs via manual inspection; we measure automated API-level BC
   prevalence in Maven+PyPI security PRs, merged population included."
4. Address head-on why SecBreak's **42.1%** is 3–13× higher than every prior number
   (ecosystem, detector strictness, 48.5% coverage, and the recovered heavyweight-legacy
   dependency skew already documented in `RECTIFICATION_REPORT.md`). Reviewers will press
   this hard.

---

## Novelty / scoop check (done today)

**Not a direct replication of any single paper.** Closest prior work:

| Work | Population | Method | Key number |
|---|---|---|---|
| Alfadel et al. MSR 2021 | npm Dependabot security PRs | manual, mostly non-merged | 3.2% build breakage; 65.4% merged |
| Jayasuriya et al. EMSE 2024 | Maven, general updates | static API diff | 11.58% BC |
| Venturini et al. TOSEM 2023 | npm, general non-major | client test execution | ~12% / 14% |
| Rebatchi 2024 / Mohayeji 2025 | Dependabot security PR mgmt / vuln mitigation | — | no API-level BC measurement |

**Defensible SecBreak delta:** Maven (+PyPI) rather than npm; automated API-level
detection rather than manual/self-report; security-motivated PRs specifically
(vs. general updates); merged population included. Alfadel 2021 is the one a reviewer
will wave — cite it prominently and differentiate explicitly.

---

## Other open items (pre-existing, not bugs)

1. **Maven-only vs dual-ecosystem** — both variants generated
   (`results/MAVEN_ONLY_COMPARISON.md`); paper carries a `PENDING AUTHOR DECISION` comment.
   RQ1 42.1% (dual) vs 65.6% (Maven-only); model AUC 0.894 vs 0.785.
2. **Manual BC validation** — `results/manual_validation_sheet.csv`, 100 rows, **0
   adjudicated**. Harness ready (`build_manual_validation_sheet.py`,
   `compute_manual_validation_metrics.py`); gate wants ≥ 20–30 with precision/recall.
3. **RQ2 metric CIs** — mean±sd across folds only; no per-metric bootstrap CIs.
4. **Behavioral BC** — harness fixed, signal confounded, reported as future work.
5. **Bibliography completeness** — several bibitems lack issue no. / pages / DOI
   (EMSE + arXiv entries). Fill before submission.
6. **Known limitations carried forward** — ecosystem mistagging from repo-root file
   presence; a few `old_version`/`new_version` = `"|"` from a regex bug. Both documented
   in `RECTIFICATION_REPORT.md`, not fixed.

---

## In flight — cohort expansion

`run_expansion.sh` → `collect_prs_expanded.py` running (PID 3275186 / child 3275194):

- Window widened **2022–2024 → 2021–2025**, per-month sampling cap **100 → 400**, same
  population filters (stars ≥ 20, Java/Python, `.github/workflows` present).
- ~22 / 60 monthly windows done; every one maxes the 400 cap → will hit the 20,000
  candidate ceiling. Then `fetch_nvd.py`, then it **stops before BC detection** and
  touches `logs/expansion_STAGE_COLLECT_ENRICH_DONE`.
- `data/raw_prs.jsonl` still at 1,180 lines (collection gathers all candidates first,
  then appends). Pre-expansion backup in `data/backups/`.
- Log: `logs/expansion_run.log`.

**Decision on record:** hold the paper at 380 analyzed / 160 BC; do **one** full
number-revision after the expanded cohort is collected + BC-detected, not two.

---

## Data basis (current paper)

**380 analyzed PRs / 160 breaking**, of a 783-PR cohort (132 repos, 554 Maven / 229 PyPI,
Jan 2022 – Dec 2024). Dual-ecosystem. Coverage 48.5%. Everything in `results/*_corrected.*`
and the presubmission claim-trace uses this basis. Originals preserved as `*_ORIGINAL_BUGGY`.

---

## Next actions, in order

1. **Kill the fabricated citation** — rework abstract / intro / Related Work / RQ1 /
   conclusion / bib to drop `raemaekers2021` + 13.2%, re-anchor to Alfadel 3.2% and
   Jayasuriya 11.58%, reframe novelty. Update the artifact to match.
2. When `logs/expansion_STAGE_COLLECT_ENRICH_DONE` appears: report new cohort size /
   ecosystem / bump mix; get go-ahead for the full re-run.
3. Full re-run on the expanded cohort → regenerate every number, figure, table; re-verify
   claim trace.
4. Resolve Maven-only vs dual-ecosystem; adjudicate ≥ 20–30 validation rows; complete
   bibitems.

---

## Key files

| File | Role |
|---|---|
| `STATUS.md` | lighter living status (this handoff supersedes it as of today) |
| `AUDIT_INITIAL.md` | Step-0 inventory + handoff-step → repo-state map |
| `RECTIFICATION_SUMMARY.md`, `results/RECTIFICATION_REPORT.md`, `results/STRENGTHENING_REPORT.md` | prior-pass records |
| `results/MAVEN_ONLY_COMPARISON.md` | scoping decision input |
| `results/presubmission_claim_trace.csv` / `_supporting_metrics.csv` | every numeric claim → source |
| `paper/secbreak_tse_revision.tex` | the manuscript (single canonical file) |
| artifact | https://claude.ai/code/artifact/2771dd50-6130-4f5b-9475-b8272e3a6d5f (needs the 13.2% bar fixed) |
