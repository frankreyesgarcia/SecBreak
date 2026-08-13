# Maven-only vs. Dual-Ecosystem: Side-by-Side Comparison

Phase 5 of the paper-strengthening pass. **This document does not make the scoping
decision** — it exists so that decision can be made after seeing real numbers side by
side. Both variants are fully generated and available in `results/*_corrected.csv`
(dual-ecosystem) and `results/*_mavenonly.csv` (Maven-only).

## RQ1: Prevalence

| Metric | Dual-ecosystem | Maven-only |
|---|---|---|
| Cohort size | 783 | 554 |
| Pipeline coverage | 47.1% (369/783) | 43.5% (241/554) |
| Analyzed-only BC prevalence | **43.1%** (159/369) | **65.6%** (158/241) |
| 95% CI | [38.1%, 48.2%] | [59.4%, 71.3%] |

Maven-only prevalence is dramatically higher — unsurprising, since PyPI's analyzed-only
rate is 0.8% (1/128) and dominates the dual-ecosystem denominator's lower end. Restricting
to Maven removes ecosystem as a source of variance entirely rather than modeling it.

## RQ2: Predictive model

| Model | Dual-ecosystem AUC | Maven-only AUC |
|---|---|---|
| Logistic Regression | 0.865 ± 0.082 | 0.695 ± 0.074 |
| Random Forest (best, dual) | **0.906 ± 0.064** | 0.785 ± 0.065 |
| Gradient Boosting | 0.878 ± 0.077 | 0.712 ± 0.092 |
| Decision Tree | 0.806 ± 0.079 | 0.581 ± 0.112 |

Every model's AUC drops substantially Maven-only (Random Forest: 0.906 → 0.785). This is
expected and mechanically explained: `ecosystem_bin` is the single strongest predictor in
the dual-ecosystem model (importance 0.191, second only to `repo_stars`) precisely because
Maven vs. PyPI is such a strong signal for BC risk (65.6% vs. 0.8%). Remove that axis of
variance and the remaining features (CVSS score, version bump, CWE category) explain less
of what's left. The dual-ecosystem model's high AUC is partly "predicting ecosystem," which
is a legitimate pre-outcome feature but worth being explicit about.

## RQ3: Team response (strict relatedness-filtered)

| Metric | Dual-ecosystem | Maven-only |
|---|---|---|
| BC-introducing PRs | 159 | 158 |
| Strict fixes found | 46 (28.9%) | 46 (29.1%) |
| Median time-to-fix | 3.54 days | 3.54 days |
| IQR | 1.11–11.06 | 1.11–11.06 |

Essentially identical — expected, since only 1 of the 159 corrected BC-introducing PRs is
PyPI. RQ3 is not meaningfully affected by the Maven-only vs. dual-ecosystem choice.

## What this means for the scoping decision

- **RQ1 and RQ2 change substantially** under Maven-only scoping; RQ3 does not.
- Dual-ecosystem is more representative of the actual security-PR population studied (both
  ecosystems were collected and analyzed), and keeps the paper's original framing
  ("Maven and PyPI projects"). The cost is a headline prevalence number whose ecosystem mix
  is doing a lot of the explanatory work, and an RQ2 model whose top feature is partly a
  proxy for ecosystem.
- Maven-only is more internally homogeneous and arguably a cleaner causal story (CVSS,
  version bump, and CWE category predicting BC risk *within* one detection methodology,
  Roseau, rather than mixing it with PyPI's much weaker signature-comparison detector) —
  but it drops PyPI from the paper's contribution entirely, which may not match the venue's
  expectations for the paper as originally scoped (RQ1's title and abstract currently say
  "Maven and PyPI").
- A middle path not generated here: keep dual-ecosystem as primary and Maven-only as an
  explicit robustness/sensitivity subsection (the RQ1 bounds/imputation section already
  established this pattern in Phase 3). This is worth considering during Phase 8's
  restructuring.

**Pending author decision**, per the task list: which framing to lead the paper with.
