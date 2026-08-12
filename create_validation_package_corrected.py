"""Phase 6: restratify the manual validation sample after Phase 1-3.

70/100 rows in the original bc_validation_sample.csv had analysis_error set —
the detector never ran on them, so "detector said no BC" and "detector never
ran" were conflated in what manual adjudicators would see. This regenerates
the sample from data/analysis_dataset_corrected.csv restricted to
analyzed_ok==True rows only, so every sampled row reflects a real detector
verdict.
"""

import json
import random

import pandas as pd

from pipeline_utils import DATA_DIR, RESULTS_DIR

ANALYSIS_PATH = DATA_DIR / "analysis_dataset_corrected.csv"
VALIDATION_DIR = RESULTS_DIR / "validation"


def sample_stratified(df: pd.DataFrame, target_n: int = 100, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)
    df = df.copy()
    df["stratum"] = (
        df["ecosystem"].fillna("unknown").astype(str)
        + "|"
        + df["version_bump_type"].fillna("unknown").astype(str)
        + "|"
        + df["has_bc"].astype(str)
    )
    strata = df["stratum"].value_counts().to_dict()
    selected = []
    for stratum, count in sorted(strata.items(), key=lambda kv: kv[1], reverse=True):
        frac = count / len(df)
        take = max(1, round(target_n * frac))
        subset = df[df["stratum"] == stratum]
        selected.append(subset.sample(min(take, len(subset)), random_state=seed))
    out = pd.concat(selected).drop_duplicates(subset=["repo_full_name", "pr_number"])
    if len(out) > target_n:
        out = out.sample(target_n, random_state=seed)
    elif len(out) < target_n:
        remaining = df.merge(out[["repo_full_name", "pr_number"]], on=["repo_full_name", "pr_number"], how="left", indicator=True)
        remaining = remaining[remaining["_merge"] == "left_only"].drop(columns=["_merge"])
        if not remaining.empty:
            fill = remaining.sample(min(target_n - len(out), len(remaining)), random_state=seed)
            out = pd.concat([out, fill]).drop_duplicates(subset=["repo_full_name", "pr_number"])
    return out.sort_values(["has_bc", "ecosystem", "version_bump_type"], ascending=[False, True, True]).reset_index(drop=True)


def main():
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(ANALYSIS_PATH)
    df["analyzed_ok"] = df["analyzed_ok"].astype(bool)
    excluded_n = int((~df["analyzed_ok"]).sum())
    df = df[df["analyzed_ok"]].copy()

    target_n = min(100, len(df))
    sample = sample_stratified(df, target_n=target_n, seed=42)
    sample["manual_bc_label"] = ""
    sample["manual_bc_confidence"] = ""
    sample["manual_bc_notes"] = ""
    sample["manual_validation_status"] = "pending"
    keep_cols = [
        "repo_full_name",
        "pr_number",
        "ecosystem",
        "dependency_name",
        "old_version",
        "new_version",
        "version_bump_type",
        "has_bc",
        "bc_types",
        "bc_count",
        "tool_used",
        "cvss_score",
        "severity",
        "repo_stars",
        "manual_bc_label",
        "manual_bc_confidence",
        "manual_bc_notes",
        "manual_validation_status",
    ]
    sample[keep_cols].to_csv(VALIDATION_DIR / "bc_validation_sample_corrected.csv", index=False)

    protocol = f"""# BC Validation Protocol (corrected)

This package supports manual adjudication of the BC detector.

**This sample is drawn only from PRs where BC detection genuinely executed**
(`analyzed_ok == True` in data/analysis_dataset_corrected.csv — no
`analysis_error`, and a detection tool actually ran). {excluded_n} rows where
detection never ran (missing dependency coordinates, failed jar/pip install,
etc.) were excluded from the sampling frame entirely rather than being mixed
in as if they were detector negatives. See results/rq1_tables_corrected.csv
for the pipeline coverage rate this implies.

## Goal
Validate whether the detector outcome for each sampled PR reflects a real public API breaking change.

## Instructions
1. Open the dependency release diff or compare old/new public API.
2. Judge whether a consumer-visible breaking change exists.
3. Fill these columns in `bc_validation_sample_corrected.csv`:
   - `manual_bc_label`: `bc`, `no_bc`, or `unclear`
   - `manual_bc_confidence`: `high`, `medium`, or `low`
   - `manual_bc_notes`: short rationale
   - `manual_validation_status`: `done`

## Recommended adjudication criteria
- Mark `bc` for removed public methods, removed types, changed signatures, removed fields, or incompatible abstract API changes.
- Mark `no_bc` for purely additive or internal changes.
- Mark `unclear` when the release artifact or API surface cannot be confidently interpreted.

## Suggested reporting
- Precision on detector-positive cases
- False-positive taxonomy
- False-negative taxonomy on sampled detector-negative cases
"""
    (VALIDATION_DIR / "VALIDATION_PROTOCOL.md").write_text(protocol, encoding="utf-8")

    summary = {
        "sample_size": int(len(sample)),
        "excluded_not_analyzed_ok": excluded_n,
        "positives_in_sample": int(sample["has_bc"].sum()),
        "ecosystem_mix": {k: int(v) for k, v in sample["ecosystem"].value_counts().to_dict().items()},
        "bump_mix": {k: int(v) for k, v in sample["version_bump_type"].value_counts().to_dict().items()},
    }
    (VALIDATION_DIR / "validation_sample_summary_corrected.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"[DONE] create_validation_package_corrected — {len(sample)} records processed, {len(sample)} changed")


if __name__ == "__main__":
    main()
