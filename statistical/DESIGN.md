# Statistical Evidence Layer — V1 design

## Purpose and scope

The layer answers one bounded question: **how unusual is an observed approved numerical response within its assigned comparable population?** It emits auditable statistical evidence, never an error/fraud/fabrication/invalidity judgment. It implements robust quantiles, empirical percentile position, MAD-based deviation, a transparent tail-position description, and a separately scoped 2023–24 linked revisit-change comparison.

It does not implement contextual/probabilistic response models, ML, duplicate detection, FSU/pattern/temporal monitoring, weight-based influence, evidence fusion, prioritisation, review workflow, automatic correction, or error classification.

## Inputs and peer dependency

Required inputs are one prepared-person Parquet file plus the matching immutable peer-group run's `peer_group_assignments.parquet`, `peer_group_references.parquet`, and metadata. Provenance must agree on release, observation route, design period, and preprocessing run ID.

The peer-group engine remains the only component that decides comparability, group dimensions, backoff, and minimum reference size. The statistical layer consumes the assigned group ID and reference definition. It materializes each reference group's members from that definition only because assignment rows can be assigned at a more detailed backoff level than a group of which they are nevertheless a reference member. The reconstructed membership count must exactly equal `peer_group_size`; otherwise the run fails rather than silently calculating against another population.

No global, cross-release, cross-route, or cross-month fallback exists. The peer definition retains release, observation, design period, visit and, in post-2025, month; therefore the January 2025 structural break and monthly boundary are preserved.

## Questionnaire applicability (V1.1)

A PLFS item is only asked of persons whose current weekly status routes to it (``survey_rules/plfs.py``): salaried earnings (Block 6 item 9, *preceding calendar month*) for status 31/71/72 (Vol. I §3.6.17); self-employment earnings (item 10, *last 30 days*) for 11/12/61/62, with helpers (21) zero by definition (§1.5.26(g), §3.6.18); day-7 hours for worker statuses 11-72. The delivered CSVs store 0 for persons the item does not apply to (verified: no non-applicable person has a non-zero value in any release). V1.0 treated those placeholders as reported values, so 88.8% of salaried "assessable" values were structural zeros (audit C1/M4). V1.1 keeps them in the output with `target_applicability` and marks them `NOT_ASSESSABLE` (`TARGET_NOT_APPLICABLE_FOR_CWS_STATUS` / `TARGET_ZERO_BY_DEFINITION_FOR_CWS_STATUS`). Comparison groups are unchanged: every group already conditions on activity status, so the reference distribution of an applicable value never contained placeholders. A genuine applicable 0 (no salaried work in the reference month, §3.6.19) remains assessable. Linked revisit changes are assessable only when the item applies at both visits.

## Targets and missingness

V1 contains exactly `cws_earnings_salaried`, `cws_earnings_self_employed`, and `day7_total_hours`. A blank, nonnumeric, non-finite, unavailable, not-ready, or peer-not-assessable response remains in the output as `NOT_ASSESSABLE`, with a reason. It is not imputed, zero-filled, or dropped.

Zero and negative responses are valid numerical values. In particular, self-employed earnings retain negative values exactly as supplied: there is no clipping, log transform, or special negative-value conclusion.

## Established methodology and implementation conventions

The established V1 methodology is robust peer-conditioned position and deviation, not a primary ordinary z-score. Its implementation conventions are recorded below for reproducibility:

- Quantiles use linear interpolation (`q=.05, .25, .50, .75, .95` by default). These supply the peer median and the central/tail reference range.
- Percentile position is the empirical mid-distribution position, including the observation: `(number below x + 0.5 × number equal to x) / n`. All tied values therefore receive one identical, row-order-independent percentile.
- `MAD = median(|x_i − median(x)|)` inside the assigned peer distribution.
- When `MAD > 0`, robust deviation is `0.6744897501960817 × (x − median) / MAD`; the constant makes it normal-consistent only as a scale convention, not as a normality assumption.
- If `MAD = 0` and `x = median`, robust deviation is `0` with status `ZERO_MAD_AT_MEDIAN`. If `MAD = 0` and `x != median`, it is explicitly null with status `ZERO_MAD_DEVIATION_NOT_NUMERIC`. No hidden epsilon or divide-by-zero substitute is used.
- `LOWER_TAIL`, `CENTRAL_REFERENCE_RANGE`, and `UPPER_TAIL` describe placement relative to configurable working quantiles. Tail percentile distances remain continuous; no binary error threshold or combined score is created.

The tail quantiles and the linked-change minimum group size are configurable research parameters, versioned in run metadata. They are not established optimal thresholds and are not translated into claims about probability of error.

## Revisit methodology

Only Release 1 (2023–24) can produce linked evidence with supplied data. The linkage is the documented exact person identity excluding quarter and visit: state, district, sector, FSU, hamlet/sub-block, second-stage stratum, household, and person serial. It intentionally recovers only in-file Visit-1 parents. Unmatched revisits are recorded as `NO_VALID_LINKED_FIRST_VISIT`; this is expected for Panel-III carry-over records, not a quality conclusion.

For a valid pair the companion table retains first/revisit values, signed and absolute change, relative change when the first value is nonzero, change direction, linkage reference, and assessability. Change unusualness is compared only among valid linked changes in the same target, revisit round and existing revisit peer group, and only when that linked-change population reaches the configurable minimum. A zero baseline makes relative change mathematically undefined and explicitly null. Day-7 total hours has no revisit target and is marked unavailable; no synthetic comparison is made. Calendar-2024 and 2025 first-visit runs do not produce a revisit table unless future valid data is supplied and a separate approved profile is added.

## Evidence schema and traceability

`statistical_evidence.parquet` preserves peer assignment provenance and adds observed raw/numeric value, statistical assessability/reason, percentile and quantile conventions, computed peer group size, quantiles, median, MAD, robust deviation/status, signed/absolute median distance, distribution position, and continuous lower/upper tail percentile distances. It also records the statistical method version. The run metadata records statistical run ID, UTC time, preprocessing and peer run references, peer specification version, parameters and output file names.

The separate revisit table contains all revisit assignments and adds linkage, both values, changes, relative-change status, change-reference-group ID, change distribution evidence, and explicit non-assessability states.

## Limitations and future research

This is unweighted response unusualness, not design-based influence. Robust univariate evidence does not establish correctness and does not explain a value. A zero-MAD group cannot yield a finite robust deviation for a distinct value; that limitation is visible rather than masked. Revisit evidence is urban/panel-coverage limited and does not prove identity beyond the documented key. Conditional multivariate methods, calibration, evaluated decision thresholds, contextual models, and evidence fusion are future work requiring separate methodology and validation.
