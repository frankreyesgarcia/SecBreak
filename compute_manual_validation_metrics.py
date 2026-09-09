"""Precision / recall / F1 for the manual BC-detector validation.

Reads results/manual_validation_sheet.csv, uses only the rows a human has put a
`label` in (TP / FP / FN / TN / unsure), and writes
results/manual_validation_metrics.json.

Safe to run on a partially-labeled sheet: blank `label` cells are skipped, and
with fewer than MIN_LABELED labeled rows it still runs and reports
`gate_met: false` rather than erroring.

`unsure` rows are counted and reported separately -- never folded into
TP/FP/FN/TN. Rows whose label contradicts the detector's own verdict (e.g.
detector said no-BC but label is TP) are listed under `inconsistent_rows` and
excluded from the confusion matrix.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
# Optional argv[1] overrides the sheet path (used by the test harness); the
# metrics JSON is written next to whichever sheet is read.
SHEET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "results/manual_validation_sheet.csv"
OUT = SHEET.with_name(SHEET.stem.replace("_sheet", "") + "_metrics.json")
MIN_LABELED = 20

VALID = {"TP", "FP", "FN", "TN", "UNSURE"}
POS_VERDICT_LABELS = {"TP", "FP", "UNSURE"}   # detector said "BC"
NEG_VERDICT_LABELS = {"FN", "TN", "UNSURE"}   # detector said "no-BC"

Z = 1.959963984540054  # 95%


def wilson_ci(k: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt((p * (1 - p) + Z * Z / (4 * n)) / n) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def block(sub: pd.DataFrame) -> dict:
    """Metrics for one slice of labeled rows (labels already normalised)."""
    counts = {lab: int((sub["label_norm"] == lab).sum()) for lab in ("TP", "FP", "FN", "TN", "UNSURE")}
    tp, fp, fn, tn = counts["TP"], counts["FP"], counts["FN"], counts["TN"]
    prec_n, rec_n = tp + fp, tp + fn
    scored = tp + fp + fn + tn
    precision = _rate(tp, prec_n)
    recall = _rate(tp, rec_n)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision and recall and (precision + recall) > 0
        else None
    )
    return {
        "labeled": int(len(sub)),
        "scored": scored,               # TP+FP+FN+TN (excludes unsure)
        "unsure": counts["UNSURE"],
        "confusion": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "precision": precision,
        "precision_ci95": wilson_ci(tp, prec_n),
        "recall": recall,
        "recall_ci95": wilson_ci(tp, rec_n),
        "f1": f1,
        "accuracy": _rate(tp + tn, scored),
    }


def main() -> None:
    if not SHEET.exists():
        raise SystemExit(f"sheet not found: {SHEET} (run build_manual_validation_sheet.py first)")

    df = pd.read_csv(SHEET, dtype=str).fillna("")
    df["label_norm"] = df["label"].str.strip().str.upper()

    total = len(df)
    labeled = df[df["label_norm"] != ""].copy()

    unrecognised = sorted(
        {v for v in labeled["label_norm"].unique() if v not in VALID}
    )
    labeled = labeled[labeled["label_norm"].isin(VALID)].copy()

    # detector verdict vs label class
    def consistent(row) -> bool:
        allowed = POS_VERDICT_LABELS if row["detector_verdict"] == "BC" else NEG_VERDICT_LABELS
        return row["label_norm"] in allowed

    if len(labeled):
        labeled["_ok"] = labeled.apply(consistent, axis=1)
    else:
        labeled["_ok"] = pd.Series(dtype=bool)
    inconsistent = labeled[~labeled["_ok"].astype(bool)]
    scored_rows = labeled[labeled["_ok"].astype(bool)].copy()

    try:
        sheet_label = str(SHEET.relative_to(ROOT))
    except ValueError:
        sheet_label = str(SHEET)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sheet": sheet_label,
        "total_rows": total,
        "labeled_rows": int(len(labeled)),
        "unlabeled_rows": int(total - len(labeled)),
        "label_counts": {
            lab: int((labeled["label_norm"] == lab).sum())
            for lab in ("TP", "FP", "FN", "TN", "UNSURE")
        },
        "unrecognised_labels": unrecognised,
        "inconsistent_rows": [
            {
                "pr_id": r["pr_id"],
                "detector_verdict": r["detector_verdict"],
                "label": r["label_norm"],
            }
            for _, r in inconsistent.iterrows()
        ],
        "gate_min_labeled": MIN_LABELED,
        "gate_met": bool(len(labeled) >= MIN_LABELED),
        "overall": block(scored_rows),
        "by_detector": {
            det: block(scored_rows[scored_rows["detector"] == det])
            for det in ("roseau", "griffe")
        },
    }

    OUT.write_text(json.dumps(result, indent=2) + "\n")

    # ---- console summary ----
    print(f"{result['labeled_rows']}/{total} rows adjudicated"
          f"  (gate: >= {MIN_LABELED} -> {'MET' if result['gate_met'] else 'not met'})")
    lc = result["label_counts"]
    print(f"  labels: TP={lc['TP']} FP={lc['FP']} FN={lc['FN']} TN={lc['TN']} unsure={lc['UNSURE']}")
    if unrecognised:
        print(f"  !! unrecognised labels ignored: {unrecognised}")
    if result["inconsistent_rows"]:
        print(f"  !! {len(result['inconsistent_rows'])} row(s) with label vs detector_verdict mismatch "
              f"(excluded): {[r['pr_id'] for r in result['inconsistent_rows']]}")
    for name in ("overall", "roseau", "griffe"):
        b = result["overall"] if name == "overall" else result["by_detector"][name]
        if b["scored"] == 0:
            print(f"  {name:8s}: no scored rows yet")
            continue
        c = b["confusion"]
        print(f"  {name:8s}: TP{c['TP']} FP{c['FP']} FN{c['FN']} TN{c['TN']}  "
              f"P={b['precision']} {b['precision_ci95']}  "
              f"R={b['recall']} {b['recall_ci95']}  F1={b['f1']}")
    try:
        print(f"wrote {OUT.relative_to(ROOT)}")
    except ValueError:
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
