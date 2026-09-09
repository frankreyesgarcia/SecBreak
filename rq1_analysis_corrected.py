"""Phase 3: RQ1 recomputed over the corrected dataset with a transparent,
non-buggy denominator.

The original rq1_analysis.py used `total = len(df)` (783) as the prevalence
denominator without checking whether BC detection actually executed for each
row. This script reports three numbers instead of one:
  - full_cohort_naive_rate: the old, wrong computation — kept only as an
    illustration of the pipeline-completeness problem, NOT a prevalence
    estimate.
  - analyzed_only_prevalence: has_bc.sum() / analyzed_ok.sum(), the number
    that belongs in the abstract/RQ1 results.
  - pipeline_coverage_rate: analyzed_ok.sum() / len(df), a methodology
    transparency metric (analogous to a survey response rate).

Original results/rq1_tables.csv and rq1_prevalence_by_bump.png are left
untouched (preserved as *_ORIGINAL_BUGGY for the record); this script writes
*_corrected outputs alongside them.
"""

import argparse
from collections import Counter

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy.stats import chi2_contingency, spearmanr
from statsmodels.stats.proportion import proportions_ztest

from pipeline_utils import DATA_DIR, FIGURES_DIR, RESULTS_DIR, pct, wilson_ci

DATASET_PATH = DATA_DIR / "analysis_dataset_corrected.csv"


def error_bar_frame(has_bc: pd.Series, labels: pd.Series):
    rows = []
    for label, values in has_bc.groupby(labels):
        n = len(values)
        s = int(values.sum())
        low, high = wilson_ci(s, n)
        rows.append({"label": label, "prevalence": s / n if n else 0, "low": low, "high": high, "n": n})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--maven-only", action="store_true", help="Filter to ecosystem=='maven' before any computation (Phase 5 robustness variant)")
    args = parser.parse_args()

    suffix = "_mavenonly" if args.maven_only else "_corrected"
    tables_path = RESULTS_DIR / f"rq1_tables{suffix}.csv"
    fig_suffix = "_mavenonly" if args.maven_only else ""

    sns.set_theme(style="whitegrid")
    df = pd.read_csv(DATASET_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    if args.maven_only:
        df = df[df["ecosystem"] == "maven"].copy()
        print(f"[rq1_analysis] --maven-only: filtered to {len(df)} Maven rows")
    analyzed = df[df["analyzed_ok"]].copy()

    tables = []
    total = len(df)
    analyzed_n = len(analyzed)

    # --- Metric 1: full-cohort naive rate (the OLD, WRONG number) ---
    naive_bc_n = int(df["has_bc"].sum())
    naive_low, naive_high = wilson_ci(naive_bc_n, total)
    print("=== METRIC 1: full-cohort naive rate (NOT a prevalence estimate) ===")
    print(f"  {naive_bc_n}/{total} = {pct(naive_bc_n, total):.1f}% [95% CI {100*naive_low:.1f}-{100*naive_high:.1f}]")
    print("  WARNING: includes rows where BC detection never ran; do not cite as prevalence.")
    tables.append({"metric": "full_cohort_naive_rate_NOT_PREVALENCE", "value": naive_bc_n / total, "ci_low": naive_low, "ci_high": naive_high, "n": total})

    # --- Metric 2: analyzed-only prevalence (THE number for RQ1) ---
    bc_n = int(analyzed["has_bc"].sum())
    low, high = wilson_ci(bc_n, analyzed_n)
    z_stat, p_value = proportions_ztest(bc_n, analyzed_n, value=0.132)
    sig = "significantly" if p_value < 0.05 else "not significantly"
    print("=== METRIC 2: analyzed-only prevalence (cite this one) ===")
    print(f"  {bc_n}/{analyzed_n} = {pct(bc_n, analyzed_n):.1f}% [95% CI {100*low:.1f}-{100*high:.1f}]")
    print(f"  vs TSE 2021 (13.2%): {sig} different, z={z_stat:.3f}, p={p_value:.4g}")
    tables.append({"metric": "analyzed_only_prevalence", "value": bc_n / analyzed_n, "ci_low": low, "ci_high": high, "n": analyzed_n})

    # --- Metric 3: pipeline coverage rate (methodology transparency) ---
    coverage = analyzed_n / total
    print("=== METRIC 3: pipeline coverage rate ===")
    print(f"  {analyzed_n}/{total} = {100*coverage:.1f}% of PRs had BC detection genuinely execute")
    tables.append({"metric": "pipeline_coverage_rate", "value": coverage, "ci_low": None, "ci_high": None, "n": total})

    # --- Behavioral BC: NOT REPORTED, see Phase 4 diagnostic conclusion ---
    # Phase 4 fixed two structural harness bugs (head_sha never fetched;
    # PyPI test env never provisioned) but a diagnostic sample then showed
    # tests_pass_old=False for ~21/21 rows almost entirely due to environment
    # confounds (missing test-only deps for PyPI, Maven Central rate-limiting
    # on cold multi-module builds) unrelated to the PR under study — not real
    # pre-existing failures or behavioral BCs. Reporting a percentage from
    # this data would be actively misleading. Per the rectification doc's
    # explicit fallback for this scenario, behavioral BC is intentionally
    # left unmeasured here; see logs/rectification_decisions.log and the
    # paper's Threats to Validity section for the full rationale.
    print("=== Behavioral BC: NOT REPORTED (see logs/rectification_decisions.log) ===")
    print("  Harness structurally fixed, but pass/fail signal is confounded by")
    print("  environment issues, not real BC signal. Left as future work.")
    tables.append({"metric": "behavioral_bc_prevalence_NOT_MEASURED", "value": None, "ci_low": None, "ci_high": None, "n": analyzed_n})

    # --- Ecosystem breakdown (analyzed_ok only) ---
    eco_table = pd.crosstab(analyzed["ecosystem"], analyzed["has_bc"])
    chi2, chi_p, _, _ = chi2_contingency(eco_table) if eco_table.shape[0] > 1 and eco_table.shape[1] > 1 else (float("nan"), float("nan"), None, None)
    print("By ecosystem (analyzed_ok only):")
    for eco, sub in analyzed.groupby("ecosystem"):
        print(f"  {eco}: {int(sub['has_bc'].sum())}/{len(sub)} = {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    print(f"  Chi-square ecosystem vs BC: chi2={chi2:.3f}, p={chi_p:.4g}")

    # --- Version bump breakdown (analyzed_ok only) ---
    bump_table = pd.crosstab(analyzed["version_bump_type"], analyzed["has_bc"])
    bump_chi2, bump_p, _, _ = chi2_contingency(bump_table) if bump_table.shape[0] > 1 and bump_table.shape[1] > 1 else (float("nan"), float("nan"), None, None)
    print("By version bump (analyzed_ok only):")
    for bump, sub in analyzed.groupby("version_bump_type"):
        print(f"  {bump}: {int(sub['has_bc'].sum())}/{len(sub)} = {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    patch_sub = analyzed[analyzed["version_bump_type"] == "patch"]
    if len(patch_sub):
        print(f"  {pct(int(patch_sub['has_bc'].sum()), len(patch_sub)):.1f}% of analyzed patch-level security PRs introduce BCs")
    print(f"  Chi-square version bump vs BC: chi2={bump_chi2:.3f}, p={bump_p:.4g}")

    # --- CVSS severity breakdown (analyzed_ok only) ---
    print("By CVSS severity (analyzed_ok only):")
    for sev, sub in analyzed.groupby("severity"):
        print(f"  {sev}: {int(sub['has_bc'].sum())}/{len(sub)} = {pct(int(sub['has_bc'].sum()), len(sub)):.1f}%")
    if analyzed["cvss_score"].notna().any():
        rho, rho_p = spearmanr(analyzed["cvss_score"], analyzed["has_bc"])
        print(f"  Spearman rho(CVSS, has_bc)={rho:.3f}, p={rho_p:.4g}")

    # --- BC type distribution (analyzed_ok only) ---
    bc_types = Counter()
    for raw in analyzed["bc_types"].dropna():
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
    # Mutually-exclusive top-level kind, keyed on the event-name prefix, matching
    # generate_presubmission_artifacts.py. An earlier version used substring tests
    # ("METHOD" in name, "TYPE" in name or "CLASS" in name, "FIELD" in name), which
    # double-counted events such as TYPE_NEW_ABSTRACT_METHOD and summed to >100%.
    method_count = sum(count for name, count in bc_types.items() if name.startswith("METHOD_"))
    type_count = sum(count for name, count in bc_types.items() if name.startswith("TYPE_"))
    field_count = sum(count for name, count in bc_types.items() if name.startswith("FIELD_"))
    classified_total = max(method_count + type_count + field_count, 1)
    print(f"BC kind distribution (analyzed_ok only; {classified_total} method/type/field events, mutually exclusive):")
    print(f"  Method-level: {100*method_count/classified_total:.1f}%")
    print(f"  Type-level: {100*type_count/classified_total:.1f}%")
    print(f"  Field-level: {100*field_count/classified_total:.1f}%")

    pd.DataFrame(tables).to_csv(tables_path, index=False)

    bump_df = error_bar_frame(analyzed["has_bc"], analyzed["version_bump_type"])
    plt.figure(figsize=(8, 5))
    plt.bar(bump_df["label"], 100 * bump_df["prevalence"], yerr=[100 * (bump_df["prevalence"] - bump_df["low"]), 100 * (bump_df["high"] - bump_df["prevalence"])], capsize=4)
    plt.ylabel("BC prevalence (%)")
    plt.title("Security PR BC Prevalence by Version Bump (analyzed_ok only, corrected)")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / f"rq1_prevalence_by_bump{fig_suffix}.png", dpi=200)
    plt.close()

    sev_df = error_bar_frame(analyzed["has_bc"], analyzed["severity"].fillna("UNKNOWN"))
    plt.figure(figsize=(8, 5))
    plt.bar(sev_df["label"], 100 * sev_df["prevalence"], yerr=[100 * (sev_df["prevalence"] - sev_df["low"]), 100 * (sev_df["high"] - sev_df["prevalence"])], capsize=4)
    plt.ylabel("BC prevalence (%)")
    plt.title("Security PR BC Prevalence by CVSS Severity (analyzed_ok only, corrected)")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / f"rq1_prevalence_by_severity{fig_suffix}.png", dpi=200)
    plt.close()

    if not type_df.empty:
        plt.figure(figsize=(10, 6))
        sns.barplot(data=type_df.head(15), x="count", y="bc_type", orient="h")
        plt.title("Most Common BC Types (analyzed_ok only, corrected)")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / f"rq1_bc_types{fig_suffix}.png", dpi=200)
        plt.close()

    print(f"[DONE] rq1_analysis_corrected — {total} records processed, {analyzed_n} analyzed_ok")


if __name__ == "__main__":
    main()
