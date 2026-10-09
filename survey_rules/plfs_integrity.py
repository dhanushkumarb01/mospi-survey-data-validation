"""PLFS concept maps and code lists for the integrity-rule engine.

Rules (integrity/rules/*.yaml) are written in survey *concepts*; this module
resolves each concept to the raw column of a given release, so the engine
itself stays survey-agnostic.  A concept missing for a release means the item
was not collected there: rules using it are "not applicable", never "passed".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

PERSON_CONCEPTS: dict[tuple[str, str], dict[str, str]] = {
    ("2023_24", "first_visit"): {
        "relation": "b4q4_perv1", "education": "b4q8_perv1", "attendance": "b4q11_perv1",
        "day7_act1_status": "b6q4_3pt1_perv1", "day7_act1_hours": "b6q6_3pt1_perv1",
        "day7_act2_status": "b6q4_act2_3pt1_perv1", "day7_act2_hours": "b6q6_act2_3pt1_perv1", "day7_wage": "b6q9_3pt1_perv1",
    },
    ("2024", "first_visit"): {
        "relation": "Relationship_To_Head", "education": "General_Education_Level", "attendance": "Current_Attendance_Status",
        "day7_act1_status": "Day7_Act1_Status_Code", "day7_act1_hours": "Day7_Act1_Hours",
        "day7_act2_status": "Day7_Act2_Status_Code", "day7_act2_hours": "Day7_Act2_Hours", "day7_wage": "Day7_Act1_Wage",
    },
    ("2025", "first_visit"): {
        "relation": "rel", "education": "gedu_lvl", "attendance": "curr_att",
        "day7_act1_status": "das17", "day7_act1_hours": "hr17", "day7_act2_status": "das27", "day7_act2_hours": "hr27", "day7_wage": "ern17",
        "day1_hours": "hr1", "day2_hours": "hr2", "day3_hours": "hr3", "day4_hours": "hr4", "day5_hours": "hr5", "day6_hours": "hr6",
        "weekly_hours": "tothrs_wrk",
    },
}

HOUSEHOLD_CONCEPTS: dict[tuple[str, str], dict[str, str]] = {
    ("2023_24", "first_visit"): {
        "household_size": "b3q1_hhv1", "mpce_a": "b3q5pt1_hhv1", "mpce_b": "b3q5pt2_hhv1", "mpce_c": "b3q5pt3_hhv1",
        "mpce_d": "b3q5pt4_hhv1", "mpce_e": "b3q5pt5_hhv1", "mpce_total": "b3q5pt6_hhv1", "survey_date": "b2q2i_hhv1", "district": "distcode_hhv1",
    },
    ("2024", "first_visit"): {
        "household_size": "Household_Size", "mpce_a": "Usual_Expenditure", "mpce_b": "Imputed_Homegrown_Consumption",
        "mpce_c": "Imputed_Wages_Consumption", "mpce_d": "Annual_Clothing_Expenditure", "mpce_e": "Annual_Durables_Expenditure",
        "mpce_total": "Monthly_Consumer_Expenditure", "survey_date": "Survey_Date", "district": "District_Code",
    },
    ("2025", "first_visit"): {
        "household_size": "hh_size", "mpce_a": "hce1", "mpce_b": "hce2", "mpce_c": "hce3", "mpce_d": "hce4", "mpce_e": "hce5",
        "mpce_total": "hce_tot", "income_rent": "rent", "income_interest": "interest", "income_pension": "pension",
        "income_remittance": "remit", "income_total": "inc_tot", "survey_date": "sur_date", "district": "dc",
    },
}

# Supplied district code lists (referential checks).  Each entry: workbook,
# sheet, header row (0-based) and the State / district code columns.
DISTRICT_CODE_LISTS: dict[str, dict[str, object]] = {
    "2023_24": {"file": "2023-June2024/District_codes_PLFS_Panel_4_202324_2024.xlsx", "header": 3, "state": "State Code", "district": "DISTRICT CODE"},
    "2024": {"file": "Jan-Dec2024/District_codes_PLFS_Panel_4_202324_2024 (1).xlsx", "header": 3, "state": "State Code", "district": "DISTRICT CODE"},
    "2025": {"file": "Post2025/Indian_Districts_CodeName.xlsx", "header": 0, "state": "State Code", "district": "District Code"},
}

# Calendar months of each period on the design axis (survey_rules.plfs).
PRE_2025_QUARTER_MONTHS = {
    ("2023_24", "Q1"): (7, 8, 9), ("2023_24", "Q2"): (10, 11, 12), ("2023_24", "Q3"): (1, 2, 3), ("2023_24", "Q4"): (4, 5, 6),
    ("2024", "Q3"): (1, 2, 3), ("2024", "Q4"): (4, 5, 6), ("2024", "Q5"): (7, 8, 9), ("2024", "Q6"): (10, 11, 12),
}


def district_code_list(release: str) -> set[tuple[str, str]] | None:
    """(State code, district code) pairs from the supplied workbook, or None when unavailable."""
    spec = DISTRICT_CODE_LISTS.get(release)
    if spec is None:
        return None
    path = ROOT / str(spec["file"])
    if not path.is_file():
        return None
    frame = pd.read_excel(path, header=int(spec["header"]), dtype=str)
    state = frame[str(spec["state"])].astype("string").str.strip().str.zfill(2)
    district = frame[str(spec["district"])].astype("string").str.strip().str.zfill(2)
    valid = state.str.fullmatch(r"\d{2}") & district.str.fullmatch(r"\d{2,3}")
    return set(zip(state[valid], district[valid]))


def period_months(release: str, quarter: str, month: str) -> tuple[int, ...] | None:
    if str(release) == "2025":
        try:
            return (int(float(month)),)
        except (TypeError, ValueError):
            return None
    return PRE_2025_QUARTER_MONTHS.get((str(release), str(quarter).strip()))
