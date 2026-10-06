# Integrity rules

`python -m integrity.engine --prepared-persons <prepared_persons.parquet> --output-root integrity/runs --run-id v2`

Rules are plain YAML in `rules/plfs_person_rules.yaml`. Each refers to survey **concepts** (age, cws_status, earnings_salaried, earnings_self_employed, day7_hours, record_key, person_serial), mapped per release from the existing documented contracts, and must cite its documentary source — a rule without a source is rejected. Rule types: `allowed_values`, `range`, `required_when`, `value_when`, `not_value_when`, `unique`. A rule whose concept is not collected in a release is skipped (not "passed").

The bundled PLFS rules come only from the supplied documents (code list for Block 6 item 5 including "99 for persons age < 5"; Vol. I §1.5.26(g), §3.6.9, §3.6.17–3.6.18; README primary keys). On the real 2023-24, 2024 and 2025 deliveries they find no violations: these rules are already enforced in CAPI. They serve as the deterministic E0 baseline and as the place where HSD can add further documented checks without code changes. The same engine powers `POST /api/validate/record` (one record, nothing stored). No value is ever changed.
