# Documentation index

Start with these two:

* [WALKTHROUGH.md](WALKTHROUGH.md): what the platform does and how to use it, page by page (no technical background needed).
* [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md): architecture, pipeline stages, fusion and queue, API, data stores, deployment, configuration, security, evaluation and testing.

| Folder | What is in it |
|---|---|
| [specification/](specification/) | [10_10_IMPROVEMENT_PLAN.md](specification/10_10_IMPROVEMENT_PLAN.md) (master method specification and status), [V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md](specification/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md), [ESIGMA_INTEGRATION_ROADMAP.md](specification/ESIGMA_INTEGRATION_ROADMAP.md). |
| [deployment/](deployment/) | [DOCKER.md](deployment/DOCKER.md), [POSTGRESQL.md](deployment/POSTGRESQL.md) (Supabase, hosted data, backup, teardown), [VERCEL_REVIEW_ONLY_DEPLOYMENT.md](deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md). |
| [stages/](stages/) | Per-stage `README`, `DESIGN` and `VALIDATION_REPORT` for preprocessing, integrity, peer_groups, statistical, contextual, ml, pattern, historical and fusion. |
| [evaluation/](evaluation/) | The pre-registered [PROTOCOL.md](evaluation/PROTOCOL.md) and the injection design ([README.md](evaluation/README.md)). |
| [audits/](audits/) | [AUDIT_2026-10-03.md](audits/AUDIT_2026-10-03.md): the pre-V2 audit (historical record). |
| [research/](research/) | PLFS data research foundation and the original architecture design. |

Dated documents keep the file paths they were written with. TECHNICAL_DOCUMENTATION.md §3 maps the former top-level folders to the current layout.
