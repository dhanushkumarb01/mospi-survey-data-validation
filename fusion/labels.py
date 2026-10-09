"""Plain-language labels for PLFS codes and MoSPI variables shown to supervisors.

Code descriptions are transcribed from the supplied official code lists only:

- ``Post2025/Indian_States_and_UTs_CodeName.xlsx`` (State/UT names)
- ``Jan-Dec2024/PLFS Panel 4 Sch 10.4 Item Code Description & Codes (1).xlsx``
  (Block 4 relation/marital/education codes, Block 6 activity status codes)
- Sector 1 = Rural, 2 = Urban and the three-valued sex code are recorded in
  ``PLFS_Data_Research_Foundation.md``.

A code that is not in these lists is shown as its raw code, never guessed.
"""

from __future__ import annotations

from typing import Any


STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "25": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "28": "Andhra Pradesh",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Ladakh",
}

SECTORS = {"1": "Rural", "2": "Urban"}

SEX = {"1": "Male", "2": "Female", "3": "Transgender"}

RELATION_TO_HEAD = {
    "1": "Head of household", "2": "Spouse of head", "3": "Married child", "4": "Spouse of married child",
    "5": "Unmarried child", "6": "Grandchild", "7": "Parent / parent-in-law",
    "8": "Sibling / sibling-in-law / other relative", "9": "Servant / employee / other non-relative",
}

MARITAL_STATUS = {"1": "Never married", "2": "Currently married", "3": "Widowed", "4": "Divorced / separated"}

EDUCATION = {
    "01": "Not literate", "02": "Literate without formal schooling (EGS/NFEC/AEC)",
    "03": "Literate without formal schooling (TLC)", "04": "Literate without formal schooling (others)",
    "05": "Literate, below primary", "06": "Primary", "07": "Middle", "08": "Secondary", "10": "Higher secondary",
    "11": "Diploma / certificate course", "12": "Graduate", "13": "Postgraduate and above",
}

# Block 6 (current weekly / day-wise) activity status codes.
ACTIVITY_STATUS = {
    "11": "Self-employed: own-account worker", "12": "Self-employed: employer",
    "21": "Unpaid helper in household enterprise", "31": "Regular salaried / wage employee",
    "41": "Casual wage labour: public works", "42": "Casual wage labour: MGNREG works",
    "51": "Casual wage labour: other work", "61": "Had household-enterprise work but did not work: sickness",
    "62": "Had household-enterprise work but did not work: other reasons",
    "71": "Had salaried/wage job but did not work: sickness", "72": "Had salaried/wage job but did not work: other reasons",
    "81": "Sought work", "82": "Did not seek but was available for work", "91": "Attended educational institution",
    "92": "Domestic duties only", "93": "Domestic duties and free collection of goods for household use",
    "94": "Rentier / pensioner / remittance recipient", "95": "Not able to work due to disability",
    "97": "Others", "98": "Did not work due to temporary sickness (casual workers)", "99": "Age below 5",
}

# MoSPI target / pattern variables in supervisor language.
VARIABLES = {
    "cws_earnings_salaried": {"label": "Earnings from regular salaried/wage work", "short": "salaried earnings", "unit": "rupees"},
    "cws_earnings_self_employed": {"label": "Earnings from self-employment", "short": "self-employment earnings", "unit": "rupees"},
    "day7_total_hours": {"label": "Total hours worked on day 7 of the reference week", "short": "hours worked on day 7", "unit": "hours"},
    "day7_casual_wage": {"label": "Daily wage for casual work on day 7 of the reference week", "short": "day-7 casual wage", "unit": "rupees"},
    "age": {"label": "Age", "short": "age", "unit": "years"},
    "cws_status": {"label": "Current weekly activity status", "short": "activity status", "unit": "code"},
    "principal_industry_division": {"label": "Industry division of principal activity", "short": "industry", "unit": "code"},
    "principal_occupation_major_group": {"label": "Occupation group of principal activity", "short": "occupation group", "unit": "code"},
    "median_age": {"label": "Median age", "short": "median age", "unit": "years"},
    "median_cws_earnings_salaried": {"label": "Median salaried earnings", "short": "median salaried earnings", "unit": "rupees"},
    "median_cws_earnings_self_employed": {"label": "Median self-employment earnings", "short": "median self-employment earnings", "unit": "rupees"},
    "median_day7_total_hours": {"label": "Median hours worked on day 7", "short": "median day-7 hours", "unit": "hours"},
    "cws_status_code_1_proportion": {"label": "Share with activity status code group 1", "short": "status share", "unit": "share"},
}

# Peer-group dimension names in supervisor language.
DIMENSIONS = {
    "state": "State/UT", "sector": "Sector", "cws_status": "Current weekly activity status",
    "occupation_major_group": "Occupation", "education": "General education level", "industry_division": "Industry division",
    "day7_activity1_status": "Activity on day 7", "day7_activity1_industry": "Industry of day-7 work", "quarter": "Survey quarter",
}

PRIORITY_BANDS = {
    "CHECK_NOW": "Check now", "CHECK_IF_TIME": "Check if time", "NOT_FLAGGED": "Not flagged", "NOT_ASSESSABLE": "No check possible",
    # Superseded V2.0 runs (risk x influence bands), shown only when such a run is selected.
    "CRITICAL": "Highest priority (superseded method)", "HIGH": "High priority (superseded method)", "MEDIUM": "Medium priority (superseded method)",
    "LOW": "Low priority (superseded method)",
}

LANES = {
    "RULE": "Questionnaire rule not met", "RULE_SOFT": "Soft questionnaire check", "VALUE": "Unusual value",
    "CODING": "Unusual occupation code",
}

# FSU group alerts are banded by the Benjamini-Hochberg q-value of the strongest FSU check.
GROUP_BANDS = {
    "HIGH": "Clear group difference", "MEDIUM": "Group difference", "LOW": "No notable group difference",
    "NOT_ASSESSABLE": "Not assessed", "CRITICAL": "Highest priority",
}

DECISIONS = {
    "CONFIRMED_ERROR": "Confirmed error", "VALID_BUT_UNUSUAL": "Valid but unusual", "NEEDS_FIELD_VERIFICATION": "Needs field verification",
    "CANNOT_VERIFY": "Cannot verify", "ESCALATE": "Escalated", "UNREVIEWED": "Not yet reviewed",
}

REASON_CODES = {
    "EXTRA_OR_MISSING_ZERO": "Extra or missing zero", "MONTHLY_ANNUAL_CONFUSION": "Monthly / annual amount confused",
    "DIGIT_TRANSPOSITION": "Digits swapped", "WRONG_CODE": "Wrong code recorded", "WRONG_UNIT_OR_PERIOD": "Wrong unit or reference period",
    "WRONG_PERSON_OR_HOUSEHOLD": "Answer belongs to another person or household", "GENUINE_HIGH_OR_LOW_VALUE": "Genuinely high or low value",
    "SEASONAL_OR_ONE_OFF": "Seasonal or one-off situation", "SPECIAL_CIRCUMSTANCE": "Special circumstance", "RARE_BUT_CORRECT_CODE": "Rare but correct code",
    "CALL_BACK": "Call the household back", "REVISIT": "Revisit the household", "CHECK_SCHEDULE_IMAGE": "Check the schedule image",
    "RESPONDENT_UNREACHABLE": "Respondent unreachable", "NO_SCHEDULE_IMAGE": "No schedule image available",
    "POSSIBLE_FIELDWORK_ISSUE": "Possible fieldwork issue", "NEEDS_SUBJECT_EXPERT": "Needs a subject expert", "OTHER": "Other (explain in the note)",
}

VERIFICATION_SOURCES = {
    "PHONE_CALL": "Phone call", "FIELD_REVISIT": "Field revisit", "SCHEDULE_IMAGE": "Schedule image",
    "SUPERVISOR_KNOWLEDGE": "Supervisor's knowledge", "NOT_VERIFIED": "Not verified",
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def code_label(mapping: dict[str, str], value: Any, *, width: int | None = None) -> str | None:
    """Return the documented label for a code, or ``None`` when undocumented."""
    text = clean(value)
    if not text:
        return None
    if text in mapping:
        return mapping[text]
    if width and text.isdigit():
        return mapping.get(text.zfill(width))
    return mapping.get(text.lstrip("0") or text)


def state_name(value: Any) -> str:
    text = clean(value)
    label = code_label(STATES, text, width=2)
    return f"{label}" if label else (f"State code {text}" if text else "State not recorded")


def sector_name(value: Any) -> str:
    text = clean(value)
    return SECTORS.get(text, f"Sector code {text}" if text else "Sector not recorded")


def variable_label(name: Any) -> str:
    text = clean(name)
    return VARIABLES.get(text, {}).get("label", text.replace("_", " ").capitalize() if text else "Value")


def variable_unit(name: Any) -> str:
    return VARIABLES.get(clean(name), {}).get("unit", "")


def format_value(value: Any, unit: str) -> str:
    """Format a stored number in the unit it was recorded in (no rescaling)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return clean(value) or "not recorded"
    if number != number:  # NaN
        return "not recorded"
    if unit == "rupees":
        return "₹" + _indian_grouping(number)
    if unit == "hours":
        return f"{number:g} hour" + ("" if number == 1 else "s")
    if unit == "years":
        return f"{number:g} years"
    if unit == "share":
        return f"{number * 100:.0f}%"
    return f"{number:g}"


def count(value: Any) -> str:
    """Whole-number count with Indian digit grouping (e.g. 4,11,344)."""
    try:
        return _indian_grouping(float(value))
    except (TypeError, ValueError):
        return "—"


def _indian_grouping(number: float) -> str:
    negative = number < 0
    integer = int(round(abs(number)))
    text = str(integer)
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        text = ",".join(groups + [tail])
    return ("−" if negative else "") + text
