# BC Validation Protocol

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
