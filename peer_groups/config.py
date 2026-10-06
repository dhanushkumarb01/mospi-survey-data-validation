"""Versioned PLFS V1 peer-group specifications and source mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


PEER_GROUP_SPECIFICATION_VERSION = "plfs-peer-groups-v1.0"


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
        },
        target_columns={
            "cws_earnings_salaried": "b6q9_perv1",
            "cws_earnings_self_employed": "b6q10_perv1",
            "day7_total_hours": "b6q7_3pt1_perv1",
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
        },
        target_columns={
            "cws_earnings_salaried": "CWS_Earnings_Salaried",
            "cws_earnings_self_employed": "CWS_Earnings_SelfEmployed",
            "day7_total_hours": "Day7_Total_Hours",
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
        },
        target_columns={
            "cws_earnings_salaried": "ern_reg",
            "cws_earnings_self_employed": "ern_self",
            "day7_total_hours": "hr7",
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
)
