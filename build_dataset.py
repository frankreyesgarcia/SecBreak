from collections import Counter

import numpy as np
import pandas as pd

from pipeline_utils import DATA_DIR, load_jsonl, pct, wilson_ci


RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
BC_RESULTS_PATH = DATA_DIR / "bc_results.jsonl"
CVE_DETAILS_PATH = DATA_DIR / "cve_details.json"
OUT_PATH = DATA_DIR / "analysis_dataset.csv"


SEVERITY_ORD = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
BUMP_ORD = {"patch": 0, "minor": 1, "major": 2}


def top_level_cwe(cwe_ids):
    if not cwe_ids:
        return "UNKNOWN"
    first = cwe_ids[0]
    return first.split("-")[0] + "-" + first.split("-")[1] if "-" in first else first


def main():
    prs = pd.DataFrame(load_jsonl(RAW_PRS_PATH))
    bc = pd.DataFrame(load_jsonl(BC_RESULTS_PATH))
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

    error_rate = merged["analysis_error"].notna().mean()
    if error_rate <= 0.4:
        merged = merged[merged["analysis_error"].isna()].copy()
        merged["kept_with_error_flag"] = 0
    else:
        merged["kept_with_error_flag"] = merged["analysis_error"].notna().astype(int)

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
    bc_n = int(merged["has_bc"].sum())
    low, high = wilson_ci(bc_n, total)
    syntactic_n = bc_n
    behavioral_n = int(merged["has_behavioral_bc"].sum())
    print("=== DATASET SUMMARY ===")
    print(f"Total PRs:              {total}")
    for ecosystem in ["maven", "pypi"]:
        sub = merged[merged["ecosystem"] == ecosystem]
        print(f"  - {ecosystem.capitalize()}:              {len(sub)} ({pct(len(sub), total):.1f}%)")
    merged_prs = merged["merged_at"].notna().sum()
    print(f"Merged PRs:             {merged_prs} ({pct(int(merged_prs), total):.1f}%)")
    print(f"PRs with BCs:           {bc_n} ({pct(bc_n, total):.1f}%) [95% CI: {100*low:.1f}%–{100*high:.1f}%]")
    print(f"  - Syntactic BCs:      {syntactic_n} ({pct(syntactic_n, total):.1f}%)")
    print(f"  - Behavioral BCs:     {behavioral_n} ({pct(behavioral_n, total):.1f}%)")
    print("By version bump:")
    for bump in ["patch", "minor", "major"]:
        sub = merged[merged["version_bump_type"] == bump]
        print(f"  - {bump}:  {int(sub['has_bc'].sum())}/{len(sub)} ({pct(int(sub['has_bc'].sum()), len(sub)):.1f}%)")
    print("By CVSS severity:")
    for sev in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        sub = merged[merged["severity"] == sev]
        print(f"  - {sev}:     {int(sub['has_bc'].sum())}/{len(sub)} ({pct(int(sub['has_bc'].sum()), len(sub)):.1f}%)")
    print("Top BC types (Roseau):")
    counts = Counter()
    for value in merged["bc_types"].dropna():
        if isinstance(value, str):
            try:
                items = eval(value)
            except Exception:
                items = [value]
        else:
            items = value
        counts.update(items or [])
    for idx, (name, count) in enumerate(counts.most_common(10), start=1):
        print(f"  {idx}. {name}:   {count}")


if __name__ == "__main__":
    main()
