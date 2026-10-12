# Fusion V1 validation report

## Technical checks

The automated suite covers calibration direction/ties/constant scores/NaN/inf, missing-source reweighting, extreme-source override, formula separation of risk and influence, unavailable influence, configuration checks, and append-only review/audit status behaviour. The real-data Fusion execution report is written into each immutable `fusion/runs/<run>/fusion_report.md` after a run.

## Interpretation boundary

Passing software tests verifies deterministic code paths and provenance safeguards. It does **not** establish PLFS error-detection accuracy, probability calibration, scientific optimality of the default weights or thresholds, or effectiveness of the proposed influence proxy. Those require confirmed supervisory outcomes, approved error-injection studies and estimator-level methodology review.
