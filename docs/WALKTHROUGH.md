# Walkthrough: MoSPI Intelligent Survey Data Validation Platform (PLFS)

This guide explains what the platform does and walks through a typical review session, page by page. It is written for supervisors, new team members and reviewers. No programming knowledge is needed. The engineering details are in [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md).

---

## 1. What the platform is for

The Periodic Labour Force Survey (PLFS) collects answers from hundreds of thousands of people every year. The CAPI software already rejects answers that are impossible, such as an age of 250. Some answers pass every CAPI check and are still worth a second look. Examples:

* a monthly salary recorded with an extra zero (₹1,50,000 instead of ₹15,000);
* an annual amount entered where a monthly amount was asked for;
* an occupation code that is very rare for people doing that kind of work;
* a whole First Stage Unit (FSU) whose interviews were all completed on one day, or were unusually short.

The platform finds records, households, FSUs and areas like these, and shows the stored evidence behind each one. **The supervisor decides.** The platform never declares an answer wrong, never changes survey data and never states a probability that a record is in error. It only says "this is unusual compared with similar people, and here is how unusual".

## 2. How a survey round becomes a review list

```
 1. Prepare           Check the delivered files against the documented layout for that release
 2. Rules             Apply the documented questionnaire rules (for example, "only salaried workers report a salary")
 3. Comparison groups Place each person among comparable people (same State, sector, activity, period)
 4. Value checks      How unusual is each earnings / hours / wage answer?
                      - against comparable people in the same round
                      - against the same kind of people in earlier periods
                      - against the value a model trained on earlier periods expects
 5. Coding check      How rare is this occupation code for comparable people?
 6. FSU checks        Do an FSU's answers or fieldwork records differ from comparable FSUs?
 7. Area trends       Weighted indicators by State, district and sector, with notable changes
 8. Review list       Combine the evidence, rank it and fit it to the review capacity
```

Each step saves its results and never overwrites an earlier run. That is why every number on a case page can be traced back to where it came from.

### Two lists, not one score

Every case lands in one of two tiers:

| Tier | What it contains |
|---|---|
| **Check now** | Every breach of an approved questionnaire rule, plus the strongest value and coding checks, up to the review budget (1% of records by default) and at most 10 value cases per FSU. |
| **Check if time** | Soft-rule findings, strong checks that did not fit the budget or the per-FSU cap, and the next band of evidence. |

Within a tier, cases are ordered by **impact**: how far that single answer would move the published estimate for its State and sector, measured in standard errors. Impact only sets the order inside a tier. It never moves a case from one tier to the other.

FSU alerts are kept separate. They describe how a group of interviews looks and are background for case review, not findings about any person.

## 3. Signing in and choosing a round

Open the workspace in a browser. Locally it runs at `http://127.0.0.1:8000`. The hosted review copy is at `https://mospi-survey-data-validation.vercel.app`. Sign in with the username and password your administrator gave you. At the first sign-in you choose your own password.

In the sidebar:

* **Survey round**: the stored validation run you are reviewing, for example *PLFS 2024, first visit*. It appears only when more than one run is stored.
* Your name and role, with **Change password** and **Sign out**. Decisions are recorded under the signed-in name.

The left sidebar has three sections: **Review**, **Operations** and **Reference**.

Roles:

| Role | Can |
|---|---|
| `supervisor` | review cases, record decisions, export case lists |
| `technical` | view everything, including operational records; cannot record decisions |
| `admin` | everything above, plus uploading deliveries and starting validation runs |

## 4. A review session, page by page

### 4.1 Overview

The starting page for each round. It shows:

* how many cases are in **Check now** and **Check if time**;
* review progress (cases decided against cases waiting);
* the mix of decisions recorded so far;
* the highest-priority records by State/UT;
* the number of FSU alerts.

Use it to judge the size of the day's work before opening the list.

### 4.2 Worklist by FSU

Verification is usually done per household visit or phone call, so this page groups cases **by FSU and then by household**, in queue order. A supervisor who is calling one household can clear all of that household's cases together.

### 4.3 All cases

Every case of the round in queue order, with filters for tier (list), reason, State/area and review status, and a search box for an FSU or record key. Supervisors and administrators can export the filtered list as CSV. Each export is recorded in the audit trail.

### 4.4 The case page

The core of the platform. It tells the case as a short story, in this order:

1. **Why you are seeing this case**: the tier and the main reason, for example *Check now · value check · salaried earnings*.
2. **What was recorded**: the answer, with the person's context (age, sex, activity status, occupation, State, sector, period).
3. **Compared with similar people now**: for example "above the range covering 9 in 10 comparable records".
4. **Compared with earlier periods**: the same kind of people in the previous quarters or months of the same survey design.
5. **Expected value**: the range a model trained on earlier periods expects for someone with these characteristics. It is always labelled as a model estimate.
6. **Rules**: any documented questionnaire rule this record breaks, with the rule's citation.
7. **Group context**: whether the record's FSU has an alert, and why.
8. **Importance**: the impact on the State/sector estimate.
9. **What to check**: a checklist (call back, look at the schedule image, confirm the unit and period).

Every figure on the page is read from the stored runs. Nothing is recalculated when the page opens.

### 4.5 Recording a decision

At the bottom of the case page, choose a decision, a reason and how the answer was verified:

| Decision | Typical reasons |
|---|---|
| **Confirmed error** | extra or missing zero, monthly/annual confusion, digit transposition, wrong code, wrong unit or period, wrong person or household |
| **Valid but unusual** | genuine high or low value, seasonal or one-off, special circumstance, rare but correct code |
| **Needs field verification** | call back, revisit, check schedule image |
| **Cannot verify** | respondent unreachable, no schedule image |
| **Escalate** | possible fieldwork issue, needs a subject expert |

Verification source: phone call, field revisit, schedule image, supervisor knowledge, or not verified. For a confirmed error you may note the corrected field and value. This is recorded for follow-up only and is **never written back to the survey data**.

When you save, the decision is added to the audit trail. *Previous case* and *Next case* move through the queue. If another reviewer decided the same case while you had it open, the platform says so and does not overwrite their decision.

### 4.6 Group alerts (FSU)

FSUs whose answers or fieldwork records differ clearly from comparable FSUs (same State, sector, stratum and period), ordered by strength of evidence. Checks include:

* the mix of activity statuses, adjusted for the age and sex of the people listed;
* age and earnings heaping (too many round numbers);
* unusually little variation in earnings within the FSU;
* short interview durations;
* many households interviewed on a single day;
* an unusual mix of response codes, or many substituted households;
* people in different households with near-identical answers.

An FSU is never treated as an enumerator: the released files contain no investigator code.

### 4.7 Area trends

Weighted current-weekly-status indicators by nation, State/UT, district and sector, for each period:

* Labour Force Participation Rate (LFPR), Worker Population Ratio (WPR) and Unemployment Rate (UR), for ages 15 and above;
* median salaried earnings;
* mean day-7 hours.

Each value carries a design-based standard error. A period-on-period change is highlighted only when it stands out against other areas **and** exceeds three standard errors. These are screening values from first-visit records, not official PLFS estimates.

### 4.8 Decisions

Every decision recorded for the round, newest first, with reviewer, reason, verification source and time.

### 4.9 Technical reference

For analysts and auditors:

* run provenance (which stage runs and code version produced this round);
* audit-trail verification (the hash chain is recomputed and reported INTACT or BROKEN);
* the questionnaire rules, with citations and dry-run counts;
* evaluation results;
* **feedback from decisions**: per lane and tier, the share of decided cases that were confirmed errors, valid but unusual, or unresolved, with 95% intervals. These rates can support a future change to thresholds; the platform never changes them by itself;
* a **single-record check**: enter one record's answers to see which rules and comparisons it would trigger. Nothing is stored.

## 5. Operations (administrators)

### 5.1 Upload & validate

Available on the local instance when the PostgreSQL operational store is enabled.

1. **Upload** the household and person CSV files of one delivery. Files are stored under server-generated names and fingerprinted (SHA-256).
2. **Pre-flight report**: the files are checked against the documented layout of that release, covering file pairing, required columns, keys and duplicates. Findings are *blocking*, *warning* or *info*. The report shows counts and column names only, never survey values.
3. **Start validation**: an explicit click. A separate worker process runs the full pipeline with its quality gates. Progress is shown per stage.
4. **Publication**: when every gate passes, the new round appears in the *Survey round* list. If a gate fails, nothing is published and the reason is shown. An interrupted job is retried once automatically.

The worker also runs **periodic integrity checks**. These confirm that stored runs and uploaded files are unchanged and that every audit chain is intact. Failures appear as alerts in a bar at the top of the page.

### 5.2 Batch validation

Starts a full validation run for a delivery that has already been prepared on the server, and follows its progress. Only administrators can start a run. The hosted copy cannot start runs.

## 6. Local workspace and hosted copy

| | Local / Docker | Hosted (Vercel) |
|---|---|---|
| View rounds, cases, FSU alerts, area trends | Yes | Yes (PLFS 2024 first visit) |
| Record decisions | Yes | No, read-only |
| Export CSV | Yes | No |
| Upload, batch validation | Yes (admin) | No |
| Sign-in | Optional on 127.0.0.1, required beyond it | Always required |

The hosted copy is meant for review and demonstration. Decisions are recorded on the processing machine only.

## 7. What the platform does not do

* It does not correct, impute or delete any survey answer.
* It does not estimate the probability that a record is wrong. A small tail probability means "rare among comparable people", nothing more.
* It does not assess enumerators (no investigator code in the released data).
* It does not compare across the January 2025 survey redesign.
* Its real-world precision and miss rate are not yet known. Measuring them needs a pilot with pre-scrutiny data and supervisor decisions.

## 8. Quick start

```bash
# Docker (recommended)
docker compose build
docker compose --profile seed run --rm seed     # copy stored runs into the data volume
docker compose up -d                            # open http://127.0.0.1:8000

# Without Docker (Python 3.11)
pip install -r requirements.txt
python -m mospi.app.serve                       # open http://127.0.0.1:8000
```

For everything else (running batches, the database, hosting, tests), see [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md).
