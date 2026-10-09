# Integrity rules

## Current rule facility (October 2026)

* 13 rule types: `allowed_values`, `range`, `required_when`, `absent_when`, `value_when`, `not_value_when`, `unique`, `arithmetic`, `lower_bound_sum`, `exists_exactly`, `count_matches`, `references`, `within_period`; person and household level (cross-level aggregates such as persons listed and heads per household).
* Mandatory metadata: version, level, severity, citation, owner, approval status, ≥ 1 violating and ≥ 1 passing test case. Test cases run on every load; a failing rule is refused.
* Every batch writes `rule_dry_run.json` (all rules, active or not). Approved hard rules show 0 violations on all three stored releases. The district referential rule applies to 2025 only: the supplied pre-2025 list predates 54 district codes used in 2024.
* Only approved, active rules produce findings. Soft rules (`S01`, `S02`) are drafts until HSD approves them. There is no rule-authoring UI yet (rules are edited as YAML and reviewed in version control).

`python -m integrity.engine --prepared-persons <prepared_persons.parquet> --output-root integrity/runs --run-id v2`

Rules are plain YAML in `rules/plfs_person_rules.yaml`. Each refers to survey **concepts** (age, cws_status, earnings_salaried, earnings_self_employed, day7_hours, record_key, person_serial), mapped per release from the existing documented contracts, and must cite its documentary source — a rule without a source is rejected. Rule types: `allowed_values`, `range`, `required_when`, `value_when`, `not_value_when`, `unique`. A rule whose concept is not collected in a release is skipped (not "passed").

The bundled PLFS rules come only from the supplied documents (code list for Block 6 item 5 including "99 for persons age < 5"; Vol. I §1.5.26(g), §3.6.9, §3.6.17–3.6.18; README primary keys). On the real 2023-24, 2024 and 2025 deliveries they find no violations: these rules are already enforced in CAPI. They serve as the deterministic E0 baseline and as the place where HSD can add further documented checks without code changes. The same engine powers `POST /api/validate/record` (one record, nothing stored). No value is ever changed.
