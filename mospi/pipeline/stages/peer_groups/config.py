"""Versioned PLFS peer-group specifications and source mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


# v1.1: pre-2025 quarter boundary (with backoff to the pooled release) and the
# day-7 casual-wage target.  v1.0 runs remain readable by every engine.
PEER_GROUP_SPECIFICATION_VERSION = "plfs-peer-groups-v1.1"
COMPATIBLE_SPECIFICATION_VERSIONS = frozenset({"plfs-peer-groups-v1.0", PEER_GROUP_SPECIFICATION_VERSION})


@dataclass(frozen=True)
class SourceProfile:
    """Release/observation-specific raw-field mapping for one prepared file."""

    name: str
    release: str
    observation: str
    person_serial_column: str
    context_columns: Mapping[str, str]
    target_columns: Mapping[str, str]


@dataclass(frozen=True)
class GroupingProfile:
    """Ordered, target-specific peer-group levels for one observation route."""

    name: str
    observation: str
    levels: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class PeerGroupSpecification:
    """Definition of one behavioural target's comparison populations."""

    target_variable: str
    description: str
    profiles: tuple[GroupingProfile, ...]
    respect_post_2025_month: bool = True
    # Pre-2025 releases span four quarters.  Each configured level is tried
    # first within the record's own quarter and then pooled over the release
    # (audit M2: pooling all quarters ignored seasonality).
    respect_pre_2025_quarter: bool = True


FIRST_VISIT_PROFILES: tuple[SourceProfile, ...] = (
    SourceProfile(
        name="2023_24_first_visit",
        release="2023_24",
        observation="first_visit",
        person_serial_column="b4q1_perv1",
        context_columns={
            "cws_status": "b6q5_perv1",
            "education": "b4q8_perv1",
            "occupation_major_group": "b5pt1q6_perv1",
            "industry_division": "b5pt1q5_perv1",
            "day7_activity1_status": "b6q4_3pt1_perv1",
            "day7_activity1_industry": "b6q5_3pt1_perv1",
        },
        target_columns={
            "cws_earnings_salaried": "b6q9_perv1",
            "cws_earnings_self_employed": "b6q10_perv1",
            "day7_total_hours": "b6q7_3pt1_perv1",
            "day7_casual_wage": "b6q9_3pt1_perv1",
        },
    ),
    SourceProfile(
        name="2024_first_visit",
        release="2024",
        observation="first_visit",
        person_serial_column="Person_Serial_No",
        context_columns={
            "cws_status": "CWS_Status_Code",
            "education": "General_Education_Level",
            "occupation_major_group": "Principal_Occupation_Code",
            "industry_division": "Principal_Industry_Code",
            "day7_activity1_status": "Day7_Act1_Status_Code",
            "day7_activity1_industry": "Day7_Act1_Industry_Code",
        },
        target_columns={
            "cws_earnings_salaried": "CWS_Earnings_Salaried",
            "cws_earnings_self_employed": "CWS_Earnings_SelfEmployed",
            "day7_total_hours": "Day7_Total_Hours",
            "day7_casual_wage": "Day7_Act1_Wage",
        },
    ),
    SourceProfile(
        name="2025_first_visit",
        release="2025",
        observation="first_visit",
        person_serial_column="srl",
        context_columns={
            "cws_status": "acws",
            "education": "gedu_lvl",
            "occupation_major_group": "ocu_pas",
            "industry_division": "ind_pas",
            "day7_activity1_status": "das17",
            "day7_activity1_industry": "ind17",
        },
        target_columns={
            "cws_earnings_salaried": "ern_reg",
            "cws_earnings_self_employed": "ern_self",
            "day7_total_hours": "hr7",
            "day7_casual_wage": "ern17",
        },
    ),
    SourceProfile(
        name="2023_24_revisit",
        release="2023_24",
        observation="revisit",
        person_serial_column="b4q1_pervv",
        context_columns={"cws_status": "b6q5_perrv"},
        target_columns={
            "cws_earnings_salaried": "b6q9_perrv",
            "cws_earnings_self_employed": "b6q10_perrv",
        },
    ),
)

SOURCE_PROFILES = {(profile.release, profile.observation): profile for profile in FIRST_VISIT_PROFILES}

EARNINGS_LEVELS = (
    ("state", "sector", "cws_status", "occupation_major_group", "education"),
    ("state", "sector", "cws_status", "occupation_major_group"),
    ("state", "sector", "cws_status"),
)

HOURS_LEVELS = (
    ("state", "sector", "cws_status", "industry_division"),
    ("state", "sector", "cws_status"),
)

# Casual wages are compared within the same day-7 activity status (41 public
# works, 42 MGNREG works, 51 other casual work) and, where support permits,
# the same 2-digit NIC division of that day's work.
CASUAL_WAGE_LEVELS = (
    ("state", "sector", "day7_activity1_status", "day7_activity1_industry"),
    ("state", "sector", "day7_activity1_status"),
)

DEFAULT_SPECIFICATIONS: tuple[PeerGroupSpecification, ...] = (
    PeerGroupSpecification(
        target_variable="cws_earnings_salaried",
        description="Current-week salaried earnings retained by PLFS.",
        profiles=(
            GroupingProfile("earnings_first_visit", "first_visit", EARNINGS_LEVELS),
            GroupingProfile("earnings_revisit_context_limited", "revisit", (("state", "sector", "cws_status"),)),
        ),
    ),
    PeerGroupSpecification(
        target_variable="cws_earnings_self_employed",
        description="Current-week self-employed earnings retained by PLFS.",
        profiles=(
            GroupingProfile("earnings_first_visit", "first_visit", EARNINGS_LEVELS),
            GroupingProfile("earnings_revisit_context_limited", "revisit", (("state", "sector", "cws_status"),)),
        ),
    ),
    PeerGroupSpecification(
        target_variable="day7_total_hours",
        description="Day-7 total hours, supplied only in first-visit records.",
        profiles=(GroupingProfile("hours_first_visit", "first_visit", HOURS_LEVELS),),
    ),
    PeerGroupSpecification(
        target_variable="day7_casual_wage",
        description="Day-7 activity-1 wage of casual labour (Block 6 col. 9; statuses 41, 42, 51), first visit only.",
        profiles=(GroupingProfile("casual_wage_first_visit", "first_visit", CASUAL_WAGE_LEVELS),),
    ),
)


def _clean_text(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def derive_context(frame: pd.DataFrame, source: SourceProfile, *, design_period: str | None = None,
                   quarter_column: str = "MoSPI_quarter") -> pd.DataFrame:
    """Comparison dimensions in concept names: the one definition every engine uses.

    Occupation is coarsened to its NCO major group (first digit of a valid
    3-digit code); principal industry to its NIC division (first two digits of
    a valid 4/5-digit code); the day-7 activity industry is recorded as a
    2-digit division.  Invalid codes become blank and so never form a
    comparison cell.  ``quarter`` is added for pre-2025 releases only.
    """
    context = pd.DataFrame(index=frame.index)
    context["state"] = _clean_text(frame["MoSPI_state"])
    context["sector"] = _clean_text(frame["MoSPI_sector"])
    for concept, column in source.context_columns.items():
        if column not in frame:
            continue
        raw = _clean_text(frame[column])
        if concept == "occupation_major_group":
            context[concept] = raw.where(raw.str.fullmatch(r"\d{3}"), "").str.slice(0, 1).astype("string")
        elif concept == "industry_division":
            context[concept] = raw.where(raw.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2).astype("string")
        elif concept == "day7_activity1_industry":
            valid = raw.str.fullmatch(r"\d{1,2}")
            context[concept] = raw.where(valid, "").str.zfill(2).where(valid, "").astype("string")
        else:
            context[concept] = raw
    if design_period == "pre_2025" and quarter_column in frame:
        context["quarter"] = _clean_text(frame[quarter_column])
    return context


def expanded_levels(specification: PeerGroupSpecification, profile: GroupingProfile, design_period: str) -> tuple[tuple[str, ...], ...]:
    """Configured levels; for pre-2025 releases each is tried within its quarter first."""
    if not (specification.respect_pre_2025_quarter and design_period == "pre_2025"):
        return profile.levels
    return tuple(level for dims in profile.levels for level in ((*dims, "quarter"), dims))
