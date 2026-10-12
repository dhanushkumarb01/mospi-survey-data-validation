"""Versioned, release-aware configuration for the ML evidence layer.

The mapping is deliberately small.  It only names fields that are present in
the issued prepared-person contracts and that have a documented analytical
meaning in the preceding layers.  It never uses identifiers or weights as ML
features.
"""
from __future__ import annotations

from dataclasses import dataclass


# v2.0: conditional expected-value models trained on earlier periods with
# split-conformal tail probabilities (four targets); Isolation Forest and LOF
# are research-only outputs, excluded from the supervisor queue (plan §14).
# v2.1: State-conditional (Mondrian) conformal calibration of the expected-value
# models.  Measured reason: with one national calibration set the 2024/2025
# model tail probabilities were calibrated overall (1.06x nominal at 0.01) but
# 2-3x nominal in Delhi, DNH & Daman and Diu, Lakshadweep, A&N Islands and
# 0.8-0.9x in Uttar Pradesh, which concentrated "Check now" in small UTs.
ML_METHOD_VERSION = "plfs-ml-v2.1"
IF_FEATURE_SPEC_VERSION = "plfs-if-features-v1.1"  # non-applicable items are missing, not 0
LOF_FEATURE_SPEC_VERSION = "plfs-lof-features-v1.1"  # distinct-point fitting
CONDITIONAL_FEATURE_SPEC_VERSION = "plfs-conditional-features-v2.0"  # per-target features; target never a predictor
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
    day7_activity1_status: str | None = None
    day7_activity1_industry: str | None = None
    casual_wage: str | None = None


SOURCE_FIELDS: dict[tuple[str, str], SourceFields] = {
    ("2023_24", "first_visit"): SourceFields(
        "b4q1_perv1", "b4q6_perv1", "b4q5_perv1", "b4q8_perv1", "b6q5_perv1",
        "b5pt1q6_perv1", "b5pt1q5_perv1", "b6q7_3pt1_perv1", "b6q9_perv1", "b6q10_perv1",
        "b6q4_3pt1_perv1", "b6q5_3pt1_perv1", "b6q9_3pt1_perv1",
    ),
    ("2023_24", "revisit"): SourceFields(
        "b4q1_pervv", "b4q6_perrv", "b4q5_perrv", "b4q8_perrv", "b6q5_perrv",
        None, None, None, "b6q9_perrv", "b6q10_perrv",
    ),
    ("2024", "first_visit"): SourceFields(
        "Person_Serial_No", "Age", "Sex", "General_Education_Level", "CWS_Status_Code",
        "Principal_Occupation_Code", "Principal_Industry_Code", "Day7_Total_Hours",
        "CWS_Earnings_Salaried", "CWS_Earnings_SelfEmployed",
        "Day7_Act1_Status_Code", "Day7_Act1_Industry_Code", "Day7_Act1_Wage",
    ),
    ("2025", "first_visit"): SourceFields(
        "srl", "age", "sex", "gedu_lvl", "acws", "ocu_pas", "ind_pas", "hr7", "ern_reg", "ern_self", "das17", "ind17", "ern17",
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
    # Conformal tail probabilities are calibrated within the record's State when
    # the State has at least this many calibration residuals (floor 1/(n+1) < 0.01);
    # otherwise against the national calibration set.  0 = national only (v2.0).
    conformal_group_minimum: int = 100
    lof_minimum_distinct_points: int = 21  # must exceed lof_neighbors (20)
    similarity_minimum_present_fields: int = 6
    # Isolation Forest and LOF did not earn a place in the supervisor queue
    # (alone 1.5%/4.0% and 23.3%/26.3% top-1% recall; LOF redundant with the
    # statistical layer).  They are still computed for research comparison
    # unless switched off; fusion never reads them.
    run_research_models: bool = True
