"""A synthetic RAW delivery (household + person CSV) in the documented Calendar-2024 contract layout (tests only).

It is the prepared fixture of tests/synthetic.py written back as raw files with the contract's own header names,
so the upload path runs the real preparation stage and then the real pipeline.  Nothing resembles real respondents.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tests.synthetic import write_delivery

KEY_PARTS = ("Quarter", "Sector", "STATE", "District_Code", "FSU", "Sample_Sg_Sb_No", "Second_Stage_Stratum_No", "Sample_Household_Number")


def _raw(frame: pd.DataFrame, state_column: str, rng: np.random.Generator) -> pd.DataFrame:
    parts = frame["MoSPI_record_key"].str.split("|", expand=True)
    parts.columns = list(KEY_PARTS)
    raw = frame[[c for c in frame.columns if not c.startswith("MoSPI_") and c not in KEY_PARTS]].copy()
    for column in KEY_PARTS:
        raw[state_column if column == "STATE" else column] = parts[column].values
    raw["Panel"] = "P4"
    raw["Visit"] = frame["MoSPI_visit"].values
    raw["Stratum"] = frame["MoSPI_stratum"].values
    if "Subsample_Multiplier" not in raw:
        raw["Subsample_Multiplier"] = [str(int(v)) for v in rng.integers(2000, 6000, len(raw))]
    return raw


def write_raw_delivery(folder: Path, *, seed: int = 11, **sizes: int) -> dict[str, Path]:
    """Write ``chhv1.csv`` and ``cperv1.csv``; return their paths (person rows carry an injected x10 salary)."""
    rng = np.random.default_rng(seed)
    prepared, _ = write_delivery(folder / "_prepared", seed=seed, **sizes)
    persons = _raw(pd.read_parquet(prepared), "State_UT_Code", rng)
    households = _raw(pd.read_parquet(prepared.with_name("prepared_households.parquet")), "State_Ut_Code", rng)
    households["Reason_for_Substitution"] = ""
    for column in ("Principal_Industry_Code", "Training_Completed_365_Days", "Day7_Act2_Status_Code"):
        persons[column] = persons.get(column, "")
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"household": folder / "chhv1.csv", "person": folder / "cperv1.csv"}
    households.to_csv(paths["household"], index=False)
    persons.to_csv(paths["person"], index=False)
    for leftover in (folder / "_prepared").glob("*"):
        leftover.unlink()
    (folder / "_prepared").rmdir()
    return paths
