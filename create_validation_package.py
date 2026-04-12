import json
import random
from pathlib import Path

import pandas as pd

from pipeline_utils import DATA_DIR, RESULTS_DIR, load_jsonl


ANALYSIS_PATH = DATA_DIR / "analysis_dataset.csv"
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
    sample = sample_stratified(df, target_n=100, seed=42)
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
    sample[keep_cols].to_csv(VALIDATION_DIR / "bc_validation_sample.csv", index=False)

    protocol = """# BC Validation Protocol

This package supports manual adjudication of the BC detector.

## Goal
Validate whether the detector outcome for each sampled PR reflects a real public API breaking change.

## Instructions
1. Open the dependency release diff or compare old/new public API.
2. Judge whether a consumer-visible breaking change exists.
3. Fill these columns in `bc_validation_sample.csv`:
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
        "positives_in_sample": int(sample["has_bc"].sum()),
        "ecosystem_mix": {k: int(v) for k, v in sample["ecosystem"].value_counts().to_dict().items()},
        "bump_mix": {k: int(v) for k, v in sample["version_bump_type"].value_counts().to_dict().items()},
    }
    (VALIDATION_DIR / "validation_sample_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
