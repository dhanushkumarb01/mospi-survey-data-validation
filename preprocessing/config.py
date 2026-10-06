"""Documented PLFS delivery contracts used by the preparation pipeline.

The field mappings and key choices below are facts recorded in the project's
PLFS evidence notebook and the release README files.  They are intentionally
release-specific: raw headers must never be treated as a pooled schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DatasetContract:
    """A contract for one supplied release/observation path."""

    release: str
    observation: str
    design_period: str
    cadence: str
    household_path: str
    person_path: str
    household_fields: Mapping[str, str]
    person_fields: Mapping[str, str]
    household_key: tuple[str, ...]
    person_serial: str
    expected_household_columns: int
    expected_person_columns: int
    documented_code_values: Mapping[str, frozenset[str]] = field(default_factory=dict)
    expected_household_headers: frozenset[str] | None = None
    expected_person_headers: frozenset[str] | None = None
    reference_files: tuple[str, ...] = ()

    def file_path(self, root: Path, level: str) -> Path:
        return root / (self.household_path if level == "household" else self.person_path)

    def fields(self, level: str) -> Mapping[str, str]:
        return self.household_fields if level == "household" else self.person_fields


# The codes below are directly evidenced in the supplied README/codebook and
# the completed EDA.  Blank substitution reasons are allowed: applicability is
# not inferred solely from the raw CSV and is therefore reported, not changed.
COMMON_CODES = {
    "sector": frozenset({"1", "2"}),
    "response": frozenset({"1", "2", "3", "4", "9"}),
    "survey_code": frozenset({"1", "2"}),
    "substitution_reason": frozenset({"1", "2", "3", "9"}),
}

PRE2025_HH_KEY = ("quarter", "sector", "state", "district", "fsu", "segment", "sss", "household")
POST2025_HH_KEY = ("quarter", "month", "sector", "state", "district", "fsu", "sss", "household")
REVISIT_HH_KEY = ("quarter", "visit", "sector", "state", "district", "fsu", "segment", "sss", "household")


def _codes(*, quarters: set[str], visits: set[str], month: bool = False) -> dict[str, frozenset[str]]:
    codes = dict(COMMON_CODES)
    codes["quarter"] = frozenset(quarters)
    codes["visit"] = frozenset(visits)
    if month:
        codes["month"] = frozenset(str(value) for value in range(1, 13))
    return codes


CONTRACTS: dict[str, DatasetContract] = {
    "2023_24_first": DatasetContract(
        release="2023_24", observation="first_visit", design_period="pre_2025", cadence="quarterly",
        household_path="2023-June2024/CSV_data_PLFS_2023_2024/CSV_data_PLFS_2023_2024/hhv1.csv",
        person_path="2023-June2024/CSV_data_PLFS_2023_2024/CSV_data_PLFS_2023_2024/perv1.csv",
        household_fields={"panel": "B1q2_hhv1", "quarter": "qtr_hhv1", "visit": "visit_hhv1", "sector": "b1q3_hhv1", "state": "state_hhv1", "district": "distcode_hhv1", "stratum": "b1q5_hhv1", "fsu": "b1q1_hhv1", "segment": "b1q13_hhv1", "sss": "b1q14_hhv1", "household": "b1q15_hhv1", "household_size": "b3q1_hhv1", "response": "b1q17_hhv1", "survey_code": "b1q18_hhv1", "substitution_reason": "b1q19_hhv1", "survey_date": "b2q2i_hhv1", "survey_duration": "b2q4_hhv1", "weight": "mult_hhv1"},
        person_fields={"panel": "B1q2_perv1", "quarter": "qtr_perv1", "visit": "visit_perv1", "sector": "b1q3_perv1", "state": "state_perv1", "district": "distcode_perv1", "stratum": "b1q5_perv1", "fsu": "b1q1_perv1", "segment": "b1q13_perv1", "sss": "b1q14_perv1", "household": "b1q15_perv1", "person": "b4q1_perv1", "age": "b4q6_perv1", "principal_industry": "b5pt1q5_perv1", "training_completed": "b4pt1q3_perv1", "day7_activity2": "b6q4_act2_3pt1_perv1", "earnings_salaried": "b6q9_perv1", "earnings_self_employed": "b6q10_perv1", "weight": "mult_perv1"},
        household_key=PRE2025_HH_KEY, person_serial="person", expected_household_columns=37, expected_person_columns=139,
        documented_code_values=_codes(quarters={"Q1", "Q2", "Q3", "Q4"}, visits={"V1"}),
        reference_files=("2023-June2024/1_README.docx", "2023-June2024/Data_LayoutPLFS_2023-24.xlsx"),
    ),
    "2023_24_revisit": DatasetContract(
        release="2023_24", observation="revisit", design_period="pre_2025", cadence="quarterly",
        household_path="2023-June2024/CSV_data_PLFS_2023_2024/CSV_data_PLFS_2023_2024/hhrv.csv",
        person_path="2023-June2024/CSV_data_PLFS_2023_2024/CSV_data_PLFS_2023_2024/perrv.csv",
        household_fields={"panel": "B1q2_hhrv", "quarter": "qtr_hhrv", "visit": "visit_hhrv", "sector": "b1q3_hhrv", "state": "state_hhrv", "district": "distcode_hhrv", "stratum": "b1q5_hhrv", "fsu": "b1q1_hhrv", "segment": "b1q13_hhrv", "sss": "b1q14_hhrv", "household": "b1q15_hhrv", "household_size": "b3q1_hhrv", "response": "b1q17_hhrv", "survey_code": "b1q18_hhrv", "substitution_reason": "b1q19_hhrv", "survey_date": "b2q2i_hhrv", "survey_duration": "b2q4_hhrv", "weight": "mult_hhrv"},
        person_fields={"panel": "B1q2_perrv", "quarter": "qtr_perrv", "visit": "visit_perrv", "sector": "b1q3_perrv", "state": "state_perrv", "district": "dist_code_perrv", "stratum": "b1q5_perrv", "fsu": "b1q1_perrv", "segment": "b1q13_perrv", "sss": "b1q14_perrv", "household": "b1q15_perrv", "person": "b4q1_pervv", "age": "b4q6_perrv", "earnings_salaried": "b6q9_perrv", "earnings_self_employed": "b6q10_perrv", "weight": "mult_perrv"},
        household_key=REVISIT_HH_KEY, person_serial="person", expected_household_columns=32, expected_person_columns=104,
        documented_code_values=_codes(quarters={"Q1", "Q2", "Q3", "Q4"}, visits={"V2", "V3", "V4"}),
        reference_files=("2023-June2024/1_README.docx", "2023-June2024/Data_LayoutPLFS_2023-24.xlsx"),
    ),
    "2024_first": DatasetContract(
        release="2024", observation="first_visit", design_period="pre_2025", cadence="quarterly",
        household_path="Jan-Dec2024/Data in CSV/chhv1.csv", person_path="Jan-Dec2024/Data in CSV/cperv1.csv",
        household_fields={"panel": "Panel", "quarter": "Quarter", "visit": "Visit", "sector": "Sector", "state": "State_Ut_Code", "district": "District_Code", "stratum": "Stratum", "fsu": "FSU", "segment": "Sample_Sg_Sb_No", "sss": "Second_Stage_Stratum_No", "household": "Sample_Household_Number", "household_size": "Household_Size", "response": "Response_Code", "survey_code": "Survey_Code", "substitution_reason": "Reason_for_Substitution", "survey_date": "Survey_Date", "survey_duration": "Total_Time_Taken", "weight": "Subsample_Multiplier"},
        person_fields={"panel": "Panel", "quarter": "Quarter", "visit": "Visit", "sector": "Sector", "state": "State_UT_Code", "district": "District_Code", "stratum": "Stratum", "fsu": "FSU", "segment": "Sample_Sg_Sb_No", "sss": "Second_Stage_Stratum_No", "household": "Sample_Household_Number", "person": "Person_Serial_No", "age": "Age", "principal_industry": "Principal_Industry_Code", "training_completed": "Training_Completed_365_Days", "day7_activity2": "Day7_Act2_Status_Code", "earnings_salaried": "CWS_Earnings_Salaried", "earnings_self_employed": "CWS_Earnings_SelfEmployed", "weight": "Subsample_Multiplier"},
        household_key=PRE2025_HH_KEY, person_serial="person", expected_household_columns=38, expected_person_columns=140,
        documented_code_values=_codes(quarters={"Q3", "Q4", "Q5", "Q6"}, visits={"V1"}),
        reference_files=("Jan-Dec2024/README_Calendar_2024 (3).docx", "Jan-Dec2024/Data_LayoutPLFS_Calendar_2024 (4).xlsx", "Jan-Dec2024/PLFS Panel 4 Sch 10.4 Item Code Description & Codes (1).xlsx"),
    ),
    "2025_first": DatasetContract(
        release="2025", observation="first_visit", design_period="post_2025", cadence="monthly",
        household_path="Post2025/Data_in_CSV/Data_in_CSV/chhv12025.csv", person_path="Post2025/Data_in_CSV/Data_in_CSV/cperv12025.csv",
        household_fields={"panel": "panel", "quarter": "qtr", "month": "month", "visit": "visit", "sector": "sec", "state": "st", "district": "dc", "stratum": "strm", "group": "grp", "substratum": "sstrm", "fsu": "mfsu", "sss": "sss", "household": "ssu", "household_size": "hh_size", "response": "resp_code", "survey_code": "svc", "substitution_reason": "rea_sub", "survey_date": "sur_date", "survey_duration": "sur_time", "weight": "mult"},
        person_fields={"panel": "panel", "quarter": "qtr", "month": "month", "visit": "visit", "sector": "sec", "state": "st", "district": "dc", "stratum": "strm", "group": "grp", "substratum": "sstrm", "fsu": "mfsu", "sss": "sss", "household": "ssu", "person": "srl", "age": "age", "principal_industry": "ind_pas", "training_completed": "voc_compl", "day7_activity2": "das27", "earnings_salaried": "ern_reg", "earnings_self_employed": "ern_self", "weight": "mult"},
        household_key=POST2025_HH_KEY, person_serial="person", expected_household_columns=48, expected_person_columns=153,
        documented_code_values=_codes(quarters={"Q1", "Q2", "Q3", "Q4"}, visits={"V1"}, month=True),
        reference_files=("Post2025/README2025.docx", "Post2025/FV_Data_LayoutPLFS_2025.xlsx", "Post2025/Indian_States_and_UTs_CodeName.xlsx", "Post2025/Indian_Districts_CodeName.xlsx"),
    ),
}
