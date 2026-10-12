# MoSPI Intelligent Survey Data Validation Platform — technical and architectural roadmap for eSigma integration

*(The platform's internal code packages keep the working name "MoSPI"; see README.)*

Brief objective 5: "Prepare a technical and architectural roadmap for phased integration with the eSigma platform and MoSPI data ecosystem."

eSigma internals (APIs, identity provider, hosting, CAPI event model, enumerator identifiers) are **not documented in this repository**. Everything below marked *[needs HSD/eSigma confirmation]* depends on that information and is a proposal, not a specification of eSigma.

## Current state (what exists now)

| Capability | Interface | Status |
|---|---|---|
| Batch validation of a delivery | `python -m pipeline.run --release <r> --suffix <id>` (all layers, quality gates, immutable runs, report) | Implemented |
| Online validation of one record | `POST /api/validate/record` — person-level rule check plus position in the stored comparison groups; nothing stored | Prototype |
| Documented integrity rules | `integrity/rules/*.yaml` (person and household level, cited, self-tested, dry-run per batch) | Implemented |
| Supervisor review and audit | local web workspace; decision taxonomy with reason codes; append-only, hash-chained SQLite audit with evidence snapshots | Implemented (single file; PostgreSQL store is a later stage) |
| Decisions out | `GET /api/reviews` (case, decision, reason, verification source, corrected item and value) and CSV export of any review list | Implemented; no push to eSigma |
| Authentication | optional bearer tokens with supervisor / technical / admin roles (`--users-file`) | Prototype; not GoI-approved identity |

**Not implemented in this stage (deliberately):** any connection to eSigma, an ingestion API that stores submissions (idempotency, revisions), a scheduler/drop zone, and PostgreSQL stores. Nothing in the code simulates eSigma. The boundary the platform expects is: per household, the schedule's Block 1–6 items in the agreed layout plus schema version, visit and revision; optionally `investigator_id`, `supervisor_id` and timestamps (the paper schedule has an enumerator code in Block 2, but the released files do not carry it, so the enumerator lane cannot be built or tested now).

## Phase A — loosely coupled pilot (no change to eSigma)

1. eSigma (or an export job) drops periodic delivery files in the agreed PLFS layout to a controlled directory.
2. The platform's batch pipeline prepares, validates and fuses them; supervisors review in the platform.
3. Decisions are exported (CSV) and returned to eSigma through the existing correction process.

Requires: agreed file drop and layout versioning; a documented mapping for any new release (a new `preprocessing.config` contract and `survey_rules` entry).

## Phase B — online screening at data entry / upload

1. eSigma calls `POST /api/validate/record` (or a batch variant) when a schedule is submitted, passing concept fields.
2. The platform returns rule breaches and comparison-group positions; eSigma shows them to the enumerator/supervisor as soft prompts.
3. Reference distributions are those of the last approved platform run (provenance returned with every response).

Requires *[needs HSD/eSigma confirmation]*: service authentication (mutual TLS or the GoI identity provider in place of local tokens), network placement, latency budget, concept-to-eSigma field mapping, and whether eSigma can show advisory prompts.

## Phase C — integrated supervision

1. Review decisions flow back to eSigma through an authenticated API; eSigma remains the system of record for corrections. The platform never edits survey data.
2. Confirmed outcomes become labelled data: `GET /api/feedback` already summarises decisions per lane with confidence intervals and proposes (never applies) threshold or budget changes; with real decisions and a random audit sample of unflagged records, thresholds and budgets can be set from real outcomes rather than engineering defaults (pilot protocol, plan §12.7).
3. If eSigma can supply an enumerator/interviewer identifier, an enumerator-level layer can be designed — with the same rule that patterns prompt review and are never presented as misconduct.

## Non-functional requirements carried into every phase

* GoI hosting and data-security compliance review; encryption at rest and in transit; RBAC through the approved identity provider; access logs.
* No external services; all computation on approved infrastructure.
* Immutable, versioned evidence runs and provenance in every response.
* Separate validation of any change to methods (re-run `evaluation/` before promoting a new method version).
