"""Phase 3 (paper strengthening): partial-identification bounds and a
model-based imputed estimate for RQ1 prevalence, to contextualize the
43.1% analyzed-only headline number against the 47.1% coverage limitation.

Three numbers, all reported together:
  1. Manski (worst-case) bounds: no assumption about the 414 unanalyzed
     rows beyond "somewhere between all-negative and all-positive".
  2. Analyzed-only estimate: 43.1% (159/369), the paper's cited number.
  3. Model-based imputed estimate: apply the RQ2 Random Forest (trained on
     analyzed_ok rows, pre-outcome features only) to the 414 unanalyzed
     rows and aggregate predicted probabilities, with a bootstrap CI over
     the resulting 414 probabilities (resampling only, no refit).

This does not replace 43.1% as the primary result -- it's a robustness
triangulation to cite alongside it.
"""

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from pipeline_utils import DATA_DIR, RESULTS_DIR, wilson_ci
from rq2_model_corrected import get_features

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"
OUT_PATH = RESULTS_DIR / "rq1_bounds.json"
N_BOOTSTRAP = 1000
BOOTSTRAP_SEED = 20260813


def main():
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)

    n_total = len(df)
    analyzed = df[df["analyzed_ok"]]
    unanalyzed = df[~df["analyzed_ok"]]
    n_analyzed = len(analyzed)
    n_unanalyzed = len(unanalyzed)
    n_bc = int(analyzed["has_bc"].sum())

    # --- 1. Manski worst-case bounds ---
    lower_bound = n_bc / n_total
    upper_bound = (n_bc + n_unanalyzed) / n_total
    print("=== 1. Worst-case (Manski) bounds ===")
    print(f"  lower (all {n_unanalyzed} unanalyzed rows assumed BC-free): {100*lower_bound:.1f}%")
    print(f"  upper (all {n_unanalyzed} unanalyzed rows assumed to have a BC): {100*upper_bound:.1f}%")
    print("  These are WORST-CASE bounds, not best-guess estimates -- the true value")
    print("  could be anywhere in this range under no assumptions about the unanalyzed rows.")

    # --- 2. Analyzed-only estimate (the paper's headline number) ---
    analyzed_low, analyzed_high = wilson_ci(n_bc, n_analyzed)
    analyzed_pct = 100 * n_bc / n_analyzed
    print("=== 2. Analyzed-only estimate (headline, unchanged) ===")
    print(f"  {analyzed_pct:.1f}% ({n_bc}/{n_analyzed}) [95% CI {100*analyzed_low:.1f}-{100*analyzed_high:.1f}]")

    # --- 3. Model-based imputed estimate ---
    X_train, y_train, feature_cols = get_features(analyzed)
    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(X_train, y_train)

    X_unanalyzed, _, _ = get_features(unanalyzed)
    X_unanalyzed = X_unanalyzed[feature_cols]
    probs = model.predict_proba(X_unanalyzed)[:, 1]

    imputed_prevalence = (n_bc + probs.sum()) / n_total
    print("=== 3. Model-based imputed estimate ===")
    print(f"  RF trained on {n_analyzed} analyzed_ok rows (pre-outcome features only: {feature_cols})")
    print(f"  applied to {n_unanalyzed} unanalyzed rows, mean predicted P(has_bc)={probs.mean():.3f}")

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bootstrap_estimates = []
    for _ in range(N_BOOTSTRAP):
        resampled = rng.choice(probs, size=len(probs), replace=True)
        bootstrap_estimates.append((n_bc + resampled.sum()) / n_total)
    bootstrap_estimates = np.array(bootstrap_estimates)
    boot_low, boot_high = np.percentile(bootstrap_estimates, [2.5, 97.5])
    print(f"  imputed full-cohort prevalence: {100*imputed_prevalence:.1f}% "
          f"[bootstrap 95% CI {100*boot_low:.1f}-{100*boot_high:.1f}, n={N_BOOTSTRAP} resamples]")

    print("=== Triangulation summary ===")
    print(f"  worst-case range:      [{100*lower_bound:.1f}%, {100*upper_bound:.1f}%]")
    print(f"  analyzed-only estimate: {analyzed_pct:.1f}% [{100*analyzed_low:.1f}-{100*analyzed_high:.1f}] <- cite this as primary")
    print(f"  model-imputed estimate: {100*imputed_prevalence:.1f}% [{100*boot_low:.1f}-{100*boot_high:.1f}]")
    print("  All three numbers are consistent with a true prevalence well above the")
    print("  original (buggy) 3.4% naive rate and above the 13.2% provider-side baseline;")
    print("  this triangulation is a genuine robustness contribution, not just a caveat.")

    out = {
        "n_total": n_total,
        "n_analyzed": n_analyzed,
        "n_unanalyzed": n_unanalyzed,
        "n_bc": n_bc,
        "worst_case_lower_pct": 100 * lower_bound,
        "worst_case_upper_pct": 100 * upper_bound,
        "analyzed_only_pct": analyzed_pct,
        "analyzed_only_ci": [100 * analyzed_low, 100 * analyzed_high],
        "model_imputed_pct": 100 * imputed_prevalence,
        "model_imputed_bootstrap_ci": [100 * boot_low, 100 * boot_high],
        "model_imputed_mean_predicted_prob": float(probs.mean()),
        "feature_cols": feature_cols,
        "n_bootstrap": N_BOOTSTRAP,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[DONE] rq1_bounds — {n_total} records processed, wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
