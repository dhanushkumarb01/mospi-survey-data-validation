# Historical evidence layer — design (plfs-historical-v1.1)

## Why

The project brief identifies the gap directly: supervisors have "no mechanism … to use the past data or related survey data for checking anomalies". Every other MoSPI layer compares a record only with its own survey round. This layer adds two kinds of past-data evidence without inventing longitudinal identity.

## What is comparable (and what is not)

* **One design period at a time.** The January-2025 redesign (monthly first-visit sample, new weighting, new identifiers) is a hard boundary: no 2025 record is compared with any pre-2025 record, and January 2025 is `DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD`.
* **One time axis per design period** (`survey_rules.period_index`). Pre-2025: Jul–Sep 2023 … Oct–Dec 2024 (six quarters). Calendar-2024 Q3/Q4 are the *same records* as 2023-24 Q3/Q4 (verified: 209,512 identical person keys and weights, 4 differing answers), so each period is taken from one release only and no record is ever its own reference. 2025: months 1–12.
* **No record linkage across releases.** First-visit FSUs are visited once; the only within-file panel (2023-24 revisit) is handled by the statistical layer.
* **Same variable meaning.** The three record targets have the same questionnaire wording and applicability in all three releases (Vol. I §3.6.17–3.6.19, verified in the 2023-24, 2024 and 2025 manuals and the 2025 schedule).

## Record level

For each applicable value (salaried earnings, self-employment earnings, day-7 hours; placeholders excluded) the reference is the same comparison cell — State/UT × sector × activity status × occupation group (earnings) or industry division (hours), backing off to State/UT × sector × status — in strictly preceding periods: up to 4 quarters (pre-2025) or 3 months (2025). At least 30 past records are required. Output: past-period percentile (mid-rank), quantiles, median, tail position, `historical_score = |2p − 1|`, the periods used and the cell. Values are unweighted and in current rupees (no deflator is supplied).

## Aggregate level

Per period and domain (All-India × sector, State/UT × sector, district × sector), with the documented quarterly/monthly final weight (`MULT/100` or `MULT/200` when NSS ≠ NSC before 2025; `MULT/100` in 2025): CWS LFPR, WPR and UR for ages 15+ (Vol. I §1.5.11: workers 11–72, unemployed 81–82), weighted median salaried earnings of salaried workers, weighted mean day-7 hours of workers. A period-on-period change is screened by its robust z among the same period's changes in other domains of the same level and sector (needs ≥ 5 domains, ≥ 150 persons / 30 earners in both periods); |z| ≥ 3.5 is required, **and** (v1.1) the change must be at least 3 times its own simple-random-sampling standard error (proportions √(p(1−p)/n); mean hours sd/√n; median earnings 1.2533·(IQR/1.349)/√n). v1.0 used the robust z alone, and the first real run showed small domains (e.g. Goa rural, Andaman & Nicobar) dominating the "unusual" list through sampling noise — the same small-sample bias fixed in the Pattern layer. Design effects are ignored, so these SEs understate sampling error and the screen remains somewhat liberal. National 2023-24/2024 values match published PLFS magnitudes (urban CWS LFPR ≈ 51%, WPR ≈ 47.5%, UR ≈ 7%).

**Limitations.** These are screening values from first-visit records only (urban quarterly estimates also use revisits); no design-based standard errors are computed; nominal rupees are not deflated; seasonality is not modelled; 2025 history is limited to earlier 2025 months.
