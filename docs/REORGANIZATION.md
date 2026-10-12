# Repository reorganization (V2.2, no behaviour change)

The repository was reorganized from a flat set of top-level stage folders into one package (`mospi/`) with separate `tests/`, `data/` and `docs/`. No validation algorithm, statistic, model, score, queue order, schema, dataset contract or review logic was changed. The stored data, runs, audit databases and result files were moved without modification; this was checked file by file (size, modification time, and SHA-256 for every file under 8 MB and every audit database).

## Later change: Supabase hosting (12 Oct 2026)

Added `mospi/db/serving.py` (hosted serving set), migration `mospi/db/migrations/0004_hosted_serving.sql`,
`deploy/supabase/prod-ca-2021.crt` (public CA), `tests/postgres/test_supabase_hosted.py` and `.env.example`. Removed the
Cloudflare Tunnel / signed-gateway path and the laptop's remote-access tooling: `mospi/gateway/`, `mospi/db/remote_access.py`,
`deploy/cloudflare/`, `deploy/postgres/`, `docs/deployment/CLOUDFLARE_TUNNEL.md`, `tests/app/test_gateway.py`,
`tests/postgres/test_gateway_postgres.py`. See docs/deployment/POSTGRESQL.md.

## Old to new

| Before | After |
|---|---|
| `survey_rules/` | `mospi/survey_rules/` |
| `preprocessing/ integrity/ peer_groups/ statistical/ contextual/ ml/ pattern/ historical/` | `mospi/pipeline/stages/<stage>/` (`integrity/rules/*.yaml` and `historical/known_events.yaml` moved unchanged with their packages) |
| `fusion/` (engine, lanes, calibration, review, ...) | `mospi/pipeline/stages/fusion/` |
| `fusion/api.py`, `serve.py`, `vercel_app.py`, `ui/` | `mospi/app/` |
| `pipeline/run.py jobs.py qa.py` | `mospi/pipeline/` |
| `evaluation/run.py inject.py metrics.py` | `mospi/evaluation/` |
| `<package>/tests/` | `tests/stages/<stage>/`, `tests/fusion/`, `tests/app/` (`test_deployment`, `test_ui_contract`), `tests/pipeline/`, `tests/evaluation/` |
| `pipeline/tests/synthetic.py` | `tests/synthetic.py` |
| `<stage>/runs/` (all stages, git-ignored) | `data/<stage>/runs/` |
| `pipeline/runs`, `pipeline/jobs`, `pipeline/logs` | `data/pipeline/...` |
| `evaluation/runs`, `evaluation/logs` | `data/evaluation/...` |
| `evaluation/results/` | `data/evaluation/results/` |
| `2023-June2024/ Jan-Dec2024/ Post2025/` | `data/raw/...` |
| `demo-data/` | `data/demo/` |
| `EDA/` | `notebooks/` |
| per-stage `README.md DESIGN.md VALIDATION_REPORT.md`, `evaluation/PROTOCOL.md README.md` | `docs/stages/<stage>/`, `docs/evaluation/` |
| `AUDIT_2026-10-03.md`, `docs/*.md`, `PLFS_*.md` | `docs/{specification,deployment,audits,research}/` |

Import names changed accordingly: `from ml.engine import ...` is now `from mospi.pipeline.stages.ml.engine import ...`; `fusion.api`, `fusion.serve` and `fusion.vercel_app` are `mospi.app.*`; `pipeline.*` is `mospi.pipeline.*`; `survey_rules` is `mospi.survey_rules`; `evaluation.*` is `mospi.evaluation.*`. Commands: `python -m mospi.pipeline.run`, `python -m mospi.evaluation.run`, `python -m mospi.app.serve`.

## What the code resolves through `mospi/paths.py`

The data root (`data/`, or `MOSPI_DATA_DIR`) replaces "the current directory is the repository root". It is used by the pipeline presets and reports, the evaluation presets, results and `--verify` (stored artefact paths such as `evaluation\runs\protocol_v1\...` are read relative to it), the server defaults, `scripts/export_serving_data.py` (`--project-root`) and the district-code workbooks under `data/raw/`. Dataset contracts (`preprocessing/config.py`) still name raw files relative to an input root; pass `--input-root data/raw`.

## Not rewritten on purpose

* Dated documents (`docs/audits/`, `docs/specification/`, validation reports) keep the paths they were written with.
* Stored records are historical text and were not edited: `data/pipeline/jobs/*.json` and `data/pipeline/runs/*.json` hold the old absolute or repository-relative paths of the time; `data/demo/SERVING_DATA_MANIFEST.json` names `pipeline/tests/synthetic.py` as its generator (now `tests/synthetic.py`); stored evaluation results hold `evaluation\runs\...` artefact paths.
* `implementation_plan.md` (untracked, at the repository root) still uses the old paths.
* The integrity rule files and `known_events.yaml` are unmodified (an integrity run records a SHA-256 of the rule files).

## Deleted (regenerable only)

`__pycache__/` folders (27, holding 178 `.pyc` files), `.pytest_cache/`, and `survey_rules/tests/` (it contained only a stale `__pycache__`; the `test_schema.py` source exists only on branch `backup/v3-snapshot-2026-10-08`).

## Rolling back

Nothing was committed. To undo: move `data/<stage>/runs`, `data/pipeline/*`, `data/evaluation/{runs,logs}`, `data/raw/*` and `notebooks/*` back to the "Before" locations above; run `git reset` and `git restore .` to return tracked files to `HEAD` (the tracked moves are listed below); then remove the new untracked files (`mospi/__init__.py`, `mospi/paths.py`, the new `__init__.py` files, `docs/README.md`, `docs/REORGANIZATION.md`, `data/README.md`).

## Tracked file moves

| Before | After |
|---|---|
| `AUDIT_2026-10-03.md` | `docs/audits/AUDIT_2026-10-03.md` |
| `PLFS_Data_Research_Foundation.md` | `docs/research/PLFS_Data_Research_Foundation.md` |
| `PLFS_Low_Level_Architecture_and_Research_Desig.md` | `docs/research/PLFS_Low_Level_Architecture_and_Research_Desig.md` |
| `contextual/DESIGN.md` | `docs/stages/contextual/DESIGN.md` |
| `contextual/README.md` | `docs/stages/contextual/README.md` |
| `contextual/__init__.py` | `mospi/pipeline/stages/contextual/__init__.py` |
| `contextual/cli.py` | `mospi/pipeline/stages/contextual/cli.py` |
| `contextual/config.py` | `mospi/pipeline/stages/contextual/config.py` |
| `contextual/engine.py` | `mospi/pipeline/stages/contextual/engine.py` |
| `contextual/reporting.py` | `mospi/pipeline/stages/contextual/reporting.py` |
| `contextual/tests/__init__.py` | `tests/stages/contextual/__init__.py` |
| `contextual/tests/test_engine.py` | `tests/stages/contextual/test_engine.py` |
| `demo-data/SERVING_DATA_MANIFEST.json` | `data/demo/SERVING_DATA_MANIFEST.json` |
| `demo-data/contextual/runs/2024_first_visit_demo/contextual_evidence.parquet` | `data/demo/contextual/runs/2024_first_visit_demo/contextual_evidence.parquet` |
| `demo-data/contextual/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/contextual/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/fusion/runs/2024_first_visit_demo/evidence_cards.parquet` | `data/demo/fusion/runs/2024_first_visit_demo/evidence_cards.parquet` |
| `demo-data/fusion/runs/2024_first_visit_demo/fused_cases.parquet` | `data/demo/fusion/runs/2024_first_visit_demo/fused_cases.parquet` |
| `demo-data/fusion/runs/2024_first_visit_demo/fusion_report.json` | `data/demo/fusion/runs/2024_first_visit_demo/fusion_report.json` |
| `demo-data/fusion/runs/2024_first_visit_demo/fusion_report.md` | `data/demo/fusion/runs/2024_first_visit_demo/fusion_report.md` |
| `demo-data/fusion/runs/2024_first_visit_demo/group_priorities.parquet` | `data/demo/fusion/runs/2024_first_visit_demo/group_priorities.parquet` |
| `demo-data/fusion/runs/2024_first_visit_demo/impact_domains.parquet` | `data/demo/fusion/runs/2024_first_visit_demo/impact_domains.parquet` |
| `demo-data/fusion/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/fusion/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/fusion/runs/2024_first_visit_demo/value_evidence.parquet` | `data/demo/fusion/runs/2024_first_visit_demo/value_evidence.parquet` |
| `demo-data/historical/runs/2024_first_visit_demo/aggregate_indicators.parquet` | `data/demo/historical/runs/2024_first_visit_demo/aggregate_indicators.parquet` |
| `demo-data/historical/runs/2024_first_visit_demo/historical_record_evidence.parquet` | `data/demo/historical/runs/2024_first_visit_demo/historical_record_evidence.parquet` |
| `demo-data/historical/runs/2024_first_visit_demo/historical_report.json` | `data/demo/historical/runs/2024_first_visit_demo/historical_report.json` |
| `demo-data/historical/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/historical/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/integrity/runs/2024_first_visit_demo/integrity_report.json` | `data/demo/integrity/runs/2024_first_visit_demo/integrity_report.json` |
| `demo-data/integrity/runs/2024_first_visit_demo/integrity_violations.parquet` | `data/demo/integrity/runs/2024_first_visit_demo/integrity_violations.parquet` |
| `demo-data/integrity/runs/2024_first_visit_demo/rule_dry_run.json` | `data/demo/integrity/runs/2024_first_visit_demo/rule_dry_run.json` |
| `demo-data/integrity/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/integrity/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/ml/runs/2024_first_visit_demo/conditional_model_evidence.parquet` | `data/demo/ml/runs/2024_first_visit_demo/conditional_model_evidence.parquet` |
| `demo-data/ml/runs/2024_first_visit_demo/isolation_forest_evidence.parquet` | `data/demo/ml/runs/2024_first_visit_demo/isolation_forest_evidence.parquet` |
| `demo-data/ml/runs/2024_first_visit_demo/lof_evidence.parquet` | `data/demo/ml/runs/2024_first_visit_demo/lof_evidence.parquet` |
| `demo-data/ml/runs/2024_first_visit_demo/ml_report.json` | `data/demo/ml/runs/2024_first_visit_demo/ml_report.json` |
| `demo-data/ml/runs/2024_first_visit_demo/model_registry.json` | `data/demo/ml/runs/2024_first_visit_demo/model_registry.json` |
| `demo-data/ml/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/ml/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/ml/runs/2024_first_visit_demo/similarity_evidence.parquet` | `data/demo/ml/runs/2024_first_visit_demo/similarity_evidence.parquet` |
| `demo-data/pattern/runs/2024_first_visit_demo/fsu_summary.parquet` | `data/demo/pattern/runs/2024_first_visit_demo/fsu_summary.parquet` |
| `demo-data/pattern/runs/2024_first_visit_demo/pattern_evidence.parquet` | `data/demo/pattern/runs/2024_first_visit_demo/pattern_evidence.parquet` |
| `demo-data/pattern/runs/2024_first_visit_demo/pattern_report.json` | `data/demo/pattern/runs/2024_first_visit_demo/pattern_report.json` |
| `demo-data/pattern/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/pattern/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/preprocessing/runs/2024_first_visit_synthetic-prep/prepared_persons.parquet` | `data/demo/preprocessing/runs/2024_first_visit_synthetic-prep/prepared_persons.parquet` |
| `demo-data/preprocessing/runs/2024_first_visit_synthetic-prep/run_metadata.json` | `data/demo/preprocessing/runs/2024_first_visit_synthetic-prep/run_metadata.json` |
| `demo-data/statistical/runs/2024_first_visit_demo/run_metadata.json` | `data/demo/statistical/runs/2024_first_visit_demo/run_metadata.json` |
| `demo-data/statistical/runs/2024_first_visit_demo/statistical_evidence.parquet` | `data/demo/statistical/runs/2024_first_visit_demo/statistical_evidence.parquet` |
| `demo-data/statistical/runs/2024_first_visit_demo/statistical_report.json` | `data/demo/statistical/runs/2024_first_visit_demo/statistical_report.json` |
| `docs/10_10_IMPROVEMENT_PLAN.md` | `docs/specification/10_10_IMPROVEMENT_PLAN.md` |
| `docs/DOCKER.md` | `docs/deployment/DOCKER.md` |
| `docs/ESIGMA_INTEGRATION_ROADMAP.md` | `docs/specification/ESIGMA_INTEGRATION_ROADMAP.md` |
| `docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md` | `docs/specification/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md` |
| `docs/UI_AUDIT_2026-10-05.md` | `docs/audits/UI_AUDIT_2026-10-05.md` |
| `docs/UI_REDESIGN_2026-10-06.md` | `docs/audits/UI_REDESIGN_2026-10-06.md` |
| `docs/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md` | `docs/specification/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md` |
| `docs/VERCEL_COMPATIBILITY_AUDIT.md` | `docs/deployment/VERCEL_COMPATIBILITY_AUDIT.md` |
| `docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md` | `docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md` |
| `evaluation/PROTOCOL.md` | `docs/evaluation/PROTOCOL.md` |
| `evaluation/README.md` | `docs/evaluation/README.md` |
| `evaluation/__init__.py` | `mospi/evaluation/__init__.py` |
| `evaluation/inject.py` | `mospi/evaluation/inject.py` |
| `evaluation/metrics.py` | `mospi/evaluation/metrics.py` |
| `evaluation/results/2024.json` | `data/evaluation/results/2024.json` |
| `evaluation/results/2025.json` | `data/evaluation/results/2025.json` |
| `evaluation/results/protocol_v1/2024_A_seed1.json` | `data/evaluation/results/protocol_v1/2024_A_seed1.json` |
| `evaluation/results/protocol_v1/2025_A_seed1.json` | `data/evaluation/results/protocol_v1/2025_A_seed1.json` |
| `evaluation/run.py` | `mospi/evaluation/run.py` |
| `evaluation/tests/__init__.py` | `tests/evaluation/__init__.py` |
| `evaluation/tests/test_inject.py` | `tests/evaluation/test_inject.py` |
| `evaluation/tests/test_metrics.py` | `tests/evaluation/test_metrics.py` |
| `fusion/DESIGN.md` | `docs/stages/fusion/DESIGN.md` |
| `fusion/README.md` | `docs/stages/fusion/README.md` |
| `fusion/VALIDATION_REPORT.md` | `docs/stages/fusion/VALIDATION_REPORT.md` |
| `fusion/__init__.py` | `mospi/pipeline/stages/fusion/__init__.py` |
| `fusion/api.py` | `mospi/app/api.py` |
| `fusion/calibration.py` | `mospi/pipeline/stages/fusion/calibration.py` |
| `fusion/cli.py` | `mospi/pipeline/stages/fusion/cli.py` |
| `fusion/config.py` | `mospi/pipeline/stages/fusion/config.py` |
| `fusion/engine.py` | `mospi/pipeline/stages/fusion/engine.py` |
| `fusion/evidence_card.py` | `mospi/pipeline/stages/fusion/evidence_card.py` |
| `fusion/explain.py` | `mospi/pipeline/stages/fusion/explain.py` |
| `fusion/feedback.py` | `mospi/pipeline/stages/fusion/feedback.py` |
| `fusion/impact.py` | `mospi/pipeline/stages/fusion/impact.py` |
| `fusion/labels.py` | `mospi/pipeline/stages/fusion/labels.py` |
| `fusion/lanes.py` | `mospi/pipeline/stages/fusion/lanes.py` |
| `fusion/legacy.py` | `mospi/pipeline/stages/fusion/legacy.py` |
| `fusion/queue.py` | `mospi/pipeline/stages/fusion/queue.py` |
| `fusion/reporting.py` | `mospi/pipeline/stages/fusion/reporting.py` |
| `fusion/review.py` | `mospi/pipeline/stages/fusion/review.py` |
| `fusion/serve.py` | `mospi/app/serve.py` |
| `fusion/story.py` | `mospi/pipeline/stages/fusion/story.py` |
| `fusion/tests/__init__.py` | `tests/fusion/__init__.py` |
| `fusion/tests/test_calibration.py` | `tests/fusion/test_calibration.py` |
| `fusion/tests/test_deployment.py` | `tests/app/test_deployment.py` |
| `fusion/tests/test_explain.py` | `tests/fusion/test_explain.py` |
| `fusion/tests/test_fusion.py` | `tests/fusion/test_fusion.py` |
| `fusion/tests/test_review.py` | `tests/fusion/test_review.py` |
| `fusion/tests/test_ui_contract.py` | `tests/app/test_ui_contract.py` |
| `fusion/ui/app.js` | `mospi/app/ui/app.js` |
| `fusion/ui/index.html` | `mospi/app/ui/index.html` |
| `fusion/ui/styles.css` | `mospi/app/ui/styles.css` |
| `fusion/vercel_app.py` | `mospi/app/vercel_app.py` |
| `historical/DESIGN.md` | `docs/stages/historical/DESIGN.md` |
| `historical/__init__.py` | `mospi/pipeline/stages/historical/__init__.py` |
| `historical/cli.py` | `mospi/pipeline/stages/historical/cli.py` |
| `historical/config.py` | `mospi/pipeline/stages/historical/config.py` |
| `historical/engine.py` | `mospi/pipeline/stages/historical/engine.py` |
| `historical/known_events.yaml` | `mospi/pipeline/stages/historical/known_events.yaml` |
| `historical/tests/__init__.py` | `tests/stages/historical/__init__.py` |
| `historical/tests/test_engine.py` | `tests/stages/historical/test_engine.py` |
| `integrity/README.md` | `docs/stages/integrity/README.md` |
| `integrity/__init__.py` | `mospi/pipeline/stages/integrity/__init__.py` |
| `integrity/engine.py` | `mospi/pipeline/stages/integrity/engine.py` |
| `integrity/rules/plfs_household_rules.yaml` | `mospi/pipeline/stages/integrity/rules/plfs_household_rules.yaml` |
| `integrity/rules/plfs_person_rules.yaml` | `mospi/pipeline/stages/integrity/rules/plfs_person_rules.yaml` |
| `integrity/tests/__init__.py` | `tests/stages/integrity/__init__.py` |
| `integrity/tests/test_engine.py` | `tests/stages/integrity/test_engine.py` |
| `ml/DESIGN.md` | `docs/stages/ml/DESIGN.md` |
| `ml/README.md` | `docs/stages/ml/README.md` |
| `ml/VALIDATION_REPORT.md` | `docs/stages/ml/VALIDATION_REPORT.md` |
| `ml/__init__.py` | `mospi/pipeline/stages/ml/__init__.py` |
| `ml/cli.py` | `mospi/pipeline/stages/ml/cli.py` |
| `ml/conditional_models.py` | `mospi/pipeline/stages/ml/conditional_models.py` |
| `ml/config.py` | `mospi/pipeline/stages/ml/config.py` |
| `ml/engine.py` | `mospi/pipeline/stages/ml/engine.py` |
| `ml/isolation_forest.py` | `mospi/pipeline/stages/ml/isolation_forest.py` |
| `ml/lof.py` | `mospi/pipeline/stages/ml/lof.py` |
| `ml/reporting.py` | `mospi/pipeline/stages/ml/reporting.py` |
| `ml/similarity.py` | `mospi/pipeline/stages/ml/similarity.py` |
| `ml/tests/__init__.py` | `tests/stages/ml/__init__.py` |
| `ml/tests/test_conditional_models.py` | `tests/stages/ml/test_conditional_models.py` |
| `ml/tests/test_engine.py` | `tests/stages/ml/test_engine.py` |
| `ml/tests/test_isolation_forest.py` | `tests/stages/ml/test_isolation_forest.py` |
| `ml/tests/test_lof.py` | `tests/stages/ml/test_lof.py` |
| `ml/tests/test_similarity.py` | `tests/stages/ml/test_similarity.py` |
| `pattern/DESIGN.md` | `docs/stages/pattern/DESIGN.md` |
| `pattern/README.md` | `docs/stages/pattern/README.md` |
| `pattern/VALIDATION_REPORT.md` | `docs/stages/pattern/VALIDATION_REPORT.md` |
| `pattern/__init__.py` | `mospi/pipeline/stages/pattern/__init__.py` |
| `pattern/cli.py` | `mospi/pipeline/stages/pattern/cli.py` |
| `pattern/config.py` | `mospi/pipeline/stages/pattern/config.py` |
| `pattern/engine.py` | `mospi/pipeline/stages/pattern/engine.py` |
| `pattern/fieldwork.py` | `mospi/pipeline/stages/pattern/fieldwork.py` |
| `pattern/reporting.py` | `mospi/pipeline/stages/pattern/reporting.py` |
| `pattern/tests/__init__.py` | `tests/stages/pattern/__init__.py` |
| `pattern/tests/test_engine.py` | `tests/stages/pattern/test_engine.py` |
| `pattern/tests/test_fieldwork.py` | `tests/stages/pattern/test_fieldwork.py` |
| `peer_groups/DESIGN.md` | `docs/stages/peer_groups/DESIGN.md` |
| `peer_groups/README.md` | `docs/stages/peer_groups/README.md` |
| `peer_groups/__init__.py` | `mospi/pipeline/stages/peer_groups/__init__.py` |
| `peer_groups/cli.py` | `mospi/pipeline/stages/peer_groups/cli.py` |
| `peer_groups/config.py` | `mospi/pipeline/stages/peer_groups/config.py` |
| `peer_groups/engine.py` | `mospi/pipeline/stages/peer_groups/engine.py` |
| `peer_groups/reporting.py` | `mospi/pipeline/stages/peer_groups/reporting.py` |
| `peer_groups/tests/test_engine.py` | `tests/stages/peer_groups/test_engine.py` |
| `pipeline/__init__.py` | `mospi/pipeline/__init__.py` |
| `pipeline/jobs.py` | `mospi/pipeline/jobs.py` |
| `pipeline/qa.py` | `mospi/pipeline/qa.py` |
| `pipeline/run.py` | `mospi/pipeline/run.py` |
| `pipeline/tests/__init__.py` | `tests/pipeline/__init__.py` |
| `pipeline/tests/synthetic.py` | `tests/synthetic.py` |
| `pipeline/tests/test_jobs.py` | `tests/pipeline/test_jobs.py` |
| `pipeline/tests/test_pipeline.py` | `tests/pipeline/test_pipeline.py` |
| `preprocessing/README.md` | `docs/stages/preprocessing/README.md` |
| `preprocessing/__init__.py` | `mospi/pipeline/stages/preprocessing/__init__.py` |
| `preprocessing/cli.py` | `mospi/pipeline/stages/preprocessing/cli.py` |
| `preprocessing/config.py` | `mospi/pipeline/stages/preprocessing/config.py` |
| `preprocessing/pipeline.py` | `mospi/pipeline/stages/preprocessing/pipeline.py` |
| `preprocessing/reporting.py` | `mospi/pipeline/stages/preprocessing/reporting.py` |
| `preprocessing/tests/test_pipeline.py` | `tests/stages/preprocessing/test_pipeline.py` |
| `statistical/DESIGN.md` | `docs/stages/statistical/DESIGN.md` |
| `statistical/README.md` | `docs/stages/statistical/README.md` |
| `statistical/VALIDATION_REPORT.md` | `docs/stages/statistical/VALIDATION_REPORT.md` |
| `statistical/__init__.py` | `mospi/pipeline/stages/statistical/__init__.py` |
| `statistical/cli.py` | `mospi/pipeline/stages/statistical/cli.py` |
| `statistical/config.py` | `mospi/pipeline/stages/statistical/config.py` |
| `statistical/engine.py` | `mospi/pipeline/stages/statistical/engine.py` |
| `statistical/reporting.py` | `mospi/pipeline/stages/statistical/reporting.py` |
| `statistical/revisit.py` | `mospi/pipeline/stages/statistical/revisit.py` |
| `statistical/statistics.py` | `mospi/pipeline/stages/statistical/statistics.py` |
| `statistical/tests/__init__.py` | `tests/stages/statistical/__init__.py` |
| `statistical/tests/test_engine.py` | `tests/stages/statistical/test_engine.py` |
| `survey_rules/__init__.py` | `mospi/survey_rules/__init__.py` |
| `survey_rules/plfs.py` | `mospi/survey_rules/plfs.py` |
| `survey_rules/plfs_integrity.py` | `mospi/survey_rules/plfs_integrity.py` |
| `survey_rules/schema.py` | `mospi/survey_rules/schema.py` |
| `survey_rules/variance.py` | `mospi/survey_rules/variance.py` |
