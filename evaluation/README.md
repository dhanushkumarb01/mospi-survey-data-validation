# Controlled-injection evaluation (E0–E7)

`python -m evaluation.run --release 2024` and `--release 2025`. Results: `evaluation/results/<release>.json`, summarised in `EVALUATION_REPORT.md` and on the Technical reference page.

## Why a controlled injection study

No confirmed PLFS error labels exist, so the only way to measure whether the ranking finds errors is to insert known errors and see where they land. This answers "does the method find errors of these kinds, and which layers find which?" — it does **not** measure accuracy on real PLFS errors.

## Design (kept deliberately small)

* **Sample:** all records of six States/UTs — Bihar, Maharashtra, Tamil Nadu, Assam, Punjab, Delhi (East, West, South, North-East, North, an urban UT). Every MoSPI comparison is bounded by State/UT, so the comparison groups of a State subset are identical to the full-data groups for those States, at about a quarter of the computation.
* **Pre-2025:** Calendar 2024 (injected) with the same States' 2023-24 records as clean history. **Post-2025:** January–June 2025, errors injected in February–June (January has no comparable earlier period).
* **Injection** (`inject.py`, seed 20261003, ≈300 records per type, each change labelled; nothing outside a label changes — verified): earnings ×10, ÷10, first-two-digit transposition; occupation code replaced by a code of another major group; day-7 hours + 10; salaried worker's status recoded to 91 (rule breach); a worker's age keyed as 3 (rule breach); a person's answers copied from another person in the FSU; and 30 FSUs "fabricated" (all ages rounded to multiples of 5, all salaried earnings set to ₹15,000). Panel/revisit inconsistencies cannot be injected into first-visit data and are **not evaluated**.
* **One pipeline run per release** on the injected copy (peer groups, statistical, contextual, ML, pattern, historical, integrity, fusion — all rebuilt), then E0–E7 recomputed from the stored source scores:

| Experiment | Ranking score |
|---|---|
| E0 | documented integrity rules only |
| E1 / E2 / E3 / E3h | statistical / contextual / ML / historical rank alone |
| E4 | statistical + contextual |
| E5 | statistical + contextual + ML |
| E6 | full record-level hybrid + rules (also without the override, and the operational risk × influence queue) |
| E7 | E6 with each source removed in turn |

## Metrics

Average precision (with its chance level, the injected share), ROC-AUC, precision / recall / F0.5 / false-positive rate in the top 1% and 5% and at k = number injected, recall by error type, recall by sector and State, and for FSU fabrication the recall/precision of FSU alerts (q < 0.05) plus a check that fabricated-FSU members are not lifted in record risk. Ties are broken by a stable hash, never by the label.

**Interpretation limits:** unlabelled records may contain real errors (precision is a lower bound); injected errors are stylised; one seed and six States per release; no confidence intervals are claimed.
