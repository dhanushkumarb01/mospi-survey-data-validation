"""A small synthetic delivery in the documented Calendar-2024 prepared layout (tests only).

Nothing here resembles real respondents; values are drawn from simple
distributions so that every stage has enough comparable records to run.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

READY = "ready_for_downstream_preparation_only"
STATUS_MIX = ("31", "31", "11", "51", "91", "92")


def write_delivery(folder: Path, *, seed: int = 11, fsus_per_cell: int = 6, households: int = 6, persons: int = 4) -> tuple[Path, dict[str, str]]:
    """Write prepared_persons/households + run_metadata; return (person path, ids of injected cases)."""
    rng = np.random.default_rng(seed)
    person_rows, household_rows = [], []
    for quarter, month in (("Q3", 2), ("Q4", 5), ("Q5", 8), ("Q6", 11)):
        for sector in ("1", "2"):
            for f in range(fsus_per_cell):
                fsu = f"{quarter}{sector}{f:03d}"
                stratum = f"{1 + f % 2:02d}"
                for h in range(households):
                    key = f"{quarter}|{sector}|07|01|{fsu}|1|1|{h + 1:02d}"
                    household_rows.append({
                        "MoSPI_record_key": key, "MoSPI_release": "2024", "MoSPI_observation": "first_visit", "MoSPI_design_period": "pre_2025",
                        "MoSPI_visit": "V1", "MoSPI_state": "07", "MoSPI_sector": sector, "MoSPI_stratum": stratum, "MoSPI_fsu": fsu, "MoSPI_quarter": quarter,
                        "MoSPI_prepared_status": READY, "Household_Size": str(persons), "Usual_Expenditure": "6000", "Imputed_Homegrown_Consumption": "500",
                        "Imputed_Wages_Consumption": "0", "Annual_Clothing_Expenditure": "1200", "Annual_Durables_Expenditure": "2400",
                        "Monthly_Consumer_Expenditure": "6800", "Survey_Date": f"{10 + h:02d}{month:02d}2024", "Total_Time_Taken": str(int(rng.integers(40, 80))),
                        "Response_Code": "1", "Survey_Code": "1", "District_Code": "01"})
                    for p in range(persons):
                        status = STATUS_MIX[int(rng.integers(len(STATUS_MIX)))] if p else "31"
                        age = int(rng.integers(18, 60)) if status != "91" else int(rng.integers(6, 20))
                        hours = {"31": 8, "11": 9, "51": 8}.get(status, 0)
                        salary = int(round(float(np.exp(rng.normal(np.log(18000 if sector == "2" else 12000), 0.25))), -2)) if status == "31" else 0
                        self_emp = int(round(float(np.exp(rng.normal(np.log(9000), 0.4))), -2)) if status == "11" else 0
                        wage = int(round(float(np.exp(rng.normal(np.log(400), 0.2))))) if status == "51" else 0
                        person_rows.append({
                            "MoSPI_source_row": len(person_rows) + 2, "MoSPI_record_key": key, "MoSPI_release": "2024", "MoSPI_observation": "first_visit",
                            "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V1", "MoSPI_prepared_status": READY, "MoSPI_state": "07", "MoSPI_sector": sector,
                            "MoSPI_stratum": stratum, "MoSPI_fsu": fsu, "MoSPI_quarter": quarter, "MoSPI_household_link_status": "matched",
                            "Person_Serial_No": str(p + 1), "Age": str(age), "Sex": str(1 + p % 2), "Marital_Status": "2", "Relationship_To_Head": "1" if p == 0 else "2",
                            "General_Education_Level": "08", "Technical_Education_Level": "01", "Years_Formal_Education": "10",
                            "Current_Attendance_Status": "24" if status == "91" else "", "Vocational_Training": "6", "Principal_Status_Code": status,
                            "Principal_Industry_Code": {"31": "84110", "11": "47190", "51": "41001"}.get(status, ""),
                            "Principal_Occupation_Code": {"31": "411", "11": "522", "51": "931"}.get(status, ""), "Subsidiary_Work_Engagement": "2",
                            "Principal_Workplace_Location": "", "Principal_Enterprise_Type": "", "Principal_Workers_Count": "", "Principal_Job_Contract_Type": "",
                            "Principal_Paid_Leave": "", "Principal_Social_Security": "", "CWS_Status_Code": status,
                            "Day7_Act1_Status_Code": status, "Day7_Act1_Industry_Code": {"31": "84", "11": "47", "51": "41"}.get(status, "99"),
                            "Day7_Act1_Hours": str(hours), "Day7_Act1_Wage": str(wage), "Day7_Act2_Status_Code": "", "Day7_Act2_Hours": "",
                            "Day7_Total_Hours": str(hours), "Day6_Total_Hours": str(hours), "Day1_Total_Hours": str(hours),
                            "CWS_Earnings_Salaried": str(salary), "CWS_Earnings_SelfEmployed": str(self_emp), "District_Code": "01",
                            "Training_Completed_365_Days": "", "Subsample_Multiplier": str(int(rng.integers(2000, 6000))),
                            "Ns_Count_Sector_Stratum_Substratum_Subsample": "4", "Ns_Count_Sector_Stratum_Substratum": "8", "State_Sector_Stratum_Substra": "4"})
    persons_frame, households_frame = pd.DataFrame(person_rows), pd.DataFrame(household_rows)
    # Injected: an extra zero in one Q6 salary (passes every CAPI-style rule), and a household-size breach.
    salaried = persons_frame.index[persons_frame["MoSPI_quarter"].eq("Q6") & persons_frame["CWS_Status_Code"].eq("31")]
    target = int(salaried[3])
    persons_frame.loc[target, "CWS_Earnings_Salaried"] = str(int(persons_frame.loc[target, "CWS_Earnings_Salaried"]) * 10)
    households_frame.loc[5, "Household_Size"] = str(persons + 2)
    folder.mkdir(parents=True, exist_ok=True)
    persons_frame.to_parquet(folder / "prepared_persons.parquet", index=False)
    households_frame.to_parquet(folder / "prepared_households.parquet", index=False)
    (folder / "run_metadata.json").write_text(json.dumps({"run_id": "synthetic-prep", "release": "2024", "observation": "first_visit",
                                                          "design_period": "pre_2025"}), encoding="utf-8")
    injected = {"x10_salary": f"{persons_frame.loc[target, 'MoSPI_record_key']}|person={persons_frame.loc[target, 'Person_Serial_No']}",
                "household_size": f"{households_frame.loc[5, 'MoSPI_record_key']}|household"}
    return folder / "prepared_persons.parquet", injected
