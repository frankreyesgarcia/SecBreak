# SecBreak — Pre-Submission Analysis Checklist
**Goal: not to change the paper's content (that's `secbreak_paper_strengthening_tasks.md`),
but to systematically verify and pressure-test it once those changes land — the
kind of scrutiny three tough SANER reviewers would apply, done by you before they do.**

Run this after Phases 1-8 of the strengthening task list are complete. Some items
can run in parallel (anything not depending on the Maven-only decision or the
Related Work insertion).

---

## A. Claim-by-claim verification

Every number that appears in prose in the paper must trace to a script output.
This is the single highest-value check — it's exactly how the original RQ1 bug
was caught, and it's cheap to do systematically.

1. Extract every numeric claim from the `.tex` file (percentages, counts, p-values,
   CIs, AUCs) into a spreadsheet: `claim text | value | section | source file/line`.
2. For each one, locate the exact script and output line that produced it. If you
   can't find the source, that's a red flag — either the number is stale (computed
   before a later correction) or was hand-typed and never re-verified.
3. Specifically re-verify after Phases 1-5 land, since these will change existing
   numbers:
   - RQ3 merge rate / median fix time (Phase 1 fix will change these)
   - Any prevalence number if Maven-only scoping is adopted (Phase 5)
   - RQ2 AUC comparison table (Phase 4 adds a baseline row — check nothing shifted)
4. Confirm the abstract's numbers match the body's numbers exactly (a common
   failure mode: abstract written first, body numbers updated later, abstract
   never revisited).

## B. Statistical rigor audit

1. Every p-value has a matching effect size nearby (not just "significant" —
   Cramér's V for the chi-square tests, odds ratios or standardized coefficients
   for the logistic regression). Add any that are missing.
2. Every proportion has a CI (already true for the 43.1% headline; check it's also
   true for the ecosystem breakdown, bump-type breakdown, and RQ3 merge rate).
3. Re-check the RQ1 CVSS/Spearman correlation reported in Results — confirm the
   sign and magnitude are recomputed on the corrected 369-row set, not left over
   from an earlier draft.
4. Confirm the RQ2 cross-validation is genuinely leakage-free: spot-check that no
   `repo_full_name` appears in both a fold's train and test split (should already
   be guaranteed by `StratifiedGroupKFold`, but verify programmatically, don't
   just trust the API).
5. Sanity-check the bounds/imputation numbers from Phase 3 are internally
   consistent: worst-case upper bound ≥ imputed estimate ≥ analyzed-only estimate
   ≥ worst-case lower bound, in that order, for every subgroup you report them for.

## C. Novelty / Related Work verification

The paper's positioning claim ("to our knowledge, no prior study measures
client-side BC prevalence specifically in security PRs") is a strong claim that
needs an actual search, not an assumption carried over from earlier
conversations.

1. Run fresh literature searches (web search + Google Scholar/DBLP if available)
   for: "security update breaking changes", "Dependabot compatibility",
   "client-side breaking change security patch", covering 2024-2026 specifically,
   since this is exactly the window where a competing paper could have appeared
   without you noticing.
2. If anything close turns up, don't panic-generalize the claim away — read it and
   determine precisely how SecBreak differs (different population, different
   measurement, different scale) and say so explicitly in Related Work rather than
   silently dropping the novelty claim.
3. Double-check every citation added in Phase 7 resolves to a real paper with the
   claimed finding (this was flagged as a TODO in the strengthening tasks — treat
   it as blocking, not optional, before submission).

## D. Reproducibility / Open Science audit

SANER explicitly scores "Open Science and Verifiability" as one of five criteria.

1. Confirm `results/RECTIFICATION_REPORT.md` and `results/STRENGTHENING_REPORT.md`
   are both included in whatever replication package gets linked/uploaded.
2. Confirm the corrected pipeline can be run end-to-end by someone who is not you:
   check `README.md` actually documents the current script order (it's one line
   right now — needs the full pipeline sequence, environment setup, and where
   each output lands).
3. Verify every `*_corrected` / `*_strict` / `*_mavenonly` file referenced in the
   paper's Replication Package section actually exists in the repo at that path.
4. Write the Data Availability statement SANER requires after the Conclusion
   (separate from the existing "Replication Package" section — SANER wants this
   as its own named section).
5. Decide and document the archival plan (Zenodo/Software Heritage — GitHub alone
   doesn't satisfy SANER's Open Science policy, which explicitly says GitHub is
   not sufficient for preserved data).

## E. Writing and presentation audit

1. Read the full paper aloud, or have it read back to you, start to finish in one
   sitting — this catches redundant phrasing and inconsistent terminology
   (e.g., "breaking change" vs. "BC" vs. "compatibility break" used
   interchangeably needs to converge on one primary term after first definition).
2. Check that every figure is referenced in the text before it appears, and that
   every table has a one-sentence takeaway in prose near it (not just a caption).
3. Verify page budget: after Phase 8's trim, estimate total length against
   SANER's 10+2 page limit in the actual conference two-column format — do this
   with a real compile, not a guess, since the trim was written against journal
   single-column and will reflow differently.
4. Check the title still matches the paper's actual center of gravity after the
   reframing in Phase 8 (from "here's a bug we fixed" to "client-side BC risk in
   security PRs, measured rigorously despite pipeline incompleteness").

## F. Double-blind anonymization audit (SANER-specific)

1. Search the full `.tex` for: your name, GitHub username (`frankreyesgarcia`),
   the repo name (`bcmcp`/`SecBreak` if identifiable), institution name, any
   acknowledgments.
2. Check the replication-package links use an anonymized hosting method
   (anonymous.4open.science or similar) rather than a direct link to your named
   GitHub repo, per SANER's explicit guidance.
3. Check self-citations (if any of your own prior papers — BUMP, SCAM 2024, EMSE
   2026 work — are cited) are phrased in third person per SANER's double-blind
   rules, not "in our previous work."
4. Check commit history / file metadata isn't bundled into whatever replication
   package gets uploaded at submission time (only at camera-ready).

## G. Simulated reviewer pass, scored against SANER's actual criteria

Go through the paper once per criterion, playing a skeptical reviewer, and write
one paragraph per criterion arguing both for and against a high score:

1. **Originality and novelty** — is the client-side/security-PR framing genuinely
   new, or an incremental slice of Jayasuriya et al.? (Related Work from Phase 7
   should make this defensible either way — check it does.)
2. **Importance/significance** — does the paper convince a reader that 43.1% (or
   the Maven-only equivalent) actually changes how practitioners or tool builders
   should behave? If Discussion doesn't say something concrete and actionable,
   add it.
3. **Soundness** — this is where the coverage/bounds work from Phase 2-3 earns its
   keep. Would a skeptical reviewer accept 43.1% as a defensible headline number
   given everything disclosed about coverage? If not, what single additional
   check would move them — do that check now, don't wait for the review.
4. **Open Science/Verifiability** — covered by section D above.
5. **Presentation** — covered by section E above.

## H. Consistency check: abstract, intro, conclusion

1. Line up the abstract's contribution claims, the introduction's stated RQs, and
   the conclusion's summary side by side. They should mirror each other in scope
   and confidence — a common defect is an abstract that overclaims relative to
   what the Results/Discussion actually support after all the hedging in Phase 3's
   bounds language.
2. Confirm no numbers in the conclusion were left over from before the Phase 1/5
   corrections (conclusions are frequently the last section updated and the first
   one to go stale).

## I. Final gate before submission

Do not submit until:
- [ ] Every item in section A traces to a real script output
- [ ] Manual validation (from the strengthening task list, Phase 6) has at least
      20-30 adjudicated rows with a reported precision/recall, not zero
- [ ] Maven-only vs. dual-ecosystem decision is made and the paper reflects only
      the chosen version consistently (no leftover numbers from the other)
- [ ] All citations in Related Work are verified against real bibliographic records
- [ ] Anonymization pass (section F) is complete
- [ ] Page count fits SANER's limit in actual conference format
- [ ] Data Availability statement is present and archival plan is decided

Write the outcome of this whole checklist to `results/PRESUBMISSION_AUDIT.md`,
structured the same way as the two prior reports, so the full chain — bug found →
rectified → strengthened → audited — is one continuous, citable trail.