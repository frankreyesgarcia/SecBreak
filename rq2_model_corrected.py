"""Phase 5: RQ2 model, corrected.

Changes from rq2_model.py:
  1. has_behavioral_bc removed from get_features() — it's derived from
     post-update test execution, so it's not a legitimate pre-outcome
     feature regardless of measured importance.
  2. has_cve importance is re-checked after that removal and logged either
     way (not dropped blindly).
  3. Trained on the corrected has_bc labels (data/analysis_dataset_corrected.csv),
     restricted to analyzed_ok==True rows — has_bc is only a meaningful label
     where detection genuinely ran.
  4. Single train_test_split replaced with repeated StratifiedGroupKFold
     (grouped by repo_full_name, so a repo never appears in both train and
     test within a fold) — 5 repeats x 5 folds = 25 AUC evaluations per
     model, reported as mean +/- std instead of one point estimate.

Original results/rq2_model_results.csv, rq2_feature_importance.csv, and
figures are left untouched; this writes *_corrected outputs.
"""

import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from pipeline_utils import DATA_DIR, FIGURES_DIR, RESULTS_DIR

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"

N_REPEATS = 5
N_SPLITS = 5


def get_features(df: pd.DataFrame, drop_ecosystem: bool = False):
    base = [
        "cvss_score",
        "cvss_severity_ord",
        "version_bump_ord",
        "has_cve",
        "ecosystem_bin",
        "repo_stars",
    ]
    if drop_ecosystem:
        # constant within a single-ecosystem subset (e.g. --maven-only) --
        # zero variance breaks StandardScaler and carries no signal anyway.
        base = [c for c in base if c != "ecosystem_bin"]
    cwe_cols = [col for col in df.columns if col.startswith("cwe_") and col not in {"cwe_ids_details", "cwe_top_category"}]
    feature_cols = [col for col in base + cwe_cols if col in df.columns]
    X = df[feature_cols].fillna(0)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0)
    y = df["has_bc"].astype(int)
    return X, y, feature_cols


def build_models():
    return {
        "Logistic Regression": Pipeline([("scaler", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=1000))]),
        "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
        "Gradient Boosting": GradientBoostingClassifier(n_estimators=100, random_state=42),
        "Decision Tree": DecisionTreeClassifier(max_depth=5, random_state=42),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--maven-only", action="store_true", help="Filter to ecosystem=='maven' before any computation (Phase 5 robustness variant)")
    args = parser.parse_args()

    suffix = "_mavenonly" if args.maven_only else "_corrected"
    fig_suffix = "_mavenonly" if args.maven_only else ""
    results_path = RESULTS_DIR / f"rq2_model_results{suffix}.csv"
    importance_path = RESULTS_DIR / f"rq2_feature_importance{suffix}.csv"

    sns.set_theme(style="whitegrid")
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    if args.maven_only:
        df = df[df["ecosystem"] == "maven"].copy()
    df = df[df["analyzed_ok"]].reset_index(drop=True)
    print(f"[rq2_model_corrected] training on {len(df)} analyzed_ok rows ({df['repo_full_name'].nunique()} distinct repos)"
          + (" [--maven-only]" if args.maven_only else ""))

    X, y, feature_cols = get_features(df, drop_ecosystem=args.maven_only)
    groups = df["repo_full_name"]

    # --- sanity check: has_cve importance after removing has_behavioral_bc ---
    probe = RandomForestClassifier(n_estimators=200, random_state=42).fit(X, y)
    probe_importance = pd.Series(probe.feature_importances_, index=feature_cols).sort_values(ascending=False)
    has_cve_rank = list(probe_importance.index).index("has_cve") + 1 if "has_cve" in probe_importance.index else None
    has_cve_importance = probe_importance.get("has_cve", float("nan"))
    print(f"[rq2_model_corrected] has_cve importance after removing has_behavioral_bc: {has_cve_importance:.4f} (rank {has_cve_rank}/{len(feature_cols)})")
    if has_cve_importance < 0.01:
        print("  decision: has_cve importance ~0, but keeping it in the feature set — it is a legitimate")
        print("  pre-outcome feature (unlike has_behavioral_bc) and near-zero importance is a valid finding, not a leak.")

    models = build_models()
    per_model_fold_aucs = {name: [] for name in models}
    per_model_oof = {name: (np.array([]), np.array([])) for name in models}  # (y_true, y_prob) from repeat 0

    for repeat in range(N_REPEATS):
        cv = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=100 + repeat)
        for name in models:
            oof_true, oof_prob = [], []
            for train_idx, test_idx in cv.split(X, y, groups=groups):
                model = build_models()[name]
                model.fit(X.iloc[train_idx], y.iloc[train_idx])
                if hasattr(model, "predict_proba"):
                    prob = model.predict_proba(X.iloc[test_idx])[:, 1]
                else:
                    prob = model.decision_function(X.iloc[test_idx])
                y_test = y.iloc[test_idx]
                if y_test.nunique() > 1:
                    per_model_fold_aucs[name].append(roc_auc_score(y_test, prob))
                oof_true.extend(y_test.tolist())
                oof_prob.extend(prob.tolist())
            if repeat == 0:
                per_model_oof[name] = (np.array(oof_true), np.array(oof_prob))

    rows = []
    print("=== RQ2 MODEL COMPARISON (repeated grouped CV, corrected) ===")
    print(f"Model                mean AUC-ROC   std   n_folds")
    best_name, best_mean = None, -1.0
    for name, aucs in per_model_fold_aucs.items():
        mean_auc = float(np.mean(aucs))
        std_auc = float(np.std(aucs))
        print(f"{name:<20} {mean_auc:.3f}          {std_auc:.3f}  {len(aucs)}")
        rows.append({"model": name, "auc_roc_mean": mean_auc, "auc_roc_std": std_auc, "n_folds": len(aucs), "n_repeats": N_REPEATS, "n_splits": N_SPLITS})
        if mean_auc > best_mean:
            best_mean = mean_auc
            best_name = name

    print(f"Best: {best_name} (mean AUC-ROC = {best_mean:.3f})")

    best_model_final = build_models()[best_name]
    best_model_final.fit(X, y)
    inner = best_model_final.named_steps["model"] if isinstance(best_model_final, Pipeline) else best_model_final
    if hasattr(inner, "feature_importances_"):
        importance = pd.Series(inner.feature_importances_, index=feature_cols).sort_values(ascending=False)
    elif hasattr(inner, "coef_"):
        importance = pd.Series(abs(inner.coef_[0]), index=feature_cols).sort_values(ascending=False)
    else:
        importance = pd.Series(dtype=float)

    if not importance.empty:
        importance.head(20).rename_axis("feature").reset_index(name="importance").to_csv(importance_path, index=False)
        print("Top 10 features (fit on full analyzed_ok set):")
        for feature, score in importance.head(10).items():
            print(f"  {feature}: {score:.4f}")

    if best_mean < 0.65:
        print("MODEL NOTE: mean AUC-ROC below 0.65 suggests BC risk is not reliably predictable from CVE/version features alone under a repo-grouped evaluation.")

    pd.DataFrame(rows).to_csv(results_path, index=False)

    plt.figure(figsize=(8, 6))
    for name in models:
        y_true, y_prob = per_model_oof[name]
        if len(np.unique(y_true)) < 2:
            continue
        fpr, tpr, _ = roc_curve(y_true, y_prob)
        mean_auc = np.mean(per_model_fold_aucs[name])
        std_auc = np.std(per_model_fold_aucs[name])
        plt.plot(fpr, tpr, label=f"{name} (AUC={mean_auc:.2f}+/-{std_auc:.2f})")
    plt.plot([0, 1], [0, 1], linestyle="--", color="black")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("RQ2 ROC Curves (repo-grouped CV, corrected)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / f"rq2_roc_curves{fig_suffix}.png", dpi=200)
    plt.close()

    if not importance.empty:
        plt.figure(figsize=(10, 6))
        sns.barplot(x=importance.head(10).values, y=importance.head(10).index, orient="h")
        plt.title("Top 10 Feature Importances (corrected)")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / f"rq2_feature_importance{fig_suffix}.png", dpi=200)
        plt.close()

    total_evals = sum(len(v) for v in per_model_fold_aucs.values())
    print(f"[DONE] rq2_model_corrected — {len(df)} records processed, {total_evals} fold evaluations")


if __name__ == "__main__":
    main()
