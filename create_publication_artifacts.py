import json
from pathlib import Path

import pandas as pd

from pipeline_utils import DATA_DIR, RESULTS_DIR


def main():
    pub_dir = RESULTS_DIR / "publication"
    pub_dir.mkdir(parents=True, exist_ok=True)

    dataset = pd.read_csv(DATA_DIR / "analysis_dataset.csv")
    rq2 = pd.read_csv(RESULTS_DIR / "rq2_model_results.csv").sort_values("auc_roc", ascending=False)
    rq3 = pd.read_csv(RESULTS_DIR / "rq3_tables.csv")
    flow = json.loads((RESULTS_DIR / "cohort" / "cohort_flow.json").read_text(encoding="utf-8"))

    java_only = dataset[dataset["ecosystem"] == "maven"].copy()
    py_only = dataset[dataset["ecosystem"] == "pypi"].copy()

    summary = {
        "final_dataset_rows": int(len(dataset)),
        "final_repositories": int(dataset["repo_full_name"].nunique()),
        "java_rows": int(len(java_only)),
        "python_rows": int(len(py_only)),
        "overall_bc_prevalence": float(dataset["has_bc"].mean()),
        "java_bc_prevalence": float(java_only["has_bc"].mean()) if len(java_only) else None,
        "python_bc_prevalence": float(py_only["has_bc"].mean()) if len(py_only) else None,
        "rq2_best_model": rq2.iloc[0]["model"],
        "rq2_best_auc": float(rq2.iloc[0]["auc_roc"]),
        "flow": flow,
    }
    (pub_dir / "study_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    gap = """# TSE Gap Checklist

## Completed in this repo
- Frozen cohort manifest with deduplication accounting
- Final analysis dataset
- Leakage-safe RQ2 model rerun
- RQ3 follow-up dataset and tables
- Validation sample package for manual detector adjudication

## Remaining before a serious TSE submission
- Complete manual validation of the BC sample
- Either strengthen Python BC detection or narrow the paper to Java-only claims
- Expand related work substantially
- Add confidence intervals / uncertainty reporting to predictive modeling
- Add detector error analysis to the manuscript
- Strengthen RQ3 heuristics or validate them manually
"""
    (pub_dir / "TSE_GAP_CHECKLIST.md").write_text(gap, encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
