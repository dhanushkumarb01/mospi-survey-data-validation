# Evaluation protocol v1 (pre-registered)

Status: **committed before any confirmation run.** No result of the current method (fusion v2.1, "lanes") exists at the time of writing. The stored `evaluation/results/2024.json` and `2025.json` evaluate the **superseded** V2.0 priority and are kept for the record only.

Source of the design: `docs/10_10_IMPROVEMENT_PLAN.md` §8.4 and §12. Code: `evaluation/run.py`, `evaluation/metrics.py`, `evaluation/inject.py` (catalogue `plfs-injection-catalogue-v2`).

## Question

Does the platform find useful problems that deterministic CAPI validation would miss, within a realistic review budget and at a tolerable false-alert burden?

## Populations

* **Headline (CAPI-pass):** all records of the evaluation copy minus records breaking an approved hard rule and minus the rule-type injections (`status_earnings_rule`, `age_status_rule`).
* **Rule list:** scored separately; recall of rule-type injections must be 100%.
* **Group level:** FSUs; clean-FSU alert rate and per-variant recall.

## Data, seeds and folds

* Releases: 2024 (history: 2023-24, same design period) and 2025 (injections in February–December; January has no earlier period).
* States/UTs split into folds A and B, sorted by size and assigned A, B, B, A, ... (`evaluation.run.state_folds`).
* Seeds 1–5, fold A: **development**. Seeds 6–20, fold B: **confirmation**, run once after the design is frozen.
* Every run keeps all stage artefacts under `evaluation/runs/protocol_v1/<release>_<fold>_seed<k>/` and records the git commit, input hashes, catalogue version and seed. `python -m evaluation.run --verify <result.json>` recomputes the metrics from those artefacts.

## Rankings compared

| Code | Ranking |
|---|---|
| A0 | Superseded V2.0 priority (average of within-run ranks, max-of-ML, override, × domain-share influence), rebuilt from the same stage outputs |
| E1 | Current peers alone (leave-one-out tail probability) |
| E2 | Earlier periods alone |
| E4 | Expected-value model alone (trained on earlier periods) |
| B | References only (current + earlier) |
| D | Full value lane (references, OR model, Šidák across variables) |
| E3 | Coding lane alone (occupation miscodes are its target) |
| E6 | Operational queue order (tiers, budget, FSU cap, impact ordering) |

## Metrics (CAPI-pass)

R@K, P@K, F0.5@K for K = 0.5, 1, 2, 5% of records and K = the run's review budget; average precision; recall by error type and magnitude; recall at 5% by State and sector; paired-bootstrap difference of R@1% (500 resamples of injected records, paired). Real-data burden (observed vs nominal alerts per 1,000 records, by State) is read from each fusion report on the full released data.

## Acceptance criteria (fixed now)

1. **Combined beats parts:** D (or E6) R@1% ≥ best single lane + 3 percentage points, with the paired 95% CI of the difference above 0, in **both** releases, on the confirmation seeds.
2. **Beats the superseded design:** D R@1% > A0 R@1% with the paired CI above 0, both releases.
3. **Every retained component earns its place (E7):** removing the expected-value model from D lowers R@1% with the paired CI above 0; otherwise it is removed from the decision path. Isolation Forest and LOF are not in the decision path and would need to exceed 5× chance at R@1% *and* improve D to return.
4. **Coding lane:** occupation-miscode recall at 5% ≥ the superseded contextual layer's (77% / 62%).
5. **Burden:** on the real released data, observed value alerts per 1,000 within 0.8–1.25 × nominal; highest/median State "Check now" rate ≤ 3.
6. **FSU level:** clean-FSU alert rate ≤ 2%; recall reported per variant with CI.
7. **Rules:** rule-list recall = 100%.

**Selection rule:** choose the simplest design whose confirmation-set R@1% is not significantly below the best design (paired bootstrap, one-sided α = 0.05, margin 2 pp), with precision ≥ the best single lane and criteria 5–7 met.

## What this protocol cannot establish

Real-world precision and miss rate need pre-scrutiny eSigma data, supervisor decisions and a random audit sample of unflagged records (pilot, plan §12.7, gate G1). Injected errors are stylised; good results here are necessary, not sufficient.

## Run log (appended after registration; the protocol above is unchanged)

| Date | Release | Fold / seed | Kind | Method versions | Result file | Verified |
|---|---|---|---|---|---|---|
| 9 Oct 2026 | 2024 | A / 1 | development | fusion v2.2, ML v2.1, FSU combination v2 | `results/protocol_v1/2024_A_seed1.json` | yes |
| 9 Oct 2026 | 2025 | A / 1 | development | same | `results/protocol_v1/2025_A_seed1.json` | yes |

Development finding to resolve before confirmation: the expected-value model alone (E4) beats the full value lane (D) by 2.9 / 6.4 points of R@1% (post-hoc paired bootstrap). The design must be re-frozen (and the choice recorded here) before seeds 6–20 on fold B are run. See `docs/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md` §D.
