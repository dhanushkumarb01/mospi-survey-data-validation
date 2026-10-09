# PLFS V1 contextual / probabilistic design

## Current method: `plfs-contextual-v2.1`

The decision score is `coding_tail_p`: the share of the comparison group (the existing day-7 reference group, the person included) whose occupation code is at most as frequent as the person's — the conformal p-value with code frequency as the score, valid under exchangeability, smallest value 1/N. It depends on the code's *frequency*, not on the group's size, and a code seen once where many codes are seen once is not surprising. A leave-one-out Dirichlet variant (v2.0) was tried first and rejected before release: on the 2024 data it put 1.6% of records below 0.001 because leave-one-out treats every singleton as unseen (audit M1: raw surprisal grew with group size; tested by `test_coding_tail_probability_depends_on_frequency_not_group_size`). The coding lane has its own small share of the review budget and is no longer averaged into value evidence. Surprisal is still written for the A0 baseline. Not evaluated.

## Central question and boundary

The implemented question is: **how often does this observed occupation response occur among comparable prepared observations?** This is contextual evidence, not a conclusion about correctness. `statistical/` measures the placement of a numeric response within its peer distribution; this package estimates an empirical conditional category frequency for one categorical response.

It never makes an error-likelihood claim, anomaly label, risk score, priority, correction, survey-weighted estimate, or numerical contextual model.

## Implemented target and context

The sole V1 behavioural target is `principal_occupation_code`, the supplied three-digit principal occupation code:

| Release | Source column |
|---|---|
| 2023–24 first visit | `b5pt1q6_perv1` |
| 2024 first visit | `Principal_Occupation_Code` |
| 2025 first visit | `ocu_pas` |

The context is not re-created here. For each source observation, the layer uses its existing `day7_total_hours` peer-group assignment and its selected backoff level. The applicable existing `hours_first_visit` profiles are:

1. state + sector + CWS status + supplied industry division;
2. state + sector + CWS status.

The existing peer definition also retains release, observation, design period, visit, and calendar month for post-2025 data. Thus 2023–24, 2024 and 2025 are not pooled; 2025 months are not pooled; and no FSU or survey weight is used. Occupation is checked to be absent from the reference dimensions before any result is made, preventing target leakage.

The chosen reference is the actual membership of the existing day7-hours assignment. Its `peer_group_size` is retained as `context_reference_population_count`. The frequency denominator `reference_count` is the subset with a valid observed three-digit occupation code, because the prepared files have no field-level occupation applicability mask and blank codes cannot safely be assigned to a behavioural category.

## Conditional frequency, hierarchy and surprisal

For an assessed observation with detailed code `c` and existing context `g`:

`conditional_frequency = count(c in g with a valid three-digit occupation code) / reference_count(g)`.

The evidence includes the detailed three-digit code, its supplied natural one-digit parent, the parent count and parent frequency. This preserves the available hierarchy without inventing an NCO mapping or converting a rare detailed code into an error conclusion.

`surprisal = -ln(conditional_frequency)` uses the natural logarithm. There is no smoothing or shrinkage. A non-positive frequency has no finite surprisal; it remains unassessable rather than being replaced with a fabricated value. For any assessed row the empirical count includes the observed row, so the stored frequency is positive.

The human-readable evidence is generated directly from stored counts:

`This response occurs in X of Y comparable observations with a valid three-digit occupation code.`

## Sparse, missing and applicability treatment

The existing reference membership is already subject to the peer engine's minimum group size and selected backoff. V1 applies that same configured minimum to `reference_count`; a smaller valid-occupation population is `NOT_ASSESSABLE` with `INSUFFICIENT_REFERENCE_SIZE`. A zero valid-occupation population is `ZERO_REFERENCE_SUPPORT`.

Only a nonblank, three-digit code is eligible. Blank codes are `TARGET_MISSING_OR_NOT_APPLICABILITY_UNRESOLVED`, because preprocessing does not establish whether a blank occupation is structurally not applicable or missing when expected. They are never scored as rare. Non-three-digit, nonblank values are `INVALID_CATEGORICAL_TARGET`. Missing mandatory existing context (state, sector or CWS status) is `MISSING_CONTEXT`; an unavailable or unassigned existing peer population retains an explicit peer reason.

## Explicitly not implemented

No continuous/numerical contextual model is implemented. The prepared schema and current peer configuration safely support the categorical method above, but a conditional earnings/hours model would require a separately approved conditional model and validation beyond the existing statistical percentile, median and MAD evidence. V1 also excludes raw occupation-code hierarchy maps beyond the observed three-digit/first-digit structure, hierarchical shrinkage, revisit occupation evidence, activity-status targets, ML, fusion, influence, priority or supervisor workflow.

## Reproducibility and provenance

The engine requires adjacent preprocessing and peer-run metadata to agree on release, observation, design period and preprocessing run ID. It rejects a missing assignment/reference table, mismatched provenance, duplicate source IDs, absent issued peer definitions, reference-size reconciliation failures, and a reference definition containing the occupation target. It sorts the final evidence by source observation ID and stores source and peer provenance, the issued grouping definition, selected backoff and method version.
