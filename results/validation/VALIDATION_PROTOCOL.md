# BC Validation Protocol (corrected)

This package supports manual adjudication of the BC detector.

**This sample is drawn only from PRs where BC detection genuinely executed**
(`analyzed_ok == True` in data/analysis_dataset_corrected.csv — no
`analysis_error`, and a detection tool actually ran). 403 rows where
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
