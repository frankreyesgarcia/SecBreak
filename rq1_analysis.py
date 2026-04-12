from collections import Counter

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy.stats import chi2_contingency, spearmanr
from statsmodels.stats.proportion import proportions_ztest

from pipeline_utils import DATA_DIR, FIGURES_DIR, RESULTS_DIR, pct, wilson_ci


DATASET_PATH = DATA_DIR / "analysis_dataset.csv"
TABLES_PATH = RESULTS_DIR / "rq1_tables.csv"


def error_bar_frame(series: pd.Series, labels: pd.Series):
    rows = []
    for label, values in series.groupby(labels):
        n = len(values)
        s = int(values.sum())
        low, high = wilson_ci(s, n)
        rows.append({"label": label, "prevalence": s / n if n else 0, "low": low, "high": high, "n": n})
    return pd.DataFrame(rows)


def main():
    sns.set_theme(style="whitegrid")
    df = pd.read_csv(DATASET_PATH)
    tables = []

    total = len(df)
    bc_n = int(df["has_bc"].sum())
    beh_n = int(df["has_behavioral_bc"].sum())
    low, high = wilson_ci(bc_n, total)
    b_low, b_high = wilson_ci(beh_n, total)
    z_stat, p_value = proportions_ztest(bc_n, total, value=0.132)
    sig = "significantly" if p_value < 0.05 else "not significantly"
    print(f"Overall syntactic BC prevalence: {pct(bc_n, total):.1f}% [95% CI {100*low:.1f}–{100*high:.1f}]")
    print(f"Behavioral BC prevalence: {pct(beh_n, total):.1f}% [95% CI {100*b_low:.1f}–{100*b_high:.1f}]")
    print(f"Our prevalence ({pct(bc_n, total):.1f}%) is {sig} higher than TSE 2021 (13.2%), z={z_stat:.3f}, p={p_value:.4g}")
    tables.append({"metric": "overall_bc_prevalence", "value": bc_n / total, "ci_low": low, "ci_high": high})
    tables.append({"metric": "behavioral_bc_prevalence", "value": beh_n / total, "ci_low": b_low, "ci_high": b_high})

    eco_table = pd.crosstab(df["ecosystem"], df["has_bc"])
    chi2, chi_p, _, _ = chi2_contingency(eco_table)
    print("By ecosystem:")
    for eco, sub in df.groupby("ecosystem"):
        print(f"  {eco}: {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    print(f"Chi-square ecosystem vs BC: chi2={chi2:.3f}, p={chi_p:.4g}")

    bump_table = pd.crosstab(df["version_bump_type"], df["has_bc"])
    bump_chi2, bump_p, _, _ = chi2_contingency(bump_table)
    print("By version bump:")
    for bump, sub in df.groupby("version_bump_type"):
        print(f"  {bump}: {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    patch_sub = df[df["version_bump_type"] == "patch"]
    print(f"{pct(int(patch_sub['has_bc'].sum()), len(patch_sub)):.1f}% of patch-level security PRs introduce BCs")
    print(f"Chi-square version bump vs BC: chi2={bump_chi2:.3f}, p={bump_p:.4g}")

    print("By CVSS severity:")
    for sev, sub in df.groupby("severity"):
        print(f"  {sev}: {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    rho, rho_p = spearmanr(df["cvss_score"], df["has_bc"])
    print(f"Spearman rho(CVSS, has_bc)={rho:.3f}, p={rho_p:.4g}")

    bc_types = Counter()
    for raw in df["bc_types"].dropna():
        if isinstance(raw, str):
            try:
                items = eval(raw)
            except Exception:
                items = [raw]
        else:
            items = raw
        bc_types.update(items or [])
    type_rows = [{"bc_type": name, "count": count} for name, count in bc_types.most_common()]
    type_df = pd.DataFrame(type_rows)
    method_count = sum(count for name, count in bc_types.items() if "METHOD" in name)
    type_count = sum(count for name, count in bc_types.items() if "TYPE" in name or "CLASS" in name)
    field_count = sum(count for name, count in bc_types.items() if "FIELD" in name)
    total_types = max(sum(bc_types.values()), 1)
    print("BC type distribution:")
    print(f"  Method-level: {100*method_count/total_types:.1f}%")
    print(f"  Type-level: {100*type_count/total_types:.1f}%")
    print(f"  Field-level: {100*field_count/total_types:.1f}%")

    pd.DataFrame(tables).to_csv(TABLES_PATH, index=False)

    bump_df = error_bar_frame(df["has_bc"], df["version_bump_type"])
    plt.figure(figsize=(8, 5))
    plt.bar(bump_df["label"], 100 * bump_df["prevalence"], yerr=[100 * (bump_df["prevalence"] - bump_df["low"]), 100 * (bump_df["high"] - bump_df["prevalence"])], capsize=4)
    plt.ylabel("BC prevalence (%)")
    plt.title("Security PR BC Prevalence by Version Bump")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq1_prevalence_by_bump.png", dpi=200)
    plt.close()

    sev_df = error_bar_frame(df["has_bc"], df["severity"].fillna("UNKNOWN"))
    plt.figure(figsize=(8, 5))
    plt.bar(sev_df["label"], 100 * sev_df["prevalence"], yerr=[100 * (sev_df["prevalence"] - sev_df["low"]), 100 * (sev_df["high"] - sev_df["prevalence"])], capsize=4)
    plt.ylabel("BC prevalence (%)")
    plt.title("Security PR BC Prevalence by CVSS Severity")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq1_prevalence_by_severity.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.barplot(data=type_df.head(15), x="count", y="bc_type", orient="h")
    plt.title("Most Common BC Types")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq1_bc_types.png", dpi=200)
    plt.close()


if __name__ == "__main__":
    main()
