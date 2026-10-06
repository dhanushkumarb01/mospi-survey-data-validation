"""Release-1-only linked first-visit/revisit change evidence."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from peer_groups.config import SOURCE_PROFILES
from survey_rules import APPLICABLE, applicability_series

from .config import APPROVED_TARGETS, REVISIT_LINK_COLUMNS, StatisticalParameters
from .statistics import add_distribution_evidence, finite_numeric


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _source_id(frame: pd.DataFrame, serial_column: str) -> pd.Series:
    serial = _clean(frame[serial_column])
    return _clean(frame["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), _clean(frame["MoSPI_source_row"])), sep="|person=")


def _link_id(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    joined = _clean(frame[columns[0]])
    for column in columns[1:]:
        joined = joined.str.cat(_clean(frame[column]), sep="|")
    return joined.map(lambda value: "rv_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24])


def _prepared_values(path, observation: str) -> pd.DataFrame:
    source = SOURCE_PROFILES[("2023_24", observation)]
    link_columns = list(REVISIT_LINK_COLUMNS[observation])
    required = {"MoSPI_record_key", "MoSPI_source_row", *link_columns, source.person_serial_column, source.context_columns["cws_status"], *source.target_columns.values()}
    frame = pd.read_parquet(path, columns=sorted(required))
    result = pd.DataFrame({"source_observation_id": _source_id(frame, source.person_serial_column)})
    result["linkage_identifier"] = _link_id(frame, link_columns)
    if result["source_observation_id"].duplicated().any():
        raise ValueError("Prepared revisit linkage source IDs are not unique")
    status = frame[source.context_columns["cws_status"]]
    for target in APPROVED_TARGETS:
        column = source.target_columns.get(target)
        result[target] = finite_numeric(frame[column]) if column else np.nan
        result[f"{target}__applicable"] = applicability_series(target, status).eq(APPLICABLE).to_numpy()
    return result


def build_revisit_evidence(
    *,
    first_prepared_path,
    revisit_prepared_path,
    revisit_assignment_path,
    parameters: StatisticalParameters,
) -> pd.DataFrame:
    """Return one traceable row per revisit assignment, including non-links.

    Only the documented 2023-24 identity is used.  Matched changes are compared
    within target, revisit round, and the already assigned revisit peer group.
    """
    columns = [
        "source_observation_id", "target_variable", "visit", "peer_group_id", "peer_group_size",
        "backoff_level", "assessability_status", "not_assessable_reason", "release", "observation",
        "design_period", "month", "reference_run_id", "specification_version",
    ]
    assignments = pd.read_parquet(revisit_assignment_path, columns=columns)
    assignments = assignments.rename(columns={"assessability_status": "revisit_peer_assessability_status", "not_assessable_reason": "revisit_peer_not_assessable_reason"})
    revisits = _prepared_values(revisit_prepared_path, "revisit")
    firsts = _prepared_values(first_prepared_path, "first_visit").rename(columns={"source_observation_id": "first_source_observation_id"})
    firsts = firsts.rename(columns={**{target: f"first_visit_{target}" for target in APPROVED_TARGETS},
                                    **{f"{target}__applicable": f"first_visit_{target}__applicable" for target in APPROVED_TARGETS}})
    revisits = revisits.rename(columns={**{target: f"revisit_{target}" for target in APPROVED_TARGETS},
                                        **{f"{target}__applicable": f"revisit_{target}__applicable" for target in APPROVED_TARGETS}})
    # Assignments contain one row per target for each physical revisit record;
    # the prepared source value is therefore a many-to-one lookup.
    output = assignments.merge(revisits, on="source_observation_id", how="left", validate="many_to_one")
    output["revisit_comparison_status"] = "NOT_ASSESSABLE"
    output["revisit_assessability_reason"] = "NO_VALID_LINKED_FIRST_VISIT"
    output["first_source_observation_id"] = pd.NA
    output["first_visit_value"] = np.nan
    output["revisit_value"] = np.nan
    output["applicable_both_visits"] = False
    for target in APPROVED_TARGETS:
        target_mask = output["target_variable"].eq(target)
        if not target_mask.any():
            continue
        if target not in SOURCE_PROFILES[("2023_24", "revisit")].target_columns:
            output.loc[target_mask, "revisit_assessability_reason"] = "REVISIT_TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"
            continue
        target_rows = output.loc[target_mask, ["source_observation_id", "linkage_identifier"]].merge(
            firsts[["first_source_observation_id", "linkage_identifier", f"first_visit_{target}", f"first_visit_{target}__applicable"]],
            on="linkage_identifier", how="left", validate="many_to_one",
        ).set_index(output.index[target_mask])
        output.loc[target_mask, "first_source_observation_id"] = target_rows["first_source_observation_id"]
        output.loc[target_mask, "first_visit_value"] = target_rows[f"first_visit_{target}"]
        output.loc[target_mask, "revisit_value"] = output.loc[target_mask, f"revisit_{target}"]
        # A change is only an earnings change when the item applies at both
        # visits; otherwise one value is a questionnaire placeholder 0.
        output.loc[target_mask, "applicable_both_visits"] = (
            target_rows[f"first_visit_{target}__applicable"].fillna(False).astype(bool).to_numpy()
            & output.loc[target_mask, f"revisit_{target}__applicable"].fillna(False).astype(bool).to_numpy())
    linked = output["first_source_observation_id"].notna()
    peer_ready = output["revisit_peer_assessability_status"].eq("ASSESSABLE") & output["peer_group_id"].notna()
    finite_values = np.isfinite(output["first_visit_value"]) & np.isfinite(output["revisit_value"])
    both = output["applicable_both_visits"].astype(bool)
    eligible = linked & peer_ready & finite_values & both
    output.loc[linked & ~peer_ready, "revisit_assessability_reason"] = "REVISIT_PEER_NOT_ASSESSABLE"
    output.loc[linked & peer_ready & ~finite_values, "revisit_assessability_reason"] = "LINKED_TARGET_VALUE_MISSING_OR_INVALID"
    output.loc[linked & peer_ready & finite_values & ~both, "revisit_assessability_reason"] = "TARGET_NOT_APPLICABLE_AT_ONE_OR_BOTH_VISITS"
    output.loc[eligible, "revisit_assessability_reason"] = pd.NA
    output.loc[eligible, "revisit_comparison_status"] = "PENDING_CHANGE_REFERENCE"
    output["revisit_signed_change"] = output["revisit_value"] - output["first_visit_value"]
    output["revisit_absolute_change"] = output["revisit_signed_change"].abs()
    nonzero_baseline = output["first_visit_value"].ne(0) & output["first_visit_value"].notna()
    output["revisit_relative_change"] = np.where(nonzero_baseline, output["revisit_signed_change"] / output["first_visit_value"].abs(), np.nan)
    output["revisit_relative_change_status"] = np.where(nonzero_baseline, "COMPUTED", "UNDEFINED_ZERO_OR_MISSING_BASELINE")
    output["revisit_change_direction"] = np.select(
        [output["revisit_signed_change"].lt(0), output["revisit_signed_change"].gt(0)], ["DECREASE", "INCREASE"], default="NO_CHANGE_OR_UNAVAILABLE"
    )
    output["revisit_change_reference_group_id"] = pd.NA
    output.loc[eligible, "revisit_change_reference_group_id"] = (
        output.loc[eligible, "target_variable"].astype("string") + "|" + output.loc[eligible, "visit"].astype("string") + "|" + output.loc[eligible, "peer_group_id"].astype("string")
    )
    candidates = output.loc[eligible].copy()
    if not candidates.empty:
        sizes = candidates.groupby("revisit_change_reference_group_id", sort=False).size()
        sufficient = candidates["revisit_change_reference_group_id"].map(sizes).ge(parameters.minimum_revisit_change_group_size)
        insufficient_indexes = candidates.index[~sufficient]
        output.loc[insufficient_indexes, "revisit_assessability_reason"] = "REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM"
        output.loc[insufficient_indexes, "revisit_comparison_status"] = "NOT_ASSESSABLE"
        sufficient_rows = candidates.loc[sufficient].copy()
        if not sufficient_rows.empty:
            evidence = add_distribution_evidence(
                sufficient_rows, value_column="revisit_signed_change", group_column="revisit_change_reference_group_id",
                lower_quantile=parameters.lower_tail_quantile, upper_quantile=parameters.upper_tail_quantile, prefix="revisit_change_",
            )
            extra = [column for column in evidence.columns if column.startswith("revisit_change_") and column not in {"revisit_change_reference_group_id", "revisit_change_direction"}]
            for column in extra:
                output.loc[evidence.index, column] = evidence[column]
            output.loc[evidence.index, "revisit_comparison_status"] = "ASSESSABLE"
            output.loc[evidence.index, "revisit_assessability_reason"] = pd.NA
    output.replace([np.inf, -np.inf], np.nan, inplace=True)
    return output.sort_values(["target_variable", "source_observation_id"], kind="mergesort", ignore_index=True)
