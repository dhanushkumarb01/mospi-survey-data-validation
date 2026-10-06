# Pattern V1 implementation validation report

## Implementation review

The implementation was reviewed against the existing preparation, peer-group, Statistical, Contextual and ML modules; their configurations, engines, CLI/reporting conventions, tests, metadata and actual Parquet schemas were inspected. Pattern uses the same prepared-data provenance contract and release-specific source mappings.

One documentation/code discrepancy was found in the supplied project material: the broader research design describes a future post-2025 panel/revisit capability, while the current supplied prepared delivery and existing configured profiles contain only 2025 first visit. Pattern follows the operational code/data truth and emits no synthetic 2025 revisit evidence.

## Automated software tests

`python -m pytest -q` passed **39 tests** after adding eight Pattern tests. Coverage includes schema/unique IDs/determinism, shifted and small FSU distributions, reduced spread including zero IQR, controlled digit heaping and categorical exclusion, post-2025 month separation, temporal-history non-assessability, no-revisit behavior, and paired revisit-input validation. The suite emitted only existing third-party core-detection and pandas future warnings.

Passing these tests establishes controlled software behavior only. It is not a methodological validation or an estimate of real survey-error accuracy, precision, recall, F1, or probability.

## Real-data execution and inspection

The 2024 first-visit delivery completed at `pattern/runs/2024_first_visit_2024_first_v1/`: 415,549 prepared records, 12,749 FSU groups, 254,981 unique combined evidence rows and 573.035 seconds. All evidence IDs were unique; no assessable score was infinite; no group/reference population was negative; and the no-input revisit output was exactly one `REVISIT_DATA_UNAVAILABLE` row. Its temporal component was appropriately not assessable because the available FSU histories did not meet the configured prior-history requirement. The 2023–24 first/revisit linked run is the next release-scoped execution. The inspection procedure checks unique IDs, finite assessable scores, valid counts/rates, release/visit/design/month consistency, and lack of cross-break or fabricated revisit evidence.

## Known limitations

- No verified HSD enumerator identifier: FSU evidence is never attributed to an enumerator/interviewer.
- No supplied 2025 revisit data: no post-2025 panel evidence is produced.
- Only existing Statistical V1 linked tail-change signals are aggregated; public data/configuration do not establish an approved sex, relationship, or activity transition definition for this module.
- Temporal V1 is preceding-period, within-release and not seasonally adjusted; it marks insufficient or zero-variation history rather than making a stronger claim.
- Default minimums and distance choices are V1 research settings. They need future E0–E7/error-injection and HSD review, not claims of optimality.
