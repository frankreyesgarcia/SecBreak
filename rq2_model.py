import pickle

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from pipeline_utils import DATA_DIR, FIGURES_DIR, RESULTS_DIR


DATASET_PATH = DATA_DIR / "analysis_dataset.csv"
RESULTS_PATH = RESULTS_DIR / "rq2_model_results.csv"
MODEL_PATH = RESULTS_DIR / "best_model.pkl"
IMPORTANCE_PATH = RESULTS_DIR / "rq2_feature_importance.csv"


def get_features(df: pd.DataFrame):
    base = [
        "cvss_score",
        "cvss_severity_ord",
        "version_bump_ord",
        "has_cve",
        "ecosystem_bin",
        "has_behavioral_bc",
        "repo_stars",
    ]
    cwe_cols = [col for col in df.columns if col.startswith("cwe_") and col not in {"cwe_ids_details", "cwe_top_category"}]
    feature_cols = [col for col in base + cwe_cols if col in df.columns]
    X = df[feature_cols].fillna(0)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0)
    y = df["has_bc"].astype(int)
    return X, y, feature_cols


def main():
    sns.set_theme(style="whitegrid")
    df = pd.read_csv(DATASET_PATH)
    X, y, feature_cols = get_features(df)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)

    models = {
        "Logistic Regression": Pipeline(
            [("scaler", StandardScaler()), ("model", LogisticRegression(C=1.0, max_iter=1000))]
        ),
        "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
        "Gradient Boosting": GradientBoostingClassifier(n_estimators=100, random_state=42),
        "Decision Tree": DecisionTreeClassifier(max_depth=5, random_state=42),
    }

    rows = []
    roc_payload = []
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    best_name = None
    best_auc = -1.0
    best_model = None

    print("=== RQ2 MODEL COMPARISON ===")
    print("Model                AUC-ROC   F1      Precision  Recall")
    for name, model in models.items():
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else model.decision_function(X_test)
        auc = roc_auc_score(y_test, y_prob)
        pr_auc = average_precision_score(y_test, y_prob)
        f1 = f1_score(y_test, y_pred, average="weighted")
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        accuracy = accuracy_score(y_test, y_pred)
        cv_auc = cross_val_score(model, X_train, y_train, cv=cv, scoring="roc_auc").mean()
        rows.append(
            {
                "model": name,
                "auc_roc": auc,
                "f1_weighted": f1,
                "precision": precision,
                "recall": recall,
                "accuracy": accuracy,
                "cv_auc_mean": cv_auc,
                "pr_auc": pr_auc,
            }
        )
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        roc_payload.append((name, fpr, tpr, auc))
        print(f"{name:<20} {auc:.2f}      {f1:.2f}    {precision:.2f}       {recall:.2f}")
        if auc > best_auc:
            best_auc = auc
            best_name = name
            best_model = model

    print(f"Best: {best_name} (AUC-ROC = {best_auc:.2f})")

    importance = None
    inner = best_model.named_steps["model"] if isinstance(best_model, Pipeline) else best_model
    if hasattr(inner, "feature_importances_"):
        importance = pd.Series(inner.feature_importances_, index=feature_cols).sort_values(ascending=False)
    elif hasattr(inner, "coef_"):
        importance = pd.Series(abs(inner.coef_[0]), index=feature_cols).sort_values(ascending=False)
    else:
        importance = pd.Series(dtype=float)

    if not importance.empty:
        importance.head(20).rename_axis("feature").reset_index(name="importance").to_csv(IMPORTANCE_PATH, index=False)
        print("Top 10 features:")
        for feature, score in importance.head(10).items():
            print(f"  {feature}: {score:.4f}")

    if best_auc < 0.65:
        print("MODEL NOTE: AUC-ROC below 0.65 suggests BC risk is not reliably predictable from CVE/version features alone. Consider adding repository-level features (test coverage, CI pass rate) in future work.")

    pd.DataFrame(rows).to_csv(RESULTS_PATH, index=False)
    with MODEL_PATH.open("wb") as fh:
        pickle.dump(best_model, fh)

    plt.figure(figsize=(8, 6))
    for name, fpr, tpr, auc in roc_payload:
        plt.plot(fpr, tpr, label=f"{name} (AUC={auc:.2f})")
    plt.plot([0, 1], [0, 1], linestyle="--", color="black")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("RQ2 ROC Curves")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq2_roc_curves.png", dpi=200)
    plt.close()

    if not importance.empty:
        plt.figure(figsize=(10, 6))
        sns.barplot(x=importance.head(10).values, y=importance.head(10).index, orient="h")
        plt.title("Top 10 Feature Importances")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "rq2_feature_importance.png", dpi=200)
        plt.close()


if __name__ == "__main__":
    main()
