import json
from collections import Counter
from pathlib import Path

import pandas as pd

from pipeline_utils import DATA_DIR, RESULTS_DIR, load_jsonl, write_json


RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
BC_RESULTS_PATH = DATA_DIR / "bc_results.jsonl"
CVE_DETAILS_PATH = DATA_DIR / "cve_details.json"
COHORT_DIR = RESULTS_DIR / "cohort"


def main():
    COHORT_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.DataFrame(load_jsonl(RAW_PRS_PATH))
    bc = pd.DataFrame(load_jsonl(BC_RESULTS_PATH))
    cves = json.loads(CVE_DETAILS_PATH.read_text(encoding="utf-8"))

    raw["cohort_key"] = raw["repo_full_name"] + "#" + raw["pr_number"].astype(str)
    bc["cohort_key"] = bc["repo_full_name"] + "#" + bc["pr_number"].astype(str)

    duplicate_counts = raw["cohort_key"].value_counts()
    raw_unique = raw.drop_duplicates(subset=["repo_full_name", "pr_number"]).copy()
    bc_unique = bc.drop_duplicates(subset=["repo_full_name", "pr_number"]).copy()
    merged = raw_unique.merge(
        bc_unique,
        on=["repo_full_name", "pr_number"],
        how="left",
        suffixes=("", "_bc"),
    )

    merged["has_cve"] = merged["cve_ids"].apply(lambda x: int(bool(x)))
    merged["has_bc_result"] = merged["has_bc"].notna().astype(int)
    merged["included_final_dataset"] = merged["has_bc_result"]
    merged["duplicate_raw_rows"] = merged["cohort_key"].map(duplicate_counts).fillna(1).astype(int) - 1
    merged["exclusion_reason"] = merged["included_final_dataset"].map({1: "", 0: "missing_bc_result"})

    flow = {
        "raw_rows": int(len(raw)),
        "raw_unique_prs": int(len(raw_unique)),
        "duplicate_rows_removed": int(len(raw) - len(raw_unique)),
        "prs_with_cve": int(merged["has_cve"].sum()),
        "prs_with_bc_results": int(merged["has_bc_result"].sum()),
        "final_dataset_prs": int(merged["included_final_dataset"].sum()),
        "repos_final": int(merged.loc[merged["included_final_dataset"] == 1, "repo_full_name"].nunique()),
        "ecosystem_counts_final": {
            k: int(v)
            for k, v in merged.loc[merged["included_final_dataset"] == 1, "ecosystem"].value_counts().to_dict().items()
        },
        "version_bump_counts_final": {
            k: int(v)
            for k, v in merged.loc[merged["included_final_dataset"] == 1, "version_bump_type"].value_counts().to_dict().items()
        },
        "cve_records_enriched": int(len(cves)),
    }

    merged.sort_values(["repo_full_name", "pr_number"]).to_csv(COHORT_DIR / "frozen_cohort.csv", index=False)
    write_json(COHORT_DIR / "cohort_flow.json", flow)

    md = [
        "# Frozen Cohort",
        "",
        "## Flow Summary",
        f"- Raw collected rows: {flow['raw_rows']}",
        f"- Unique PRs after deduplication: {flow['raw_unique_prs']}",
        f"- Duplicate raw rows removed: {flow['duplicate_rows_removed']}",
        f"- PRs with at least one CVE: {flow['prs_with_cve']}",
        f"- PRs with BC results: {flow['prs_with_bc_results']}",
        f"- Final dataset PRs: {flow['final_dataset_prs']}",
        f"- Final repositories: {flow['repos_final']}",
        f"- CVE records enriched: {flow['cve_records_enriched']}",
        "",
        "## Final Ecosystem Mix",
    ]
    for eco, count in flow["ecosystem_counts_final"].items():
        md.append(f"- {eco}: {count}")
    md.extend(["", "## Final Version-Bump Mix"])
    for bump, count in flow["version_bump_counts_final"].items():
        md.append(f"- {bump}: {count}")
    (COHORT_DIR / "cohort_flow.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(flow, indent=2))


if __name__ == "__main__":
    main()
