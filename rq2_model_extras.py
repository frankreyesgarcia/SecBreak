"""Phase 4 (paper strengthening): RQ2 additions.

1. A DummyClassifier(most_frequent) baseline, evaluated with the same
   repeated repo-grouped CV as the four real models, appended as a row to
   results/rq2_model_results_corrected.csv -- contextualizes AUC 0.906
   against a trivial baseline (per the task doc, this appends to the
   existing corrected file rather than writing a new one).
2. Logistic Regression coefficients with 95% CIs via statsmodels.Logit
   (sklearn doesn't expose CIs directly), refit once on the full
   analyzed_ok set. Written to results/rq2_logit_coefficients.csv.
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.dummy import DummyClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from pipeline_utils import DATA_DIR, RESULTS_DIR
from rq2_model_corrected import get_features

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"
RESULTS_PATH = RESULTS_DIR / "rq2_model_results_corrected.csv"
COEF_PATH = RESULTS_DIR / "rq2_logit_coefficients.csv"

N_REPEATS = 5
N_SPLITS = 5
HEADLINE_COEFS = ["ecosystem_bin", "cvss_score", "version_bump_ord", "repo_stars"]


def evaluate_dummy(X, y, groups):
    fold_aucs = []
    for repeat in range(N_REPEATS):
        cv = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=100 + repeat)
        for train_idx, test_idx in cv.split(X, y, groups=groups):
            model = DummyClassifier(strategy="most_frequent")
            model.fit(X.iloc[train_idx], y.iloc[train_idx])
            y_test = y.iloc[test_idx]
            if y_test.nunique() < 2:
                continue
            # DummyClassifier(most_frequent) has no meaningful decision function;
            # predict_proba is constant, so AUC is 0.5 by construction. We compute
            # it explicitly (not hardcode 0.5) so the number is measured, not assumed.
            prob = model.predict_proba(X.iloc[test_idx])[:, 1]
            fold_aucs.append(roc_auc_score(y_test, prob))
    return fold_aucs


def main():
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    df = df[df["analyzed_ok"]].reset_index(drop=True)
    X, y, feature_cols = get_features(df)
    groups = df["repo_full_name"]

    print(f"[rq2_model_extras] dummy baseline on {len(df)} analyzed_ok rows")
    dummy_aucs = evaluate_dummy(X, y, groups)
    dummy_mean = float(np.mean(dummy_aucs)) if dummy_aucs else float("nan")
    dummy_std = float(np.std(dummy_aucs)) if dummy_aucs else float("nan")
    print(f"  Dummy (most_frequent): mean AUC={dummy_mean:.3f} +/- {dummy_std:.3f} ({len(dummy_aucs)} folds)")

    existing = pd.read_csv(RESULTS_PATH)
    if "Dummy (most_frequent)" not in existing["model"].values:
        new_row = pd.DataFrame([{
            "model": "Dummy (most_frequent)",
            "auc_roc_mean": dummy_mean,
            "auc_roc_std": dummy_std,
            "n_folds": len(dummy_aucs),
            "n_repeats": N_REPEATS,
            "n_splits": N_SPLITS,
        }])
        existing = pd.concat([existing, new_row], ignore_index=True)
        existing.to_csv(RESULTS_PATH, index=False)
        print(f"  appended dummy baseline row to {RESULTS_PATH}")
    else:
        print("  dummy baseline row already present, not duplicating")

    print("[rq2_model_extras] checking for quasi-complete separation before fitting Logit")
    separated_features = []
    for col in X.columns:
        if X[col].nunique() <= 5:  # only meaningful to check near-binary/ordinal predictors
            table = pd.crosstab(X[col], y)
            if (table.min(axis=1) == 0).any():
                separated_features.append(col)
    if separated_features:
        print(f"  WARNING: quasi-complete separation detected for: {separated_features}")
        print("  (at least one level of these predictors has zero positive- or zero")
        print("  negative-outcome rows -- the unpenalized MLE coefficient for these")
        print("  predictors does not converge to a finite value; treat their reported")
        print("  coefficient/CI as directionally indicative only, not a stable estimate.)")

    print("[rq2_model_extras] fitting statsmodels Logit on full analyzed_ok set")
    X_const = sm.add_constant(X.astype(float), has_constant="add")
    fit = sm.Logit(y, X_const).fit(disp=False, maxiter=200)
    conf_int = fit.conf_int(alpha=0.05)
    conf_int.columns = ["ci_low", "ci_high"]

    coef_df = pd.DataFrame({
        "feature": fit.params.index,
        "coef": fit.params.values,
        "std_err": fit.bse.values,
        "z": fit.tvalues.values,
        "p_value": fit.pvalues.values,
        "ci_low": conf_int["ci_low"].values,
        "ci_high": conf_int["ci_high"].values,
        "converged": fit.mle_retvals.get("converged", None),
        "quasi_separated": [f in separated_features for f in fit.params.index],
    })
    coef_df.to_csv(COEF_PATH, index=False)
    print(f"  wrote {len(coef_df)} coefficients to {COEF_PATH} (converged={fit.mle_retvals.get('converged')})")

    print("Headline coefficients (full model, 95% CI):")
    for name in HEADLINE_COEFS:
        if name in coef_df["feature"].values:
            row = coef_df[coef_df["feature"] == name].iloc[0]
            sig = "significant" if row["p_value"] < 0.05 else "not significant"
            flag = " [UNSTABLE: quasi-separated, interpret direction only]" if row["quasi_separated"] else ""
            print(f"  {name}: coef={row['coef']:.4g} [95% CI {row['ci_low']:.4g}, {row['ci_high']:.4g}], p={row['p_value']:.4g} ({sig}){flag}")

    # Robustness check: refit excluding any quasi-separated predictor so the
    # remaining coefficients (cvss_score, version_bump_ord, repo_stars) get a
    # genuinely converged, stable estimate uncontaminated by the separation issue.
    stable_path = RESULTS_DIR / "rq2_logit_coefficients_converged.csv"
    if separated_features:
        stable_cols = [c for c in X.columns if c not in separated_features]
        X_stable = sm.add_constant(X[stable_cols].astype(float), has_constant="add")
        fit_stable = sm.Logit(y, X_stable).fit(disp=False, maxiter=200)
        print(f"  robustness refit excluding {separated_features}: converged={fit_stable.mle_retvals.get('converged')}")
        stable_conf = fit_stable.conf_int(alpha=0.05)
        stable_conf.columns = ["ci_low", "ci_high"]
        stable_df = pd.DataFrame({
            "feature": fit_stable.params.index,
            "coef": fit_stable.params.values,
            "std_err": fit_stable.bse.values,
            "p_value": fit_stable.pvalues.values,
            "ci_low": stable_conf["ci_low"].values,
            "ci_high": stable_conf["ci_high"].values,
        })
        stable_df.to_csv(stable_path, index=False)
        for name in HEADLINE_COEFS:
            if name in stable_df["feature"].values:
                row = stable_df[stable_df["feature"] == name].iloc[0]
                print(f"    (converged, excl. {separated_features}) {name}: coef={row['coef']:.4g} [95% CI {row['ci_low']:.4g}, {row['ci_high']:.4g}], p={row['p_value']:.4g}")

    print(f"[DONE] rq2_model_extras — {len(df)} records processed, {len(dummy_aucs)} dummy folds + {len(coef_df)} coefficients")


if __name__ == "__main__":
    main()
