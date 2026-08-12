"""Phase 3 dataset build: same as build_dataset.py but sourced from the
Phase 1/2 corrected files, with an explicit analyzed_ok column and without
build_dataset.py's silent row-dropping.

build_dataset.py's original bug: `if error_rate <= 0.4: merged =
merged[merged["analysis_error"].isna()]` — a no-op here since the baseline
error rate is 74.3% (> 0.4), so it fell into the else branch and kept all 783
rows including ones where detection never ran. Those rows' has_bc is already
hardcoded False inside detect_maven_bcs()'s error-path return values (not
NaN), so nothing downstream could tell a real negative from "never analyzed".
This script keeps every row (still no silent dropping) but adds analyzed_ok
so rq1_analysis_corrected.py can compute prevalence over the right
denominator instead of len(df).
"""

from collections import Counter

import pandas as pd

from pipeline_utils import DATA_DIR, load_jsonl, pct, wilson_ci

RAW_PRS_PATH = DATA_DIR / "raw_prs_corrected.jsonl"
RAW_PRS_FALLBACK = DATA_DIR / "raw_prs.jsonl"
BC_RESULTS_PATH = DATA_DIR / "bc_results_corrected.jsonl"
BC_RESULTS_FALLBACK = DATA_DIR / "bc_results.jsonl"
CVE_DETAILS_PATH = DATA_DIR / "cve_details.json"
OUT_PATH = DATA_DIR / "analysis_dataset_corrected.csv"

SEVERITY_ORD = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
BUMP_ORD = {"patch": 0, "minor": 1, "major": 2}


def top_level_cwe(cwe_ids):
    if not cwe_ids:
        return "UNKNOWN"
    first = cwe_ids[0]
    return first.split("-")[0] + "-" + first.split("-")[1] if "-" in first else first


def main():
    raw_path = RAW_PRS_PATH if RAW_PRS_PATH.exists() else RAW_PRS_FALLBACK
    bc_path = BC_RESULTS_PATH if BC_RESULTS_PATH.exists() else BC_RESULTS_FALLBACK
    print(f"[build_dataset_corrected] reading {raw_path.name}, {bc_path.name}")

    prs = pd.DataFrame(load_jsonl(raw_path))
    bc = pd.DataFrame(load_jsonl(bc_path))
    cves = pd.read_json(CVE_DETAILS_PATH, orient="index").reset_index().rename(columns={"index": "cve_id"})

    if prs.empty:
        raise SystemExit("No raw PRs found.")
    if bc.empty:
        raise SystemExit("No BC results found.")

    prs = prs.drop_duplicates(subset=["repo_full_name", "pr_number"]).copy()
    bc = bc.drop_duplicates(subset=["repo_full_name", "pr_number"]).copy()

    expanded = prs.explode("cve_ids")
    merged = prs.merge(bc, on=["repo_full_name", "pr_number"], how="left")
    if not cves.empty:
        expanded = expanded.merge(cves, left_on="cve_ids", right_on="cve_id", how="left")
        cve_agg = (
            expanded.groupby(["repo_full_name", "pr_number"])
            .agg(
                cvss_score=("cvss_score", "max"),
                severity=("severity", "first"),
                cwe_ids_details=("cwe_ids", lambda x: list({item for sub in x.dropna() for item in (sub or [])})),
                cve_description=("description", "first"),
            )
            .reset_index()
        )
        merged = merged.merge(cve_agg, on=["repo_full_name", "pr_number"], how="left")

    # analyzed_ok: detection genuinely ran (no analysis_error AND a tool actually executed).
    merged["analyzed_ok"] = merged["analysis_error"].isna() & merged["tool_used"].notna()

    merged["cvss_score"] = pd.to_numeric(merged["cvss_score"], errors="coerce")
    merged["cvss_score"] = merged["cvss_score"].fillna(merged["cvss_score"].median())
    merged["cvss_severity_ord"] = merged["severity"].map(SEVERITY_ORD).fillna(0).astype(int)
    merged["version_bump_ord"] = merged["version_bump_type"].map(BUMP_ORD).fillna(-1).astype(int)
    merged["cwe_top_category"] = merged["cwe_ids_details"].apply(top_level_cwe)
    merged["has_cve"] = merged["cve_ids"].apply(lambda x: int(bool(x)))
    merged["ecosystem_bin"] = merged["ecosystem"].map({"maven": 0, "pypi": 1}).fillna(-1).astype(int)
    merged["bc_count_roseau"] = pd.to_numeric(merged["bc_count"], errors="coerce").fillna(0).astype(int)
    merged["has_behavioral_bc"] = ((merged["tests_pass_new"] == False) & (merged["tests_available"] == True)).astype(int)
    merged["has_bc"] = merged["has_bc"].fillna(False).astype(int)

    top_cwe = merged["cwe_top_category"].value_counts().head(10).index.tolist()
    for cwe in top_cwe:
        merged[f"cwe_{cwe.replace('-', '_')}"] = (merged["cwe_top_category"] == cwe).astype(int)

    merged.to_csv(OUT_PATH, index=False)

    total = len(merged)
    analyzed_ok_n = int(merged["analyzed_ok"].sum())
    bc_n = int(merged["has_bc"].sum())
    bc_analyzed_n = int(merged.loc[merged["analyzed_ok"], "has_bc"].sum())
    low, high = wilson_ci(bc_analyzed_n, analyzed_ok_n) if analyzed_ok_n else (0.0, 0.0)
    print("=== CORRECTED DATASET SUMMARY ===")
    print(f"Total PRs:                    {total}")
    print(f"Pipeline coverage (analyzed_ok): {analyzed_ok_n} ({pct(analyzed_ok_n, total):.1f}%)")
    print(f"Naive full-cohort BC rate (NOT a prevalence estimate): {bc_n} ({pct(bc_n, total):.1f}%)")
    print(f"Analyzed-only BC prevalence: {bc_analyzed_n}/{analyzed_ok_n} ({pct(bc_analyzed_n, analyzed_ok_n):.1f}%) [95% CI {100*low:.1f}-{100*high:.1f}]")
    for ecosystem in ["maven", "pypi"]:
        sub = merged[merged["ecosystem"] == ecosystem]
        print(f"  - {ecosystem.capitalize()}: {len(sub)} total, {int(sub['analyzed_ok'].sum())} analyzed_ok")
    print("Top BC types (Roseau/japicmp/griffe):")
    counts = Counter()
    for value in merged.loc[merged["analyzed_ok"], "bc_types"].dropna():
        if isinstance(value, str):
            try:
                items = eval(value)
            except Exception:
                items = [value]
        else:
            items = value
        counts.update(items or [])
    for idx, (name, count) in enumerate(counts.most_common(10), start=1):
        print(f"  {idx}. {name}: {count}")

    print(f"[DONE] build_dataset_corrected — {total} records processed, {analyzed_ok_n} analyzed_ok")


if __name__ == "__main__":
    main()
