# PLFS V1 peer-group design

## Current specification: `plfs-peer-groups-v1.1` (October 2026)

* Pre-2025 releases span four quarters: every configured level is tried **within the record's quarter first**, then pooled over the release (`(L0+q, L0, L1+q, L1, ...)`; plan M2).
* New target `day7_casual_wage`, compared within the same day-7 activity status (41/42/51) and 2-digit industry of that day's work.
* One shared context definition (`derive_context`) is used by the peer, statistical and contextual engines. v1.0 runs remain readable.

## Scope and evidence base

This is a reference-population mechanism, not a statistical-validation
mechanism.  It assigns each prepared person observation and behavioural target
to a reproducible, sufficiently sized comparison group or marks it `NOT_ASSESSABLE`.
It intentionally calculates no percentile, dispersion, anomaly, probability,
or priority measure.

This design was based on the completed preparation package, its final prepared
person files, and `EDA/PLFS_Evidence_Analysis.ipynb`.  The research-design and
research-plan files named in the development brief were not present in this
workspace at implementation time.

The supplied files establish the following material constraints:

* Releases have distinct raw schemas.  The engine therefore uses an explicit
  source-profile mapping rather than raw-name matching.
* `2023_24` and `2024` are quarterly, pre-January-2025 first-visit data;
  `2025` is monthly post-January-2025 first-visit data.  They are never pooled.
* `2023_24_revisit` is a separate observation route (V2--V4).  It contains CWS
  earnings and CWS status but not the first-visit general-education, principal
  occupation, principal-industry, or Day-7-total-hours fields retained by the
  prepared data.
* The prepared tables retain `MoSPI_*` release, observation, design, visit,
  month (where applicable), linkage, key-status, FSU, and weight provenance.
  Weight and FSU are not peer-group dimensions.

## V1 behavioural targets

The targets are existing PLFS fields, retained as raw numeric responses:

| Target key | First-visit source concept | Revisit availability | Rationale |
|---|---|---|---|
| `cws_earnings_salaried` | CWS salaried earnings | yes | Existing current-week behavioural measure across the deliveries. |
| `cws_earnings_self_employed` | CWS self-employed earnings | yes | Existing current-week behavioural measure across the deliveries. |
| `day7_total_hours` | Day-7 total hours | no | Existing continuous work-time measure in all supplied first-visit releases. |

Zero is a valid PLFS response and remains eligible.  A blank or non-numeric
target is not eligible as a reference value and receives `NOT_ASSESSABLE` for
that target; the row itself is never discarded from the assignment output.

## Context boundaries

Every group has mandatory boundary dimensions added by the engine:

* release;
* observation route/visit type;
* pre/post-2025 design period; and
* for post-2025 targets configured as seasonal, calendar month.

All three V1 measures use month for post-2025, because they describe
current-week work or earnings and may be seasonal.  `MoSPI_visit` is retained
in the identity and first/revisit routes have separate source profiles.  This
means no peer group crosses release, the 2025 redesign boundary, or visit
route.  Groups are formed across FSUs.

## Grouping specifications

The context variables use documented existing fields: State/UT, rural/urban
sector, detailed CWS activity-status code, general-education level, principal
occupation major group (first digit of the supplied three-digit occupation
code), and principal-industry division (first two digits of the supplied NIC
code).  The first two transformations are transparent coarsenings of supplied
codes, not inferred classifications.

First-visit earnings, preferred through backoff:

1. State + sector + CWS activity status + principal-occupation major group +
   general-education level
2. State + sector + CWS activity status + principal-occupation major group
3. State + sector + CWS activity status

Revisit earnings (the documented context-limited profile):

1. State + sector + CWS activity status

First-visit Day-7 total hours, preferred through backoff:

1. State + sector + CWS activity status + principal-industry division
2. State + sector + CWS activity status

Broad age is a candidate dimension in the wider research approach, but is not
in this V1 configuration.  It was deliberately deferred rather than added by
default: occupation/education (earnings) and activity-status/industry (hours)
already create narrow cells, and an unvalidated age-band definition would add
another arbitrary partition.  A future configuration may add a documented age
band without code changes.

`State`, `sector`, and CWS activity status are retained at every V1 level.
The engine does not silently fall back to a state-only, national, or pooled
reference population.  Missing values in a required level dimension make that
level ineligible; they may be considered only at a later configured level that
does not require the missing dimension.

## Minimum size and assessability

`minimum_group_size=30` is a configurable V1 operating value.  It is inside
the research design's proposed 30--50 working range, but is neither a claimed
scientific optimum nor a final threshold.  Each level is attempted in the
listed order.  The first level with at least this many eligible target values
is selected deterministically and its zero-based `backoff_level` is recorded.

If no configured level reaches the threshold, or the target/context/source
profile is unavailable, the assignment is `NOT_ASSESSABLE` with an explicit
reason.  No arbitrary global group is introduced.

## Traceability and reproducibility

The assignment table has one row per source observation and target.  It stores
the source observation ID, target, assessability result, group ID/size,
profile/specification/version, selected dimensions and values, backoff level,
and reference-run/design metadata.  The reference table has one row per
unique assessable group and retains the full definition.  IDs are a truncated
SHA-256 digest of canonical JSON containing the specification version,
target, boundary values, selected dimensions, and selected dimension values.

The source input is accepted only when it is a prepared person file with the
required preparation provenance.  `MoSPI_fsu` and `MoSPI_weight` are rejected
if they appear in a grouping level, protecting the survey-design rules in
configuration as well as in code.
