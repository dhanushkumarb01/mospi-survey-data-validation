"""Versioned, conservative working configuration for Pattern V1.

The values here are research operating settings, not PLFS error thresholds or
claims of statistical optimality.  Targets are configured separately from the
generic aggregate calculations so another survey can supply an adapter.
"""
from __future__ import annotations

from dataclasses import dataclass


# v1.1: tested scores, applicability, q-values.
# v2.0: FSU-level Cauchy combination + BH across FSUs (W5.2); dispersion per
#       State x sector (W5.3); age/sex-standardised status mix (W5.4);
#       fieldwork paradata checks (W5.5); near-duplicate persons (W5.6).
PATTERN_METHOD_VERSION = "plfs-pattern-v2.0"
PATTERN_SPECIFICATION_VERSION = "plfs-pattern-spec-v2.0"
READY_STATUS = "ready_for_downstream_preparation_only"

# Items compared for near-duplicate answer sets (concept -> raw column per
# release).  Identifiers, weights and FSU/household keys are never compared.
DUPLICATE_FIELDS: dict[tuple[str, str], dict[str, str]] = {
    ("2023_24", "first_visit"): {
        "relation": "b4q4_perv1", "sex": "b4q5_perv1", "age": "b4q6_perv1", "marital": "b4q7_perv1", "education": "b4q8_perv1",
        "technical_education": "b4q9_perv1", "years_education": "b4q10_perv1", "attendance": "b4q11_perv1", "vocational": "b4q12_perv1",
        "principal_status": "b5pt1q3_perv1", "principal_industry": "b5pt1q5_perv1", "principal_occupation": "b5pt1q6_perv1",
        "subsidiary_work": "b5pt1q7_perv1", "workplace": "b5pt1q8_perv1", "enterprise_type": "b5pt1q9_perv1", "enterprise_workers": "b5pt1q10_perv1",
        "job_contract": "b5pt1q11_perv1", "paid_leave": "b5pt1q12_perv1", "social_security": "b5pt1q13_perv1", "cws_status": "b6q5_perv1",
        "day7_status": "b6q4_3pt1_perv1", "day7_industry": "b6q5_3pt1_perv1", "day7_hours": "b6q7_3pt1_perv1", "day6_hours": "b6q7_3pt2_perv1",
        "day1_hours": "b6q7_3pt7_perv1", "earnings_salaried": "b6q9_perv1", "earnings_self_employed": "b6q10_perv1", "day7_wage": "b6q9_3pt1_perv1",
    },
    ("2024", "first_visit"): {
        "relation": "Relationship_To_Head", "sex": "Sex", "age": "Age", "marital": "Marital_Status", "education": "General_Education_Level",
        "technical_education": "Technical_Education_Level", "years_education": "Years_Formal_Education", "attendance": "Current_Attendance_Status",
        "vocational": "Vocational_Training", "principal_status": "Principal_Status_Code", "principal_industry": "Principal_Industry_Code",
        "principal_occupation": "Principal_Occupation_Code", "subsidiary_work": "Subsidiary_Work_Engagement", "workplace": "Principal_Workplace_Location",
        "enterprise_type": "Principal_Enterprise_Type", "enterprise_workers": "Principal_Workers_Count", "job_contract": "Principal_Job_Contract_Type",
        "paid_leave": "Principal_Paid_Leave", "social_security": "Principal_Social_Security", "cws_status": "CWS_Status_Code",
        "day7_status": "Day7_Act1_Status_Code", "day7_industry": "Day7_Act1_Industry_Code", "day7_hours": "Day7_Total_Hours", "day6_hours": "Day6_Total_Hours",
        "day1_hours": "Day1_Total_Hours", "earnings_salaried": "CWS_Earnings_Salaried", "earnings_self_employed": "CWS_Earnings_SelfEmployed", "day7_wage": "Day7_Act1_Wage",
    },
    ("2025", "first_visit"): {
        "relation": "rel", "sex": "sex", "age": "age", "marital": "marst", "education": "gedu_lvl", "technical_education": "tedu_lvl",
        "years_education": "grade", "attendance": "curr_att", "vocational": "voc", "principal_status": "pas", "principal_industry": "ind_pas",
        "principal_occupation": "ocu_pas", "subsidiary_work": "has_sas", "workplace": "loc_pas", "enterprise_type": "etyp_pas",
        "enterprise_workers": "wrkr_pas", "job_contract": "job_pas", "paid_leave": "leave_pas", "social_security": "ssec_pas", "cws_status": "acws",
        "day7_status": "das17", "day7_industry": "ind17", "day7_hours": "hr7", "day6_hours": "hr6", "day1_hours": "hr1",
        "earnings_salaried": "ern_reg", "earnings_self_employed": "ern_self", "day7_wage": "ern17",
    },
}


@dataclass(frozen=True)
class PatternParameters:
    """V1 research configuration. Scores are evidence ranks, never probabilities."""

    minimum_fsu_population: int = 10
    minimum_reference_population: int = 30
    minimum_valid_target_population: int = 10
    minimum_temporal_history: int = 2
    minimum_temporal_population: int = 10
    minimum_revisit_linked_population: int = 10
    categorical_targets: tuple[str, ...] = (
        "cws_status", "principal_occupation_major_group", "principal_industry_division",
    )
    numerical_targets: tuple[str, ...] = (
        "day7_total_hours", "cws_earnings_salaried", "cws_earnings_self_employed", "age",
    )
    # Only age: 0/5 terminal-digit preference is an established heaping
    # signal for age; rupee amounts are routinely rounded and day-7 hours are
    # not a terminal-digit measure (audit H4/H5).
    heaping_targets: tuple[str, ...] = ("age",)
    temporal_targets: tuple[str, ...] = (
        "day7_total_hours", "cws_earnings_salaried", "cws_earnings_self_employed", "age", "cws_status",
    )
    distribution_metric: str = "g_test_williams_corrected_minus_log10_p"
    numerical_distance_metric: str = "mann_whitney_two_sided_minus_log10_p"
    concentration_metric: str = "one_sided_binomial_share_inside_reference_iqr"
    heaping_metric: str = "one_sided_binomial_share_ending_0_or_5"
    multiplicity: str = ("per-check: Benjamini-Hochberg within component and variable; per-FSU: Cauchy combination of the FSU's checks, "
                         "then Benjamini-Hochberg across FSUs")
    notable_q_value: float = 0.05
    ranking_method: str = "empirical_percentile_of_minus_log10_p_among_assessable_fsus"
    # Overdispersion is estimated per State/UT x sector when it has this many
    # assessed FSUs; otherwise the national value is used (W5.3).
    minimum_local_dispersion_fsus: int = 30
    # Fieldwork paradata (household level).
    minimum_fsu_households: int = 4
    minimum_reference_households: int = 20
    # Near-duplicate answer sets (W5.6).
    duplicate_similarity_threshold: float = 0.95
    duplicate_minimum_common_fields: int = 15
    minimum_reference_pairs: int = 100
    # Age bands (years) and prior strength for the standardised status mix (W5.4).
    status_mix_age_band_width: int = 10
    status_mix_prior_strength: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "minimum_fsu_population", "minimum_reference_population", "minimum_valid_target_population",
            "minimum_temporal_history", "minimum_temporal_population", "minimum_revisit_linked_population",
        ):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2")
