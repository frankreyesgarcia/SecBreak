# SecBreak — Current Status (single source of truth)

Last updated: 2026-09-09 · Branch: `paper-strengthening/v2` · Target: IEEE TSE

This is the one file to read for "where are we". The three historical pass reports
(`results/RECTIFICATION_REPORT.md`, `results/STRENGTHENING_REPORT.md`,
`RECTIFICATION_SUMMARY.md`) and `AUDIT_INITIAL.md` remain as the record of each pass;
this file supersedes them for *current* state.

## Data basis

**380 analyzed PRs / 160 BC-introducing**, out of a 783-PR cohort (Jan 2022 – Dec 2024).
This is what the committed paper, all `results/*_corrected.*` artifacts, and the
presubmission claim-trace stand on. Decision (2026-09-09): **hold here; do one full
number-revision after the cohort expansion lands**, rather than revising twice.

## Paper state — `paper/secbreak_tse_revision.tex`

Unified and internally consistent. Verified 2026-09-09:

| Check | Result |
|---|---|
| `pdflatex` ×2 | clean, 6 pages, no undefined references or citations |
| Claim trace (`results/presubmission_claim_trace.csv`) | 48/50 claims traced to a script output; 1 external citation (Jayasuriya 11.6%, verified); 1 narrative ("2,000-PR target", no structured source, acceptable) |
| RQ1 prevalence | 42.1% (160/380), 95% Wilson CI [37.2%, 47.1%] — abstract = body = conclusion |
| RQ1 bounds | Manski [20.4%, 71.9%]; model-imputed 38.0% [36.6%, 39.2%] (×100 print bug fixed) |
| RQ3 merged share | 54/160 = 33.8% — abstract = body (was a stray 33.1%) |
| BC-kind mix | method 79.0% / type 11.6% / field 9.4%, mutually exclusive, footnoted (was an overlapping-substring 83.3/20.5/9.1% that summed to 112.9%) |
| RQ2 | RF AUC 0.894 ± 0.069, repo-grouped 5×5 CV, dummy 0.500, logit coeffs w/ 95% CI |
| Related Work | 6 target citations present with differentiation clauses; all keys resolve to verified sources |
| Threats to Validity | selection-bias table + Manski bounds + NVD metadata-quality paragraph (0% mismatch on 100 sampled Maven CVE PRs) |

## Commit history of this consolidation (all pushed to `origin/paper-strengthening/v2`)

| Commit | Session | What |
|---|---|---|
| `1d1942a` | parallel | Fixed RQ3 33.1→33.8%, BC-kind → 79/12/9%, bounds ×100 print bug; added `generate_presubmission_artifacts.py` + presubmission CSVs |
| `ade2882` | this | Related Work citations (BreakGuard, Venturini added; Alfadel/Rebatchi sharpened; `cogo2024`→`rombaut2024` fixed + moved to Intro); NVD metadata validation (`nvd_metadata_validation.py` + data + TtV paragraph); cohort-expansion tooling; README results table; `AUDIT_INITIAL.md` |
| `5002151` | this | Consolidated dangling files: manual-validation harness (`build_manual_validation_sheet.py`, `compute_manual_validation_metrics.py`, `results/manual_validation_*`), `push_coverage_corrected.py`, STRENGTHENING_REPORT sync, gitignore hygiene |

## In flight

- **Cohort expansion** — `run_expansion.sh` (PID at launch 3275186) running
  `collect_prs_expanded.py`: window widened to 2021–2025, per-month sampling cap
  100→400, same population filters (stars ≥ 20, Java/Python, CI-required). Every month
  is maxing the 400 cap, so it will reach the 20k-candidate ceiling. Then `fetch_nvd.py`,
  then it **stops before BC detection** and touches
  `logs/expansion_STAGE_COLLECT_ENRICH_DONE`. Log: `logs/expansion_run.log`.
  Pre-expansion `data/raw_prs.jsonl` backed up to `data/backups/`.

- **`git stash@{0}`** — a partial BC-detection re-run (407 analyzed / 173 BC) the
  parallel session set aside. **Not adopted.** Superseded by the expansion; keep or drop
  when the expanded run is built.

## Pending (post-expansion or author decision)

1. **One full re-run on the expanded cohort**: coordinate resolution → NVD → BC detection
   → `build_dataset_corrected.py` → RQ1/RQ2/RQ3 → figures/tables → revise every paper
   number → re-verify claim trace. This is the "revise all" the current hold defers.
2. **Maven-only vs. dual-ecosystem scoping** — both variants generated
   (`results/MAVEN_ONLY_COMPARISON.md`); paper carries a `PENDING AUTHOR DECISION` comment.
3. **Manual BC-detector validation** — `results/manual_validation_sheet.csv`, 0/100
   adjudicated; gate wants ≥ 20–30 with reported precision/recall.
4. **RQ2 per-metric bootstrap CIs** — currently mean ± std across folds only.
5. **Behavioral BC** — harness fixed, signal confounded, reported as future work (no number).

## Push (SSH remote has no key here; use the PAT in `token.txt`)

```bash
git push "https://$(tr -d ' \n' < token.txt)@github.com/frankreyesgarcia/SecBreak.git" \
  HEAD:paper-strengthening/v2
```

Equivalent without embedding the token in the URL:

```bash
TOK=$(tr -d ' \n' < token.txt)
git -c http.https://github.com/.extraheader="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$TOK" | base64 -w0)" \
  push https://github.com/frankreyesgarcia/SecBreak.git HEAD:paper-strengthening/v2
```

To make it permanent for this clone (so plain `git push` works):

```bash
git remote set-url origin "https://$(tr -d ' \n' < token.txt)@github.com/frankreyesgarcia/SecBreak.git"
# token.txt is gitignored; the URL lives only in .git/config
```
