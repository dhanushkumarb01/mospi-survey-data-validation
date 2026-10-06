"""Versioned, release-aware configuration for the ML evidence layer.

The mapping is deliberately small.  It only names fields that are present in
the issued prepared-person contracts and that have a documented analytical
meaning in the preceding layers.  It never uses identifiers or weights as ML
features.
"""
from __future__ import annotations

from dataclasses import dataclass


ML_METHOD_VERSION = "plfs-ml-v1.1"
IF_FEATURE_SPEC_VERSION = "plfs-if-features-v1.1"  # non-applicable items are missing, not 0
LOF_FEATURE_SPEC_VERSION = "plfs-lof-features-v1.1"  # distinct-point fitting
CONDITIONAL_FEATURE_SPEC_VERSION = "plfs-conditional-features-v1.1"  # applicable earners; + State/UT, sector
SIMILARITY_FEATURE_SPEC_VERSION = "plfs-exact-signature-v1.0"
RANDOM_SEED = 20260925
READY_STATUS = "ready_for_downstream_preparation_only"
LOF_REFERENCE_TARGET = "day7_total_hours"
CONDITIONAL_TARGET = "cws_earnings_salaried"


@dataclass(frozen=True)
class SourceFields:
    serial: str
    age: str
    sex: str
    education: str
    cws_status: str
    occupation: str | None
    industry: str | None
    day7_hours: str | None
    earnings_salaried: str
    earnings_self_employed: str


SOURCE_FIELDS: dict[tuple[str, str], SourceFields] = {
    ("2023_24", "first_visit"): SourceFields(
        "b4q1_perv1", "b4q6_perv1", "b4q5_perv1", "b4q8_perv1", "b6q5_perv1",
        "b5pt1q6_perv1", "b5pt1q5_perv1", "b6q7_3pt1_perv1", "b6q9_perv1", "b6q10_perv1",
    ),
    ("2023_24", "revisit"): SourceFields(
        "b4q1_pervv", "b4q6_perrv", "b4q5_perrv", "b4q8_perrv", "b6q5_perrv",
        None, None, None, "b6q9_perrv", "b6q10_perrv",
    ),
    ("2024", "first_visit"): SourceFields(
        "Person_Serial_No", "Age", "Sex", "General_Education_Level", "CWS_Status_Code",
        "Principal_Occupation_Code", "Principal_Industry_Code", "Day7_Total_Hours",
        "CWS_Earnings_Salaried", "CWS_Earnings_SelfEmployed",
    ),
    ("2025", "first_visit"): SourceFields(
        "srl", "age", "sex", "gedu_lvl", "acws", "ocu_pas", "ind_pas", "hr7", "ern_reg", "ern_self",
    ),
}


@dataclass(frozen=True)
class Parameters:
    minimum_model_population: int = 50
    maximum_training_rows: int = 50_000
    isolation_max_training_rows: int = 10_000
    isolation_trees: int = 25
    isolation_max_samples: int = 1_024
    lof_minimum_population: int = 30
    lof_maximum_reference_rows: int = 1_000
    lof_neighbors: int = 20
    conditional_folds: int = 2
    # Upper bound; deterministic early stopping (10% internal validation,
    # 20 rounds without improvement) chooses the actual number of rounds.
    conditional_max_iterations: int = 500
    conditional_learning_rate: float = 0.1
    lof_minimum_distinct_points: int = 21  # must exceed lof_neighbors (20)
    similarity_minimum_present_fields: int = 6
