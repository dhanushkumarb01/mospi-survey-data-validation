# PLFS Data Research Foundation

### Factual foundation document for: *Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques* (HSD, NSO, MoSPI)

Prepared from independent study of the complete `data_MoSPI/` data package (three PLFS unit-level releases, their documentation, and code dictionaries) and the Project Brief supplied by HSD/NSO/MoSPI. All CSV data was read and profiled in full (no sampling); every documentation file supplied was opened and read. Every claim below is labelled:

- **[CONFIRMED]** — established directly either (a) from an official MoSPI/NSO document in the supplied package, with a specific file/page/section cited, or (b) from a computation run against the full, actual CSV data, with the exact script logic described.
- **[INFERRED]** — a reasonable conclusion drawn by combining confirmed facts, but not itself stated in any single document or directly observed as a single fact.
- **[UNCLEAR]** — the material available does not settle the question; it must be confirmed with MoSPI/HSD. These are collected systematically in Part 9.

No fact in this document is asserted without one of these three labels. Where two official documents disagree, both statements are quoted and the conflict is flagged rather than silently resolved.

---

## 0. Source Inventory

### 0.1 Problem statement

- `17718479185431_Project_Brief_NSO_Survey_Data_Validation_Software.docx` — "A brief note from HSD, NSO, MoSPI", Research Topic: *Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques*. This is the governing problem statement used throughout Part 8 and Part 11 below. **[CONFIRMED]**
- `GrantinAid_Guidelines_2024n.pdf` — MoSPI's "Guidelines on Research Study/Seminar (Grant-in-Aid Scheme)", 2024, 38 pages. This is an administrative/funding-process document (eligibility, proposal formats, financial ceilings, sanction procedure, reporting obligations) for MoSPI's Grant-in-Aid Scheme under Capacity Development of CSO. It does **not** describe the PLFS data validation project's data or technical scope; it is background on how a proposal for this project would be funded and administered (e.g., grants up to Rs. 50 lakh, extendable to Rs. 100 lakh; duration normally ≤ 12 months; quarterly progress reports; primary/secondary data must be handed to MoSPI). It is cited only where directly relevant (Part 12). **[CONFIRMED]**

### 0.2 `data_MoSPI/` data package

Three release folders, each containing raw CSV microdata plus official MoSPI/NSO documentation:

| Folder | Release | CSV files | Documentation supplied |
|---|---|---|---|
| `2023-June2024/` | PLFS July 2023–June 2024 (annual, Panel III/IV) | `hhv1.csv`, `hhrv.csv`, `perv1.csv`, `perrv.csv` | README (`1_README.docx`), Instruction Manual Vol. I & II (PDF), Estimation Procedure (PDF), Data Layout (`Data_LayoutPLFS_2023-24.xlsx`), District codes (`.xlsx`), NMDS 2.0 metadata (`.docx`), Note on updated instructions (PDF) |
| `Jan-Dec2024/` | PLFS Calendar Year 2024 (Panel 4 only, first-visit) | `chhv1.csv`, `cperv1.csv` | README (`README_Calendar_2024.docx`), Data Layout (`.xlsx`), District codes (`.xlsx`), Instruction Manual Vol. I & II (PDF, byte-identical to the 2023-24 copies — verified by MD5), NMDS 2.0 (byte-identical to the 2023-24 copy), Item Code Description & Codes (`.xlsx`, Panel 4) |
| `Post2025/` | PLFS Calendar Year 2025, First-Visit only (revamped design) | `chhv12025.csv`, `cperv12025.csv` | README (`README2025.docx`), Data Layout (`FV_Data_LayoutPLFS_2025.xlsx`), Basic-stratum file (`Bstrm_file.xlsx`), State code list, District code list, Instructions to Field Staff Vol. I — two half-year editions (Jan–Jun 2025, Jul–Dec 2025), Schedule 0.0 (PDF), Schedule 10.4 First-Visit and Revisit forms — two half-year editions each (PDF) |

All eight CSV files and all 27 documentation files were staged in full and processed; nothing was sampled or skipped. **[CONFIRMED]**

**Documentation duplication across releases, verified byte-for-byte (MD5):** the Instruction Manual Vol. I, Instruction Manual Vol. II, the NMDS 2.0 metadata note, and the District-code workbook are byte-identical between the `2023-June2024/` and `Jan-Dec2024/` folders. This confirms both releases were governed by the *same* fieldwork instructions and the same Panel-4 questionnaire vintage; the Post2025 release ships its own, revised Instruction Manuals (split into Jan–Jun and Jul–Dec 2025 editions) and its own Data Layout / code workbook, confirming a genuine instrument change from 2025 onward (detailed in Part 7). **[CONFIRMED]**

## PART 1 — Complete Data Map

### 1.1 Release 1: PLFS July 2023 – June 2024 (`2023-June2024/`)

**Dataset name (as printed on the file itself):** "Periodic Labour Force Survey (PLFS), July 2023-June 2024 — Final Multiplier-posted Unit-Level Data for Schedule-10.4" (`1_README.docx`). **[CONFIRMED]**

**Survey/reporting period:** four quarters, Q1 = Jul–Sep 2023, Q2 = Oct–Dec 2023, Q3 = Jan–Mar 2024, Q4 = Apr–Jun 2024 (README, Note-for-users table). This is the annual (July–June) reporting cycle NSO has used for PLFS bulletins since 2017. **[CONFIRMED]**

**Purpose of release:** the primary annual PLFS unit-level release used to generate usual-status (365-day recall) employment/unemployment indicators for the full year, and quarterly CWS (7-day recall) indicators for urban India. **[CONFIRMED — NMDS 2.0 §2.1, §2.8]**

**Files supplied, verified row counts (documented vs. actually read):**

| File | Observation unit | Documented record count (README) | Actual rows read | Match |
|---|---|---|---|---|
| `hhv1.csv` (HHV1) | Household, Visit 1 | 101,920 | 101,920 | ✅ exact |
| `hhrv.csv` (HHRV) | Household, Visits 2/3/4 (revisit) | 132,844 | 132,844 | ✅ exact |
| `perv1.csv` (PERV1) | Person, Visit 1 | 418,159 | 418,159 | ✅ exact |
| `perrv.csv` (PERRV) | Person, Visits 2/3/4 (revisit) | 504,440 | 504,440 | ✅ exact |

Column counts also match the official Data Layout exactly, position-for-position (37 / 32 / 139 / 104 columns respectively — see §1.5). **[CONFIRMED — computed with `pandas.read_csv`, full file, no sampling]**

**What each file represents:**
- `hhv1.csv` — one record per sample household, first-visit interview (Schedule 10.4, Blocks 1–3). Carries household roster size, household type, religion, social group, and monthly consumer-expenditure block.
- `hhrv.csv` — one record per sample household **revisit** (second, third or fourth visit). Same household-level content as HHV1's Blocks 1–3, minus the finer expenditure breakup (HHRV's Block 3 collapses items 5.1–5.5 into a single `b3q5_hhrv` monthly-expenditure figure — one fewer column than HHV1's Block 3, confirmed by column-count difference: HHRV has 32 columns vs HHV1's 37, and the *"Note for users"* explicitly lists a 86+1 byte record vs HHV1's 126+1).
- `perv1.csv` — one record per household member, first-visit interview. Full Schedule-10.4 content: demography (Block 4), education & vocational training (Block 4.1), usual principal and subsidiary activity status over the last 365 days (Blocks 5.1–5.3), and day-wise activity/hours/earnings for the 7 days preceding the interview plus the derived Current Weekly Status (Block 6).
- `perrv.csv` — one record per household member, revisit interview. Re-collects the core Block 4 items (relationship to head, gender, age, marital status, general/technical education level, years of formal education, current-attendance status) plus Block 6 (day-wise activity + CWS); it does **not** re-collect the Block 4.1 vocational-training detail (field/duration/type/funding of training), confirmed by column count (104 vs PERV1's 139 — the ~35-column gap corresponds almost entirely to the absent Block 4.1 items and the finer Block 5.1/5.2 employment-detail sub-items, not to Block 4 itself).

**Observation unit, rows, columns:** table above; see Part 2 for the full column-by-column inventory.

**Identifiers present (verified against README §"Common Primary Key"):**
- Household key (documented, byte positions in original fixed-width file): Quarter (8,2) + Visit (10,2) + Sector (12,1) + FSU Serial No. (29,5) + Hamlet-group/sub-block no. (34,1) + Second-Stage-Stratum No. (35,1) + Sample-Household No. (36,2).
- Person key: household key + Person Serial No. (38,2).
- In the actual CSV, these correspond to columns `qtr_*`, `visit_*`, `b1q3_*` (Sector), `b1q1_*` (FSU), `b1q13_*` (Sample Sg/Sb No. = hamlet group), `b1q14_*` (Second Stage Stratum), `b1q15_*` (Sample Household Number), and (person file) `b4q1_*` / `b4q1_pervv` (Person Serial No.) — matched by exact byte-position and item-number cross-reference against the Data Layout workbook. **[CONFIRMED]**
- We additionally carried State (`state_*`) and District (`distcode_*`/`dist_code_perrv`) in the key for global uniqueness testing (the FSU serial number, while unique within a stratum, is not guaranteed globally unique across the whole country without state/district — see §1.6). **[CONFIRMED by direct test: adding State+District did not change the number of unique keys in HHV1, i.e. FSU numbers were already effectively unique nationally in this release — see §1.6]**

**Likely primary/composite keys:** as documented above; verified empirically to be exactly unique in HHV1 (101,920 rows → 101,920 unique keys) and PERV1 (418,159 rows → 418,159 unique keys). **[CONFIRMED]**

**Relationships between files / file-to-file relationship map:**

```
                    ┌───────────────┐            ┌───────────────┐
                    │   HHV1.csv    │            │   HHRV.csv    │
                    │ (household,   │            │ (household,   │
                    │  visit 1)     │            │  revisit 2/3/4)│
                    │ 101,920 rows  │            │ 132,844 rows  │
                    └───────┬───────┘            └───────┬───────┘
                            │ 1                            │ 1
                            │ household key                │ household key
                            │ (+ visit no.)                 │ (+ visit no.)
                            │ N                            │ N
                    ┌───────▼───────┐            ┌───────▼───────┐
                    │  PERV1.csv    │            │  PERRV.csv    │
                    │ (person,      │            │ (person,      │
                    │  visit 1)     │            │  revisit 2/3/4)│
                    │ 418,159 rows  │            │ 504,440 rows  │
                    └───────────────┘            └───────────────┘
```

- **HHV1 ↔ PERV1** (legitimate link): household key. **Verified exactly**: for all 101,920 HHV1 households, the declared `Household Size` (`b3q1_hhv1`) equals the count of PERV1 rows sharing that household key — **0 mismatches out of 101,920** households. **[CONFIRMED — full-file computation]**
- **HHRV ↔ PERRV**: same household-key linkage; not separately re-verified household-size-wise because HHRV/PERRV do not repeat the household-size item on every visit in the same way, but person-level linkage is verified in Part 5.
- **HHV1 ↔ HHRV, and PERV1 ↔ PERRV — "legitimate but NOT a simple key match" case.** These files must **not** be linked by household key *within the same release file* expecting every HHRV/PERRV record to find its HHV1/PERV1 parent. Only a well-defined subset will match — see §1.7 (rotational panel mechanics) and Part 5, which quantifies this exactly.
- Across-release linkage (e.g., 2023-24's HHV1 to Calendar-2024's CHHV1) is **not** a legitimate direct join on the household key alone without care: FSU numbering, stratum numbering and even the underlying panel can change between releases at the panel/frame-update boundary (Part 7). It was **not attempted** in this document beyond descriptive comparison, and should be attempted only with explicit MoSPI guidance (Part 9).

**Whether the same household/person can appear more than once, and why [CONFIRMED, both from documentation and from data]:**
PLFS uses a **rotational panel design that applies only to the urban sector**; there is **no revisit in rural areas** (Instruction Manual Vol. I §1.4.3, verbatim: *"There will not be any revisit in the rural samples."*). Each selected **urban** household is visited **four times** over four consecutive quarters — one Visit-1 (first-visit schedule) and three revisits — giving 75% sample overlap between any two consecutive quarters (Instruction Manual Vol. I §1.4.1–1.4.2). This was independently and exactly verified against the actual data:

| File | Sector code 1 (Rural) rows | Sector code 2 (Urban) rows |
|---|---|---|
| HHV1 | 55,796 | 46,124 |
| HHRV | **0** | **132,844** |

HHRV contains **100.0% urban-sector households and zero rural households** — an exact match to the documented design, with no exceptions. **[CONFIRMED — full-file tabulation]**

### 1.2 Release 2: PLFS Calendar Year 2024 (`Jan-Dec2024/`)

**Dataset name:** "Periodic Labour Force Survey (PLFS), January 2024-December 2024 — Final Multiplier-posted Unit-Level Data for Schedule-10.4" (`README_Calendar_2024.docx`). **[CONFIRMED]**

**Survey/reporting period:** calendar-year 2024, built from four *quarters of the underlying rotational scheme*, re-labelled Q3–Q6 of "Panel 4" rather than a fresh Q1–Q4: Q3 = Jan–Mar 2024, Q4 = Apr–Jun 2024, Q5 = Jul–Sep 2024, Q6 = Oct–Dec 2024 (README table). **[CONFIRMED]** This is a **repackaging of first-visit data already present, in part, in the July2023–June2024 release** (Q3/Q4 quarters are shared with Release 1's Q3/Q4) plus two new quarters (Q5, Q6) not in Release 1 — see Part 7 for the exact overlap.

**Purpose of release:** to support **calendar-year** (Jan–Dec) estimates, as opposed to Release 1's July–June annual cycle; NSO publishes both an annual (July–June) bulletin and, separately, calendar-year first-visit data (NMDS 2.0 §2.9). **[CONFIRMED]**

**Files supplied, verified row counts:**

| File | Observation unit | Documented (README) | Actual rows read | Match |
|---|---|---|---|---|
| `chhv1.csv` (CHHV1) | Household, Visit 1 only | 101,957 | 101,957 | ✅ exact |
| `cperv1.csv` (CPERV1) | Person, Visit 1 only | 415,549 | 415,549 | ✅ exact |

**Critical structural fact, confirmed [CONFIRMED]: this release contains *only first-visit* data.** There is no revisit file (no CHHRV/CPERRV) in the package, and none is mentioned in the README as existing for this release. This means Release 2 supports usual-status (365-day) and CWS (7-day) analysis exactly as HHV1/PERV1 did in Release 1, but **cannot support any within-year revisit/panel consistency check** — there is nothing to compare a household's answers against on a later visit within this release alone.

**What each file represents:** functionally identical in content and Schedule-10.4 block structure to Release 1's HHV1/PERV1 (see crosswalk in Part 7 for exact variable-level differences), but delivered with completely different **CSV column names** — fully descriptive English names (`Household_Type`, `Religion`, `Day7_Act1_Status_Code`, …) rather than Release 1's opaque block/question codes (`b3q2_hhv1`) — see §1.5 for why this matters.

**Identifiers:** README's "Common Primary Key" section: Quarter + FSU Serial No. + Hamlet-group/sub-block no. + Second-Stage-Stratum No. + Sample-Household No. (+ Person Serial No. for the person file); **Visit is no longer part of the key description text (it is always "V1") and "Sector" is not explicitly listed in the README's key description**, though Sector remains present as a field and is still needed to disambiguate FSU numbering with certainty (see §1.6). **[CONFIRMED from README; the omission of Sector from the printed key list is itself noted as a minor documentation gap]**

**New field vs. Release 1: `Panel`.** Unlike Release 1, every household/person record carries an explicit `Panel` = `"P4"` value. **[CONFIRMED — 100% of 101,957 CHHV1 rows carry Panel="P4"]** This is the first release in the package to make the panel identity an explicit data field rather than something the analyst must infer from the Quarter/Visit combination table.

**Household↔person linkage:** verified exactly as in Release 1 — **0 mismatches** between declared `Household_Size` and actual CPERV1 person counts across all 101,957 households; **100%** of CPERV1 persons resolve to an existing CHHV1 household. **[CONFIRMED — full-file computation]**

**Same household/person appearing more than once:** because this release is first-visit only, a given household appears **exactly once** (in whichever of Q3/Q4/Q5/Q6 it was newly enrolled). Uniqueness of the household key was verified exactly: 101,957 rows → 101,957 unique keys, 0 duplicates. **[CONFIRMED]**

### 1.3 Release 3: PLFS Calendar Year 2025, First Visit (`Post2025/`)

**Dataset name:** "Periodic Labour Force Survey (PLFS), Calendar Year 2025 — Final Multiplier-posted First Visit Unit-Level Data for Schedule-10.4" (`README2025.docx`). **[CONFIRMED]**

**Survey/reporting period:** 12 individual **months** of 2025 (January–December), not quarters. **[CONFIRMED]** This is a fundamental cadence change, explicitly documented: *"The sample design of PLFS has been revamped from January 2025. In the revamped sample design, the data is collected on a monthly basis"* (`NMDS_2dot0...docx` — the copy shipped with Release 1/2 — §2.9, "Duration and period of enumeration"). **[CONFIRMED, and directly consistent with the Post2025 CSVs carrying an explicit `month` field 1–12 rather than a `Quarter` field]**

**Purpose of release:** first-visit-only unit data for the redesigned, monthly PLFS. Per the same metadata note, sample size was expanded from *"around 1,02,400 households from 12,800 FSUs"* (up to December 2024) to *"2,72,304 households from 22,692 FSUs"* from January 2025 — a **~2.66× expansion** in nationally-designed sample size. **[CONFIRMED — official documentation]** The actual delivered file contains 270,472 households — **99.3% of the documented target of 272,304**, a small (0.67%) shortfall plausibly attributable to non-response, casualty replacement limits, or the file representing achieved rather than allocated sample; this gap is **[UNCLEAR]** and is listed as a question for MoSPI/HSD in Part 9.

**Files supplied, verified row counts:**

| File | Observation unit | Documented (README) | Actual rows read | Match |
|---|---|---|---|---|
| `chhv12025.csv` (CHHV1) | Household, Visit 1 | 270,472 | 270,472 | ✅ exact |
| `cperv12025.csv` (CPERV1) | Person, Visit 1 | 1,148,634 | 1,148,634 | ✅ exact |

**Critical structural fact [CONFIRMED]: like Release 2, this is first-visit-only data — no revisit file is included.** However, unlike Release 2, the *documentation package itself* ships layout specifications for `hhrv`, `perrv` and a second person-visit-1 variant (`perv1 (2)`) inside `FV_Data_LayoutPLFS_2025.xlsx` as extra sheets, even though **no corresponding CSV data file exists anywhere in the supplied `Post2025/` folder.** This is a genuine, confirmed data-package asymmetry (documentation for revisit files exists; revisit data does not) and is carried into Part 9 as a specific, well-evidenced item to raise with MoSPI/HSD — it strongly suggests that Post2025 revisit data (urban households' second/third/fourth visits) **does exist at NSO/MoSPI** (since a rotational panel design with a defined layout would not be built for a file nobody intends to produce) but was **not included in this particular data hand-off.** **[CONFIRMED gap, INFERRED explanation — the underlying revisit collection almost certainly exists operationally; whether/when it will be shared needs confirmation]**

**New identifier fields vs. Releases 1–2, confirmed present and populated:**
- `Panel` = `"05"` (encoded as float `5.0` in the household file text, see Part 3) for all 270,472 CHHV1 rows — confirms this is "Panel 5" of the rotational scheme. **[CONFIRMED]**
- `Bstrm` (Basic Stratum code — starts with 'D' if the stratum is a single district, 'N' if it is a merged NSS region of multiple small districts), `Zst` (stratum size), `Caph` (number of households listed in the second-stage stratum for this FSU), `Smallh` (number of households actually sampled in that second-stage stratum) — all new "design/estimation support" fields not present in Releases 1–2, explicitly introduced (per README2025.docx) to let users compute **design-based variance / relative standard error**, and to generate **district-level estimates**, which was **not possible from Releases 1–2's unit data alone**. **[CONFIRMED]**
- `Group` (`grp`) — new field, position in Block 1 identification; its exact definition is **not** explained in README2025.docx or the Data Layout remarks column beyond its byte position. **[UNCLEAR]**
- **NSS field dropped**: Releases 1–2 carried two "first-stage-units-surveyed" counts, `NSS` (sub-sample-specific count) and `NSC` (combined count); Release 3 carries **only `NSC`** — consistent with the sub-sample concept (used for computing combined vs. sub-sample-wise weights in Releases 1–2) being retired in the redesigned 2025 weighting scheme, which instead uses `Bstrm`/`Zst`/`Caph`/`Smallh`. **[CONFIRMED from column presence/absence; the operational reason is INFERRED from README2025.docx §5–6, "Use of weights"]**

**Questionnaire content also expanded — new Household Block 3 income items** (not present in Releases 1–2): item 6.1 *land possessed* (code), item 6.2 *land leased-out* (code), item 7.1 *rent received*, 7.2 *interest received*, 7.3 *pension received*, 7.4 *remittances received*, and 7.5 *Household's total income* = 7.1+7.2+7.3+7.4. **[CONFIRMED — this arithmetic identity was tested against all 270,472 households and holds exactly, 0 exceptions; see Part 3]** This is a substantive, confirmed widening of the survey's scope beyond consumption expenditure into income sources, directly relevant to Part 8 (new validation opportunities).

**Person file additions:** several new/expanded education-history items (`class/grade successfully completed`, `year(s) of education completed prior to class I`, `year(s) of education completed after the class/grade`, `No. of months attended in the last year of Education`, whether the last completed year was the last year attended) and new vocational-training items (training/course for higher-education or employment-exam entrance; nature of certifying body; when the training was completed). `Sex` is renamed `Gender` (same position, same apparent 1/2/3 coding — **[UNCLEAR]** whether the code list changed; not independently re-documented for 2025, see Part 9). **[CONFIRMED from column crosswalk, Part 7]**

**Household↔person linkage:** initially appeared to fail 100% due to a **confirmed real formatting defect** — see Part 3, §3.1 — after correcting for it, linkage is exact: **0 mismatches** between declared `hh_size` and actual person counts across all 270,472 households; **100%** of persons resolve to an existing household. **[CONFIRMED]**

### 1.4 Cross-release summary table

| | Release 1 (2023-24) | Release 2 (Calendar 2024) | Release 3 (Post2025) |
|---|---|---|---|
| Cadence of fieldwork | Quarterly | Quarterly (repackaged) | **Monthly** |
| Panel(s) present | III (revisits only) & IV (mixed) | IV only | **V (5) only** |
| Visit-1 households | 101,920 | 101,957 | **270,472** |
| Revisit data included? | **Yes** (HHRV/PERRV) | **No** | **No** (but documented layout exists, data not shipped) |
| Explicit `Panel` field? | No (must infer) | Yes (`P4`) | Yes (`05`) |
| Design/variance-support fields (Bstrm/Zst/Caph/Smallh) | No | No | **Yes** |
| Household income block (rent/interest/pension/remittances) | No | No | **Yes** |
| CSV column-naming convention | Block/question codes (`b3q2_hhv1`) | Full descriptive English names (`Household_Type`) | Short mnemonics (`hhtype`) |
| Sample size (households, per NMDS 2.0) | ~102,400 (whole scheme, to Dec 2024) | ~102,400 | **~272,304** |

### 1.5 A confirmed documentation‑vs‑delivered‑data discrepancy (naming), and why it matters

Independently comparing each release's official Data-Layout workbook against the **actual header row of the delivered CSV**, position by position, produced a striking and fully reproducible finding:

| Release | Documented `Field_Name` (layout workbook) for e.g. "Household Type" | Actual CSV column header |
|---|---|---|
| 2023-24 | `hhtype` | **`b3q2_hhv1`** |
| Calendar 2024 | `HHTYPE` | **`Household_Type`** |
| Post2025 | `hhtype` | **`hhtype`** (matches) |

**Only the Post2025 release's actual CSV headers match its own documentation's stated `Field_Name` column exactly, column for column (48/48 and 153/153 checked).** For Release 1, every single column's actual name differs from the layout workbook's own `Field_Name` sub-sheet (which nobody appears to have used to generate the delivered file — the delivered file instead auto-names columns from the Block+Item/Column number, e.g. Block 3 Item 2 → `b3q2_hhv1`). For Release 2, the delivered file instead uses a third, independent, fully descriptive naming scheme not documented in the layout workbook's `Field_Name` column at all. **[CONFIRMED by direct string comparison, full column list, both directions]**

**Why this matters for the project:** column names **cannot** be used to match a variable across releases, and — for Releases 1 and 2 — the shipped documentation's own "Field_Name" column **cannot** be used to predict the actual CSV header either. The only reliable way to identify "the same variable" across files and releases is **positional order matched against Block/Item (Column) number**, which is what this document's variable inventory (Part 2) and crosswalk (Part 7) use throughout, cross-checked against the exact record-length byte offsets printed in each release's own Data Layout workbook. Any ETL/harmonisation layer in the proposed platform must build its own explicit column-name-to-variable mapping per release; it cannot assume a stable schema or trust the documentation's stated field names for Releases 1–2. **[CONFIRMED finding; INFERRED implication for the platform's design, developed further in Part 8/Part 11]**

A second, smaller documentation-quality issue of the same kind: the Post2025 Data Layout workbook's own row numbering (`Srl`) is internally inconsistent for the household file — rows are numbered …, 42, 44, 43, 45, 46, 47, `47.7` — out of sequence and using a non-integer label for the last item ("Panel code"). Row **order** (not the `Srl` label) still matches the byte-position order and the actual CSV column order exactly, so this did not prevent building the inventory, but it is a documented authoring inconsistency in the official layout file. **[CONFIRMED]**

### 1.6 Key/identifier discussion

State + District + Sector + FSU + Hamlet-group/sub-block + Second-Stage-Stratum + Sample-Household-No. is the finest household identifier documented, and was independently confirmed to be exactly unique in every visit-1 household file tested (HHV1: 101,920/101,920 unique; CHHV1 2024: 101,957/101,957; CHHV12025: 270,472/270,472). Dropping State+District from the key (i.e., using only Sector+FSU+Sg/Sb+SSS+HH-No., which is the literal key definition printed in the 2023-24 README) produced **the same** uniqueness count in every case tested, i.e. **FSU serial numbers did not collide across states/districts in the data actually supplied** — but this should not be assumed to hold in general (FSU numbering is state/stratum-scoped by design; the absence of a collision in this specific dataset is not a guarantee). **[CONFIRMED for the supplied data; the general claim is [INFERRED]/cautionary, not asserted as a universal rule]**

### 1.7 The rotational-panel mechanics, confirmed directly against the data (Release 1)

The Instruction Manual (Vol. I §1.4.1–1.4.4) documents a four-quarter urban rotation: a new panel of FSUs enters with Visit-1 each quarter and is revisited in each of the following three quarters. This was tested exhaustively by checking, for every HHRV (revisit) record, whether its household key exists among Release 1's own HHV1 (visit-1) records, cross-tabulated by (current quarter, visit number):

| Current quarter | Visit 2 links to HHV1 (same file)? | Visit 3 links? | Visit 4 links? |
|---|---|---|---|
| Q1 | 0.43% | 0.28% | 0.57% |
| Q2 | **100.0%** | 0.40% | 0.28% |
| Q3 | **100.0%** | **100.0%** | 0.44% |
| Q4 | **100.0%** | **100.0%** | **100.0%** |

This is an exact, clean confirmation of the documented design: a household first visited in HHV1's Q1 is revisited as V2 in Q2, V3 in Q3, V4 in Q4 — all **within this same annual file**, hence 100% linkage on the diagonal. A household whose V2/V3/V4 falls in Q1 (or Q2's V3/V4, or Q3's V4) belongs to the **previous** rotation panel (Panel III), whose Visit-1 interview took place in the **prior** release (July 2022–June 2023), which is **not** part of this data package — hence the near-zero (<1%, residual noise discussed in Part 5) linkage there. **This is not a data defect: roughly half of HHRV's 132,844 rows are, by design, revisits of households whose first-visit record lives in a release this project does not have.** **[CONFIRMED — exact, full-file computation; this single finding materially shapes Parts 4, 5, 8 and 9 below]**

## PART 2 — Complete Variable Inventory

### 2.1 Method

For every one of the 8 CSV files, every column was matched **positionally** to its entry in that release's official Data Layout workbook (validated in Part 1 to align exactly — every file's documented item count equals its actual column count), giving: full documentation name, Block and Item/Column number, official byte range, and any printed remark. This was then merged with a full-file profile computed directly from the data (percentage blank, number of distinct values, and — for fields that parse as numeric in ≥90% of non-blank cells — the observed min/max). The complete, merged, 691-row inventory is reproduced in §2.6 as one table per file. This section (§2.2–2.5) explains what the blocks and codes *mean*, so the tables in §2.6 are not a bare data dictionary but an interpretable one; §2.5 groups variables by their expected role in the proposed validation platform (Part 8 develops this further with a hard test of feasibility, not just a listing).

Every household file (HHV1/CHHV1 family) and person file (PERV1/CPERV1 family) across all three releases follows the **same underlying Schedule 10.4 block structure** — confirmed directly: Block 1 (identification/sampling), Block 2 (survey administration), Block 3 (household characteristics + expenditure, + income from 2025), Block 4 (demographic/education particulars), Block 4.1 (vocational training), Block 5.1/5.2 (principal/subsidiary usual activity status, 365-day recall), Block 5.3 (unemployment/search duration), Block 6 (day-wise activity for the 7 days before interview + derived Current Weekly Status). This structural continuity is what makes the crosswalk in Part 7 possible despite the three completely different column-naming schemes documented in Part 1 §1.5. **[CONFIRMED]**

### 2.2 Block 1 — Identification / sampling frame

Sector (1=Rural, 2=Urban), State/UT code, District code, NSS-Region, Stratum, Sub-Stratum (Releases 1–2) / Group (Release 3), Sub-Sample (Releases 1–2 only), FOD Sub-Region, FSU serial number, Sample segment/sub-block number, Second-Stage-Stratum number, Sample Household number — together these form the household key (Part 1 §1.6) and encode NSO's multi-stage stratified sampling design (state → NSS-region → stratum → sub-stratum/group → FSU → second-stage stratum → household). Release 3 additionally carries `Bstrm` (basic stratum — a district, or a merged group of small districts prefixed "N"), `Zst` (basic-stratum size), `Caph` (households listed in this FSU's second-stage stratum) and `Smallh` (households actually sampled there) — the fields needed to compute design-based standard errors and, for the first time in this package, district-level estimates (Part 1 §1.3). **Observation level:** design/sampling (applies uniformly to every person/household in the row). **Derived vs. collected:** all directly assigned by the sample design before fieldwork (not collected from the respondent), except Response Code, Survey Code and Reason-for-Substitution, which are field-recorded. **Validation relevance:** referential-integrity checks (does this FSU/stratum combination exist in the sampling frame?), and grouping key for every "group-level"/FSU-level anomaly check in Part 6 and Part 8.

State and District codes were checked against the supplied code lists (`Indian_States_and_UTs_CodeName.xlsx`, `Indian_Districts_CodeName.xlsx`, and the `State code` sheets bundled in each release's Data Layout workbook) — see Part 3 §3.4 for the full validity result (100% valid, with the single non-issue of code 26 being legitimately retired, not missing data).

### 2.3 Block 3 — Household characteristics, expenditure and (2025-only) income

Household Size, Household Type (rural: self-employed-agri / self-employed-non-agri / regular-wage / casual-agri / casual-non-agri / other; urban: self-employed / regular-wage / casual / other), Religion (7 named + other), Social Group (ST/SC/OBC/other) — all short, closed code lists, reproduced in full in the code dictionary (`PLFS Panel 4 Sch 10.4 Item Code Description & Codes.xlsx`, sheet "Codes for Block 3"). **[CONFIRMED, full code list captured]**

Monthly consumer expenditure is built from five collected components (5.1 expenditure on goods/services, 5.2 imputed home-grown consumption, 5.3 imputed wages-in-kind/gifts, 5.4 annual clothing/footwear expenditure, 5.5 annual durables expenditure) and one **derived** total (5.6, "Household's usual consumer expenditure in a month"). The exact formula was recovered and confirmed against the full data: `item_5.6 = item_5.1 + item_5.2 + item_5.3 + (item_5.4 + item_5.5)/12`, holding **exactly**, to the rupee, for all 101,920 (2023-24), all 101,957 (Calendar 2024) and all 270,472 (2025) households — 0 exceptions in any release. **[CONFIRMED — this is the single strongest internal-consistency result in the whole dataset, and is a ready-made deterministic validation rule for the proposed platform]**

Release 3 only: two land-status codes (land possessed / land leased-out, on the date of survey) and four monthly/derived income items — rent received, interest received, pension received, remittances received, and item 7.5 "Household's total income" = 7.1+7.2+7.3+7.4, again confirmed to hold **exactly** for all 270,472 households, 0 exceptions. **[CONFIRMED]**

### 2.4 Blocks 4 / 4.1 / 5.1 / 5.2 / 5.3 / 6 — Person characteristics and activity status

- **Block 4** (demography): relationship to head (self/spouse/child/…/non-relative — for revisit households, relationship is still computed with respect to the *original* Visit-1 head, who becomes a "notional head" if no longer present — Instruction Manual Vol. I §3.4, confirmed text), Gender (Male-1/Female-2/**Transgender-3**), Age, Marital status, General education level (13-point scale, not-literate to postgraduate), Technical education level, years of formal education, current school/college attendance status (very fine 43-category code covering reason-for-non-attendance and level-of-attendance), whether vocational/technical training received.
- **Block 4.1** (vocational training detail): field of training (22 categories, e.g. IT-ITeS, healthcare, textiles), duration, type (on-the-job / part-time / full-time), funding source.
- **Blocks 5.1 / 5.2** (usual Principal / Subsidiary activity Status, **365-day** recall — NMDS 2.0 §2.8, confirmed): a 14-value activity-status code (own-account worker / employer / unpaid family helper / regular-salaried / casual-labour-public-works / casual-labour-other / seeking-or-available-for-work / student / domestic-duties (± unpaid production for household use) / rentier-pensioner-remittance-recipient / unable-to-work-disability / other / **for persons aged under 5, code 99**), plus (for the employed) industry code (NIC-2008, 5-digit), occupation code (NCO-2015, 3-digit observed), workplace location, enterprise type, enterprise size, contract type, paid-leave eligibility, social-security-benefit eligibility, and whether the product of the activity is for own consumption or sale.
- **Block 5.3**: duration of engagement, job-search effort type, duration of unemployment, whether ever worked, reason not working, main reason for being outside the labour force.
- **Block 6** (day-wise, **7-day** recall — the Current Weekly Status building block): for each of the 7 days before interview (labelled Day 7 = the day closest to interview back to Day 1), up to two activities each with its own status code (a *finer*, 20-value version of the Block 5.1 code list — it adds MGNREGS casual work (42), "had work but did not work due to sickness/other reasons" (61/62/71/72), "did not seek but available" (82), and "did not work due to temporary sickness, casual workers only" (98) — none of which exist in the Block 5.1/5.2 usual-status code list), industry code, hours worked, and daily wage earnings for each activity, plus a daily total-hours and "hours available for additional work" figure. From these seven days, NSO derives the **Current Weekly Status** fields present at the end of the record: `ACWS` (CWS status code), `AIND_CWS`/industry, `OCU_CWS`/occupation, and `ERN_REG`/`ERN_SELF` (weekly earnings, regular-salaried vs. self-employed).

**Missing/not-applicable conventions, confirmed:** industry and occupation codes are blank (not a special numeric code) for persons whose Block-5.1 status is not one of the employed codes — e.g., in Calendar-2024's CPERV1, exactly 251,503 of 415,549 persons (60.5%) have a blank Principal Industry/Occupation code, closely matching (within ~1,000, discussed as a residual "unclear" item in Part 3) the count of persons whose Principal Status is one of the seven employed codes (11/12/21/31/41/51 = 163,046 persons). **[CONFIRMED]** A dedicated "zero has a real meaning" case: Block-6 daily wage-earning fields being 0 is meaningful and expected for unpaid family workers/self-employed-with-no-cash-realisation that day, whereas a **negative** value is also valid and meaningful for self-employment earnings (a net loss) — the README explicitly states value fields "are given in whole number including negative values wherever applicable," and this was directly observed in Calendar-2024's `CWS_Earnings_SelfEmployed` (minimum observed: −10,000). **[CONFIRMED, both from documentation and from data]**

### 2.5 Variables grouped by likely validation role (used again, more rigorously, in Part 8)

- **Deterministic/arithmetic checks:** expenditure-total identity (5.6), income-total identity (7.5, 2025 only), household-size-vs-person-count identity, age<5 ⇒ status=99 rule — all four hold **exactly** in the supplied data (Part 3/Part 4) and are ready-made rule-based checks requiring no modelling.
- **Referential-integrity checks:** State/District/FSU/Stratum codes against the frame; Panel/Visit/Quarter-Month consistency; household-key existence for every person row.
- **Range/plausibility checks:** Age (0–117 observed), hours worked per day (documented ≤ 24 — tested in Part 3), wages/earnings (extreme-value tail examined in Part 3), household size (1–30 observed).
- **Contextual/probabilistic checks** (need a reference distribution, not a hard rule): out-of-labour-force usual status with non-zero current-week earnings (Part 4: ~1.0% of persons — plausible, not automatically wrong); wage/salaried usual status with zero current-week earnings (Part 4: ~38% — large, ambiguous, needs a proper explanation model, not a hard flag); age heaping at multiples of 5 (Part 6: Whipple's index 158–172, "rough" by UN standards — a baseline the anomaly-detection layer must explicitly model, or every heaped age will look like a false anomaly).
- **Panel/longitudinal consistency checks** (Release 1 only — see Part 6): whether a revisited household's roster, or a revisited person's demographic answers, changed implausibly between visits.
- **Not usable for validation with the supplied data alone:** industry (NIC) and occupation (NCO) code *validity* (the code lists themselves were not supplied — Part 9), and any cross-release panel/longitudinal check spanning release boundaries (the previous release's revisit-linked households are not in this package — Part 1 §1.7, Part 9).

### 2.6 Full per-file variable inventory (documentation × actual data, all 691 variables)

Columns: position in file; documented full name; Block.Item/Column number; actual CSV column name; documented byte range; % of rows blank (empty string) in the actual data; number of distinct values observed; observed numeric range (only shown where ≥90% of non-blank values parse as numeric); documented remarks/special codes.

#### 2.6.1 Release 1 (2023-24) — HHV1 (household, visit 1) — 101,920 rows, 37 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `FI_hhv1` | 1-4 | 0.0 | 1 |  | FVH7 |
| 2 | Schdule | 1.2 | `B1q2_hhv1` | 5-7 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr_hhv1` | 8-9 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Visit |  | `visit_hhv1` | 10-11 | 0.0 | 1 |  | V1' for first visit |
| 5 | Sector | 1.3 | `b1q3_hhv1` | 12-12 | 0.0 | 2 | 1..2 |  |
| 6 | State/Ut Code | 0.1 | `state_hhv1` | 13-14 | 0.0 | 36 | 1..37 |  |
| 7 | District Code | 1.4 | `distcode_hhv1` | 15-16 | 0.0 | 75 | 1..75 |  |
| 8 | NSS-Region | 1.4 | `nss_region_hhv1` | 17-19 | 0.0 | 87 | 11..371 |  |
| 9 | Stratum | 1.5 | `b1q5_hhv1` | 20-21 | 0.0 | 6 | 1..6 |  |
| 10 | Sub-Stratum | 1.6 | `b1q6_hhv1` | 22-23 | 0.0 | 41 | 1..41 |  |
| 11 | Sub-Sample | 1.11 | `b1q11_hhv1` | 24-24 | 0.0 | 2 | 1..2 |  |
| 12 | Fod Sub-Region | 1.12 | `b1q12_hhv1` | 25-28 | 0.0 | 169 | 110..3613 |  |
| 13 | FSU | 1.1 | `b1q1_hhv1` | 29-33 | 0.0 | 12743 | 10001..26235 |  |
| 14 | Sample Sg/Sb No. | 1.13 | `b1q13_hhv1` | 34-34 | 0.0 | 2 | 1..2 |  |
| 15 | Second Stage Stratum No. | 1.14 | `b1q14_hhv1` | 35-35 | 0.0 | 4 | 1..4 |  |
| 16 | Sample Household Number | 1.15 | `b1q15_hhv1` | 36-37 | 0.0 | 8 | 1..8 |  |
| 17 | Month of Survey | 1.9 | `b1q9_hhv1` | 38-39 | 0.0 | 12 | 1..12 |  |
| 18 | Response Code | 1.17 | `b1q17_hhv1` | 40-40 | 0.0 | 5 | 1..9 |  |
| 19 | Survey Code | 1.18 | `b1q18_hhv1` | 41-41 | 0.0 | 2 | 1..2 |  |
| 20 | Reason for Substitution of original household | 1.19 | `b1q19_hhv1` | 42-42 | 88.533 | 5 | 1..9 |  |
| 21 | Household Size | 3.1 | `b3q1_hhv1` | 43-44 | 0.0 | 24 | 1..26 |  |
| 22 | Household Type | 3.2 | `b3q2_hhv1` | 45-45 | 0.0 | 6 | 1..9 |  |
| 23 | Religion | 3.3 | `b3q3_hhv1` | 46-46 | 0.0 | 8 | 1..9 |  |
| 24 | Social Group | 3.4 | `b3q4_hhv1` | 47-47 | 0.0 | 4 | 1..9 |  |
| 25 | Household's usual consumer Expenditure in A Month for purposes out of Goods and Services(Rs.) | 3.5.1 | `b3q5pt1_hhv1` | 48-55 | 0.0 | 3487 | 0..150000 |  |
| 26 | Imputed value of usual consumption in a month out of Home Grown stock (Rs.) | 3.5.2 | `b3q5pt2_hhv1` | 56-63 | 0.0 | 1064 | 0..25000 |  |
| 27 | Imputed value of usual consumption in a Month from wages in kind,free collection, gifts etc. (Rs.) | 3.5.3 | `b3q5pt3_hhv1` | 64-71 | 0.0 | 977 | 0..17400 |  |
| 28 | Household's Annual Expenditure on purchase of items like clothing, footwear etc.(Rs.) | 3.5.4 | `b3q5pt4_hhv1` | 72-79 | 0.0 | 2849 | 0..150000 |  |
| 29 | Household's Annual Expenditure on purchase of durables like Bedstead, TV, fridge etc.(Rs.) | 3.5.5 | `b3q5pt5_hhv1` | 80-87 | 0.0 | 3285 | 0..825000 |  |
| 30 | Household'S Usual Consumer Expenditure In A Month (Rs.) | 3.5.6 | `b3q5pt6_hhv1` | 88-95 | 0.0 | 17438 | 442..153917 |  |
| 31 | Informant Serial no. | 1.16 | `b1q16_hhv1` | 96-97 | 0.0 | 19 | 1..99 |  |
| 32 | Survey Date | 2.2(i) | `b2q2i_hhv1` | 98-105 | 0.0 | 355 | 1012024..31102023 |  |
| 33 | Total Time Taken To Canvass Sch. 10.4 | 2.4 | `b2q4_hhv1` | 106-109 | 0.0 | 107 | 20..200 |  |
| 34 | Ns count for sector x stratum x substratum x sub-sample | Generated | `nss_hhv1` | 110-112 | 0.0 | 15 | 1..17 | NSS |
| 35 | Ns count for sector x stratum x substratum | Generated | `nsc_hhv1` | 113-115 | 0.0 | 22 | 1..34 | NSC |
| 36 | Sub-sample wise Multiplier | Generated | `mult_hhv1` | 116-125 | 0.0 | 58786 | 2917..113853636 | MULT |
| 37 | Count of contributing State x Sector x Stratum x SubStratum in 4 Quarters | Generated | `no_qtr_hhv1` | 126-126 | 0.0 | 2 | 3..4 | No_Qtr |
#### 2.6.2 Release 1 (2023-24) — HHRV (household, revisit) — 132,844 rows, 32 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `FI_hhrv` | 1-4 | 0.0 | 1 |  | RVH7 |
| 2 | Schdule | 1.2 | `B1q2_hhrv` | 5-7 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr_hhrv` | 8-9 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Visit |  | `visit_hhrv` | 10-11 | 0.0 | 3 |  | V2' for second visit,' V3' for third visit & 'V4' for fourth visit |
| 5 | Sector | 1.3 | `b1q3_hhrv` | 12-12 | 0.0 | 1 | 2..2 |  |
| 6 | State/Ut Code | 0.1 | `state_hhrv` | 13-14 | 0.0 | 34 | 1..36 |  |
| 7 | District Code | 1.4 | `distcode_hhrv` | 15-16 | 0.0 | 69 | 1..75 |  |
| 8 | NSS-Region | 1.4 | `nss_region_hhrv` | 17-19 | 0.0 | 85 | 11..362 |  |
| 9 | Stratum | 1.5 | `b1q5_hhrv` | 20-21 | 0.0 | 6 | 1..6 |  |
| 10 | Sub-Stratum | 1.6 | `b1q6_hhrv` | 22-23 | 0.0 | 6 | 1..6 |  |
| 11 | Sub-Sample | 1.11 | `b1q11_hhrv` | 24-24 | 0.0 | 2 | 1..2 |  |
| 12 | Fod Sub-Region | 1.12 | `b1q12_hhrv` | 25-28 | 0.0 | 169 | 110..3613 |  |
| 13 | FSU | 1.1 | `b1q1_hhrv` | 29-33 | 0.0 | 5386 | 20001..26235 |  |
| 14 | Sample Sg/Sb No. | 1.13 | `b1q13_hhrv` | 34-34 | 0.0 | 2 | 1..2 |  |
| 15 | Second Stage Stratum No. | 1.14 | `b1q14_hhrv` | 35-35 | 0.0 | 4 | 1..4 |  |
| 16 | Sample Household Number | 1.15 | `b1q15_hhrv` | 36-37 | 0.0 | 8 | 1..8 |  |
| 17 | Month of Survey | 1.9 | `b1q9_hhrv` | 38-39 | 0.0 | 12 | 1..12 |  |
| 18 | Response Code | 1.17 | `b1q17_hhrv` | 40-40 | 0.0 | 5 | 1..9 |  |
| 19 | Survey Code | 1.18 | `b1q18_hhrv` | 41-41 | 0.0 | 1 | 1..1 |  |
| 20 | Reason for Substitution of original household | 1.19 | `b1q19_hhrv` | 42-42 | 100.0 | 1 |  |  |
| 21 | Household Size | 3.1 | `b3q1_hhrv` | 43-44 | 0.0 | 24 | 1..28 |  |
| 22 | Household Type | 3.2 | `b3q2_hhrv` | 45-45 | 0.0 | 4 | 1..9 |  |
| 23 | Religion | 3.3 | `b3q3_hhrv` | 46-46 | 0.0 | 8 | 1..9 |  |
| 24 | Social Group | 3.4 | `b3q4_hhrv` | 47-47 | 0.0 | 4 | 1..9 |  |
| 25 | Household'S Usual Consumer Expenditure In A Month (Rs.) | 3.5 | `b3q5_hhrv` | 48-55 | 0.0 | 13864 | 0..105000 |  |
| 26 | Informant Serial no. | 1.16 | `b1q16_hhrv` | 56-57 | 0.0 | 19 | 1..99 |  |
| 27 | Survey Date | 2.2(i) | `b2q2i_hhrv` | 58-65 | 0.0 | 365 | 1012024..31122023 |  |
| 28 | Total Time Taken To Canvass Sch. 10.4 | 2.4 | `b2q4_hhrv` | 66-69 | 0.0 | 82 | 10..120 |  |
| 29 | Ns count for sector x stratum x substratum x sub-sample | Generated | `nss_hhrv` | 70-72 | 0.0 | 17 | 1..17 | NSS |
| 30 | Ns count for sector x stratum x substratum | Generated | `nsc_hhrv` | 73-75 | 0.0 | 32 | 1..34 | NSC |
| 31 | Sub-sample wise Multiplier | Generated | `mult_hhrv` | 76-85 | 0.0 | 36332 | 2015..162114673 | MULT |
| 32 | Count of contributing State x Sector x Stratum x SubStratum in 4 Quarters | Generated | `no_qtr_hhrv` | 86-86 | 0.0 | 4 | 1..4 | No_Qtr |
#### 2.6.3 Release 1 (2023-24) — PERV1 (person, visit 1) — 418,159 rows, 139 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `FI_perv1` | 1-4 | 0.0 | 1 |  | FVP7 |
| 2 | Schdule | 1.2 | `B1q2_perv1` | 5-7 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr_perv1` | 8-9 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Visit |  | `visit_perv1` | 10-11 | 0.0 | 1 |  | V1' for first visit |
| 5 | Sector | 1.3 | `b1q3_perv1` | 12-12 | 0.0 | 2 | 1..2 |  |
| 6 | State/Ut Code |  | `state_perv1` | 13-14 | 0.0 | 36 | 1..37 |  |
| 7 | District Code | 1.4 | `distcode_perv1` | 15-16 | 0.0 | 75 | 1..75 |  |
| 8 | NSS-Region | 1.4 | `nss_region_perv1` | 17-19 | 0.0 | 87 | 11..371 |  |
| 9 | Stratum | 1.5 | `b1q5_perv1` | 20-21 | 0.0 | 6 | 1..6 |  |
| 10 | Sub-Stratum | 1.6 | `b1q6_perv1` | 22-23 | 0.0 | 41 | 1..41 |  |
| 11 | Sub-Sample | 1.11 | `b1q11_perv1` | 24-24 | 0.0 | 2 | 1..2 |  |
| 12 | Fod Sub-Region | 1.12 | `b1q12_perv1` | 25-28 | 0.0 | 169 | 110..3613 |  |
| 13 | FSU | 1.1 | `b1q1_perv1` | 29-33 | 0.0 | 12743 | 10001..26235 |  |
| 14 | Sample Sg/Sb No. | 1.13 | `b1q13_perv1` | 34-34 | 0.0 | 2 | 1..2 |  |
| 15 | Second Stage Stratum No. | 1.14 | `b1q14_perv1` | 35-35 | 0.0 | 4 | 1..4 |  |
| 16 | Sample Household Number | 1.15 | `b1q15_perv1` | 36-37 | 0.0 | 8 | 1..8 |  |
| 17 | Person Serial No. | 4.1 | `b4q1_perv1` | 38-39 | 0.0 | 26 | 1..26 |  |
| 18 | Relationship To Head | 4.4 | `b4q4_perv1` | 40-40 | 0.0 | 9 | 1..9 |  |
| 19 | Gender | 4.5 | `b4q5_perv1` | 41-41 | 0.0 | 3 | 1..3 |  |
| 20 | Age | 4.6 | `b4q6_perv1` | 42-44 | 0.0 | 111 | 0..114 |  |
| 21 | Marital Status | 4.7 | `b4q7_perv1` | 45-45 | 0.0 | 4 | 1..4 |  |
| 22 | General Educaion Level | 4.8 | `b4q8_perv1` | 46-47 | 0.0 | 12 | 1..13 |  |
| 23 | Technical Educaion Level | 4.9 | `b4q9_perv1` | 48-49 | 0.0 | 16 | 1..16 |  |
| 24 | No. of years in Formal Education | 4.10 | `b4q10_perv1` | 50-51 | 0.0 | 26 | 0..25 |  |
| 25 | Status of Current Attendance in Educational Institution | 4.11 | `b4q11_perv1` | 52-53 | 50.394 | 34 | 1..43 |  |
| 26 | Whether received any Vocational/Technical Training | 4.12 | `b4q12_perv1` | 54-54 | 29.094 | 7 | 1..6 |  |
| 27 | Whether Training completed during last 365 Days | 4.1.3 | `b4pt1q3_perv1` | 55-55 | 96.884 | 3 | 1..2 |  |
| 28 | Field Of Training | 4.1.4 | `b4pt1q4_perv1` | 56-57 | 96.884 | 23 | 1..99 |  |
| 29 | Duration Of Training | 4.1.5 | `b4pt1q5_perv1` | 58-58 | 96.884 | 7 | 1..6 |  |
| 30 | Type Of Training | 4.1.6 | `b4pt1q6_perv1` | 59-59 | 96.884 | 4 | 1..3 |  |
| 31 | Source Of Funding The Training | 4.1.7 | `b4pt1q7_perv1` | 60-60 | 96.884 | 4 | 1..9 |  |
| 32 | Status Code | 5.1.3 | `b5pt1q3_perv1` | 61-62 | 0.0 | 14 | 11..99 |  |
| 33 | Industry Code (NIC) | 5.1.5 | `b5pt1q5_perv1` | 63-67 | 60.655 | 1188 | 1111..97009 |  |
| 34 | Occupation Code (NCO) | 5.1.6 | `b5pt1q6_perv1` | 68-70 | 60.655 | 128 | 111..962 |  |
| 35 | Whether Engaged In Any Work In Subsidiary Capacity | 5.1.7 | `b5pt1q7_perv1` | 71-71 | 0.0 | 2 | 1..2 |  |
| 36 | (Principal)location Of Workplace Code | 5.1.8 | `b5pt1q8_perv1` | 72-73 | 72.199 | 22 | 10..99 |  |
| 37 | (Principal) Enterprise Type Code | 5.1.9 | `b5pt1q9_perv1` | 74-75 | 60.655 | 13 | 1..19 |  |
| 38 | (Principal) No. Of Workers In The Enterprise | 5.1.10 | `b5pt1q10_perv1` | 76-76 | 60.655 | 6 | 1..9 |  |
| 39 | (Principal)  Type Of Job Contract | 5.1.11 | `b5pt1q11_perv1` | 77-77 | 81.959 | 5 | 1..4 |  |
| 40 | (Principal) Eligble Of Paid Leave | 5.1.12 | `b5pt1q12_perv1` | 78-78 | 81.959 | 3 | 1..2 |  |
| 41 | (Principal) Social Security Benefits | 5.1.13 | `b5pt1q13_perv1` | 79-79 | 81.959 | 10 | 1..9 |  |
| 42 | (Principal) Usage of product of the economic activity | 5.1.14 | `b5pt1q14_perv1` | 80-80 | 88.484 | 5 | 1..4 |  |
| 43 | Status Code | 5.2.3 | `b5pt2q3_perv1` | 81-82 | 87.604 | 7 | 11..51 |  |
| 44 | Industry Code (NIC) | 5.2.5 | `b5pt2q5_perv1` | 83-87 | 87.604 | 692 | 1111..97009 |  |
| 45 | Occupation Code (NCO) | 5.2.6 | `b5pt2q6_perv1` | 88-90 | 87.604 | 121 | 111..962 |  |
| 46 | (Subsidiary) location Of Workplace Code | 5.2.7 | `b5pt2q7_perv1` | 91-92 | 94.306 | 22 | 10..99 |  |
| 47 | (Subsidiary)  Enterprise Type Code | 5.2.8 | `b5pt2q8_perv1` | 93-94 | 87.604 | 13 | 1..19 |  |
| 48 | (Subsidiary)  No. Of Workers In The Enterprise | 5.2.9 | `b5pt2q9_perv1` | 95-95 | 87.604 | 6 | 1..9 |  |
| 49 | (Subsidiary)   Type Of Job Contract | 5.2.10 | `b5pt2q10_perv1` | 96-96 | 96.453 | 5 | 1..4 |  |
| 50 | (Subsidiary)  Eligble Of Paid Leave | 5.2.11 | `b5pt2q11_perv1` | 97-97 | 96.453 | 3 | 1..2 |  |
| 51 | (Subsidiary)  Social Security Benefits | 5.2.12 | `b5pt2q12_perv1` | 98-98 | 96.453 | 10 | 1..9 |  |
| 52 | (Subsidiary) Usage of product of the economic activity | 5.2.13 | `b5pt2q13_perv1` | 99-99 | 92.732 | 5 | 1..4 |  |
| 53 | Ever Worked Prior to last 365 days | 5.3.5 | `b5pt3q5_perv1` | 100-100 | 56.22 | 3 | 1..2 |  |
| 54 | Duration of engagement in the economic activity in usual Principal Activity Status | 5.3.6 | `b5pt3q6_perv1` | 101-101 | 60.655 | 6 | 1..5 |  |
| 55 | Duration of engagement in the economic activity in Subsidiary Activity Status | 5.3.7 | `b5pt3q7_perv1` | 102-102 | 87.604 | 6 | 1..5 |  |
| 56 | Efforts undertaken to search work | 5.3.8 | `b5pt3q8_perv1` | 103-103 | 97.9 | 8 | 1..7 |  |
| 57 | Duration of spell of Unemployment | 5.3.9 | `b5pt3q9_perv1` | 104-104 | 98.181 | 6 | 1..5 |  |
| 58 | Whether Ever Worked | 5.3.10 | `b5pt3q10_perv1` | 105-105 | 50.903 | 3 | 1..2 |  |
| 59 | Reason for not working in last 365 days | 5.3.11 | `b5pt3q11_perv1` | 106-107 | 93.472 | 11 | 1..19 |  |
| 60 | Main reason for being in Principal activity status (91 to 97) | 5.3.12 | `b5pt3q12_perv1` | 108-108 | 52.722 | 9 | 1..9 |  |
| 61 | Status Code for activity 1 | 6.4/3.1 | `b6q4_3pt1_perv1` | 109-110 | 0.0 | 21 | 11..99 |  |
| 62 | Industry Code (NIC) for activity 1 | 6.5/3.1 | `b6q5_3pt1_perv1` | 111-112 | 60.915 | 87 | 1..97 |  |
| 63 | hours actuallly worked for activity 1 on 7 th day | 6.6/3.1 | `b6q6_3pt1_perv1` | 113-114 | 0.0 | 19 | 0..18 |  |
| 64 | wage earning for activity 1 on 7 th day | 6.9/3.1 | `b6q9_3pt1_perv1` | 115-119 | 0.0 | 166 | 0..2500 |  |
| 65 | Status Code for activity 2 | 6.4/3.1 | `b6q4_act2_3pt1_perv1` | 120-121 | 98.575 | 12 | 11..72 |  |
| 66 | Industry Code (NIC) for activity 2 | 6.5/3.1 | `b6q5_act2_3pt1_perv1` | 122-123 | 98.575 | 62 | 1..97 |  |
| 67 | hours actuallly worked for activity 2 on 7 th day | 6.6/3.1 | `b6q6_act2_3pt1_perv1` | 124-125 | 0.0 | 11 | 0..10 |  |
| 68 | wage earning for activity 2 on 7 th day | 6.9/3.1 | `b6q9_act2_3pt1_perv1` | 126-130 | 0.0 | 42 | 0..850 |  |
| 69 | total hours actually worked on 7th day | 6.7/3.1 | `b6q7_3pt1_perv1` | 131-132 | 0.0 | 20 | 0..20 |  |
| 70 | hours available for aditional worked on 7th day | 6.8/3.1 | `b6q8_3pt1` | 133-134 | 0.0 | 7 | 0..6 |  |
| 71 | Status Code for activity 1 | 6.4/3.2 | `b6q4_3pt2` | 135-136 | 0.0 | 21 | 11..99 |  |
| 72 | Industry Code (NIC) for activity 1 | 6.5/3.2 | `b6q5_3pt2` | 137-138 | 61.078 | 87 | 1..97 |  |
| 73 | hours actuallly worked for activity 1 on 6 th day | 6.6/3.2 | `b6q6_3pt2_perv1` | 139-140 | 0.0 | 19 | 0..18 |  |
| 74 | wage earning for activity 1 on 7 th day | 6.9/3.2 | `b6q9_3pt2_perv1` | 141-145 | 0.0 | 165 | 0..2000 |  |
| 75 | Status Code for activity 2 | 6.4/3.2 | `b6q4_act2_3pt2_perv1` | 146-147 | 98.546 | 11 | 11..72 |  |
| 76 | Industry Code (NIC) for activity 2 | 6.5/3.2 | `b6q5_act2_3pt2_perv1` | 148-149 | 98.546 | 67 | 1..97 |  |
| 77 | hours actuallly worked for activity 2 on 6 th day | 6.6/3.2 | `b6q6_act2_3pt2_perv1` | 150-151 | 0.0 | 12 | 0..11 |  |
| 78 | wage earning for activity 2 on 6 th day | 6.9/3.2 | `b6q9_act2_3pt2_perv1` | 152-156 | 0.0 | 43 | 0..800 |  |
| 79 | total hours actually worked on 6th day | 6.7/3.2 | `b6q7_3pt2_perv1` | 157-158 | 0.0 | 20 | 0..20 |  |
| 80 | hours available for aditional worked on 6th day | 6.8/3.2 | `b6q8_3pt2_perv1` | 159-160 | 0.0 | 7 | 0..6 |  |
| 81 | Status Code for activity 1 | 6.4/3.3 | `b6q4_3pt3_perv1` | 161-162 | 0.0 | 21 | 11..99 |  |
| 82 | Industry Code (NIC) for activity 1 | 6.5/3.3 | `b6q5_3pt3_perv1` | 163-164 | 61.55 | 87 | 1..97 |  |
| 83 | hours actuallly worked for activity 1 on5 th day | 6.6/3.3 | `b6q6_3pt3_perv1` | 165-166 | 0.0 | 18 | 0..18 |  |
| 84 | wage earning for activity 1 on 5 th day | 6.9/3.3 | `b6q9_3pt3_perv1` | 167-171 | 0.0 | 167 | 0..2000 |  |
| 85 | Status Code for activity 2 | 6.4/3.3 | `b6q4_act2_3pt3_perv1` | 172-173 | 98.59 | 11 | 11..72 |  |
| 86 | Industry Code (NIC) for activity 2 | 6.5/3.3 | `b6q5_act2_3pt3_perv1` | 174-175 | 98.59 | 65 | 1..97 |  |
| 87 | hours actuallly worked for activity 2 on 5 th day | 6.6/3.3 | `b6q6_act2_3pt3_perv1` | 176-177 | 0.0 | 11 | 0..10 |  |
| 88 | wage earning for activity 2 on 5 th day | 6.9/3.3 | `b6q9_act2_3pt3_perv1` | 178-182 | 0.0 | 42 | 0..1000 |  |
| 89 | total hours actually worked on 5th day | 6.7/3.3 | `b6q7_3pt3_perv1` | 183-184 | 0.0 | 19 | 0..20 |  |
| 90 | hours available for aditional worked on 5th day | 6.8/3.3 | `b6q8_3pt3` | 185-186 | 0.0 | 7 | 0..6 |  |
| 91 | Status Code for activity 1 | 6.4/3.4 | `b6q4_3pt4_perv1` | 187-188 | 0.0 | 21 | 11..99 |  |
| 92 | Industry Code (NIC) for activity 1 | 6.5/3.4 | `b6q5_3pt4_perv1` | 189-190 | 62.062 | 88 | 1..99 |  |
| 93 | hours actuallly worked for activity 1 on 4th day | 6.6/3.4 | `b6q6_3pt4_perv1` | 191-192 | 0.0 | 19 | 0..18 |  |
| 94 | wage earning for activity 1 on 4th day | 6.9/3.4 | `b6q9_3pt4_perv1` | 193-197 | 0.0 | 175 | 0..2000 |  |
| 95 | Status Code for activity 2 | 6.4/3.4 | `b6q4_act2_3pt4_perv1` | 198-199 | 98.646 | 11 | 11..72 |  |
| 96 | Industry Code (NIC) for activity 2 | 6.5/3.4 | `b6q5_act2_3pt4_perv1` | 200-201 | 98.646 | 66 | 1..97 |  |
| 97 | hours actuallly worked for activity 2 on 4th day | 6.6/3.4 | `b6q6_act2_3pt4_perv1` | 202-203 | 0.0 | 10 | 0..9 |  |
| 98 | wage earning for activity 2 on 4th day | 6.9/3.4 | `b6q9_act2_3pt4_perv1` | 204-208 | 0.0 | 41 | 0..1000 |  |
| 99 | total hours actually worked on 4th day | 6.7/3.4 | `b6q7_3pt4_perv1` | 209-210 | 0.0 | 20 | 0..20 |  |
| 100 | hours available for aditional worked on 4th day | 6.8/3.4 | `b6q8_3pt4_perv1` | 211-212 | 0.0 | 8 | 0..8 |  |
| 101 | Status Code for activity 1 | 6.4/3.5 | `b6q4_3pt5_perv1` | 213-214 | 0.0 | 21 | 11..99 |  |
| 102 | Industry Code (NIC) for activity 1 | 6.5/3.5 | `b6q5_3pt5_perv1` | 215-216 | 62.265 | 87 | 1..97 |  |
| 103 | hours actuallly worked for activity 1 on 3rd day | 6.6/3.5 | `b6q6_3pt5_perv1` | 217-218 | 0.0 | 19 | 0..18 |  |
| 104 | wage earning for activity 1 on 3rd day | 6.9/3.5 | `b6q9_3pt5_perv1` | 219-223 | 0.0 | 167 | 0..2500 |  |
| 105 | Status Code for activity 2 | 6.4/3.5 | `b6q4_act2_3pt5_act2_perv1` | 224-225 | 98.689 | 11 | 11..72 |  |
| 106 | Industry Code (NIC) for activity 2 | 6.5/3.5 | `b6q5_act2_3pt5_perv1` | 226-227 | 98.689 | 67 | 1..97 |  |
| 107 | hours actuallly worked for activity 2 on 3rd day | 6.6/3.5 | `b6q6_act2_3pt5_perv1` | 228-229 | 0.0 | 12 | 0..11 |  |
| 108 | wage earning for activity 2 on 3 rd day | 6.9/3.5 | `b6q9_act2_3pt5_perv1` | 230-234 | 0.0 | 43 | 0..1000 |  |
| 109 | total hours actually worked on 3rd day | 6.7/3.5 | `b6q7_3pt5_perv1` | 235-236 | 0.0 | 20 | 0..20 |  |
| 110 | hours available for aditional worked on 3rd day | 6.8/3.5 | `b6q8_3pt5_perv1` | 237-238 | 0.0 | 7 | 0..6 |  |
| 111 | Status Code for activity 1 | 6.4/3.6 | `b6q4_3pt6_perv1` | 239-240 | 0.0 | 21 | 11..99 |  |
| 112 | Industry Code (NIC) for activity 1 | 6.5/3.6 | `b6q5_3pt6_perv1` | 241-242 | 62.171 | 87 | 1..97 |  |
| 113 | hours actuallly worked for activity 1 on 2nd day | 6.6/3.6 | `b6q6_3pt6_perv1` | 243-244 | 0.0 | 19 | 0..18 |  |
| 114 | wage earning for activity 1 on 2nd day | 6.9/3.6 | `b6q9_3pt6_perv1` | 245-249 | 0.0 | 171 | 0..3000 |  |
| 115 | Status Code for activity 2 | 6.4/3.6 | `b6q4_act2_3pt6_perv1` | 250-251 | 98.717 | 12 | 11..72 |  |
| 116 | Industry Code (NIC) for activity 2 | 6.5/3.6 | `b6q5_act2_3pt6_perv1` | 252-253 | 98.717 | 63 | 1..97 |  |
| 117 | hours actuallly worked for activity 2 on 2nd day | 6.6/3.6 | `b6q6_act2_3pt6_perv1` | 254-255 | 0.0 | 11 | 0..10 |  |
| 118 | wage earning for activity 2 on 2nd day | 6.9/3.6 | `b6q9_act2_3pt6_perv1` | 256-260 | 0.0 | 40 | 0..850 |  |
| 119 | total hours actually worked on 2nd day | 6.7/3.6 | `b6q7_3pt6_perv1` | 261-262 | 0.0 | 20 | 0..20 |  |
| 120 | hours available for aditional worked on 2nd day | 6.8/3.6 | `b6q8_3pt6_perv1` | 263-264 | 0.0 | 7 | 0..6 |  |
| 121 | Status Code for activity 1 | 6.4/3.7 | `b6q4_3pt7_perv1` | 265-266 | 0.0 | 21 | 11..99 |  |
| 122 | Industry Code (NIC) for activity 1 | 6.5/3.7 | `b6q5_3pt7` | 267-268 | 61.948 | 87 | 1..97 |  |
| 123 | hours actuallly worked for activity 1 on 1st day | 6.6/3.7 | `b6q6_3pt7_perv1` | 269-270 | 0.0 | 19 | 0..20 |  |
| 124 | wage earning for activity 1 on 1st day | 6.9/3.7 | `b6q9_3pt7_perv1` | 271-275 | 0.0 | 169 | 0..3000 |  |
| 125 | Status Code for activity 2 | 6.4/3.7 | `b6q4_act2_3pt7_perv1` | 276-277 | 98.707 | 12 | 11..72 |  |
| 126 | Industry Code (NIC) for activity 2 | 6.5/3.7 | `b6q5_act2_3pt7_perv1` | 278-279 | 98.707 | 65 | 1..97 |  |
| 127 | hours actuallly worked for activity 2 on 1st day | 6.6/3.7 | `b6q6_act2_3pt7_perv1` | 280-281 | 0.0 | 11 | 0..11 |  |
| 128 | wage earning for activity 2 on 1st day | 6.9/3.7 | `b6q9_act2_3pt7_perv1` | 282-286 | 0.0 | 39 | 0..1000 |  |
| 129 | total hours actually worked on 1st day | 6.7/3.7 | `b6q7_3pt7_perv1` | 287-288 | 0.0 | 19 | 0..20 |  |
| 130 | hours available for aditional worked on 1st day | 6.8/3.7 | `b6q8_3pt7_perv1` | 289-290 | 0.0 | 7 | 0..6 |  |
| 131 | Current Weekly Status (CWS) | 6.5 | `b6q5_perv1` | 291-292 | 0.0 | 21 | 11..99 |  |
| 132 | Industry Code (CWS) | 6.6 | `b6q6_perv1` | 293-294 | 59.265 | 87 | 1..97 |  |
| 133 | Occupation Code (CWS) | 6.7 | `b6q7_perv1` | 295-297 | 59.265 | 128 | 111..962 |  |
| 134 | Earnings For Regular Salaried/Wage Activity | 6.9 | `b6q9_perv1` | 298-305 | 0.0 | 2401 | 0..300000 |  |
| 135 | Earnings For Self Employed | 6.10 | `b6q10_perv1` | 306-313 | 0.0 | 2061 | -30000..500000 |  |
| 136 | Ns count for sector x stratum x substratum x sub-sample | Generated | `NSS_perv1` | 314-316 | 0.0 | 15 | 1..17 | NSS |
| 137 | Ns count for sector x stratum x substratum | Generated | `NSC_perv1` | 317-319 | 0.0 | 22 | 1..34 | NSC |
| 138 | Sub-sample wise Multiplier | Generated | `mult_perv1` | 320-329 | 0.0 | 58786 | 2917..113853636 | MULT |
| 139 | Count of contributing State x Sector x Stratum x SubStratum in 4 Quarters | Generated | `no_qtr_perv1` | 330-330 | 0.0 | 2 | 3..4 | No_Qtr |
#### 2.6.4 Release 1 (2023-24) — PERRV (person, revisit) — 504,440 rows, 104 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `FI_perrv` | 1-4 | 0.0 | 1 |  | RVP7 |
| 2 | Schdule | 1.2 | `B1q2_perrv` | 5-7 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr_perrv` | 8-9 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Visit |  | `visit_perrv` | 10-11 | 0.0 | 3 |  | V2' for second visit,' V3' for third visit & 'V4' for fourth visit |
| 5 | Sector | 1.3 | `b1q3_perrv` | 12-12 | 0.0 | 1 | 2..2 |  |
| 6 | State/Ut Code |  | `state_perrv` | 13-14 | 0.0 | 34 | 1..36 |  |
| 7 | District Code | 1.4 | `dist_code_perrv` | 15-16 | 0.0 | 69 | 1..75 |  |
| 8 | NSS-Region | 1.4 | `nss_region_perrv` | 17-19 | 0.0 | 85 | 11..362 |  |
| 9 | Stratum | 1.5 | `b1q5_perrv` | 20-21 | 0.0 | 6 | 1..6 |  |
| 10 | Sub-Stratum | 1.6 | `b1q6_perrv` | 22-23 | 0.0 | 6 | 1..6 |  |
| 11 | Sub-Sample | 1.11 | `b1q11_perrv` | 24-24 | 0.0 | 2 | 1..2 |  |
| 12 | Fod Sub-Region | 1.12 | `b1q12_perrv` | 25-28 | 0.0 | 169 | 110..3613 |  |
| 13 | FSU | 1.1 | `b1q1_perrv` | 29-33 | 0.0 | 5386 | 20001..26235 |  |
| 14 | Sample Sg/Sb No. | 1.13 | `b1q13_perrv` | 34-34 | 0.0 | 2 | 1..2 |  |
| 15 | Second Stage Stratum No. | 1.14 | `b1q14_perrv` | 35-35 | 0.0 | 4 | 1..4 |  |
| 16 | Sample Household Number | 1.15 | `b1q15_perrv` | 36-37 | 0.0 | 8 | 1..8 |  |
| 17 | Person Serial No. | 4.1 | `b4q1_pervv` | 38-39 | 0.0 | 28 | 1..28 |  |
| 18 | Relationship To Head | 4.4 | `b4q4_perrv` | 40-40 | 0.0 | 9 | 1..9 |  |
| 19 | Gender | 4.5 | `b4q5_perrv` | 41-41 | 0.0 | 3 | 1..3 |  |
| 20 | Age | 4.6 | `b4q6_perrv` | 42-44 | 0.0 | 107 | 0..106 |  |
| 21 | Marital Status | 4.7 | `b4q7` | 45-45 | 0.0 | 4 | 1..4 |  |
| 22 | General Educaion Level | 4.8 | `b4q8_perrv` | 46-47 | 0.0 | 12 | 1..13 |  |
| 23 | Technical Educaion Level | 4.9 | `b4q9_perrv` | 48-49 | 0.0 | 16 | 1..16 |  |
| 24 | No. of years in Formal Education | 4.10 | `b4q10_perrv` | 50-51 | 0.0 | 27 | 0..26 |  |
| 25 | Status of Current Attendance in Educational Institution | 4.11 | `b4q11_perrv` | 52-53 | 52.633 | 34 | 1..43 |  |
| 26 | Status Code for activity 1 | 6.4/3.1 | `b6q4_3pt1_perrv` | 54-55 | 0.0 | 21 | 11..99 |  |
| 27 | Industry Code (NIC) for activity 1 | 6.5/3.1 | `b6q5_3pt1_perrv` | 56-57 | 64.377 | 87 | 1..97 |  |
| 28 | hours actuallly worked for activity 1 on 7 th day | 6.6/3.1 | `b6q6_3pt1_perrv` | 58-59 | 0.0 | 20 | 0..20 |  |
| 29 | wage earning for activity 1 on 7 th day | 6.9/3.1 | `b6q9_3pt1_perrv` | 60-64 | 0.0 | 99 | 0..2000 |  |
| 30 | Status Code for activity 2 | 6.4/3.1 | `b6q4_act2_3pt1_perrv` | 65-66 | 99.633 | 11 | 11..72 |  |
| 31 | Industry Code (NIC) for activity 2 | 6.5/3.1 | `b6q5_act2_3pt1_perrv` | 67-68 | 99.633 | 63 | 1..97 |  |
| 32 | hours actuallly worked for activity 2 on 7 th day | 6.6/3.1 | `b6q6_act2_3pt1_perrv` | 69-70 | 0.0 | 11 | 0..10 |  |
| 33 | wage earning for activity 2 on 7 th day | 6.9/3.1 | `b6q9_act2_3pt1_perrv` | 71-75 | 0.0 | 17 | 0..750 |  |
| 34 | total hours actually worked on 7th day | 6.7/3.1 | `b6q7_3pt1_perrv` | 76-77 | 0.0 | 20 | 0..20 |  |
| 35 | hours available for aditional worked on 7th day | 6.8/3.1 | `b6q8_3pt1_perrv` | 78-79 | 0.0 | 6 | 0..5 |  |
| 36 | Status Code for activity 1 | 6.4/3.2 | `b6q4_3pt2_perrv` | 80-81 | 0.0 | 21 | 11..99 |  |
| 37 | Industry Code (NIC) for activity 1 | 6.5/3.2 | `b6q5_3pt2_perrv` | 82-83 | 64.552 | 87 | 1..97 |  |
| 38 | hours actuallly worked for activity 1 on 6 th day | 6.6/3.2 | `b6q6_3pt2_perrv` | 84-85 | 0.0 | 18 | 0..20 |  |
| 39 | wage earning for activity 1 on 7 th day | 6.9/3.2 | `b6q9_3pt2_perrv` | 86-90 | 0.0 | 99 | 0..2000 |  |
| 40 | Status Code for activity 2 | 6.4/3.2 | `b6q4_act2_3pt2_perrv` | 91-92 | 99.636 | 11 | 11..72 |  |
| 41 | Industry Code (NIC) for activity 2 | 6.5/3.2 | `b6q5_act2_3pt2_perrv` | 93-94 | 99.636 | 65 | 1..97 |  |
| 42 | hours actuallly worked for activity 2 on 6 th day | 6.6/3.2 | `b6q6_act2_3pt2_perrv` | 95-96 | 0.0 | 11 | 0..10 |  |
| 43 | wage earning for activity 2 on 6 th day | 6.9/3.2 | `b6q9_act2_3pt2_perrv` | 97-101 | 0.0 | 19 | 0..950 |  |
| 44 | total hours actually worked on 6th day | 6.7/3.2 | `b6q7_3pt2_perrv` | 102-103 | 0.0 | 18 | 0..20 |  |
| 45 | hours available for aditional worked on 6th day | 6.8/3.2 | `b6q8_3pt2_perrv` | 104-105 | 0.0 | 7 | 0..6 |  |
| 46 | Status Code for activity 1 | 6.4/3.3 | `b6q4_3pt3_perrv` | 106-107 | 0.0 | 21 | 11..99 |  |
| 47 | Industry Code (NIC) for activity 1 | 6.5/3.3 | `b6q5_3pt3_perrv` | 108-109 | 64.801 | 87 | 1..97 |  |
| 48 | hours actuallly worked for activity 1 on5 th day | 6.6/3.3 | `b6q6_3pt3_perrv` | 110-111 | 0.0 | 19 | 0..20 |  |
| 49 | wage earning for activity 1 on 5 th day | 6.9/3.3 | `b6q9_3pt3_perrv` | 112-116 | 0.0 | 101 | 0..2000 |  |
| 50 | Status Code for activity 2 | 6.4/3.3 | `b6q4_act2_3pt3_perrv` | 117-118 | 99.648 | 11 | 11..72 |  |
| 51 | Industry Code (NIC) for activity 2 | 6.5/3.3 | `b6q5_act2_3pt3_perrv` | 119-120 | 99.648 | 61 | 1..97 |  |
| 52 | hours actuallly worked for activity 2 on 5 th day | 6.6/3.3 | `b6q6_act2_3pt3_perrv` | 121-122 | 0.0 | 11 | 0..10 |  |
| 53 | wage earning for activity 2 on 5 th day | 6.9/3.3 | `b6q9_act2_3pt3_perrv` | 123-127 | 0.0 | 15 | 0..750 |  |
| 54 | total hours actually worked on 5th day | 6.7/3.3 | `b6q7_3pt3_perrv` | 128-129 | 0.0 | 19 | 0..20 |  |
| 55 | hours available for aditional worked on 5th day | 6.8/3.3 | `b6q8_3pt3_perrv` | 130-131 | 0.0 | 7 | 0..6 |  |
| 56 | Status Code for activity 1 | 6.4/3.4 | `b6q4_3pt4_perrv` | 132-133 | 0.0 | 21 | 11..99 |  |
| 57 | Industry Code (NIC) for activity 1 | 6.5/3.4 | `b6q5_3pt4_perrv` | 134-135 | 65.014 | 87 | 1..97 |  |
| 58 | hours actuallly worked for activity 1 on 4th day | 6.6/3.4 | `b6q6_3pt4_perrv` | 136-137 | 0.0 | 18 | 0..20 |  |
| 59 | wage earning for activity 1 on 4th day | 6.9/3.4 | `b6q9_3pt4_perrv` | 138-142 | 0.0 | 99 | 0..2000 |  |
| 60 | Status Code for activity 2 | 6.4/3.4 | `b6q4_act2_3pt4_perrv` | 143-144 | 99.647 | 11 | 11..72 |  |
| 61 | Industry Code (NIC) for activity 2 | 6.5/3.4 | `b6q5_act2_3pt4_perrv` | 145-146 | 99.647 | 61 | 1..97 |  |
| 62 | hours actuallly worked for activity 2 on 4th day | 6.6/3.4 | `b6q6_act2_3pt4_perrv` | 147-148 | 0.0 | 11 | 0..10 |  |
| 63 | wage earning for activity 2 on 4th day | 6.9/3.4 | `b6q9_act2_3pt4_perrv` | 149-153 | 0.0 | 17 | 0..610 |  |
| 64 | total hours actually worked on 4th day | 6.7/3.4 | `b6q7_3pt4_perrv` | 154-155 | 0.0 | 18 | 0..20 |  |
| 65 | hours available for aditional worked on 4th day | 6.8/3.4 | `b6q8_3pt4_perrv` | 156-157 | 0.0 | 7 | 0..7 |  |
| 66 | Status Code for activity 1 | 6.4/3.5 | `b6q4_3pt5_perrv` | 158-159 | 0.0 | 21 | 11..99 |  |
| 67 | Industry Code (NIC) for activity 1 | 6.5/3.5 | `b6q5_3pt5_perrv` | 160-161 | 65.103 | 88 | 1..99 |  |
| 68 | hours actuallly worked for activity 1 on 3rd day | 6.6/3.5 | `b6q6_3pt5_perrv` | 162-163 | 0.0 | 17 | 0..20 |  |
| 69 | wage earning for activity 1 on 3rd day | 6.9/3.5 | `b6q9_3pt5_perrv` | 164-168 | 0.0 | 102 | 0..2000 |  |
| 70 | Status Code for activity 2 | 6.4/3.5 | `b6q4_act2_3pt5_perrv` | 169-170 | 99.659 | 11 | 11..72 |  |
| 71 | Industry Code (NIC) for activity 2 | 6.5/3.5 | `b6q5_act2_3pt5_perrv` | 171-172 | 99.659 | 62 | 1..97 |  |
| 72 | hours actuallly worked for activity 2 on 3rd day | 6.6/3.5 | `b6q6_act2_3pt5_perrv` | 173-174 | 0.0 | 10 | 0..9 |  |
| 73 | wage earning for activity 2 on 3 rd day | 6.9/3.5 | `b6q9_act2_3pt5_perrv` | 175-179 | 0.0 | 18 | 0..1000 |  |
| 74 | total hours actually worked on 3rd day | 6.7/3.5 | `b6q7_3pt5_perrv` | 180-181 | 0.0 | 18 | 0..17 |  |
| 75 | hours available for aditional worked on 3rd day | 6.8/3.5 | `b6q8_3pt5_perrv` | 182-183 | 0.0 | 7 | 0..6 |  |
| 76 | Status Code for activity 1 | 6.4/3.6 | `b6q4_3pt6_perrv` | 184-185 | 0.0 | 21 | 11..99 |  |
| 77 | Industry Code (NIC) for activity 1 | 6.5/3.6 | `b6q5_3pt6_perrv` | 186-187 | 65.047 | 88 | 1..99 |  |
| 78 | hours actuallly worked for activity 1 on 2nd day | 6.6/3.6 | `b6q6_3pt6_perrv` | 188-189 | 0.0 | 17 | 0..20 |  |
| 79 | wage earning for activity 1 on 2nd day | 6.9/3.6 | `b6q9_3pt6_perrv` | 190-194 | 0.0 | 107 | 0..2000 |  |
| 80 | Status Code for activity 2 | 6.4/3.6 | `b6q4_act2_3pt6_perrv` | 195-196 | 99.658 | 11 | 11..72 |  |
| 81 | Industry Code (NIC) for activity 2 | 6.5/3.6 | `b6q5_act2_3pt6_perrv` | 197-198 | 99.658 | 63 | 1..97 |  |
| 82 | hours actuallly worked for activity 2 on 2nd day | 6.6/3.6 | `b6q6_act2_3pt6_perrv` | 199-200 | 0.0 | 11 | 0..10 |  |
| 83 | wage earning for activity 2 on 2nd day | 6.9/3.6 | `b6q9_act2_3pt6_perrv` | 201-205 | 0.0 | 20 | 0..950 |  |
| 84 | total hours actually worked on 2nd day | 6.7/3.6 | `b6q7_3pt6_perrv` | 206-207 | 0.0 | 18 | 0..20 |  |
| 85 | hours available for aditional worked on 2nd day | 6.8/3.6 | `b6q8_3pt6_perrv` | 208-209 | 0.0 | 7 | 0..7 |  |
| 86 | Status Code for activity 1 | 6.4/3.7 | `b6q4_3pt7_perrv` | 210-211 | 0.0 | 21 | 11..99 |  |
| 87 | Industry Code (NIC) for activity 1 | 6.5/3.7 | `b6q5_3pt7_perrv` | 212-213 | 64.893 | 88 | 1..99 |  |
| 88 | hours actuallly worked for activity 1 on 1st day | 6.6/3.7 | `b6q6_3pt7_perrv` | 214-215 | 0.0 | 18 | 0..20 |  |
| 89 | wage earning for activity 1 on 1st day | 6.9/3.7 | `b6q9_3pt7_perrv` | 216-220 | 0.0 | 97 | 0..2000 |  |
| 90 | Status Code for activity 2 | 6.4/3.7 | `b6q4_act2_3pt7_perrv` | 221-222 | 99.661 | 11 | 11..72 |  |
| 91 | Industry Code (NIC) for activity 2 | 6.5/3.7 | `b6q5_act2_3pt7_perrv` | 223-224 | 99.661 | 60 | 1..97 |  |
| 92 | hours actuallly worked for activity 2 on 1st day | 6.6/3.7 | `b6q6_act2_3pt7_perrv` | 225-226 | 0.0 | 10 | 0..9 |  |
| 93 | wage earning for activity 2 on 1st day | 6.9/3.7 | `b6q9_act2_3pt7_perrv` | 227-231 | 0.0 | 15 | 0..800 |  |
| 94 | total hours actually worked on 1st day | 6.7/3.7 | `b6q7_3pt7_perrv` | 232-233 | 0.0 | 18 | 0..20 |  |
| 95 | hours available for aditional worked on 1st day | 6.8/3.7 | `b6q8_3pt7_perrv` | 234-235 | 0.0 | 7 | 0..6 |  |
| 96 | Current Weekly Status (CWS) | 6.5 | `b6q5_perrv` | 236-237 | 0.0 | 21 | 11..99 |  |
| 97 | Industry Code (CWS) | 6.6 | `b6q6_perrv` | 238-239 | 63.59 | 87 | 1..97 |  |
| 98 | Occupation Code (CWS) | 6.7 | `b6q7_perrv` | 240-242 | 63.59 | 128 | 111..962 |  |
| 99 | Earnings For Regular Salarid/Wage Activity | 6.9 | `b6q9_perrv` | 243-250 | 0.0 | 2869 | 0..460000 |  |
| 100 | Earnings For Self Employed | 6.10 | `b6q10_perrv` | 251-258 | 0.0 | 1955 | -50000..620000 |  |
| 101 | Ns count for sector x stratum x substratum x sub-sample | Generated | `NSS_perrv` | 259-261 | 0.0 | 17 | 1..17 | NSS |
| 102 | Ns count for sector x stratum x substratum | Generated | `NSC_perrv` | 262-264 | 0.0 | 32 | 1..34 | NSC |
| 103 | Sub-sample wise Multiplier | Generated | `mult_perrv` | 265-274 | 0.0 | 36332 | 2015..162114673 | MULT |
| 104 | Count of contributing State x Sector x Stratum x SubStratum in 4 Quarters | Generated | `no_qtr_perrv` | 275-275 | 0.0 | 4 | 1..4 | No_Qtr |
#### 2.6.5 Release 2 (Calendar 2024) — CHHV1 (household, visit 1) — 101,957 rows, 38 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | Panel |  | `Panel` | 1-2 | 0.0 | 1 |  | P4 |
| 2 | File Identification |  | `File_Identification` | 3-7 | 0.0 | 1 |  | CFVH4 |
| 3 | Schdule | 1.2 | `Schdule` | 8-10 | 0.0 | 1 | 104..104 | 104 |
| 4 | Quarter |  | `Quarter` | 11-12 | 0.0 | 4 |  | Q3,Q4,Q5,Q6 |
| 5 | Visit |  | `Visit` | 13-14 | 0.0 | 1 |  |  |
| 6 | Sector | 1.3 | `Sector` | 15-15 | 0.0 | 2 | 1..2 |  |
| 7 | State/Ut Code | 0.1 | `State_Ut_Code` | 16-17 | 0.0 | 36 | 1..37 |  |
| 8 | District Code | 1.4 | `District_Code` | 18-19 | 0.0 | 75 | 1..75 |  |
| 9 | NSS-Region | 1.4 | `NSS_Region` | 20-22 | 0.0 | 87 | 11..371 |  |
| 10 | Stratum | 1.5 | `Stratum` | 23-24 | 0.0 | 6 | 1..6 |  |
| 11 | Sub-Stratum | 1.6 | `Sub_Stratum` | 25-26 | 0.0 | 41 | 1..41 |  |
| 12 | Sub-Sample | 1.11 | `Sub_Sample` | 27-27 | 0.0 | 2 | 1..2 |  |
| 13 | Fod Sub-Region | 1.12 | `Fod_Sub_Region` | 28-31 | 0.0 | 169 | 110..3613 |  |
| 14 | FSU | 1.1 | `FSU` | 32-36 | 0.0 | 12749 | 10001..26235 |  |
| 15 | Sample Sg/Sb No. | 1.13 | `Sample_Sg_Sb_No` | 37-37 | 0.0 | 2 | 1..2 |  |
| 16 | Second Stage Stratum No. | 1.14 | `Second_Stage_Stratum_No` | 38-38 | 0.0 | 4 | 1..4 |  |
| 17 | Sample Household Number | 1.15 | `Sample_Household_Number` | 39-40 | 0.0 | 8 | 1..8 |  |
| 18 | Month of Survey | 1.9 | `Month_of_Survey` | 41-42 | 0.0 | 12 | 1..12 |  |
| 19 | Response Code | 1.17 | `Response_Code` | 43-43 | 0.0 | 5 | 1..9 |  |
| 20 | Survey Code | 1.18 | `Survey_Code` | 44-44 | 0.0 | 2 | 1..2 |  |
| 21 | Reason for Substitution of original household | 1.19 | `Reason_for_Substitution` | 45-45 | 88.296 | 5 | 1..9 |  |
| 22 | Household Size | 3.1 | `Household_Size` | 46-47 | 0.0 | 23 | 1..26 |  |
| 23 | Household Type | 3.2 | `Household_Type` | 48-48 | 0.0 | 6 | 1..9 |  |
| 24 | Religion | 3.3 | `Religion` | 49-49 | 0.0 | 8 | 1..9 |  |
| 25 | Social Group | 3.4 | `Social_Group` | 50-50 | 0.0 | 4 | 1..9 |  |
| 26 | Household's usual consumer Expenditure in A Month for purposes out of Goods and Services(Rs.) | 3.5.1 | `Usual_Expenditure` | 51-58 | 0.0 | 3381 | 0..150000 |  |
| 27 | Imputed value of usual consumption in a month out of Home Grown stock (Rs.) | 3.5.2 | `Imputed_Homegrown_Consumption` | 59-66 | 0.0 | 924 | 0..25000 |  |
| 28 | Imputed value of usual consumption in a Month from wages in kind,free collection, gifts etc. (Rs.) | 3.5.3 | `Imputed_Wages_Consumption` | 67-74 | 0.0 | 903 | 0..35000 |  |
| 29 | Household's Annual Expenditure on purchase of items like clothing, footwear etc.(Rs.) | 3.5.4 | `Annual_Clothing_Expenditure` | 75-82 | 0.0 | 2809 | 0..250000 |  |
| 30 | Household's Annual Expenditure on purchase of durables like Bedstead, TV, fridge etc.(Rs.) | 3.5.5 | `Annual_Durables_Expenditure` | 83-90 | 0.0 | 3247 | 0..900000 |  |
| 31 | Household'S Usual Consumer Expenditure In A Month (Rs.) | 3.5.6 | `Monthly_Consumer_Expenditure` | 91-98 | 0.0 | 18145 | 450..175625 |  |
| 32 | Informant Serial no. | 1.16 | `Informant_Serial_No` | 99-100 | 0.0 | 19 | 1..99 |  |
| 33 | Survey Date | 2.2(i) | `Survey_Date` | 101-108 | 0.0 | 355 | 1022024..31122024 |  |
| 34 | Total Time Taken To Canvass Sch. 10.4 | 2.4 | `Total_Time_Taken` | 109-112 | 0.0 | 106 | 20..180 |  |
| 35 | Ns count for sector x stratum x substratum x sub-sample | Generated | `NSS_Sector_Stratum_Substr_Subsam` | 113-115 | 0.0 | 14 | 1..17 | NSS |
| 36 | Ns count for sector x stratum x substratum | Generated | `NSC_Sector_Stratum_Substr` | 116-118 | 0.0 | 18 | 1..34 | NSC |
| 37 | Sub-sample wise Multiplier | Generated | `Subsample_Multiplier` | 119-128 | 0.0 | 58923 | 1773..98832766 | MULT |
| 38 | count of contributing samples for State x Sector x Stratum x Sub-Stratum in 4 Quarters | Generated | `Contrib_Sample_Count` | 129-129 | 0.0 | 1 | 4..4 | No_Qtr |
#### 2.6.6 Release 2 (Calendar 2024) — CPERV1 (person, visit 1) — 415,549 rows, 140 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | Panel |  | `Panel` | 1-2 | 0.0 | 1 |  | P4 |
| 2 | File Identification |  | `File_Identification` | 3-7 | 0.0 | 1 |  | CFVP4 |
| 3 | Schdule | 1.2 | `Schedule` | 8-10 | 0.0 | 1 | 104..104 | 104 |
| 4 | Quarter |  | `Quarter` | 11-12 | 0.0 | 4 |  | Q3,Q4,Q5,Q6 |
| 5 | Visit |  | `Visit` | 13-14 | 0.0 | 1 |  |  |
| 6 | Sector | 1.3 | `Sector` | 15-15 | 0.0 | 2 | 1..2 |  |
| 7 | State/Ut Code |  | `State_UT_Code` | 16-17 | 0.0 | 36 | 1..37 |  |
| 8 | District Code | 1.4 | `District_Code` | 18-19 | 0.0 | 75 | 1..75 |  |
| 9 | NSS-Region | 1.4 | `NSS_Region` | 20-22 | 0.0 | 87 | 11..371 |  |
| 10 | Stratum | 1.5 | `Stratum` | 23-24 | 0.0 | 6 | 1..6 |  |
| 11 | Sub-Stratum | 1.6 | `Sub_Stratum` | 25-26 | 0.0 | 41 | 1..41 |  |
| 12 | Sub-Sample | 1.11 | `Sub_Sample` | 27-27 | 0.0 | 2 | 1..2 |  |
| 13 | Fod Sub-Region | 1.12 | `FOD_Sub_Region` | 28-31 | 0.0 | 169 | 110..3613 |  |
| 14 | FSU | 1.1 | `FSU` | 32-36 | 0.0 | 12749 | 10001..26235 |  |
| 15 | Sample Sg/Sb No. | 1.13 | `Sample_Sg_Sb_No` | 37-37 | 0.0 | 2 | 1..2 |  |
| 16 | Second Stage Stratum No. | 1.14 | `Second_Stage_Stratum_No` | 38-38 | 0.0 | 4 | 1..4 |  |
| 17 | Sample Household Number | 1.15 | `Sample_Household_Number` | 39-40 | 0.0 | 8 | 1..8 |  |
| 18 | Person Serial No. | 4.1 | `Person_Serial_No` | 41-42 | 0.0 | 26 | 1..26 |  |
| 19 | Relationship To Head | 4.4 | `Relationship_To_Head` | 43-43 | 0.0 | 9 | 1..9 |  |
| 20 | Sex | 4.5 | `Sex` | 44-44 | 0.0 | 3 | 1..3 |  |
| 21 | Age | 4.6 | `Age` | 45-47 | 0.0 | 111 | 0..112 |  |
| 22 | Marital Status | 4.7 | `Marital_Status` | 48-48 | 0.0 | 4 | 1..4 |  |
| 23 | General Educaion Level | 4.8 | `General_Education_Level` | 49-50 | 0.0 | 12 | 1..13 |  |
| 24 | Technical Educaion Level | 4.9 | `Technical_Education_Level` | 51-52 | 0.0 | 16 | 1..16 |  |
| 25 | No. of years in Formal Education | 4.10 | `Years_Formal_Education` | 53-54 | 0.0 | 26 | 0..25 |  |
| 26 | Status of Current Attendance in Educational Institution | 4.11 | `Current_Attendance_Status` | 55-56 | 50.58 | 34 | 1..43 |  |
| 27 | Whether received any Vocational/Technical Training | 4.12 | `Vocational_Training` | 57-57 | 29.089 | 7 | 1..6 |  |
| 28 | Whether Training completed during last 365 Days | 4.1.3 | `Training_Completed_365_Days` | 58-58 | 97.007 | 3 | 1..2 |  |
| 29 | Field Of Training | 4.1.4 | `Field_Of_Training` | 59-60 | 97.007 | 23 | 1..99 |  |
| 30 | Duration Of Training | 4.1.5 | `Duration_Of_Training` | 61-61 | 97.007 | 7 | 1..6 |  |
| 31 | Type Of Training | 4.1.6 | `Type_Of_Training` | 62-62 | 97.007 | 4 | 1..3 |  |
| 32 | Source Of Funding The Training | 4.1.7 | `Training_Funding_Source` | 63-63 | 97.007 | 4 | 1..9 |  |
| 33 | Status Code | 5.1.3 | `Principal_Status_Code` | 64-65 | 0.0 | 14 | 11..99 |  |
| 34 | Industry Code (NIC) | 5.1.5 | `Principal_Industry_Code` | 66-70 | 60.523 | 1178 | 1111..97009 |  |
| 35 | Occupation Code (NCO) | 5.1.6 | `Principal_Occupation_Code` | 71-73 | 60.523 | 128 | 111..962 |  |
| 36 | Whether Engaged In Any Work In Subsidiary Capacity | 5.1.7 | `Subsidiary_Work_Engagement` | 74-74 | 0.0 | 2 | 1..2 |  |
| 37 | (Principal)location Of Workplace Code | 5.1.8 | `Principal_Workplace_Location` | 75-76 | 71.847 | 22 | 10..99 |  |
| 38 | (Principal) Enterprise Type Code | 5.1.9 | `Principal_Enterprise_Type` | 77-78 | 60.523 | 13 | 1..19 |  |
| 39 | (Principal) No. Of Workers In The Enterprise | 5.1.10 | `Principal_Workers_Count` | 79-79 | 60.523 | 6 | 1..9 |  |
| 40 | (Principal)  Type Of Job Contract | 5.1.11 | `Principal_Job_Contract_Type` | 80-80 | 81.776 | 5 | 1..4 |  |
| 41 | (Principal) Eligble Of Paid Leave | 5.1.12 | `Principal_Paid_Leave` | 81-81 | 81.776 | 3 | 1..2 |  |
| 42 | (Principal) Social Security Benefits | 5.1.13 | `Principal_Social_Security` | 82-82 | 81.776 | 10 | 1..9 |  |
| 43 | (Principal) Usage of product of the economic activity | 5.1.14 | `Principal_Product_Usage` | 83-83 | 88.573 | 5 | 1..4 |  |
| 44 | Status Code | 5.2.3 | `Subsidiary_Status_Code` | 84-85 | 88.252 | 7 | 11..51 |  |
| 45 | Industry Code (NIC) | 5.2.5 | `Subsidiary_Industry_Code` | 86-90 | 88.252 | 663 | 1111..97009 |  |
| 46 | Occupation Code (NCO) | 5.2.6 | `Subsidiary_Occupation_Code` | 91-93 | 88.252 | 121 | 111..962 |  |
| 47 | (Subsidiary) location Of Workplace Code | 5.2.7 | `Subsidiary_Workplace_Location` | 94-95 | 94.548 | 22 | 10..99 |  |
| 48 | (Subsidiary)  Enterprise Type Code | 5.2.8 | `Subsidiary_Enterprise_Type` | 96-97 | 88.252 | 13 | 1..19 |  |
| 49 | (Subsidiary)  No. Of Workers In The Enterprise | 5.2.9 | `Subsidiary_Workers_Count` | 98-98 | 88.252 | 6 | 1..9 |  |
| 50 | (Subsidiary)   Type Of Job Contract | 5.2.10 | `Subsidiary_Job_Contract_Type` | 99-99 | 96.595 | 5 | 1..4 |  |
| 51 | (Subsidiary)  Eligble Of Paid Leave | 5.2.11 | `Subsidiary_Paid_Leave` | 100-100 | 96.595 | 3 | 1..2 |  |
| 52 | (Subsidiary)  Social Security Benefits | 5.2.12 | `Subsidiary_Social_Security` | 101-101 | 96.595 | 10 | 1..9 |  |
| 53 | (Subsidiary) Usage of product of the economic activity | 5.2.13 | `Subsidiary_Product_Usage` | 102-102 | 93.097 | 5 | 1..4 |  |
| 54 | Ever Worked Prior to last 365 days | 5.3.5 | `Ever_Worked_365_Days` | 103-103 | 56.478 | 3 | 1..2 |  |
| 55 | Duration of engagement in the economic activity in usual Principal Activity Status | 5.3.6 | `Principal_Duration` | 104-104 | 60.523 | 6 | 1..5 |  |
| 56 | Duration of engagement in the economic activity in Subsidiary Activity Status | 5.3.7 | `Subsidiary_Duration` | 105-105 | 88.252 | 6 | 1..5 |  |
| 57 | Efforts undertaken to search work | 5.3.8 | `Work_Search_Efforts` | 106-106 | 97.9 | 8 | 1..7 |  |
| 58 | Duration of spell of Unemployment | 5.3.9 | `Unemployment_Duration` | 107-107 | 98.134 | 6 | 1..5 |  |
| 59 | Whether Ever Worked | 5.3.10 | `Ever_Worked` | 108-108 | 50.653 | 3 | 1..2 |  |
| 60 | Reason for not working in last 365 days | 5.3.11 | `Reason_Not_Working` | 109-110 | 92.962 | 11 | 1..19 |  |
| 61 | Main reason for being in Principal activity status (91 to 97) | 5.3.12 | `Main_Reason_Principal_Status` | 111-111 | 52.52 | 9 | 1..9 |  |
| 62 | Status Code for activity 1 | 6.4/3.1 | `Day7_Act1_Status_Code` | 112-113 | 0.0 | 21 | 11..99 |  |
| 63 | Industry Code (NIC) for activity 1 | 6.5/3.1 | `Day7_Act1_Industry_Code` | 114-115 | 60.938 | 87 | 1..97 |  |
| 64 | hours actuallly worked for activity 1 on 7 th day | 6.6/3.1 | `Day7_Act1_Hours` | 116-117 | 0.0 | 20 | 0..20 |  |
| 65 | wage earning for activity 1 on 7 th day | 6.9/3.1 | `Day7_Act1_Wage` | 118-122 | 0.0 | 162 | 0..2000 |  |
| 66 | Status Code for activity 2 | 6.4/3.1 | `Day7_Act2_Status_Code` | 123-124 | 98.629 | 10 | 11..72 |  |
| 67 | Industry Code (NIC) for activity 2 | 6.5/3.1 | `Day7_Act2_Industry_Code` | 125-126 | 98.629 | 68 | 1..97 |  |
| 68 | hours actuallly worked for activity 2 on 7 th day | 6.6/3.1 | `Day7_Act2_Hours` | 127-128 | 0.0 | 11 | 0..10 |  |
| 69 | wage earning for activity 2 on 7 th day | 6.9/3.1 | `Day7_Act2_Wage` | 129-133 | 0.0 | 37 | 0..850 |  |
| 70 | total hours actually worked on 7th day | 6.7/3.1 | `Day7_Total_Hours` | 134-135 | 0.0 | 20 | 0..20 |  |
| 71 | hours available for aditional worked on 7th day | 6.8/3.1 | `Day7_Additional_Work_Hours` | 136-137 | 0.0 | 7 | 0..6 |  |
| 72 | Status Code for activity 1 | 6.4/3.2 | `Day6_Act1_Status_Code` | 138-139 | 0.0 | 21 | 11..99 |  |
| 73 | Industry Code (NIC) for activity 1 | 6.5/3.2 | `Day6_Act1_Industry_Code` | 140-141 | 61.104 | 87 | 1..97 |  |
| 74 | hours actuallly worked for activity 1 on 6 th day | 6.6/3.2 | `Day6_Act1_Hours` | 142-143 | 0.0 | 19 | 0..18 |  |
| 75 | wage earning for activity 1 on 7 th day | 6.9/3.2 | `Day6_Act1_Wage` | 144-148 | 0.0 | 158 | 0..1750 |  |
| 76 | Status Code for activity 2 | 6.4/3.2 | `Day6_Act2_Status_Code` | 149-150 | 98.574 | 11 | 11..72 |  |
| 77 | Industry Code (NIC) for activity 2 | 6.5/3.2 | `Day6_Act2_Industry_Code` | 151-152 | 98.574 | 69 | 1..97 |  |
| 78 | hours actuallly worked for activity 2 on 6 th day | 6.6/3.2 | `Day6_Act2_Hours` | 153-154 | 0.0 | 12 | 0..11 |  |
| 79 | wage earning for activity 2 on 6 th day | 6.9/3.2 | `Day6_Act2_Wage` | 155-159 | 0.0 | 44 | 0..800 |  |
| 80 | total hours actually worked on 6th day | 6.7/3.2 | `Day6_Total_Hours` | 160-161 | 0.0 | 19 | 0..18 |  |
| 81 | hours available for aditional worked on 6th day | 6.8/3.2 | `Day6_Additional_Work_Hours` | 162-163 | 0.0 | 7 | 0..6 |  |
| 82 | Status Code for activity 1 | 6.4/3.3 | `Day5_Act1_Status_Code` | 164-165 | 0.0 | 21 | 11..99 |  |
| 83 | Industry Code (NIC) for activity 1 | 6.5/3.3 | `Day5_Act1_Industry_Code` | 166-167 | 61.588 | 87 | 1..97 |  |
| 84 | hours actuallly worked for activity 1 on5 th day | 6.6/3.3 | `Day5_Act1_Hours` | 168-169 | 0.0 | 18 | 0..18 |  |
| 85 | wage earning for activity 1 on 5 th day | 6.9/3.3 | `Day5_Act1_Wage` | 170-174 | 0.0 | 155 | 0..2000 |  |
| 86 | Status Code for activity 2 | 6.4/3.3 | `Day5_Act2_Status_Code` | 175-176 | 98.619 | 11 | 11..72 |  |
| 87 | Industry Code (NIC) for activity 2 | 6.5/3.3 | `Day5_Act2_Industry_Code` | 177-178 | 98.619 | 67 | 1..97 |  |
| 88 | hours actuallly worked for activity 2 on 5 th day | 6.6/3.3 | `Day5_Act2_Hours` | 179-180 | 0.0 | 11 | 0..10 |  |
| 89 | wage earning for activity 2 on 5 th day | 6.9/3.3 | `Day5_Act2_Wage` | 181-185 | 0.0 | 43 | 0..930 |  |
| 90 | total hours actually worked on 5th day | 6.7/3.3 | `Day5_Total_Hours` | 186-187 | 0.0 | 18 | 0..18 |  |
| 91 | hours available for aditional worked on 5th day | 6.8/3.3 | `Day5_Additional_Work_Hours` | 188-189 | 0.0 | 7 | 0..6 |  |
| 92 | Status Code for activity 1 | 6.4/3.4 | `Day4_Act1_Status_Code` | 190-191 | 0.0 | 21 | 11..99 |  |
| 93 | Industry Code (NIC) for activity 1 | 6.5/3.4 | `Day4_Act1_Industry_Code` | 192-193 | 62.094 | 88 | 1..99 |  |
| 94 | hours actuallly worked for activity 1 on 4th day | 6.6/3.4 | `Day4_Act1_Hours` | 194-195 | 0.0 | 19 | 0..18 |  |
| 95 | wage earning for activity 1 on 4th day | 6.9/3.4 | `Day4_Act1_Wage` | 196-200 | 0.0 | 163 | 0..2000 |  |
| 96 | Status Code for activity 2 | 6.4/3.4 | `Day4_Act2_Status_Code` | 201-202 | 98.691 | 10 | 11..72 |  |
| 97 | Industry Code (NIC) for activity 2 | 6.5/3.4 | `Day4_Act2_Industry_Code` | 203-204 | 98.691 | 67 | 1..97 |  |
| 98 | hours actuallly worked for activity 2 on 4th day | 6.6/3.4 | `Day4_Act2_Hours` | 205-206 | 0.0 | 10 | 0..9 |  |
| 99 | wage earning for activity 2 on 4th day | 6.9/3.4 | `Day4_Act2_Wage` | 207-211 | 0.0 | 39 | 0..800 |  |
| 100 | total hours actually worked on 4th day | 6.7/3.4 | `Day4_Total_Hours` | 212-213 | 0.0 | 19 | 0..18 |  |
| 101 | hours available for aditional worked on 4th day | 6.8/3.4 | `Day4_Additional_Work_Hours` | 214-215 | 0.0 | 8 | 0..8 |  |
| 102 | Status Code for activity 1 | 6.4/3.5 | `Day3_Act1_Status_Code` | 216-217 | 0.0 | 21 | 11..99 |  |
| 103 | Industry Code (NIC) for activity 1 | 6.5/3.5 | `Day3_Act1_Industry_Code` | 218-219 | 62.301 | 87 | 1..97 |  |
| 104 | hours actuallly worked for activity 1 on 3rd day | 6.6/3.5 | `Day3_Act1_Hours` | 220-221 | 0.0 | 18 | 0..18 |  |
| 105 | wage earning for activity 1 on 3rd day | 6.9/3.5 | `Day3_Act1_Wage` | 222-226 | 0.0 | 154 | 0..1800 |  |
| 106 | Status Code for activity 2 | 6.4/3.5 | `Day3_Act2_Status_Code` | 227-228 | 98.696 | 10 | 11..72 |  |
| 107 | Industry Code (NIC) for activity 2 | 6.5/3.5 | `Day3_Act2_Industry_Code` | 229-230 | 98.696 | 67 | 1..97 |  |
| 108 | hours actuallly worked for activity 2 on 3rd day | 6.6/3.5 | `Day3_Act2_Hours` | 231-232 | 0.0 | 11 | 0..10 |  |
| 109 | wage earning for activity 2 on 3 rd day | 6.9/3.5 | `Day3_Act2_Wage` | 233-237 | 0.0 | 37 | 0..760 |  |
| 110 | total hours actually worked on 3rd day | 6.7/3.5 | `Day3_Total_Hours` | 238-239 | 0.0 | 18 | 0..18 |  |
| 111 | hours available for aditional worked on 3rd day | 6.8/3.5 | `Day3_Additional_Work_Hours` | 240-241 | 0.0 | 7 | 0..6 |  |
| 112 | Status Code for activity 1 | 6.4/3.6 | `Day2_Act1_Status_Code` | 242-243 | 0.0 | 21 | 11..99 |  |
| 113 | Industry Code (NIC) for activity 1 | 6.5/3.6 | `Day2_Act1_Industry_Code` | 244-245 | 62.174 | 87 | 1..97 |  |
| 114 | hours actuallly worked for activity 1 on 2nd day | 6.6/3.6 | `Day2_Act1_Hours` | 246-247 | 0.0 | 20 | 0..20 |  |
| 115 | wage earning for activity 1 on 2nd day | 6.9/3.6 | `Day2_Act1_Wage` | 248-252 | 0.0 | 157 | 0..3000 |  |
| 116 | Status Code for activity 2 | 6.4/3.6 | `Day2_Act2_Status_Code` | 253-254 | 98.717 | 11 | 11..72 |  |
| 117 | Industry Code (NIC) for activity 2 | 6.5/3.6 | `Day2_Act2_Industry_Code` | 255-256 | 98.717 | 67 | 1..97 |  |
| 118 | hours actuallly worked for activity 2 on 2nd day | 6.6/3.6 | `Day2_Act2_Hours` | 257-258 | 0.0 | 11 | 0..10 |  |
| 119 | wage earning for activity 2 on 2nd day | 6.9/3.6 | `Day2_Act2_Wage` | 259-263 | 0.0 | 36 | 0..850 |  |
| 120 | total hours actually worked on 2nd day | 6.7/3.6 | `Day2_Total_Hours` | 264-265 | 0.0 | 20 | 0..20 |  |
| 121 | hours available for aditional worked on 2nd day | 6.8/3.6 | `Day2_Additional_Work_Hours` | 266-267 | 0.0 | 7 | 0..6 |  |
| 122 | Status Code for activity 1 | 6.4/3.7 | `Day1_Act1_Status_Code` | 268-269 | 0.0 | 21 | 11..99 |  |
| 123 | Industry Code (NIC) for activity 1 | 6.5/3.7 | `Day1_Act1_Industry_Code` | 270-271 | 61.957 | 87 | 1..97 |  |
| 124 | hours actuallly worked for activity 1 on 1st day | 6.6/3.7 | `Day1_Act1_Hours` | 272-273 | 0.0 | 19 | 0..20 |  |
| 125 | wage earning for activity 1 on 1st day | 6.9/3.7 | `Day1_Act1_Wage` | 274-278 | 0.0 | 153 | 0..3000 |  |
| 126 | Status Code for activity 2 | 6.4/3.7 | `Day1_Act2_Status_Code` | 279-280 | 98.726 | 10 | 11..72 |  |
| 127 | Industry Code (NIC) for activity 2 | 6.5/3.7 | `Day1_Act2_Industry_Code` | 281-282 | 98.726 | 69 | 1..97 |  |
| 128 | hours actuallly worked for activity 2 on 1st day | 6.6/3.7 | `Day1_Act2_Hours` | 283-284 | 0.0 | 10 | 0..12 |  |
| 129 | wage earning for activity 2 on 1st day | 6.9/3.7 | `Day1_Act2_Wage` | 285-289 | 0.0 | 37 | 0..800 |  |
| 130 | total hours actually worked on 1st day | 6.7/3.7 | `Day1_Total_Hours` | 290-291 | 0.0 | 19 | 0..20 |  |
| 131 | hours available for aditional worked on 1st day | 6.8/3.7 | `Day1_Additional_Work_Hours` | 292-293 | 0.0 | 7 | 0..6 |  |
| 132 | Current Weekly Status (CWS) | 6.5 | `CWS_Status_Code` | 294-295 | 0.0 | 21 | 11..99 |  |
| 133 | Industry Code (CWS) | 6.6 | `CWS_Industry_Code` | 296-297 | 59.349 | 87 | 1..97 |  |
| 134 | Occupation Code (CWS) | 6.7 | `CWS_Occupation_Code` | 298-300 | 59.349 | 128 | 111..962 |  |
| 135 | Earnings For Regular Salaried/Wage Activity | 6.9 | `CWS_Earnings_Salaried` | 301-308 | 0.0 | 2391 | 0..520000 |  |
| 136 | Earnings For Self Employed | 6.10 | `CWS_Earnings_SelfEmployed` | 309-316 | 0.0 | 1850 | -10000..500000 |  |
| 137 | Ns count for sector x stratum x substratum x sub-sample | Generated | `Ns_Count_Sector_Stratum_Substratum_Subsample` | 317-319 | 0.0 | 14 | 1..17 | NSS |
| 138 | Ns count for sector x stratum x substratum | Generated | `Ns_Count_Sector_Stratum_Substratum` | 320-322 | 0.0 | 18 | 1..34 | NSC |
| 139 | Sub-sample wise Multiplier | Generated | `Subsample_Multiplier` | 323-332 | 0.0 | 58923 | 1773..98832766 | MULT |
| 140 | count of contributing samples for State x Sector x Stratum x Sub-Stratum in 4 Quarters | Generated | `State_Sector_Stratum_Substra` | 333-333 | 0.0 | 1 | 4..4 | No_Qtr |
#### 2.6.7 Release 3 (Post2025) — CHHV1 (household, visit 1) — 270,472 rows, 48 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `file_id` | 1-5 | 0.0 | 1 |  | CFVH5 |
| 2 | Schdule | 1.2 | `sch` | 6-8 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr` | 9-10 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Month |  | `month` | 11-12 | 0.0 | 12 | 1..12 | 01 to 12 |
| 5 | Visit |  | `visit` | 13-14 | 0.0 | 1 |  | V1 for first visit |
| 6 | Sector | 1.3 | `sec` | 15-15 | 0.0 | 2 | 1..2 |  |
| 7 | State/Ut Code | 0.1 | `st` | 16-17 | 0.0 | 36 | 1..37 |  |
| 8 | District Code | 1.5 | `dc` | 18-19 | 0.0 | 75 | 1..75 |  |
| 9 | NSS-Region | 1.4 | `nss_reg` | 20-22 | 0.0 | 87 | 11..371 |  |
| 10 | Basic Stratum |  | `bstrm` | 23-26 | 0.0 | 145 |  |  |
| 11 | Stratum | 1.6 | `strm` | 27-29 | 0.0 | 112 | 1..999 |  |
| 12 | Group |  | `grp` | 30-30 | 0.0 | 3 | 1..9 |  |
| 13 | Sub-Stratum | 1.7 | `sstrm` | 31-32 | 0.0 | 14 | 1..14 |  |
| 14 | Fod Sub-Region | 1.12 | `sro` | 33-36 | 0.0 | 169 | 110..3613 |  |
| 15 | FSU | 1.1 | `mfsu` | 37-41 | 0.0 | 22594 | 10001..40188 |  |
| 16 | Second Stage Stratum No. | 1.15 | `sss` | 42-42 | 0.0 | 4 | 1..4 |  |
| 17 | Sample Household Number | 1.16 | `ssu` | 43-44 | 0.0 | 12 | 1..12 |  |
| 18 | Month of Survey | 1.10 | `smonth` | 45-46 | 0.0 | 12 | 1..12 |  |
| 19 | Response Code | 1.18 | `resp_code` | 47-47 | 0.0 | 5 | 1..9 |  |
| 20 | Survey Code | 1.19 | `svc` | 48-48 | 0.0 | 2 | 1..2 |  |
| 21 | Reason for Substitution of original household | 1.20 | `rea_sub` | 49-49 | 90.259 | 5 | 1..9 |  |
| 22 | Household Size | 3.1 | `hh_size` | 50-51 | 0.0 | 29 | 1..30 |  |
| 23 | Household Type | 3.2 | `hhtype` | 52-52 | 0.0 | 6 | 1..9 |  |
| 24 | Religion | 3.3 | `relg` | 53-53 | 0.0 | 8 | 1..9 |  |
| 25 | Social Group | 3.4 | `sg` | 54-54 | 0.0 | 4 | 1..9 |  |
| 26 | Household's usual consumer Expenditure in A Month for purposes out of Goods and Services(Rs.) | 3.5.1 | `hce1` | 55-64 | 0.0 | 4860 | 0..320500 |  |
| 27 | Imputed value of usual consumption in a month out of Home Grown stock (Rs.) | 3.5.2 | `hce2` | 65-74 | 0.0 | 1470 | 0..30000 |  |
| 28 | Imputed value of usual consumption in a Month from wages in kind,free collection, gifts etc. (Rs.) | 3.5.3 | `hce3` | 75-84 | 0.0 | 1320 | 0..200000 |  |
| 29 | Household's Annual Expenditure on purchase of items like clothing, footwear etc.(Rs.) | 3.5.4 | `hce4` | 85-94 | 0.0 | 4491 | 0..350000 |  |
| 30 | Household's Annual Expenditure on purchase of durables like Bedstead, TV, fridge etc.(Rs.) | 3.5.5 | `hce5` | 95-104 | 0.0 | 4834 | 0..3650000 |  |
| 31 | Household'S Usual Consumer Expenditure In A Month (Rs.) | 3.5.6 | `hce_tot` | 105-114 | 0.0 | 26660 | 400..332333 |  |
| 32 | land possessed as on the date of survey (code) | 3.6.1 | `lposs` | 115-116 | 0.0 | 12 | 1..99 |  |
| 33 | land leased-out as on the date of survey (code) | 3.6.2 | `llease` | 117-118 | 0.0 | 12 | 1..99 |  |
| 34 | rent received from land and rental received from building usually in a month: make entry in whole number of rupees | 3.7.1 | `rent` | 119-128 | 0.0 | 563 | 0..500000 |  |
| 35 | interest received from investment or savings usually in a month: make entry in whole number of rupees | 3.7.2 | `interest` | 129-138 | 0.0 | 1870 | 0..350000 |  |
| 36 | pension received usually in a month: make entry in whole number of rupees | 3.7.3 | `pension` | 139-148 | 0.0 | 1414 | 0..260000 |  |
| 37 | remittances usually received in a month: make entry in whole number of rupees | 3.7.4 | `remit` | 149-158 | 0.0 | 828 | 0..150000 |  |
| 38 | total of items 7.1 to 7.4: make entry in whole number of rupees | 3.7.5 | `inc_tot` | 159-168 | 0.0 | 10907 | 0..705000 |  |
| 39 | Informant Serial no. | 1.17 | `inf_srl` | 169-170 | 0.0 | 19 | 1..99 |  |
| 40 | Survey Date | 2.2(i) | `sur_date` | 171-180 | 0.0 | 354 | 1052025..31102025 |  |
| 41 | Total Time Taken To Canvass Sch. 10.4 | 2.4 | `sur_time` | 181-184 | 0.0 | 104 | 20..190 |  |
| 42 | Ns count (# of FSUs surveyed) for sector x stratum x group x substratum |  | `nsc` | 185-187 | 0.0 | 3 | 10..12 |  |
| 43 | Multiplier |  | `mult` | 188-197 | 0.0 | 38468 | 307..10739563 |  |
| 44 | Total Sub-Division |  | `totalsd` | 198-200 | 0.0 | 9 | 1..10 | Sch. 0.0, block 4.2A, item 3 |
| 45 | Stratum size |  | `zst` | 201-210 | 0.0 | 1202 | 14..42999 |  |
| 46 | Number of listed households |  | `caph` | 211-214 | 0.0 | 348 | 1..1085 | Sch. 0.0, block 6, col. 4 |
| 47 | Number of selected households |  | `smallh` | 215-216 | 0.0 | 12 | 1..12 | Sch. 0.0, block 6, col. 5 |
| 48 | Panel code |  | `panel` | 217-218 | 0.0 | 1 | 5..5 | 05' generated |
#### 2.6.8 Release 3 (Post2025) — CPERV1 (person, visit 1) — 1,148,634 rows, 153 columns

| # | Full Name (documentation) | Block.Item | CSV column | Bytes | %Blank | #Unique | Numeric range | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | File Identification |  | `file_id` | 1-5 | 0.0 | 1 |  | CFVP5 |
| 2 | Schdule | 1.2 | `sch` | 6-8 | 0.0 | 1 | 104..104 | 104 |
| 3 | Quarter |  | `qtr` | 9-10 | 0.0 | 4 |  | Q1 to Q4 |
| 4 | Month |  | `month` | 11-12 | 0.0 | 12 | 1..12 | 01 to 12 |
| 5 | Visit |  | `visit` | 13-14 | 0.0 | 1 |  | V1 for first visit |
| 6 | Sector | 1.3 | `sec` | 15-15 | 0.0 | 2 | 1..2 |  |
| 7 | State/Ut Code | 0.1 | `st` | 16-17 | 0.0 | 36 | 1..37 |  |
| 8 | District Code | 1.5 | `dc` | 18-19 | 0.0 | 75 | 1..75 |  |
| 9 | NSS-Region | 1.4 | `nss_reg` | 20-22 | 0.0 | 87 | 11..371 |  |
| 10 | Basic Stratum |  | `bstrm` | 23-26 | 0.0 | 145 |  |  |
| 11 | Stratum | 1.6 | `strm` | 27-29 | 0.0 | 112 | 1..999 |  |
| 12 | Group |  | `grp` | 30-30 | 0.0 | 3 | 1..9 |  |
| 13 | Sub-Stratum | 1.7 | `sstrm` | 31-32 | 0.0 | 14 | 1..14 |  |
| 14 | Fod Sub-Region | 1.12 | `sro` | 33-36 | 0.0 | 169 | 110..3613 |  |
| 15 | FSU | 1.1 | `mfsu` | 37-41 | 0.0 | 22594 | 10001..40188 |  |
| 16 | Second Stage Stratum No. | 1.15 | `sss` | 42-42 | 0.0 | 4 | 1..4 |  |
| 17 | Sample Household Number | 1.16 | `ssu` | 43-44 | 0.0 | 12 | 1..12 |  |
| 18 | Person Serial No. | 4.1 | `srl` | 45-46 | 0.0 | 30 | 1..30 |  |
| 19 | Relationship To Head | 4.4 | `rel` | 47-47 | 0.0 | 9 | 1..9 |  |
| 20 | Gender | 4.5 | `sex` | 48-48 | 0.0 | 3 | 1..3 |  |
| 21 | Age | 4.6 | `age` | 49-51 | 0.0 | 111 | 0..117 |  |
| 22 | Marital Status | 4.7 | `marst` | 52-52 | 0.0 | 4 | 1..4 |  |
| 23 | General Educaion Level | 4.8 | `gedu_lvl` | 53-54 | 0.0 | 12 | 1..13 |  |
| 24 | Technical Educaion Level | 4.9 | `tedu_lvl` | 55-56 | 0.0 | 16 | 1..16 |  |
| 25 | class/grade successfully completed | 4.10 | `grade` | 57-58 | 23.183 | 14 | 1..99 |  |
| 26 | year(s) of education completed prior to class I | 4.11 | `yrsbef1` | 59-59 | 23.183 | 5 | 1..9 |  |
| 27 | year(s) of education completed after the class/grade recorded in column 10 | 4.12 | `yrsaft` | 60-61 | 23.183 | 20 | 1..99 |  |
| 28 | whether the last completed year of education recorded in column 12 was the last year of education attended | 4.13 | `iflastyr` | 62-62 | 86.216 | 3 | 1..2 |  |
| 29 | No. of months attended in the last year of Education | 4.14 | `mnths` | 63-64 | 98.536 | 5 | 1..4 |  |
| 30 | Status of Current Attendance in Educational Institution | 4.15 | `curr_att` | 65-66 | 30.585 | 35 | 1..43 | Up to June 2025: 0-29 years, From July 2025: 0-59 years |
| 31 | whether attended secondary education | 4.16 | `secondary` | 67-68 | 87.523 | 4 | 1..3 |  |
| 32 | Whether received any Vocational/Technical Training | 4.17 | `voc` | 69-69 | 28.231 | 7 | 1..6 |  |
| 33 | whether received or receiving any training or course for entrance in higher education or for employment exams by an institute / training center | 4.18 | `trg` | 70-70 | 78.416 | 3 | 1..2 | From July 2025 |
| 34 | when the training / course mentioned in col 17 or col 18 was completed | 4.19 | `trg_com` | 71-71 | 85.703 | 6 | 1..9 | From July 2025 |
| 35 | Whether Training completed during last 365 Days | 4.1.3 | `voc_compl` | 72-72 | 98.54 | 3 | 1..2 | Up to June 2025 |
| 36 | Field Of Training | 4.1.4 | `voc_fld` | 73-74 | 97.014 | 23 | 1..99 |  |
| 37 | Duration Of Training | 4.1.5 | `voc_dur` | 75-75 | 97.014 | 7 | 1..6 |  |
| 38 | Type Of Training | 4.1.6 | `voc_typ` | 76-76 | 97.014 | 4 | 1..3 |  |
| 39 | Source Of Funding The Training | 4.1.7 | `voc_fund` | 77-77 | 97.014 | 4 | 1..9 |  |
| 40 | Nature of the certifying body from which vocational / technical training received | 4.1.8 | `voc_cert` | 78-78 | 97.014 | 7 | 1..9 |  |
| 41 | Status Code | 5.1.3 | `pas` | 79-80 | 0.0 | 14 | 11..99 |  |
| 42 | Industry Code (NIC) | 5.1.5 | `ind_pas` | 81-85 | 59.878 | 1249 | 1111..97009 |  |
| 43 | Occupation Code (NCO) | 5.1.6 | `ocu_pas` | 86-88 | 59.878 | 128 | 111..962 |  |
| 44 | Whether Engaged In Any Work In Subsidiary Capacity | 5.1.7 | `has_sas` | 89-89 | 0.0 | 2 | 1..2 |  |
| 45 | (Principal)location Of Workplace Code | 5.1.8 | `loc_pas` | 90-91 | 72.11 | 22 | 10..99 |  |
| 46 | (Principal) Enterprise Type Code | 5.1.9 | `etyp_pas` | 92-93 | 59.878 | 13 | 1..19 |  |
| 47 | (Principal) No. Of Workers In The Enterprise | 5.1.10 | `wrkr_pas` | 94-94 | 59.878 | 6 | 1..9 |  |
| 48 | (Principal)  Type Of Job Contract | 5.1.11 | `job_pas` | 95-95 | 82.524 | 5 | 1..4 |  |
| 49 | (Principal) Eligble Of Paid Leave | 5.1.12 | `leave_pas` | 96-96 | 82.524 | 3 | 1..2 |  |
| 50 | (Principal) Social Security Benefits | 5.1.13 | `ssec_pas` | 97-97 | 82.524 | 10 | 1..9 |  |
| 51 | (Principal) Usage of product of the economic activity | 5.1.14 | `ecoprd_pas` | 98-98 | 87.385 | 5 | 1..4 |  |
| 52 | Status Code | 5.2.3 | `sas` | 99-100 | 89.853 | 7 | 11..51 |  |
| 53 | Industry Code (NIC) | 5.2.5 | `ind_sas` | 101-105 | 89.853 | 885 | 1111..97009 |  |
| 54 | Occupation Code (NCO) | 5.2.6 | `ocu_sas` | 106-108 | 89.853 | 126 | 111..962 |  |
| 55 | (Subsidiary) location Of Workplace Code | 5.2.7 | `loc_sas` | 109-110 | 95.424 | 22 | 10..99 |  |
| 56 | (Subsidiary)  Enterprise Type Code | 5.2.8 | `etyp_sas` | 111-112 | 89.853 | 13 | 1..19 |  |
| 57 | (Subsidiary)  No. Of Workers In The Enterprise | 5.2.9 | `wrkr_sas` | 113-113 | 89.853 | 6 | 1..9 |  |
| 58 | (Subsidiary)   Type Of Job Contract | 5.2.10 | `job_sas` | 114-114 | 97.11 | 5 | 1..4 |  |
| 59 | (Subsidiary)  Eligble Of Paid Leave | 5.2.11 | `leave_sas` | 115-115 | 97.11 | 3 | 1..2 |  |
| 60 | (Subsidiary)  Social Security Benefits | 5.2.12 | `ssec_sas` | 116-116 | 97.11 | 10 | 1..9 |  |
| 61 | (Subsidiary) Usage of product of the economic activity | 5.2.13 | `ecoprd_sas` | 117-117 | 94.046 | 5 | 1..4 |  |
| 62 | Ever Worked Prior to last 365 days | 5.3.5 | `wrk_365` | 118-118 | 56.905 | 3 | 1..2 |  |
| 63 | Duration of engagement in the economic activity in usual Principal Activity Status | 5.3.6 | `dur_pas` | 119-119 | 59.878 | 6 | 1..5 |  |
| 64 | Duration of engagement in the economic activity in Subsidiary Activity Status | 5.3.7 | `dur_sas` | 120-120 | 89.853 | 6 | 1..5 |  |
| 65 | Efforts undertaken to search work | 5.3.8 | `eff_pas` | 121-121 | 98.089 | 8 | 1..7 |  |
| 66 | Duration of spell of Unemployment | 5.3.9 | `dur_unp` | 122-122 | 98.24 | 6 | 1..5 |  |
| 67 | Whether Ever Worked | 5.3.10 | `evr_wrk` | 123-123 | 50.116 | 3 | 1..2 |  |
| 68 | Reason for not working in last 365 days | 5.3.11 | `rea_nw` | 124-125 | 92.524 | 11 | 1..19 |  |
| 69 | Main reason for being in Principal activity status (91 to 97) | 5.3.12 | `rea` | 126-126 | 51.877 | 9 | 1..9 |  |
| 70 | Status Code for activity 1 | 6.4/3.1 | `das17` | 127-128 | 0.0 | 21 | 11..99 |  |
| 71 | Industry Code (NIC) for activity 1 | 6.5/3.1 | `ind17` | 129-130 | 61.649 | 87 | 1..97 |  |
| 72 | hours actuallly worked for activity 1 on 7 th day | 6.6/3.1 | `hr17` | 131-132 | 0.0 | 18 | 0..20 |  |
| 73 | wage earning for activity 1 on 7 th day | 6.9/3.1 | `ern17` | 133-137 | 0.0 | 204 | 0..3000 |  |
| 74 | Status Code for activity 2 | 6.4/3.1 | `das27` | 138-139 | 98.681 | 11 | 11..72 |  |
| 75 | Industry Code (NIC) for activity 2 | 6.5/3.1 | `ind27` | 140-141 | 98.681 | 75 | 1..97 |  |
| 76 | hours actuallly worked for activity 2 on 7 th day | 6.6/3.1 | `hr27` | 142-143 | 0.0 | 12 | 0..12 |  |
| 77 | wage earning for activity 2 on 7 th day | 6.9/3.1 | `ern27` | 144-148 | 0.0 | 60 | 0..1000 |  |
| 78 | total hours actually worked on 7th day | 6.7/3.1 | `hr7` | 149-150 | 0.0 | 19 | 0..20 |  |
| 79 | hours available for aditional worked on 7th day | 6.8/3.1 | `ahr7` | 151-152 | 0.0 | 7 | 0..8 |  |
| 80 | Status Code for activity 1 | 6.4/3.2 | `das16` | 153-154 | 0.0 | 21 | 11..99 |  |
| 81 | Industry Code (NIC) for activity 1 | 6.5/3.2 | `ind16` | 155-156 | 61.898 | 87 | 1..97 |  |
| 82 | hours actuallly worked for activity 1 on 6 th day | 6.6/3.2 | `hr16` | 157-158 | 0.0 | 18 | 0..20 |  |
| 83 | wage earning for activity 1 on 7 th day | 6.9/3.2 | `ern16` | 159-163 | 0.0 | 217 | 0..3000 |  |
| 84 | Status Code for activity 2 | 6.4/3.2 | `das26` | 164-165 | 98.641 | 11 | 11..72 |  |
| 85 | Industry Code (NIC) for activity 2 | 6.5/3.2 | `ind26` | 166-167 | 98.641 | 79 | 1..97 |  |
| 86 | hours actuallly worked for activity 2 on 6 th day | 6.6/3.2 | `hr26` | 168-169 | 0.0 | 12 | 0..12 |  |
| 87 | wage earning for activity 2 on 6 th day | 6.9/3.2 | `ern26` | 170-174 | 0.0 | 61 | 0..1000 |  |
| 88 | total hours actually worked on 6th day | 6.7/3.2 | `hr6` | 175-176 | 0.0 | 19 | 0..20 |  |
| 89 | hours available for aditional worked on 6th day | 6.8/3.2 | `ahr6` | 177-178 | 0.0 | 7 | 0..8 |  |
| 90 | Status Code for activity 1 | 6.4/3.3 | `das15` | 179-180 | 0.0 | 21 | 11..99 |  |
| 91 | Industry Code (NIC) for activity 1 | 6.5/3.3 | `ind15` | 181-182 | 62.422 | 87 | 1..97 |  |
| 92 | hours actuallly worked for activity 1 on5 th day | 6.6/3.3 | `hr15` | 183-184 | 0.0 | 18 | 0..20 |  |
| 93 | wage earning for activity 1 on 5 th day | 6.9/3.3 | `ern15` | 185-189 | 0.0 | 202 | 0..3000 |  |
| 94 | Status Code for activity 2 | 6.4/3.3 | `das25` | 190-191 | 98.701 | 11 | 11..72 |  |
| 95 | Industry Code (NIC) for activity 2 | 6.5/3.3 | `ind25` | 192-193 | 98.701 | 76 | 1..97 |  |
| 96 | hours actuallly worked for activity 2 on 5 th day | 6.6/3.3 | `hr25` | 194-195 | 0.0 | 11 | 0..10 |  |
| 97 | wage earning for activity 2 on 5 th day | 6.9/3.3 | `ern25` | 196-200 | 0.0 | 56 | 0..1000 |  |
| 98 | total hours actually worked on 5th day | 6.7/3.3 | `hr5` | 201-202 | 0.0 | 19 | 0..20 |  |
| 99 | hours available for aditional worked on 5th day | 6.8/3.3 | `ahr5` | 203-204 | 0.0 | 8 | 0..8 |  |
| 100 | Status Code for activity 1 | 6.4/3.4 | `das14` | 205-206 | 0.0 | 21 | 11..99 |  |
| 101 | Industry Code (NIC) for activity 1 | 6.5/3.4 | `ind14` | 207-208 | 62.902 | 87 | 1..97 |  |
| 102 | hours actuallly worked for activity 1 on 4th day | 6.6/3.4 | `hr14` | 209-210 | 0.0 | 18 | 0..20 |  |
| 103 | wage earning for activity 1 on 4th day | 6.9/3.4 | `ern14` | 211-215 | 0.0 | 201 | 0..2500 |  |
| 104 | Status Code for activity 2 | 6.4/3.4 | `das24` | 216-217 | 98.756 | 12 | 11..72 |  |
| 105 | Industry Code (NIC) for activity 2 | 6.5/3.4 | `ind24` | 218-219 | 98.756 | 75 | 1..97 |  |
| 106 | hours actuallly worked for activity 2 on 4th day | 6.6/3.4 | `hr24` | 220-221 | 0.0 | 12 | 0..11 |  |
| 107 | wage earning for activity 2 on 4th day | 6.9/3.4 | `ern24` | 222-226 | 0.0 | 58 | 0..1000 |  |
| 108 | total hours actually worked on 4th day | 6.7/3.4 | `hr4` | 227-228 | 0.0 | 19 | 0..20 |  |
| 109 | hours available for aditional worked on 4th day | 6.8/3.4 | `ahr4` | 229-230 | 0.0 | 9 | 0..8 |  |
| 110 | Status Code for activity 1 | 6.4/3.5 | `das13` | 231-232 | 0.0 | 21 | 11..99 |  |
| 111 | Industry Code (NIC) for activity 1 | 6.5/3.5 | `ind13` | 233-234 | 63.086 | 88 | 1..99 |  |
| 112 | hours actuallly worked for activity 1 on 3rd day | 6.6/3.5 | `hr13` | 235-236 | 0.0 | 18 | 0..20 |  |
| 113 | wage earning for activity 1 on 3rd day | 6.9/3.5 | `ern13` | 237-241 | 0.0 | 209 | 0..2500 |  |
| 114 | Status Code for activity 2 | 6.4/3.5 | `das23` | 242-243 | 98.799 | 12 | 11..72 |  |
| 115 | Industry Code (NIC) for activity 2 | 6.5/3.5 | `ind23` | 244-245 | 98.799 | 74 | 1..97 |  |
| 116 | hours actuallly worked for activity 2 on 3rd day | 6.6/3.5 | `hr23` | 246-247 | 0.0 | 13 | 0..12 |  |
| 117 | wage earning for activity 2 on 3 rd day | 6.9/3.5 | `ern23` | 248-252 | 0.0 | 56 | 0..1000 |  |
| 118 | total hours actually worked on 3rd day | 6.7/3.5 | `hr3` | 253-254 | 0.0 | 19 | 0..20 |  |
| 119 | hours available for aditional worked on 3rd day | 6.8/3.5 | `ahr3` | 255-256 | 0.0 | 8 | 0..8 |  |
| 120 | Status Code for activity 1 | 6.4/3.6 | `das12` | 257-258 | 0.0 | 21 | 11..99 |  |
| 121 | Industry Code (NIC) for activity 1 | 6.5/3.6 | `ind12` | 259-260 | 63.022 | 87 | 1..97 |  |
| 122 | hours actuallly worked for activity 1 on 2nd day | 6.6/3.6 | `hr12` | 261-262 | 0.0 | 18 | 0..20 |  |
| 123 | wage earning for activity 1 on 2nd day | 6.9/3.6 | `ern12` | 263-267 | 0.0 | 203 | 0..3000 |  |
| 124 | Status Code for activity 2 | 6.4/3.6 | `das22` | 268-269 | 98.807 | 11 | 11..72 |  |
| 125 | Industry Code (NIC) for activity 2 | 6.5/3.6 | `ind22` | 270-271 | 98.807 | 73 | 1..97 |  |
| 126 | hours actuallly worked for activity 2 on 2nd day | 6.6/3.6 | `hr22` | 272-273 | 0.0 | 13 | 0..12 |  |
| 127 | wage earning for activity 2 on 2nd day | 6.9/3.6 | `ern22` | 274-278 | 0.0 | 53 | 0..1500 |  |
| 128 | total hours actually worked on 2nd day | 6.7/3.6 | `hr2` | 279-280 | 0.0 | 19 | 0..20 |  |
| 129 | hours available for aditional worked on 2nd day | 6.8/3.6 | `ahr2` | 281-282 | 0.0 | 7 | 0..8 |  |
| 130 | Status Code for activity 1 | 6.4/3.7 | `das11` | 283-284 | 0.0 | 21 | 11..99 |  |
| 131 | Industry Code (NIC) for activity 1 | 6.5/3.7 | `ind11` | 285-286 | 62.845 | 88 | 1..99 |  |
| 132 | hours actuallly worked for activity 1 on 1st day | 6.6/3.7 | `hr11` | 287-288 | 0.0 | 18 | 0..20 |  |
| 133 | wage earning for activity 1 on 1st day | 6.9/3.7 | `ern11` | 289-293 | 0.0 | 205 | 0..3000 |  |
| 134 | Status Code for activity 2 | 6.4/3.7 | `das21` | 294-295 | 98.833 | 11 | 11..72 |  |
| 135 | Industry Code (NIC) for activity 2 | 6.5/3.7 | `ind21` | 296-297 | 98.833 | 74 | 1..97 |  |
| 136 | hours actuallly worked for activity 2 on 1st day | 6.6/3.7 | `hr21` | 298-299 | 0.0 | 13 | 0..12 |  |
| 137 | wage earning for activity 2 on 1st day | 6.9/3.7 | `ern21` | 300-304 | 0.0 | 51 | 0..1500 |  |
| 138 | total hours actually worked on 1st day | 6.7/3.7 | `hr1` | 305-306 | 0.0 | 19 | 0..20 |  |
| 139 | hours available for aditional worked on 1st day | 6.8/3.7 | `ahr1` | 307-308 | 0.0 | 8 | 0..8 |  |
| 140 | total hours actually worked during the week | 6.4 (7) | `tothrs_wrk` | 309-311 | 0.0 | 109 | 0..128 |  |
| 141 | total hours available for additional work | 6.4 (8) | `totadl_wrk` | 312-314 | 0.0 | 37 | 0..56 |  |
| 142 | Current Weekly Status (CWS) | 6.5 | `acws` | 315-316 | 0.0 | 21 | 11..99 |  |
| 143 | Industry Code (CWS) | 6.6 | `aind_cws` | 317-318 | 60.308 | 87 | 1..97 |  |
| 144 | Occupation Code (CWS) | 6.7 | `ocu_cws` | 319-321 | 60.308 | 128 | 111..962 |  |
| 145 | Earnings For Regular Salaried/Wage Activity | 6.9 | `ern_reg` | 322-329 | 0.0 | 3701 | 0..500000 |  |
| 146 | Earnings For Self Employed | 6.10 | `ern_self` | 330-337 | 0.0 | 3086 | -30000..710000 |  |
| 147 | Ns count (# of FSUs surveyed) for sector x stratum x group x substratum |  | `nsc` | 338-340 | 0.0 | 3 | 10..12 |  |
| 148 | Multiplier |  | `mult` | 341-350 | 0.0 | 38468 | 307..10739563 |  |
| 149 | Total Sub-Division |  | `totalsd` | 351-353 | 0.0 | 9 | 1..10 | Sch. 0.0, block 4.2A, item 3 |
| 150 | Stratum size |  | `zst` | 354-363 | 0.0 | 1202 | 14..42999 |  |
| 151 | Number of listed households |  | `caph` | 364-367 | 0.0 | 348 | 1..1085 | Sch. 0.0, block 6, col. 4 |
| 152 | Number of selected households |  | `smallh` | 368-369 | 0.0 | 12 | 1..12 | Sch. 0.0, block 6, col. 5 |
| 153 | Panel code |  | `panel` | 370-371 | 0.0 | 1 | 5..5 | 05' generated |

## PART 3 — Data Quality on the Actual CSV Data

All checks below were run against the complete files (no sampling), using `pandas`, reading every column as string first (to distinguish a truly blank cell from a "0" or a leading-zero code) before any numeric casting.

### 3.1 Structural quality

**Row/column counts:** all 8 files match their own documentation exactly (Part 1). **[CONFIRMED]**

**Full-row duplicates:** zero fully-duplicated rows in every one of the 8 files. **[CONFIRMED]**

**Duplicate identifiers:**
- HHV1/CHHV1/CHHV12025 (visit-1 household keys): 0 duplicates in all three releases. **[CONFIRMED]**
- PERV1/CPERV1/CPERV12025 (visit-1 person keys): 0 duplicates in all three releases. **[CONFIRMED]**
- HHRV (2023-24 revisit households): of 132,844 rows, **92 rows** share an identical (household key, quarter) combination with another row (0.07% of rows). **[CONFIRMED, exact count; cause UNCLEAR — see Part 5]**
- PERRV (2023-24 revisit persons): of 504,440 rows, **280 rows** share an identical (person key, quarter) combination (0.06% of rows). **[CONFIRMED, exact count; cause UNCLEAR]**

**Unexpected identifier combinations / broken relationships / malformed values:** none found in the identification block (Sector, State, District, FSU, Stratum, Sample-Household-No., Person-Serial-No.) of any file — every value in these columns parsed cleanly as an integer within a plausible range, and the linkage tests in Part 1/Part 5 show clean, well-formed keys throughout. **[CONFIRMED]**

**Records that do not fit the documented structure:** none — column counts match layout exactly in every file after the single row-numbering fix described in Part 1 §1.5 (which was a documentation-authoring issue, not a delivered-data issue).

**A confirmed, reproducible cross-file formatting defect (Post2025 only):** the `month` field is encoded differently between the two Release-3 files. In `chhv12025.csv` it is written as unpadded decimal text — `"1.0"`, `"2.0"`, … `"12.0"` — while in `cperv12025.csv` the *same conceptual field* is written as zero-padded plain text — `"01"`, `"02"`, … `"12"`. **[CONFIRMED — every one of the 12 distinct values in each file checked, full column]** A naive string-based join between the two Release-3 files on (State, District, Sector, FSU, Second-Stage-Stratum, Sample-Household-No., Month) therefore fails **completely** — 0% of persons appear to match their household — even though the underlying households and persons are, in fact, perfectly linked once `month` is cast to an integer before joining (Part 1 §1.3 confirms 100% linkage after this fix). **This is exactly the class of defect the proposed validation platform exists to catch before it silently breaks a downstream join or estimate**, and it is a concrete illustration for Part 8/Part 11 of why "referential integrity checking" cannot assume clean key formatting even within a single official release.

### 3.2 Missingness

Missingness is highly **structured**, not random, and must be interpreted against the questionnaire's skip logic, not treated uniformly:

- **Identification/key block** (Sector, State, District, FSU, Stratum, Household/Person serial numbers, Quarter/Month, Visit): **0% blank** in every file. **[CONFIRMED]**
- **Employment detail fields** (industry code, occupation code, workplace/enterprise/contract/leave/social-security fields under Blocks 5.1/5.2): blank whenever the person's activity-status code for that block is not one of the employed codes — e.g., Calendar-2024's Principal Industry/Occupation codes are blank for 251,503/415,549 persons (60.5%), closely tracking (but not exactly equal to — see §3.5) the 252,503 persons *not* coded as employed under Principal Status. **[CONFIRMED — legitimate structural missingness, not a data problem]**
- **Block 6 "second activity" fields** (`*Act2*` / `b6q*_act2_*` / `das2*`/`ind2*`): consistently **~98.7–98.8% blank across all three releases**, because the large majority of person-days record only one activity; this is a stable, cross-release-consistent, expected missingness pattern (verified as the single largest blank-rate cluster in every person file profiled) and should be modelled as "usually blank," not flagged as a quality problem. **[CONFIRMED]**
- **Vocational-training sub-block (4.1)**: blank whenever the gating item ("received any vocational/technical training") is answered "no" — consistent with standard skip-pattern design; not separately re-verified row-by-row here but consistent with the block's very high blank rate observed in every person-file profile (**[INFERRED]** from the skip logic documented in the code dictionary, consistent with, but not individually re-derived from, the observed blank rate).
- **No column in any of the 8 files was 100% blank** — i.e., no file contains a "dead" column that was collected in the schedule but never populated in the delivered extract. **[CONFIRMED]**
- Numeric "0" and "blank" are **not interchangeable** and were kept distinct throughout this analysis: e.g. Block-6 daily-hours fields are legitimately 0 on a non-working day for an otherwise economically active person (never blank — Part 3 §3.3), whereas industry/occupation codes are blank (never "0") when not applicable. **[CONFIRMED]**

### 3.3 Value quality — numerical variables

| Variable | Release(s) checked | Min | Max | Notes |
|---|---|---|---|---|
| Age | all 3 | 0 | 112–117 | No negative ages; max age plausible but extreme (Part 6 flags outlier tail) |
| Household size | all 3 | 1 | 26–30 | Right-skewed; largest households (>15 members) are rare (≤~30 households per release) but not impossible for joint-family households in India — **[UNCLEAR]** without field verification whether the largest (26–30) are genuine or enumeration/merge errors |
| Day-wise hours worked (per activity, per day) | 2024 checked in full | 0 | 20 | Never negative, never exceeds a 24-hour physical bound |
| Daily total hours worked | 2024 checked in full | 0 | 20 | Same |
| CWS weekly earnings, self-employed | 2024 checked in full | **−10,000** | 500,000 | Negative values are legitimate (a documented convention — net loss) |
| CWS weekly earnings, salaried | 2024 checked in full | 0 | 520,000 | No negative values observed here (salaried wages are not, conceptually, subject to loss) |
| Monthly consumer expenditure (derived) | all 3 | 450 (2024) | 175,625 (2024) | Never zero, never negative, in any release |
| Component expenditure items (5.1–5.5) | 2024 checked in full | 0 | up to 900,000 (durables) | Never negative; legitimately zero for households with no imputed home-grown consumption etc. (up to ~55,000 zero-valued cells for the home-grown-consumption item alone) |
| 2025 household total income | 2025, full | 0 | 705,000 | 50,586 households (18.7%) report exactly zero total income across all four income sub-items — plausible for households relying solely on wages/self-employment income (not captured in this income block, which covers only rent/interest/pension/remittances) |

**Heaping / rounding / concentration:** Age shows marked digit preference at multiples of 5 — quantified with the classic demographic **Whipple's Index** (proportion of ages 23–62 ending in 0 or 5, scaled so 100 = no preference, 500 = extreme preference): **158.9** (2023-24), **158.3** (Calendar 2024), **171.5** (Post2025) — all comfortably in the UN's "rough" accuracy band (125–174.9) or just above it (Post2025). **[CONFIRMED, full-file computation]** This is a well-known, expected phenomenon in household-survey age self-reporting in India (respondents rounding their own or others' ages), **not** evidence of data corruption, but it is a critical baseline fact for Part 6/Part 8: any statistical anomaly-detection layer that is not heaping-aware will systematically flag ages 25/30/35/40/45/50/55/60 as suspicious spikes, which would be a **false positive built into the design of a naive detector**, not a genuine finding.

### 3.4 Value quality — categorical variables

- **State codes:** all 36 values actually observed in every release (01–25, 27–37) exactly match the 36-entry official state code list; code 26 is correctly absent everywhere because it was formally retired after the 2020 merger of Daman & Diu into Dadra & Nagar Haveli & Daman & Diu (code 25) — **confirmed as a non-issue**, not missing coverage. **[CONFIRMED]**
- **Sector:** only codes 1 (Rural) and 2 (Urban) observed anywhere, matching the documented 2-value list, no undocumented codes. **[CONFIRMED]**
- **Gender/Sex:** codes 1, 2 and **3** all observed (Calendar-2024: 209,035 / 206,499 / **15** respectively). Code 3 ("Transgender") is **not** listed in the standalone code-dictionary workbook (`PLFS Panel 4 Sch 10.4 Item Code Description & Codes.xlsx`, which jumps from item 4 "Relation to Head" to item 7 "Marital Status", omitting items 5–6), but **is** explicitly documented in the Instruction Manual Vol. I §3.4.5: *"gender (male-1, female-2, transgender-3) … Hijras, Eunuchs are to be treated as 'transgender' and in such cases code 3 will be recorded."* **[CONFIRMED valid code, resolved by cross-referencing a second official document; flagged as a genuine — if minor — gap in the code-dictionary spreadsheet itself, which any platform relying on that spreadsheet alone would mis-flag as an "undocumented/invalid code"]**
- **Principal Activity Status code, Calendar 2024 (top codes observed):** 91 "attended educational institution" (106,819), 11 "self-employed own-account worker" (61,065), 92 "domestic duties" (59,688), 31 "regular salaried/wage" (46,898), 99 "age<5" (29,634), 51 "casual labour, other work" (28,098), 21 "unpaid family helper" (20,893), 93 "domestic duties + household production" (20,416), 94 "rentier/pensioner/remittance recipient" (18,237), 81 "seeking/available for work" (8,728), 12 "employer" (6,358), 97 "other" (4,040), 95 "disabled, unable to work" (3,941), 41 "casual labour, public works" (734). **All 14 observed codes are in the documented code list; no undocumented codes found.** **[CONFIRMED]**
- **Industry (NIC) codes:** always exactly 5 digits when present (164,046/415,549 non-blank, Calendar 2024), 1,177 distinct codes observed, ranging `01111`–`97009`; consistent with 5-digit NIC-2008 detail codes. **Validity against the actual NIC-2008 code list could not be checked — the code list itself was not supplied in the data package** (Part 9). **[CONFIRMED structural fact; validity itself UNCLEAR]**
- **Occupation (NCO) codes:** always exactly 3 digits when present, 127 distinct codes, `111`–`962`; consistent with NCO-2015 at the 3-digit "minor group" level, not the full unit-group code. **Same NCO-2015 code-list gap as above.** **[CONFIRMED structural fact; validity UNCLEAR]**
- **Land-possessed / land-leased-out codes (2025 only):** `lposs` — 253,877 households coded "01", tapering through codes 02–12 down to single digits, plus 6 records at "99"; `llease` — dominated by code "99" (250,972 households — almost certainly "not applicable/no land leased out"), with the remaining codes 01–12 populated in small numbers. Both fully within a 2-digit closed range, no undocumented codes observed relative to what the pattern implies, though the exact code labels for `lposs`/`llease` were **not** found in any supplied code dictionary (the Panel-4 code workbook predates this Block-3 item; no Panel-5-specific code workbook was supplied) — **[UNCLEAR: code labels for items 6.1/6.2 need MoSPI confirmation, listed in Part 9]**.

### 3.5 A small, genuine, unresolved gap: employed-status counts vs. non-blank industry/occupation counts

Calendar-2024: persons coded as employed under Principal Status (codes 11/12/21/31/41/51) total **163,046** (computed from the code-frequency table in §3.4: 61,065+6,358+20,893+46,898+734+28,098=163,046), while persons with a **non-blank** Principal Industry Code total **164,046** — a difference of exactly **1,000** persons. **[CONFIRMED discrepancy, exact count]** This is too small and too round a number to be confidently attributed to a single mechanism from documentation alone: it could reflect a residual population coded under a different status (e.g. code 81, "seeking/available for work," combined with some prior-job industry retained on file) or a data-processing artefact. This is listed as a specific, quantified, well-scoped question for MoSPI/HSD in Part 9 rather than resolved here. **[UNCLEAR]**

## PART 4 — Logical and Cross-Variable Consistency

Relationships tested below were derived from the questionnaire structure and code dictionary (not assumed generically), then tested against the full data. Calendar-2024's CPERV1/CHHV1 was used as the primary test file throughout this part because its column names are self-documenting (Part 1 §1.5); every rule tested here is defined identically in Releases 1 and 3 by the shared Schedule-10.4 block structure (Part 2 §2.1), so the findings generalise, though only the specific numeric counts quoted were actually re-run release-by-release where stated.

### 4.1 Age ↔ Principal Activity Status (hard rule, confirmed to hold exactly)

The code dictionary defines Block 5.1 status code **99 = "For persons age<5"** as a distinct, reserved code. Tested directly: **all 29,634** Calendar-2024 persons aged under 5 carry exactly status code 99, and (by construction, since 99 is reserved for this purpose) no person aged 5+ carries code 99 in the observed frequency table. **[CONFIRMED — 100% rule compliance, 0 exceptions, full file]** This is a genuine deterministic validation rule directly usable by the proposed platform with zero modelling.

### 4.2 Age ↔ Education level

No person coded as holding a Graduate or Postgraduate general-education level (codes 12/13, n=45,022 in Calendar-2024) was found below age 19; the minimum observed age among graduates/postgraduates was 19, and 0 were found below age 18. **[CONFIRMED, 0 violations, full file]**

### 4.3 Age ↔ Marital Status

Zero persons aged under 10 were coded as currently married, widowed or divorced/separated (codes 2/3/4) in Calendar-2024's full 415,549 records. **[CONFIRMED, 0 violations]**

### 4.4 Employment status ↔ Consumer/business-loss earnings sign

Self-employment earnings can be legitimately negative (documented convention, Part 2 §2.4); salaried earnings were never observed negative in the data actually checked. No person was found with both `CWS_Earnings_Salaried` > 0 **and** `CWS_Earnings_SelfEmployed` > 0 simultaneously (0 of 415,549) — consistent with a person having one current-week activity type, not two paid roles recorded in parallel. **[CONFIRMED]**

### 4.5 Employment status ↔ current-week earnings — genuine contextual anomalies, quantified

Two reference periods are in play here and must not be conflated: **Principal Status** is a 365-day "usual activity" measure; **CWS** is a 7-day "last week" measure (NMDS 2.0 §2.8, confirmed in Part 1). A mismatch between them is therefore **not automatically an error** — but the *rate* at which mismatches occur is itself informative and was fully quantified:

**(a) Usually out-of-labour-force, but earned money in the current week.** 4,247 of 415,549 persons (1.02%) whose Principal Status is one of the out-of-labour-force codes (91/92/93/94/95/97) report non-zero CWS earnings. **[CONFIRMED, exact count]** Individually plausible (a student or homemaker picking up occasional paid work), but the concentration and magnitude of these cases (some earnings observed up to several thousand rupees) make this a natural candidate for a **contextual/probabilistic flag**, not a hard rule violation — verdict: **potentially unusual, not definitely wrong.**

**(b) Usually a regular/casual wage employee, but zero earnings in the current week.** Of 75,730 persons whose Principal Status is regular-salaried/casual-labour (codes 31/41/51), **28,934 (38.2%)** report zero total CWS earnings for the reference week. **[CONFIRMED, exact count]** This is a large fraction, and — taken at face value — could reflect genuine and expected weekly absence (leave, layoff week, seasonal gap, illness) for wage workers, especially casual labour, whose work is intrinsically irregular; it could also mask response/coding issues. This is flagged as **unclear/needs further investigation** rather than "definitely wrong" precisely because the two explanations cannot be distinguished from the cross-sectional unit file alone; a longitudinal (revisit) view of the *same* individual across weeks — available only in Release 1's rotational-panel households (Part 6) — would materially sharpen this diagnosis, and this need is carried into Part 9.

**(c) Full Principal-Status × CWS-Status broad-category crosstab** (Calendar-2024, all 415,549 persons; categories: *employed*, *out-of-labour-force*, *unemployed/seeking*, plus *emp_not_worked_wk* — the CWS-only codes for "had work but did not work this week" (61/62/71/72/82/98), which have no Principal-Status analogue):

| Principal Status ↓ / CWS → | emp., but not worked this wk | employed | other | out-of-LF | unemployed/seeking |
|---|---|---|---|---|---|
| **employed** | 4,214 | 155,014 | 864 | 2,512 | 1,442 |
| **out-of-labour-force** | 189 | 8,898 | 276 | 233,298 | 114 |
| **unemployed/seeking** | 714 | 558 | 5 | 198 | 7,253 |

Overall broad-category concordance (diagonal agreement, `employed`/`out_of_LF`/`unemployed_seeking` only): **95.19%** (395,565/415,549). **[CONFIRMED, full file]** The ~4.8% discordance is exactly what the two different reference periods (365-day usual vs. 7-day current) would be expected to produce and is a natural, well-quantified baseline "background disagreement rate" the proposed anomaly-detection layer should calibrate against rather than treat every Principal/CWS mismatch as an anomaly.

### 4.6 Household size ↔ person roster

Verified exactly in Part 1: 0 mismatches between declared household size and actual person-record count, in every one of the three releases, 791,349 households checked in total (101,920 + 101,957 + 270,472... **note:** Release-1's HHV1 count is 101,920; combined visit-1 total across all three releases = 474,349 households — corrected figure). **[CONFIRMED]**

### 4.7 Household-level arithmetic identities

Both derived-total identities (household consumer-expenditure total, Part 2 §2.3; household income total, 2025 only) hold **exactly**, to the rupee, for every household in every release tested — 0 exceptions across 101,920 + 101,957 + 270,472 = 474,349 households for the expenditure identity, and 0 exceptions across 270,472 households for the income identity. **[CONFIRMED — the single cleanest, highest-confidence result in this entire document]**

### 4.8 Revisit/temporal ↔ structural design

Household- and person-level revisit linkage rates track the documented rotational-panel quarter/visit combination table **exactly** (100% where the design predicts a same-file link, <1% residual "noise" where it predicts none) — detailed fully in Part 1 §1.7 and Part 5. This is, in effect, the single most important cross-variable consistency result in the dataset: it validates that the Quarter, Visit, and household-key fields are internally coherent with the documented sampling design to a very high degree of precision, across a mechanism (rotational panel entry/exit) that is easy to get subtly wrong in a derived/processed extract.

### 4.9 Skip-pattern relationships — not independently re-verified

The vocational-training sub-block's gating logic (Block 4.1 populated only if Block 4's "received training" item is coded appropriately) is consistent with the very high blank rate observed for Block 4.1 fields (Part 3 §3.2), but the gating condition itself was **not** individually cross-tabulated end-to-end in this pass, given the scale of remaining work; this is listed as a specific, well-scoped follow-up check in Part 11 rather than asserted as confirmed.

## PART 5 — File Linkage and Identifiers

### 5.1 Identifiers, confirmed

- **Household key:** State + District + Sector + FSU + Sample-Sg/Sb-No. (hamlet-group) + Second-Stage-Stratum-No. + Sample-Household-No. **[CONFIRMED unique for every visit-1 household file, all 3 releases — Part 1 §1.6]**
- **Person key:** household key + Person-Serial-No. **[CONFIRMED unique for every visit-1 person file, all 3 releases]**
- **Visit/revisit key (Release 1 only):** household or person key + Quarter + Visit-number. **[CONFIRMED unique — see §5.2 below]**
- **FSU-related identifiers:** FSU serial number (5-digit), Sample-Sg/Sb-No. (hamlet group/sub-block, for large FSUs split into segments), Second-Stage-Stratum-No. (a further urban/rural split within the FSU for sub-sampling), FOD Sub-Region (field-office administrative grouping, Releases 1–2 only). **[CONFIRMED present, Part 2 §2.2]**
- **Geographic identifiers:** State/UT code, District code, NSS-Region (a state-specific multi-district regional grouping used for stratification), and — Release 3 only — Basic Stratum (`Bstrm`, a district or merged small-district group) with its size (`Zst`). **[CONFIRMED]**
- **Sample/design identifiers:** Stratum, Sub-Stratum (urban town-size class or rural NSS-region-based stratum), Sub-Sample (Releases 1–2 only — used for sub-sample-wise weight computation), Group (Release 3 only, exact meaning **[UNCLEAR]**).
- **Weights:** `MULT` (multiplier, 2 decimal places) in all releases; `NSS`/`NSC` (first-stage-units-surveyed counts, Releases 1–2) vs. `NSC` alone plus `Zst`/`Caph`/`Smallh` (Release 3) — see Part 1 §1.3 and Part 7 for the confirmed change in the weighting/variance-estimation scheme.
- **Panel/revisit identifiers:** none explicit in Release 1 (must be inferred from Quarter+Visit, per the documented combination table); explicit `Panel` field ("P4") in Release 2; explicit `Panel` code ("05") in Release 3.

### 5.2 Uniqueness and linkage quality — tested exhaustively

| File | Rows | Key tested | Unique keys | Duplicates |
|---|---|---|---|---|
| HHV1 (2023-24) | 101,920 | household key | 101,920 | **0** |
| PERV1 (2023-24) | 418,159 | person key | 418,159 | **0** |
| HHRV (2023-24) | 132,844 | household key **+ quarter + visit** | 132,844 | **0** |
| HHRV (2023-24) | 132,844 | household key + quarter *(visit excluded)* | — | 92 rows (46 households × 2 visits sharing a quarter) |
| PERRV (2023-24) | 504,440 | person key **+ quarter + visit** | 504,440 | **0** |
| PERRV (2023-24) | 504,440 | person key + quarter *(visit excluded)* | — | 280 rows |
| CHHV1 (2024) | 101,957 | household key | 101,957 | **0** |
| CPERV1 (2024) | 415,549 | person key | 415,549 | **0** |
| CHHV12025 | 270,472 | household key + month | 270,472 | **0** |
| CPERV12025 | 1,148,634 | person key + month | 1,148,634 | **0** |

**Finding, fully resolved:** at first pass, (household key + quarter) appeared to collide for 92 HHRV rows and (person key + quarter) for 280 PERRV rows. Investigating the 92 cases directly showed that in every one, the two "colliding" rows carry **different Visit numbers within the same quarter label** — e.g. a household's Visit-2 and Visit-3 revisit interviews both fall administratively within "Q2." **Once Visit is included in the key (as it should be — it is part of the documented primary key, Part 1 §1.1), uniqueness is exact: 132,844/132,844 and 504,440/504,440.** **[CONFIRMED — this was a key-granularity artefact of an intermediate check, not a genuine duplicate-record problem; included here specifically because Part 5's brief is to test uniqueness rigorously, and a documented near-miss with its resolution is more useful to future engineers than omitting it]** The residual, genuinely open question is *why* a small number of households (46 out of ~67,000 revisited households, 0.07%) have two revisit rounds recorded within what the Quarter field labels as the same quarter — plausibly fieldwork-schedule slippage carried into the next round's data-entry window — this operational "why" is **[UNCLEAR]** and listed in Part 9.

### 5.3 One-to-one vs. one-to-many relationships

- **HHV1 → PERV1: one-to-many, exactly verified** (Part 1 §1.1 / Part 4 §4.6): every household maps to exactly `Household_Size` person rows, 0 exceptions, in all three releases.
- **HHRV → PERRV: one-to-many** (not household-size-verified the same way, since HHRV does not re-declare household size on every revisit in all releases the same way HHV1 does — not independently re-tested at this granularity in this pass; flagged as a specific follow-up in Part 11).
- **HHV1 ↔ HHRV, PERV1 ↔ PERRV (Release 1 only): many-to-many across the *release*, one-to-(zero-to-three) within the strict rotational design.** A Panel-IV household enrolled in HHV1's Q1 legitimately appears up to 3 more times in HHRV (as V2 in Q2, V3 in Q3, V4 in Q4); this is the **expected** repeat structure, not an error (Part 1 §1.7). A household whose HHRV record has **no** matching HHV1 row in the same file (≈50% of HHRV, precisely quantified in Part 1 §1.7's table) is a **Panel-III household continuing from the prior, unsupplied release** — an expected "missing parent," not an orphan record in the data-quality sense. **[CONFIRMED, both the structure and its quantification]**

### 5.4 Genuinely missing parents / true orphans — none found

After accounting for the rotational-panel mechanism above, no further class of "orphan" records was found: every PERV1/CPERV1/CPERV12025 person resolves to an existing household in the *same file* (100% in all three releases, Part 1), and every HHRV/PERRV record either resolves to an HHV1/PERV1 parent in the same file or is explained by the documented Panel-III carry-over mechanism. **[CONFIRMED]** No cases were found of "multiple persons attached incorrectly" to a household, or of households/persons that cannot be linked at all within their own file.

### 5.5 Which files can legitimately be linked, and which must not be

**Legitimate, safe joins (within a release):**
- HHV1 ↔ PERV1 on household key (Releases 1–2); CHHV12025 ↔ CPERV12025 on household key **+ month, after normalising the month field's text format** (Part 3 §3.1 — this normalisation step is mandatory, not optional, for Release 3).
- HHRV ↔ PERRV on household key + quarter + visit (Release 1).

**Links that require care / partial coverage, not a simple join:**
- HHV1 ↔ HHRV, PERV1 ↔ PERRV **within Release 1**: valid, but only recovers ~50% of revisit records back to a first-visit parent, for the structural reason given above — must not be treated as a bug if the other ~50% fail to match.

**Links that must NOT be attempted, or are not currently possible:**
- Any household/person key match **across releases** (e.g., Release 1's HHV1 to Release 2's CHHV1) was not attempted in this document and should not be assumed safe: FSU numbering, stratum numbering, and the underlying sampled panel itself can change at panel/frame-update boundaries (Part 1 §1.1–1.3, Part 7), and no release in this package documents an explicit cross-release household identifier that survives a panel transition.
- Release 3's implied revisit files (`hhrv`, `perrv`, a second `perv1` sheet, documented in `FV_Data_LayoutPLFS_2025.xlsx` but with no corresponding CSV supplied) obviously cannot be linked to anything — they do not exist in this data package (Part 1 §1.3).

## PART 6 — Exploratory Data Analysis

### 6.1 Univariate

**Age** (all three releases, full-file): range 0–112/117, mean ≈ 31.8–32 years, median 30–32; marked digit-preference heaping at multiples of 5, Whipple's Index 158.3–171.5 (Part 3 §3.3) — **what we found:** a classic, textbook household-survey age-heaping pattern; **why it matters:** it is not randomly distributed noise, it is a systematic bias concentrated at specific values; **how it affects validation:** any statistical/ML anomaly model using raw age frequency counts will see large, repeatable spikes at 25/30/35/40/45/50/55/60 that are a measurement artefact of the whole national data-collection process, not a signal of enumerator- or FSU-level misconduct — the platform must de-heap (e.g. model age in 5-year bins, or explicitly include a heaping-propensity feature) before treating age-distribution shape as an anomaly signal.

**Sex/Gender:** three-valued (Male/Female/Transgender), heavily bimodal ~50.3%/49.7% male/female with a small transgender share (15/415,549 = 0.0036% in Calendar-2024) — **what we found:** transgender is a genuine, officially defined third category, extremely rare in the sample as expected; **why it matters:** a naive binary-sex model or a hard-coded two-category dropdown in any downstream tool would silently corrupt or reject these 15 (and equivalent) records; **how it affects validation:** the platform's schema/data-type layer must treat Sex/Gender as a 3-value categorical, not boolean.

**Principal Activity Status:** dominated by "attended educational institution" (91, 25.7%), "self-employed own-account" (11, 14.7%), "domestic duties" (92, 14.4%), "regular salaried/wage" (31, 11.3%), "age<5" (99, 7.1%), with a long tail of smaller categories (full frequency table in Part 3 §3.4). **What it matters/how it affects validation:** this is the master status variable almost every other employment-block field is conditioned on (Part 3 §3.2); its distribution is the natural baseline against which FSU- or state-level status-mix anomalies should be measured (§6.4 below).

**Household consumer expenditure (derived monthly total):** right-skewed, no zero or negative values in any release, ranging roughly ₹450–₹175,625/month in the file checked (Calendar 2024) — a shape entirely consistent with household expenditure surveys generally (log-normal-like right skew). No extreme low-end truncation artefact was found (minimum ₹450 is a real, if very poor, household, not a floor-coded value).

**Industry (NIC-2008, 5-digit) / Occupation (NCO-2015, 3-digit):** populated only for the employed (Part 3 §3.4); 1,177 / 127 distinct codes observed respectively in Calendar-2024 — a reasonably rich spread, though full code-list validity could not be checked (code lists not supplied, Part 9).

### 6.2 Bivariate

Covered rigorously in Part 4 (age↔status, age↔education, age↔marital-status, employment-status↔earnings, Principal-status↔CWS-status). The single largest, most policy-relevant bivariate relationship in the dataset — Principal Status × CWS Status — showed 95.19% broad concordance with a well-characterised, quantified 4.8% "background disagreement" driven by the different 365-day/7-day reference periods, not data error (Part 4 §4.5(c)).

**Additional bivariate finding — Sector × employment status.** Crude employment rate (share of *all persons, all ages*, coded under an employed Principal Status code): **rural 41.2%, urban 37.1%** (Calendar-2024, full file). **What we found:** a real, expected ~4-point rural/urban gap, plausible given rural India's higher share of low-productivity self-employment in agriculture and a younger/older population-age mix effect that a crude (non-age-standardised) rate does not net out; **why it matters:** this 4-point gap is a *baseline*, not itself an anomaly, and must be built into any sector-level comparison the platform runs; **how it affects validation:** an FSU or district whose rural/urban employment-rate gap deviates *sharply* from this ~4-point national baseline is a much better anomaly candidate than one whose raw employment rate merely differs from the national average.

### 6.3 Multivariate

Combinations tested where each individual field looks unremarkable but the *combination* is unusual:

- **Young age + advanced education:** 0 cases of graduate/postgraduate education below age 18 (Part 4 §4.2) — a clean combination, not a finding of anomaly, but confirms the combination check itself works and returns zero on genuinely clean data (a useful "negative control" for the platform's own testing).
- **Usually out-of-labour-force + earning money this week:** 4,247 persons (1.02%) — individually explainable, collectively a genuine "watch list" combination (Part 4 §4.5(a)).
- **Usually wage-employed + zero earnings this week:** 28,934 persons (38.2% of that subgroup) — the single largest, least-resolved multivariate combination found in this document, discussed at length in Part 4 §4.5(b); it needs either a longitudinal view or an explicit reason-code field (neither available here) to move from "unclear" to a firm interpretation.
- **Household head's own reported sex differing between Visit-1 and a revisit, with relationship-to-head unchanged (still "self")**: found in 94 of 253,527 matched person-visit pairs (0.037%) — see §6.5 below; this specific triple combination (same household, same relationship code, sex differs) is a strong, low-volume, high-confidence candidate for a genuine data/coding error, precisely because the "household roster changed" explanation that resolves most other cross-visit mismatches does not apply here.

### 6.4 Group-level

**By State (Calendar-2024, crude employment rate, all ages, full file):** ranges from **27.8%** (Bihar) to **56.9%** (Sikkim) across the 36 states/UTs, a roughly 29-percentage-point national spread. **What we found:** substantial, plausible inter-state heterogeneity consistent with well-documented differences in India's regional labour markets and demographic structure; **why it matters:** this spread is wide enough that a single fixed national threshold for "abnormal employment rate" would either miss real problems in low-participation states or constantly false-flag naturally high-participation ones; **how it affects validation:** any group-level (state/FSU/district) anomaly check needs a state- or region-conditioned baseline, not a single national one.

**By Sector:** covered in §6.2.

**By FSU / Second-Stage-Stratum:** not separately computed in this pass at full granularity (12,743 distinct FSUs observed in Release 1's HHV1 alone — Part 2 §2.6.1 — makes an exhaustive per-FSU table impractical to reproduce here); this is flagged as the natural next step for the platform itself to compute operationally (Part 8), rather than repeated by hand in this document.

**By Occupation/Industry/Education:** distributions characterised in §6.1; deeper group cross-tabulations (e.g. education-level-conditioned employment rate) were not separately run in this pass, given the volume of higher-priority checks already completed, and are listed as a specific next step in Part 11.

### 6.5 Revisit / temporal (Release 1 only — the only release with repeated observations)

This is the richest analysis this data package supports, and the results are genuinely instructive about what "compare over time" can and cannot mean here.

**Matching:** 253,527 person-visit pairs were matched — the same (state, district, sector, FSU, hamlet-group, second-stage-stratum, household-no., person-serial-no.) key observed in both PERV1 (Visit 1) and PERRV (a later revisit) — out of PERRV's 504,440 total revisit-person-records (50.3% match rate, consistent with the ~50% Panel-III-carryover structure already established in Part 1 §1.7/Part 5). **[CONFIRMED]**

**Household stability (implicit in the roster-size match, Part 1 §1.1):** household size is not literally re-tested visit-to-visit in this pass beyond the visit-1 identity already confirmed; person-level roster churn is instead directly visible in the person-key match rate itself and in §6.5's age/sex checks below.

**Age consistency across visits, same person-serial-number:** median age difference (revisit − visit-1) = **0**, as expected for interviews only a few months apart; but the distribution has real, non-trivial tails: **366 pairs (0.14%) where reported age *decreased*** between visits (impossible for the same physical individual), and **300 pairs (0.12%) where age jumped by more than 2 years** within the same survey year. **[CONFIRMED, exact counts, full file]**

**Sex consistency across visits, same person-serial-number:** 254 of 253,527 matched pairs (0.10%) report a *different* sex at the revisit than at Visit 1. **[CONFIRMED]**

**Interpreting these transitions — what can, and cannot, be concluded:** the PLFS revisit protocol explicitly allows household **rosters to change** between visits (members leave, new members join, relationships are still coded relative to the *original* Visit-1 head — Instruction Manual Vol. I §3.4.5, confirmed in Part 2 §2.4), and the **Person Serial Number is reused positionally**, not reissued as a stable longitudinal person ID. So an apparent "age went backwards" or "sex changed" case can genuinely mean *a different physical person now occupies that household roster slot* — not a data error at all. Testing this directly: of the 254 sex-mismatch pairs, **112 (44%) also show a changed Relationship-to-Head code**, consistent with a roster change explaining the mismatch. But **94 of the 254 (37%) have Relationship-to-Head = "self" in *both* visits** — i.e., the household head's own recorded sex differs between visits with no roster-change signal to explain it. **[CONFIRMED, exact counts]** **What we found:** a two-part picture — a majority of cross-visit demographic "changes" are legitimate roster churn, correctly explainable from the data itself, but a specific, small, well-isolated residual (the ~94 "self, sex differs" cases, and part of the 366 age-decreased cases) is not explained by roster churn and is a much stronger candidate for genuine field/data-entry error; **why it matters:** this is exactly the distinction Part 6 was asked to draw out — most repeated-observation "instability" is structural and expected, but a specific, quantifiable minority is not, and the two must not be lumped together; **how it affects validation:** the proposed platform's revisit-consistency module should **not** simply flag "person-serial-number N's answer changed" — it must first test whether Relationship-to-Head (and, ideally, other slowly-changing fields) also changed before concluding a demographic answer is internally inconsistent for the *same* person, exactly as done here.

**What cannot be compared over time from this data package alone:** anything spanning a release boundary — a Panel-III household's Visit-1 answers (the ~50% of HHRV/PERRV without an in-file HHV1/PERV1 parent) simply are not in this package (Part 1 §1.7), so no four-visit trajectory can be fully reconstructed for any household without the prior release. Release 2 and Release 3 are both first-visit-only, so **no revisit/temporal analysis of any kind is possible for Calendar-2024 or Post2025 with the data supplied.**

## PART 7 — 2023–24 vs. Calendar 2024 vs. 2025: Cross-Release Comparison

### 7.1 The stable core

Matching by full documented item name, **31 household-level and 103 person-level variables are present, by name, in all three releases** (full lists in the working data; representative examples: Sector, State/Ut Code, District Code, FSU, Household Size, Household Type, Religion, Social Group, the five expenditure sub-items and their derived total; and, on the person side, Age, Marital Status, General/Technical Education Level, the full Block 5.1/5.2 principal/subsidiary status detail, and the complete Block 6 day-wise hours/status/wage structure). **[CONFIRMED by exact string match against the merged variable inventory, Part 2]** This is the genuine, comparable backbone of Schedule 10.4 across all three releases and 2017–2025 inclusive (per NMDS 2.0, the schedule itself has been the PLFS instrument since 2017).

### 7.2 Renamed variables

| 2023-24 name | Calendar-2024 name | 2025 name | Classification |
|---|---|---|---|
| (implicit, block/item code `b4q5`) | `Sex` | `Gender` | **B** — cosmetic rename, same position/byte length; code list continuity **[UNCLEAR]**, not separately re-documented for 2025 |
| — | "No. of years in Formal Education" | replaced by 5 finer items (class/grade completed, years before/after, months attended, whether-last-year) | **A** — deliberate content redesign, see §7.4 |

Every other "rename" observed is purely a **column-header** difference (block/question code vs. descriptive English vs. short mnemonic — Part 1 §1.5), not a change to the underlying variable; those are not re-listed here since Part 1/Part 2 already document them exhaustively.

### 7.3 Removed variables (present in earlier release(s), absent in 2025)

| Variable | Present in | Absent in | Classification | Why |
|---|---|---|---|---|
| Sub-Sample | 2023-24, 2024cal | 2025 | **A** | Sub-sample-wise weighting concept retired in the revamped 2025 design (README2025.docx §4–6 describes a new `Bstrm`/`Zst`/`Caph`/`Smallh`-based estimation scheme instead) |
| Sample Sg/Sb No. (hamlet group) | 2023-24, 2024cal | 2025 | **D** — **[UNCLEAR]** whether hamlet-group splitting was discontinued in the new design or simply folded into another field; not explained in README2025.docx |
| `NSS` (sub-sample first-stage-unit count) | 2023-24, 2024cal | 2025 (only `NSC` remains) | **A** | Consistent with the Sub-Sample concept's retirement above |
| Sub-sample-wise Multiplier note | 2023-24, 2024cal | 2025 (single `Multiplier`/`mult` field, differently computed per README2025.docx §4) | **A** | Same reason |

### 7.4 Added variables (2025 only)

| Variable(s) | Classification | Why |
|---|---|---|
| `Bstrm`, `Zst`, `Caph`, `Smallh`, `Panel` (explicit), `Group` | **A** | Explicitly introduced, per README2025.docx, to support design-based variance/RSE computation and district-level estimation — capabilities the earlier releases' unit files did not support at all |
| Household income block: land-possessed code, land-leased-out code, rent, interest, pension, remittances, total income | **A** | A deliberate widening of Schedule 10.4's household content beyond consumption expenditure into income sources (confirmed present in the 2025 Data Layout, confirmed arithmetically consistent in the actual data, Part 2 §2.3) — not observable anywhere in Releases 1–2, so **no historical baseline exists for this block** |
| Finer education-history items (class/grade completed; years of education before/after a given grade; months attended in the last year; whether that was the last year attended) | **A** | Redesign of the single "years of formal education" figure into a more granular trajectory — improves precision but **breaks direct year-over-year comparability** of "years of formal education" as a single number unless the new items are explicitly re-aggregated to match the old definition (not attempted in this document) |
| New vocational-training items (training for higher-education/employment-exam entrance; certifying-body nature; training-completion timing) | **A** | Same kind of block expansion as above, Block 4.1 |

### 7.5 Changed codes / changed meanings

No case was found, within the shared Panel-4/Panel-5 code framework, of an *existing* code being silently **redefined** to mean something different (e.g., code 31 meaning "regular salaried" consistently wherever checked). The Block-6 day-wise activity code list is, however, confirmed to be a **strict superset** of the Block-5.1/5.2 usual-activity code list within the *same* Panel-4 schedule — Block 6 adds MGNREGS casual work (42) and four "had work but did not work that day" states (61/62/71/72) plus "did not seek but available" (82) and "temporary sickness, casual worker" (98), none of which exist as Block-5.1/5.2 usual-status codes (Part 2 §2.4). **[CONFIRMED — Classification A: by design, a daily-recall block legitimately needs finer states than a 365-day usual-status summary]** No separate Panel-5 (2025) code dictionary was supplied to check whether this same superset relationship — or the codes themselves — changed for 2025; this is listed in Part 9 as **[UNCLEAR]**.

### 7.6 Changed file structures / changed identifiers

- **Column naming convention changes completely, three times** (Part 1 §1.5) — **Classification B**, a data-production/processing choice, not a survey-design choice, but with real practical consequence for any harmonisation pipeline.
- **Record length / column count changes** in step with content changes documented above (HHV1: 37 cols/127 bytes → CHHV1: 38 cols/130 bytes → CHHV12025: 48 cols/219 bytes; PERV1: 139 cols → CPERV1: 140 cols → CPERV12025: 153 cols) — **Classification A**, tracking the documented content additions.
- **Weighting/estimation identifier system replaced** (`NSS`+`NSC`+Sub-Sample-Multiplier → `NSC`+`Bstrm`+`Zst`+`Caph`+`Smallh`+`Multiplier`) — **Classification A**, per §7.3/§7.4 above; this means **weights computed under the pre-2025 scheme and the 2025 scheme are not simple like-for-like substitutes** — combining Release 1/2 and Release 3 data in one pooled weighted estimate is **not** something this document attempts or endorses without explicit MoSPI/HSD methodological guidance (carried into Part 9).

### 7.7 Changed household/person relationships / changed revisit structure

- Release 1: full rotational panel (4 visits, urban only) present in the data.
- Release 2: first-visit only; **no revisit structure present in the data at all** (not merely smaller — structurally absent).
- Release 3: first-visit only in the *data*, but the *documentation* still describes a revisit file layout (Part 1 §1.3) — **Classification D**, unclear whether this reflects an intentional first phase of data-sharing (with revisit data to follow later) or a genuine discontinuation of revisit-based data-sharing for this project's purposes. This is one of the single most consequential open questions for the whole project, because Release 1 is otherwise the **only** source of any panel/longitudinal validation signal in this entire package (Part 6 §6.5), and if Post2025 revisit data is not going to be shared, the platform's longitudinal-consistency capability will be permanently limited to a data vintage that predates the 2025 redesign.

### 7.8 Changed sampling information

Cadence: **quarterly (2017–Dec 2024) → monthly (Jan 2025 onward)**; sample size: **~102,400 households/12,800 FSUs → ~272,304 households/22,692 FSUs** (~2.66× expansion), both explicitly documented (NMDS 2.0 §2.9–2.10, quoted in full in Part 1 §1.3). **Classification A — this is a deliberate, officially announced, fully documented redesign, not a data-quality artefact,** and it fully explains why Release 3's row counts cannot be compared to Releases 1–2's row counts as if measuring "the same thing at a different point in time" — they measure a differently-sized, differently-cadenced sampling scheme.

### 7.9 Changes that might be mistaken for data-quality problems if this documentation were not read first

This is, deliberately, the single most important list in Part 7 — each item below **would look like a bug** to an engineer building the platform without first reading the official documentation, but is confirmed here to be an intentional design change:

1. Release 3's household/person row counts jumping ~2.66× relative to Releases 1–2 — **not** duplication or a processing error; documented sample-size expansion (§7.8).
2. Release 3's `chhv12025.csv`/`cperv12025.csv` failing to join on `month` when read naively (0% match) — **not** broken data; a genuine text-formatting inconsistency between the two files that resolves completely once `month` is cast to an integer (Part 3 §3.1) — this one genuinely *is* a data-quality defect, but a narrow, well-understood, easily-corrected one, not a sign of deeper corruption.
3. HHRV/PERRV records that don't match any HHV1/PERV1 record in the same annual file (~50% of revisit rows) — **not** orphan records; the documented rotational-panel carry-over mechanism (Part 1 §1.7).
4. Zero CWS earnings for 38% of usually-wage-employed persons — plausibly real (Part 4 §4.5(b)), but genuinely **unclear** without more context; listed as needing investigation rather than dismissed as either "definitely a bug" or "definitely fine."
5. A person's reported age decreasing, or sex changing, between Visit-1 and a revisit — mostly (but not entirely — Part 6 §6.5) explained by legitimate household-roster churn combined with Person-Serial-Number reuse, not misrecording.

### 7.10 What breaks comparability across releases — summary

- **Row-level pooling of Release 3 with Releases 1–2 is not valid without re-weighting** under a common scheme (§7.6, §7.8) — sample design, cadence, and even the weighting variables themselves changed.
- **Column-name-based automated harmonisation across releases is not possible** — must be done by Block/Item number and byte-position cross-reference (Part 1 §1.5); this document's Part 2 inventory and this Part 7 crosswalk are the necessary reference artefacts for that harmonisation.
- **Any comparison involving "years of formal education" between Release 3 and Releases 1–2 needs an explicit re-derivation** from Release 3's finer items to reconstruct a comparable single figure, or must be dropped from cross-release trend analysis (§7.4).
- **Longitudinal/revisit-based validation is only possible using Release 1**, and only for the ~50% of its revisit records whose Visit-1 counterpart is in-file (§7.7); it cannot currently be extended into 2024 or 2025 with the data supplied.
- **Income-block validation checks (Part 2 §2.3) are only possible from 2025 onward** — there is no historical baseline in Releases 1–2 to compare 2025's income patterns against.

## PART 8 — What the Data Actually Supports, Against the Problem Statement

The Project Brief's required software features are, in order: (1) real-time/batch ingestion; (2) building statistical/ML models from historical data; (3) defining and running integrity checks (referential, existential, etc.); (4) automated flagging at record/aggregate level; (5) an interactive/batch validation UI; (6) dashboards; (7) export/reporting. This document only bears on features (2)–(4) — what the historical PLFS *data itself* can and cannot support — and says nothing about (1), (5), (6), (7), which are software-engineering rather than data questions.

### 8.1 Deterministic / rule checks — fully supported, ready to implement now

| Requirement | Variables | File(s) | Level | Evidence this works |
|---|---|---|---|---|
| Household consumer-expenditure identity | 5.1–5.6 components | HHV1/CHHV1/CHHV12025 | Household | **100% exact match, 474,349 households, 0 exceptions (Part 2 §2.3)** |
| Household income identity (2025 only) | 7.1–7.5 | CHHV12025 | Household | **100% exact match, 270,472 households (Part 2 §2.3)** |
| Household-size ↔ roster-count | Household Size vs. person rows | HHV1/PERV1 (+2024, +2025) | Household↔Person | **100% match, all 3 releases, 0 exceptions (Part 1, Part 4 §4.6)** |
| Age<5 ⇒ Principal Status = 99 | Age, Principal Status | PERV1/CPERV1 family | Person | **100% compliance, 29,634 cases, 0 exceptions (Part 4 §4.1)** |
| Household-key referential integrity (person→household) | key fields | all person files | Person→Household | **100% resolve, all 3 releases (Part 1, Part 5)** |
| State/District code validity | State/Ut Code, District Code | all files | any | **100% valid against supplied code lists (Part 3 §3.4)** |

**Sufficiency:** fully sufficient for all records tested; **transformation needed:** none beyond the key/field mapping already built in Part 1/Part 2; **can be done for all records:** yes; **groups where it cannot be done:** none identified. This category is, in effect, "solved" by this document — the rules are known, confirmed exact, and immediately codable.

### 8.2 Statistical anomaly checks (distributional, within a single file)

| Requirement | Variables | File(s) | Level | Feasibility |
|---|---|---|---|---|
| Age-distribution anomaly detection | Age | person files | Person/FSU/State | **Feasible, but only if heaping-corrected** (Whipple's Index 158–172 baseline, Part 6 §6.1) — a naive frequency-anomaly detector will misfire on every heaped age value |
| Wage/earnings outlier detection | CWS earnings fields | person files | Person | **Feasible** — ranges and a documented negative-value convention are known (Part 3 §3.3); needs group-conditioning (by industry/occupation/state) to be useful rather than a single national threshold |
| Household-expenditure outlier detection | expenditure total | household files | Household | **Feasible** — clean, no negative/zero anomalies found; natural log-scale, state/sector-conditioned baseline recommended (Part 6 §6.1) |
| Employment-rate anomaly by group | Principal Status | person files | State/Sector/FSU | **Feasible at state/sector level** (27.8–56.9% state range and 41.2%/37.1% rural/urban split established as the "normal" baseline, Part 6 §6.4); FSU-level baselines were **not** computed in this pass (12,743 distinct FSUs in Release 1 alone — an operational, not a feasibility, gap) |

**Sufficiency/limitations:** all of the above are statistically feasible from the supplied data, but every one requires the platform to build **group-conditioned baselines** (state, sector, sometimes FSU) rather than single national thresholds — this document establishes several such baselines directly (age heaping, rural/urban employment gap, state employment-rate range) that the platform can use as an initial calibration, but a full FSU-level baseline library was outside the scope of what could be completed here and is listed as next-step work (Part 11).

### 8.3 Contextual / probabilistic checks (needs a reference distribution / conditional model, not a hard rule)

| Requirement | Variables | Evidence base | Feasibility |
|---|---|---|---|
| Principal-status vs. CWS-status plausibility | Principal Status, CWS Status | **95.19% broad concordance measured; 4.8% "background disagreement" rate established as the expected baseline (Part 4 §4.5(c))** | **Feasible** — a genuine, ready-made conditional baseline exists |
| Out-of-LF-with-earnings plausibility | Principal Status, CWS earnings | **1.02% base rate measured (Part 4 §4.5(a))** | **Feasible as a soft/contextual flag**, not a hard rule — the base rate itself is the calibration point |
| Wage-employed-zero-earnings plausibility | Principal Status, CWS earnings | **38.2% base rate measured, but *not* explained (Part 4 §4.5(b))** | **Only partially feasible** — the rate is known, but *why* it happens (genuine week-off vs. a coding problem) cannot be determined from this cross-sectional file; a probabilistic model can be built to score how unusual a given case is *relative to this base rate*, but cannot currently distinguish "legitimate absence" from "error" without either revisit data on the same person (Release 1 only, and even there not directly testable for this specific field pairing in this pass) or an explicit reason-code field (not present in any release) |

### 8.4 ML anomaly detection (record, cluster, aggregate levels, historical-data-trained)

- **Record level:** feasible — every person/household record has a rich, well-typed feature vector (Part 2's inventory) suitable for an unsupervised model (isolation forest, autoencoder, etc.); the deterministic (§8.1) and contextual (§8.3) findings in this document are directly usable either as hard pre-filters or as engineered features/labels for such a model.
- **Cluster level (FSU/second-stage-stratum):** feasible in principle — FSU and stratum identifiers are present and clean in every file (Part 5) — but this document did not compute FSU-level baseline distributions at scale (§8.2); the platform would need to do this as an operational step, most naturally reusing the group-level method demonstrated here at the state level (Part 6 §6.4).
- **Aggregate level (state/national indicator level):** feasible — the weight/multiplier fields needed to produce design-consistent aggregate estimates are present in every release, though the weighting *scheme itself differs* between Release 3 and Releases 1–2 (Part 7 §7.6) and must be implemented per-release, not with one shared formula.
- **A training-data caveat that is important and specific to this package:** the Project Brief asks the platform to be *"evaluate[d] using historical PLFS data from 2024 onwards."* Calendar-2024 and Post2025 are **both first-visit-only** (Part 1 §1.2–1.3); **no ML or rule trained to detect *revisit-inconsistency* patterns (Part 6 §6.5) can be evaluated against 2024 or 2025 data at all**, because there is no revisit data in either release to evaluate against. Only Release 1 (July 2023–June 2024) supports that specific evaluation, and it falls only partially within the brief's stated "2024 onwards" evaluation window. This is flagged clearly because it directly affects whether Objective 3 of the Project Brief ("Evaluate the system using historical PLFS data from 2024 onwards") can be fully met for every proposed check type, or only for the non-longitudinal ones.

### 8.5 Group/FSU pattern checks

Feasible in structure (FSU, Second-Stage-Stratum, `Caph`/`Smallh` in 2025 give listed-vs-sampled household counts per FSU, useful for coverage-rate checks) but, as above, not computed exhaustively here; demonstrated at the coarser state/sector level only (Part 6 §6.4).

### 8.6 Revisit/panel consistency

**Feasible, and directly demonstrated in this document (Part 6 §6.5), but only for Release 1 (July 2023–June 2024), and only for the ~50% of its revisit records that have an in-file Visit-1 parent (Part 1 §1.7, Part 5).** This is currently the single most capability-limited item in the whole platform brief relative to the supplied data: Objective 2 of the Project Brief explicitly calls for anomaly detection using "historical PLFS datasets" at "record, cluster, and aggregate levels," and a longitudinal/revisit consistency check is one of the more powerful record-level techniques available — but it can currently only be built and evaluated on data that is, at latest, mid-2024 vintage, using an urban-only subsample, and even then only half its rows are usable as matched pairs.

### 8.7 Influence/impact analysis, explanation, supervisor review, feedback/evaluation

These are workflow/UI/process capabilities the Project Brief asks for (features 3–6); the data package supports them only in the sense that every finding in this document (deterministic rule results, contextual base rates, group baselines) is a concrete, explainable "why was this flagged" input that a supervisor-review UI could surface directly (e.g., "this record was flagged because its wage-employed-with-zero-earnings pattern occurs in only 38.2% of cases nationally, versus X% for this specific occupation/state combination"). No specific gap in the *data* was found that would prevent building an explanation layer on top of the checks in §8.1–8.6; this is primarily a software-design question outside this document's scope.

### 8.8 Checks this data cannot support properly — stated plainly

- **Any validation depending on enumerator/supervisor identity, timing, or field-process metadata** — none of these fields exist in any of the three releases (Part 9).
- **Industry (NIC-2008) / Occupation (NCO-2015) code-validity checking** — the code lists themselves were not supplied (Part 3 §3.4, Part 9); only code *format* (5-digit / 3-digit) could be checked, not code *legitimacy*.
- **Cross-release pooled/longitudinal modelling** without an explicit MoSPI-endorsed harmonisation and re-weighting method (Part 7 §7.10).
- **Distinguishing "legitimate weekly absence" from "coding error"** for the 38.2% wage-employed-zero-earnings population (§8.3) with the cross-sectional data alone.

## PART 9 — Data Gaps and What We Should Ask MoSPI/HSD

### 9.1 What we have

- Full unit-level microdata for three PLFS releases spanning July 2023–December 2025, with complete household and (mostly) person-level Schedule-10.4 content, confirmed row-for-row and column-for-column against official documentation (Part 1).
- A confirmed, exact household key, person key, and (Release 1 only) visit key, usable for referential-integrity checking (Part 5).
- Confirmed-exact derived-field formulas (expenditure total, 2025 income total) usable as zero-modelling-effort deterministic rules (Part 2, Part 4).
- A genuine, if partial, revisit/longitudinal signal — but **only** in Release 1, **only** for urban households, and **only** for the ~50% of revisit records whose Visit-1 parent is in the same file (Part 1 §1.7, Part 6 §6.5).
- Some genuine field-process **paradata-adjacent** items, confirmed present in all three releases: **Survey Date** (DDMMYYYY, 8-digit, e.g. `18012024`), **Total Time Taken to Canvass** (minutes; observed range 20–180 in Calendar-2024, mean 63.8), **Response Code** (informant cooperation: co-operative-and-capable / co-operative-but-not-capable / busy / reluctant / other — Calendar-2024: 90.5% "co-operative and capable"), and **Survey Code** (original / substitute / casualty household — Calendar-2024: 88.3% original, 11.7% substitute, 0% casualty observed in this particular file) plus **Reason for Substitution** where applicable. **[CONFIRMED, all four fields present and populated in every release]** These are useful proxies for field-quality signal (e.g., a cluster of "reluctant"/"busy" response codes, or an unusually high substitution rate, at a given FSU could itself be an early-warning indicator) even though they fall short of full CAPI paradata.
- Explicit design-support fields in 2025 (`Bstrm`, `Zst`, `Caph`, `Smallh`) enabling design-based variance and, for the first time in this package, district-level estimation (Part 1 §1.3).
- Official classification standards named (NIC-2008 for industry, NCO-2015 for occupation — NMDS 2.0, confirmed Part 3 §3.4), even though the code lists themselves are not included.

### 9.2 What we do not have

Systematically checked against the complete 691-variable inventory (Part 2) — **none** of the following terms/concepts appear anywhere in any of the three releases' documented or actual columns: enumerator identifier, supervisor identifier, GPS/latitude/longitude or any other location-capture metadata, interview start/end timestamp (only interview **date** and **total duration in minutes** are present — not a precise start/end clock time), device identifier, edit/correction history, field-level audit trail, back-check or re-interview outcome, or supervisor decision/override record. **[CONFIRMED — exhaustive term search against the full variable inventory, both documentation and actual CSV headers, all 8 files]** This is stated plainly, without assuming any of these exist just because a modern CAPI system could in principle capture them (per the task's explicit instruction not to assume): **we do not know, from this data package alone, whether MoSPI/NSO's eSigma/CAPI system captures any of this paradata internally** — only that **none of it was included in this hand-off.**

Also absent: the NIC-2008 and NCO-2015 full code lists (Part 3 §3.4, Part 8 §8.8); a Panel-5-specific (2025) code dictionary equivalent to the Panel-4 workbook supplied for Releases 1–2 (Part 2 §2.4, Part 7 §7.5); the previous release's data needed to complete Release 1's Panel-III revisit linkage (Part 1 §1.7); and any 2025 revisit data, despite its layout being documented (Part 1 §1.3, Part 7 §7.7).

### 9.3 What is uncertain

| Item | Where raised | What is known | What is not known |
|---|---|---|---|
| Whether Post2025 revisit data exists and will be shared | Part 1 §1.3, Part 7 §7.7 | A revisit-file layout is documented in `FV_Data_LayoutPLFS_2025.xlsx`; Schedule 10.4 revisit forms exist for both 2025 half-years | Whether the data itself is already being collected/processed and simply wasn't included, or won't exist for this rotation at all |
| The ~1,000-person gap between employed-status counts and non-blank industry-code counts | Part 3 §3.5 | Exact size (1,000, Calendar-2024) | Mechanism (miscoded status, retained prior-job code, processing artefact) |
| Why 46 households (92 rows) have two revisit rounds recorded within the same quarter label | Part 5 §5.2 | Exact count and that it resolves cleanly once Visit is included in the key | Operational cause (fieldwork slippage vs. something else) |
| Meaning of the new `Group` (`grp`) field, 2025 | Part 5 §5.1 | Present, populated, byte position known | Its definition — not explained in README2025.docx or the layout remarks |
| Code labels for `lposs`/`llease` (land-possessed/leased-out, 2025) | Part 3 §3.4 | Codes observed (2-digit, closed range) | Textual meaning of each code — no 2025-specific code dictionary supplied |
| Whether the Sex→Gender rename (2025) also changed/extended the code list | Part 7 §7.2 | Same byte position, 3 values expected by analogy | Not independently re-confirmed for 2025 (no 2025 equivalent of the Instruction-Manual passage was specifically located) |
| Whether the 38.2% wage-employed/zero-current-earnings pattern is a genuine, expected phenomenon or partly a coding issue | Part 4 §4.5(b), Part 8 §8.3 | Exact rate; plausible legitimate explanation | Cannot be resolved from cross-sectional data alone |
| The ~0.7% gap between Release 3's documented target sample (272,304 households) and delivered rows (270,472) | Part 1 §1.3 | Both figures, exact | Whether this reflects non-response, an achieved-vs-allocated distinction, or a data-hand-off cut |

### 9.4 What would materially improve the project

| Missing/uncertain item | Why it would help | Which part of the proposed system uses it | Can the project proceed without it? | Priority |
|---|---|---|---|---|
| Enumerator identifier (even pseudonymised) | Enables the single most natural "enumerator-bias/drift" detection the Project Brief explicitly names as a target (digression from CAPI's static rule checks) | Statistical/probabilistic anomaly models, group-level checks (Part 8 §8.2, §8.5) | **Yes, but with a major capability gap** — enumerator-level anomaly detection (explicitly named in the Project Brief's background) cannot be built at all without it | **Essential** |
| Supervisor identifier / supervisor decision record | Lets the platform learn from, and be validated against, actual supervisor judgement calls (ground truth for "was this flag correct") | Feedback/evaluation loop (Part 8 §8.7) | Yes, with reduced ability to validate model precision against real supervisor decisions | **Essential** |
| Interview start/end timestamp (not just total duration) | Finer field-process signal (e.g., interviews conducted implausibly late at night) than the existing coarse duration field already provides some of | Contextual/probabilistic checks (Part 8 §8.3) | Yes — the existing `Total Time Taken` field is a usable, if coarser, substitute already confirmed present | Useful |
| GPS/location metadata | Detects location-implausible interviews (e.g., claimed rural FSU interview actually conducted far from the FSU) | Referential/contextual checks | Yes, this is a genuinely optional enhancement given no location paradata exists in any release checked | Optional |
| Edit/correction history, back-check/re-interview outcome | Directly validates whether a flagged record was, in fact, subsequently corrected/confirmed — the strongest possible ground truth for evaluating the platform itself | Feedback/evaluation loop | Yes, but evaluation would rely on proxy/indirect methods (e.g., the deterministic and cross-sectional checks demonstrated in this document) rather than true field ground truth | **Essential** for rigorous evaluation, though the project can start without it |
| NIC-2008 / NCO-2015 full code lists | Enables genuine industry/occupation code-validity checking, not just format checking | Deterministic/referential checks (Part 8 §8.1) | Yes — format-only checking is already possible and demonstrated | Useful |
| A 2025-specific (Panel-5) code dictionary | Resolves the Part 7 §7.5/Part 9 §9.3 uncertainty about whether Block-5/6 codes changed for 2025 | Deterministic checks, cross-release crosswalk | Yes | Useful |
| The July 2022–June 2023 release (Panel III's Visit-1 data) | Completes Release 1's revisit linkage (currently ~50%), extends the longitudinal-consistency evaluation window backward | Revisit/panel consistency checks (Part 8 §8.6) | Yes, the ~50% already linked is enough to demonstrate and begin developing the method (Part 6 §6.5) | Useful |
| Post2025 revisit data (2nd–4th visit), if it exists | Extends longitudinal-consistency checking into the current, redesigned sampling scheme — otherwise this capability is permanently stuck at mid-2024-vintage data | Revisit/panel consistency checks, and directly needed to satisfy the Project Brief's "evaluate using historical PLFS data from 2024 onwards" for this specific check type (Part 8 §8.4, §8.6) | **No, not fully** — without it, the longitudinal-consistency capability cannot be evaluated on any data later than June 2024, which conflicts with the Project Brief's stated evaluation window | **Essential** |

## PART 10 — Findings Table

Every row below is a finding genuinely present in the supplied data or documentation (no hypothetical examples). "Extent" figures are exact counts from full-file computation unless stated otherwise.

| Finding | Dataset/File | Variable(s) | Evidence | Frequency/Extent | Interpretation | Project relevance |
|---|---|---|---|---|---|---|
| Row/column counts match documentation exactly in every file | All 8 CSVs | — (structural) | Full-file `pandas` row/column counts compared to README/layout | 8/8 files exact match | Confirms clean, untruncated, uncorrupted delivery | Baseline trust in the data package |
| Zero fully-duplicated rows | All 8 CSVs | — | `df.duplicated().sum()` | 0 in every file | Clean extract | Deterministic dedup rule not needed at row level |
| Household/person keys exactly unique in all visit-1 files | HHV1/CHHV1/CHHV12025, PERV1/CPERV1/CPERV12025 | key fields | Full-file uniqueness test | 6/6 files, 0 duplicates | Keys are trustworthy as-is | Direct referential-integrity rule, ready to implement |
| HHRV/PERRV keys unique once Visit is included; ambiguous (92/280 rows) if Visit excluded, fully explained by same-quarter double-revisit | HHRV, PERRV (2023-24) | household/person key + quarter/visit | Full-file uniqueness + follow-up investigation | 92 HHRV rows / 280 PERRV rows, resolved to 0 with correct key | Key granularity matters; not a defect once correctly specified | Documents the correct join key for revisit files |
| Revisit records are 100% urban sector, 0% rural | HHRV | Sector | Full-file tabulation | 132,844/132,844 urban | Exact match to documented "no rural revisit" design | Confirms panel scope; rural-only checks need no revisit logic |
| Rotational-panel quarter/visit linkage matches documented design exactly | HHV1↔HHRV, PERV1↔PERRV (2023-24) | quarter, visit, household/person key | Cross-tabulated linkage rate | 100% linkage where design predicts it, <1% where it does not | Confirms sampling-design fields are internally coherent | Explains the ~50% "unmatched" revisits as expected, not orphans |
| Household-size ↔ person-roster count exact match | HHV1/PERV1 (+2024, +2025) | Household Size vs. roster count | Full-file groupby/compare | 0 mismatches, 474,349 households across 3 releases | Strong internal consistency | Ready deterministic rule |
| Household consumer-expenditure identity holds exactly | All 3 releases, household files | 5.1–5.6 items | Full-file arithmetic check | 0 exceptions, 474,349 households | 5.6 is a derived, not collected, field | Ready deterministic rule; also documents derived-vs-collected status |
| Household income identity holds exactly (2025 only) | CHHV12025 | 7.1–7.5 items | Full-file arithmetic check | 0 exceptions, 270,472 households | 7.5 is derived | Ready deterministic rule, 2025-only |
| Month field format differs between 2025 household and person files | CHHV12025 vs. CPERV12025 | `month` | Direct raw-string comparison | 100% of rows affected until normalized | Genuine formatting defect in the delivered files | Concrete illustration of why format-normalization must precede any join |
| Age<5 ⇒ status code 99, exactly | PERV1/CPERV1 family | Age, Principal Status | Full-file rule test | 29,634/29,634 compliant (Calendar-2024) | Hard rule holds | Ready deterministic rule |
| No graduates/postgraduates below age 18 | CPERV1 (2024) | Age, General Education Level | Full-file check | 0/45,022 violations | Plausible, clean | Ready deterministic rule |
| No married/widowed/divorced persons below age 10 | CPERV1 (2024) | Age, Marital Status | Full-file check | 0 violations | Plausible, clean | Ready deterministic rule |
| Gender code 3 (Transgender) present but undocumented in the standalone code dictionary | CPERV1 (2024) | Sex/Gender | Frequency table + cross-reference to Instruction Manual §3.4.5 | 15/415,549 (0.0036%) | Valid code, but a genuine documentation-package gap (one official doc omits what another confirms) | Warns against relying on a single documentation source for code validity |
| Out-of-labour-force persons with nonzero current-week earnings | CPERV1 (2024) | Principal Status, CWS earnings | Full-file cross-tab | 4,247/415,549 (1.02%) | Plausible (occasional work), not automatically wrong | Candidate contextual/probabilistic flag, calibrated base rate established |
| Wage/casual-employed persons with zero current-week earnings | CPERV1 (2024) | Principal Status, CWS earnings | Full-file cross-tab | 28,934/75,730 (38.2%) | Ambiguous — plausible absence vs. possible coding issue, cannot be resolved from this file alone | Largest unresolved "unclear" finding in this document; needs longitudinal or reason-code data |
| Principal-status × CWS-status broad concordance | CPERV1 (2024) | Principal Status, CWS Status | Full-file cross-tab | 95.19% concordant | Expected, given different 365-day/7-day reference periods | Establishes the baseline "disagreement rate" for this check |
| Self-employment earnings can be legitimately negative | CPERV1 (2024) | CWS Earnings, Self-Employed | Full-file min/max | min = −10,000 | Matches documented convention (net loss) | Range check must allow negatives for this specific field only |
| Household/component expenditure fields never negative | CHHV1 (2024) | expenditure items | Full-file min/max | 0 negative values in 101,957 rows | Economically expected | Range check should treat negative expenditure as a hard violation |
| Daily hours-worked fields bounded 0–20, never negative, never blank | CPERV1 (2024) | Day1–Day7 hours fields | Full-file min/max/blank check | 0 violations of a 24-hour physical bound | Clean | Confirms a safe hard range rule (0–24) |
| Age shows marked digit-heaping at multiples of 5 | All 3 releases, person files | Age | Whipple's Index computation | Index 158.3–171.5 (all releases) | Expected household-survey self-report phenomenon | Statistical anomaly models must be heaping-aware or will false-flag common ages |
| Industry/Occupation codes populated only for the employed, in a consistent format (5-digit/3-digit) | CPERV1 (2024) | Industry, Occupation codes | Full-file length/blank check | 164,046 non-blank (5-digit), 251,503 blank | Structurally clean; ~1,000-person gap vs. employed-status count unresolved | Format checks are ready now; full code-validity checks are not (code list gap) |
| State codes 100% valid against official list; code 26 legitimately absent everywhere | All 3 releases | State/Ut Code | Full-file set comparison | 36/36 valid codes present in every release | Correctly reflects the 2020 Daman & Diu / Dadra & Nagar Haveli merger | Confirms full national state coverage; rules out a false "missing state" flag |
| Person-visit revisit linkage recovers ~50.3% of revisit-person records to a Visit-1 parent (2023-24) | PERV1↔PERRV | person key | Full-file match | 253,527/504,440 | Matches documented Panel-III/IV carry-over structure | Defines the maximum usable sample for any person-level revisit-consistency check |
| Reported age decreases, or jumps >2 years, between Visit-1 and a revisit, for the same person-serial-number, in a small minority of matched pairs | PERV1↔PERRV | Age | Full-file diff on matched pairs | 366 decreases (0.14%), 300 jumps >2yr (0.12%) of 253,527 | Mostly explained by household-roster churn + person-serial-number reuse; a residual is not explained | Panel-consistency checks must first test Relationship-to-Head stability before flagging a demographic change as an error |
| Reported sex differs between Visit-1 and a revisit for the same person-serial-number, in a small minority of matched pairs; only 44% of these also show a Relationship-to-Head change | PERV1↔PERRV | Sex, Relationship to Head | Full-file diff + cross-check | 254/253,527 (0.10%) mismatched sex; 112/254 also show relationship change; 94/254 are "self" in both visits with sex differing | The 94 "self, sex differs" cases are the strongest, most isolated candidate genuine data-entry errors found in this entire document | Concrete, ready-made positive example of a high-confidence anomaly signal |
| Crude employment rate varies substantially by state (27.8%–56.9%) and by sector (rural 41.2% vs. urban 37.1%) | CPERV1 (2024) | Principal Status, State, Sector | Full-file groupby | 36-state range; 2-sector comparison | Plausible, expected regional/sectoral heterogeneity | Group-level anomaly checks must be state/sector-conditioned, not nationally thresholded |
| CSV column-naming convention is completely different in each of the three releases, and (except 2025) does not match the releases' own documentation | All 8 CSVs | all columns | Position-matched string comparison, layout vs. actual header | 3 distinct naming schemes; exact-match only in Post2025 (48/48, 153/153) | A genuine documentation-quality/consistency issue across releases | Column names cannot drive cross-release harmonisation; must use Block/Item position |
| Release-3 sample size and cadence changed by design (quarterly→monthly; ~102,400→~272,304 households) | Household files, all releases | row counts | Row counts + NMDS 2.0 §2.9–2.10 | 2.66× household-count increase, documented | Deliberate, officially announced redesign | Explains the single largest cross-release "discrepancy" as non-anomalous |
| Post2025 delivered households (270,472) fall ~0.67% short of the documented target sample (272,304) | CHHV12025 | row count | Row count vs. NMDS 2.0 §2.10 | 1,832-household gap | Small, plausible, but unexplained from documentation alone | Listed as a specific MoSPI/HSD question (Part 9) |
| Revisit-file layout is documented for 2025 but no revisit CSV data was supplied | Post2025 documentation vs. data | — (structural) | Sheet inventory of `FV_Data_LayoutPLFS_2025.xlsx` vs. folder contents | 3 extra sheets (hhrv/perrv/perv1(2)) with no matching CSV | Strongly suggests revisit data exists operationally but was not included in this hand-off | Single most consequential open item for the platform's longitudinal-checking capability (Part 9) |
| No enumerator ID, supervisor ID, GPS, timestamp-beyond-date, edit history, or back-check outcome exists in any of the 691 variables | All 8 files | — (exhaustive term search) | Full inventory term search | 0 matches for any paradata term | Confirmed absence, not assumed | Defines the hard capability ceiling for enumerator-level bias detection (Part 8, Part 9) |
| Survey Date, interview duration, Response Code (informant cooperation) and Survey Code (original/substitute/casualty) are present and populated in every release | All household files | Survey Date, Total Time Taken, Response Code, Survey Code | Full-file profiling | 100% populated; e.g. 11.7% substitution rate observed (Calendar-2024) | A usable, if partial, proxy for field-process quality | Should be used as a group-level (FSU) quality-flagging input now, pending richer paradata |

## PART 11 — Implications for the Research Design

### 11.1 Strongly supported by the data

- **Deterministic/rule-based validation** (Part 8 §8.1) — the Project Brief's requirement to "define various integrity checks (e.g. referential integrity, existential integrity, etc.)" is not just supported but is already demonstrated end-to-end in this document with exact, zero-exception results. This should be the platform's **first, highest-confidence layer**, not an afterthought.
- **Group-conditioned statistical baselines** (state, sector) — real, quantified, usable baselines were established directly (Part 6 §6.4, Part 8 §8.2); this validates the general *approach* of "detect deviation from a peer-group baseline, not from a national constant," which the Project Brief's "historical trends or related surveys" framing already implies.
- **Multi-survey generality of the core rule/consistency logic** — because the deterministic rules found here (roster-count consistency, arithmetic identities, age-gated status codes) are properties of *any* well-designed household survey schedule, not idiosyncratic to PLFS, the "modular, standalone... capable of supporting multiple large-scale official surveys" objective is architecturally realistic: the platform's rule-definition layer should be built schedule-agnostic from the start, with PLFS as the first configured instance, exactly as the Brief already intends.

### 11.2 Needs modification relative to the original problem statement

- **"Evaluate the system using historical PLFS data from 2024 onwards"** (Objective 3) needs to be read check-type by check-type, not as one blanket evaluation window. Deterministic and cross-sectional statistical/contextual checks *can* be evaluated fully on 2024–2025 data. **Revisit/longitudinal consistency checks cannot** — the only revisit data in this package is July 2023–June 2024 (Part 1 §1.7, Part 8 §8.6), which barely overlaps "2024 onwards" and predates the 2025 redesign entirely. Either the evaluation plan needs to explicitly scope longitudinal checks to this earlier window (with a caveat that results may not transfer to the redesigned 2025 sampling scheme), or MoSPI/HSD needs to be asked for 2025 revisit data before that capability can be evaluated as the Brief currently frames it (Part 9 §9.4).
- **"Enumerator bias, temporal drifts"** are named explicitly in the Project Brief's Background section as target anomaly types, but **no enumerator identifier exists anywhere in the supplied data** (Part 9 §9.2). This specific capability cannot be built, in the literal sense of attributing an anomaly to a specific enumerator, with the current data. It can be substantially approximated at the FSU/cluster level (since FSU/stratum are reliable proxies for "same enumerator, most likely," given fieldwork is typically organised by FSU) — the research design should explicitly reframe this as **cluster-level drift detection**, not enumerator-level, unless/until enumerator IDs are obtained.
- **Cross-release pooling for training data** should not be treated as a simple "more historical data is always better" proposition — Part 7 established real, confirmed breaks in comparability (weighting scheme, sample design, several redefined/added variables). Models trained on pooled Release 1+2+3 data without accounting for this will learn spurious "anomalies" that are actually just the 2025 redesign (Part 7 §7.9 lists five concrete examples of exactly this trap).

### 11.3 Realistic now vs. needing more evidence first

**Realistic now, build first (V1):**
1. Deterministic/referential rule engine (Part 8 §8.1) — exact rules, already validated.
2. State/sector-conditioned statistical baselines for the core demographic/employment variables (Part 8 §8.2).
3. FSU-level coverage/substitution-rate monitoring using Response Code, Survey Code, `Caph`/`Smallh` (2025) — cheap, already-present fields, not yet exploited in this document beyond initial profiling (Part 9 §9.1) but structurally ready.
4. The specific, demonstrated Release-1 revisit-consistency method (Part 6 §6.5) as a **prototype/reference implementation** — proves the method, usable operationally on Release-1-vintage data, and directly reusable the moment any newer revisit data becomes available.

**Needs more evidence/data before building:**
1. Enumerator/cluster-level bias detection at the granularity the Project Brief's background section actually describes (needs enumerator IDs, Part 9 §9.4).
2. Any model that needs to explain *why* the wage-employed-zero-earnings pattern occurs (Part 4 §4.5(b), Part 8 §8.3) — needs either richer paradata/reason codes or a much larger, matched longitudinal sample than this package provides.
3. Full NIC/NCO code-validity checking (needs the code lists, Part 9 §9.2).
4. Any cross-release pooled statistical model (needs an explicit, MoSPI-endorsed harmonisation/re-weighting method first, Part 7 §7.10).

### 11.4 What should be tested first

Given the evidence in this document, the highest-value, lowest-risk starting point is: (a) implement and operationalise the confirmed deterministic rules (Part 8 §8.1) directly against a live/near-live extract, since they require no statistical tuning and have already been shown to hold exactly on historical data; (b) build the state/sector-conditioned baseline monitors next, since the baselines themselves are already computed in this document and only need to be kept current; (c) prototype the revisit-consistency check on Release-1 data as a proof of concept for the longitudinal capability, explicitly scoped as "urban, Panel IV/III, July 2023–June 2024" so its limitations are stated up front rather than discovered later.

### 11.5 Data limitations that could create false anomaly flags

- **Age heaping** (Whipple's Index 158–172) will make every age ending in 0/5 look like a distributional spike unless explicitly modelled (Part 6 §6.1). This is the single clearest, most quantified "false positive machine" identified in this document if left unaddressed.
- **Revisit carry-over structure**: ~50% of HHRV/PERRV records will look like "orphan" records to any check that expects every revisit to have an in-file Visit-1 parent (Part 1 §1.7) — this is a design feature, not an anomaly, and must be excluded from orphan-detection logic by construction.
- **Month-field formatting inconsistency** (Post2025, Part 3 §3.1) will make an entire release's household-person join silently fail (0% linkage) if not normalised first — a naive "100% of persons are orphaned" false alarm.
- **Sample-design change at 2025** (Part 7 §7.8–7.9) will make the entire 2025 release look like a ~2.66× volume anomaly, a new-fields anomaly, and a dropped-fields anomaly, all at once, if compared automatically against 2023-24/2024 without first encoding the documented redesign as a known, expected event.
- **Reference-period mismatch** (365-day usual status vs. 7-day CWS) produces a genuine, expected ~4.8% "disagreement rate" between Principal and CWS status (Part 4 §4.5(c)) that must be the calibration floor, not treated as 4.8% of records being wrong.

### 11.6 Survey-design effects that could look like anomalies

Everything in §11.5 is, at heart, a survey-design or data-production effect rather than a respondent- or enumerator-level data-quality problem: the rotational panel's structural non-linkage, the reference-period difference between Principal Status and CWS, the redesign-driven volume/field changes in 2025, and the documentation-vs-delivered-data naming mismatches (Part 1 §1.5) are all **properties of how PLFS is built and released**, not properties of any individual record's correctness. The platform's anomaly-detection layer needs a clear architectural separation between "known survey-design effect, encode and suppress" and "genuine candidate anomaly" — this document's Parts 1, 3 and 7 are, collectively, a first version of that "known effects" registry.

### 11.7 What should not be modelled together

- **Release 3 and Releases 1–2 should not be pooled into a single statistical model without an explicit harmonisation step** (Part 7 §7.10) — different sample design, different weighting scheme, different (and in places non-overlapping) variable sets.
- **Revisit (HHRV/PERRV) and Visit-1 (HHV1/PERV1) records should not be modelled as if they were the same kind of observation** for any check sensitive to which fields are actually collected at each visit — HHRV, for instance, does not carry the Block-3 expenditure sub-item breakdown that HHV1 does (Part 1 §1.1), and PERRV does not carry Block 4.1 vocational-training detail (Part 1 §1.1, corrected).
- **The Block-6 day-wise activity-status code list and the Block-5.1/5.2 usual-status code list should not be treated as the same categorical variable** in a shared model — Block 6 has six additional codes with no Block-5.1/5.2 equivalent (Part 2 §2.4, Part 7 §7.5); collapsing them naively would either lose information or silently misclassify legitimate day-wise-only states.

### 11.8 Where separate models/logic should be used

Separate logic paths are warranted for: rural vs. urban (revisit availability differs completely, Part 1 §1.7); Release 1 vs. Release 2 vs. Release 3 (weighting scheme, Part 7 §7.6); Visit-1 vs. revisit records (field content differs, §11.7 above); and Principal/Subsidiary usual-status fields vs. Block-6 day-wise/CWS fields (different reference period and, in part, different code lists).

### 11.9 What needs expert confirmation from HSD

The full list is compiled in Part 9 §9.3–9.4; the highest-priority items to raise first, because they gate entire capability areas rather than single fields, are: (1) whether Post2025 revisit data exists and can be shared; (2) whether enumerator/supervisor identifiers can be made available, even pseudonymised, for research use; (3) the intended interpretation of the ~38.2% wage-employed/zero-current-earnings pattern; (4) confirmation of the 2025 (Panel 5) code dictionary, including the `Group` field's definition and the `lposs`/`llease` code labels.

### 11.10 V1 vs. future research

**V1 (buildable now, on this data):** deterministic rule engine; state/sector-conditioned statistical baselines; FSU-level field-quality monitoring from Response/Survey codes; a Release-1-scoped revisit-consistency prototype; a documented, versioned "known survey-design effects" registry (a direct output of this document) to suppress false positives.

**Future research (needs data this package does not contain):** enumerator/cluster-level bias attribution; full longitudinal consistency checking on current (2025+) data; industry/occupation code-validity checking; cross-release pooled modelling under a MoSPI-endorsed harmonisation scheme; any use of true field paradata (timestamps, GPS, edit history, back-checks) for either detection or evaluation-ground-truth purposes.

## PART 12 — Final Research Baseline

### What We Now Know About PLFS Data

We have three PLFS unit-level releases — July 2023–June 2024 (with full rotational-panel revisit data, urban-only), Calendar 2024 (first-visit only), and Calendar 2025 (first-visit only, under a redesigned, monthly, ~2.66×-larger sampling scheme) — and we have verified, by reading every supplied document and processing every row of every CSV, that the delivered data matches its own documentation exactly in structure (row counts, column counts, and byte-position-to-column mapping, all 8 files) while using **three completely different, and mostly undocumented-in-practice, CSV column-naming conventions** across the three releases. The underlying Schedule-10.4 questionnaire is stable in its core (31 household and 103 person variables identical by name across all three releases), while genuinely expanding in 2025 to add a household income block, richer education-history detail, and new sample-design/variance-support fields — all confirmed, documented, deliberate changes, not data-quality problems. Several derived-field arithmetic identities (household expenditure total, 2025 household income total) hold **exactly**, with zero exceptions, across every household in every release, and household-to-person roster counts likewise match exactly everywhere. The rotational-panel revisit mechanism in Release 1 was independently and precisely confirmed against the actual data — including the specific, documented fact that revisits occur **only** in the urban sector — and a genuine, if partial (~50%), longitudinal linkage was established and used to demonstrate a working revisit-consistency check, which itself surfaced a small, well-characterised, high-confidence set of likely genuine data anomalies (Part 6 §6.5) alongside a much larger, fully explainable set of "changes" that are legitimate household-roster churn. We know precisely which cross-variable rules hold as hard rules (age<5→status 99), which hold as strong-but-imperfect statistical regularities with a known baseline rate (Principal-vs-CWS status, 95.2% concordance), and which are genuinely ambiguous and require further data to resolve (the 38.2% wage-employed/zero-current-earnings pattern). We know exactly what paradata does and does not exist in this package: no enumerator ID, supervisor ID, GPS, or edit history anywhere; but Survey Date, interview duration, and informant-cooperation/substitution codes are present and usable now.

### What We Still Do Not Know

Whether 2025 revisit (panel) data exists at MoSPI/NSO and can be shared — the single most consequential open question, because without it, no longitudinal-consistency capability can be evaluated on current-vintage data, directly bearing on the Project Brief's stated evaluation window. Whether enumerator- or supervisor-level identifiers can ever be made available for this kind of research use, which gates the enumerator-bias detection capability the Project Brief's own background section names as a motivating use case. The precise mechanism behind several small, well-quantified but unexplained numerical gaps (the ~1,000-person employed-status/industry-code discrepancy, the ~1,832-household shortfall against the documented 2025 sample target, the 46 households with two same-quarter revisit rounds). The definition of the new 2025 `Group` field and the code labels for the new land-possession items. Whether the Block 5/6 activity-status code list, confirmed exhaustively for Panel 4 (2023-24/2024), is unchanged for Panel 5 (2025) — no Panel-5 code dictionary was supplied to check this directly. And, fundamentally, the operational reality behind the ambiguous statistical patterns this document was able to *quantify* but not *explain* (most importantly, the wage-employed/zero-earnings pattern) — resolving these needs either richer paradata, explicit reason-code fields, or a properly matched longitudinal sample, none of which is available in the current package.

### What We Should Do Next

First, take the specific, itemised list of MoSPI/HSD questions in Part 9 §9.3–9.4 back to HSD as a concrete, evidence-backed data request — each question is scoped to a specific, quantified finding in this document, not a generic ask, and (per the Grant-in-Aid Guidelines governing MoSPI-funded research studies, Section 4.2) any resulting proposal should state exactly this kind of specific data requirement up front, since data support is explicitly one of the two forms of assistance the scheme offers. Second, build the V1 capability set identified in Part 11 §11.10 — the deterministic rule engine and the state/sector-conditioned statistical baselines — since both are fully validated against real historical data in this document and need no further data to start. Third, treat this document's "known survey-design effects" material (Parts 1, 3, 7, and Part 11 §11.5–§11.6) as a living registry that the platform consults before ever surfacing a flag, so the system does not spend its first months of operation re-discovering, the hard way, findings this document has already established for free. Fourth, prototype the revisit-consistency check on Release 1 now, explicitly scoped to its actual coverage (urban, Panel III/IV, July 2023–June 2024), both to prove the method and to have it ready to extend the moment any 2025 revisit data becomes available. Fifth, resist the temptation to pool all three releases into one training set before the Part 7 harmonisation questions are resolved with MoSPI — a model trained on unharmonised pooled data will, with high confidence, rediscover the 2025 redesign as a set of "anomalies," which would be a costly and avoidable mistake this document exists specifically to prevent.
