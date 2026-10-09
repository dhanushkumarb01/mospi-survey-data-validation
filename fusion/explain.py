"""Supervisor-facing case explanations built only from stored MoSPI outputs.

This module is read-only. It locates the immutable source runs named in a
Fusion case's provenance, reads the stored evidence rows for that record
(observed values, comparison groups, quantiles, model estimates, earlier-period
comparisons, rule checks, FSU pattern details) and arranges them as a
plain-language review story:

    what was observed -> what it was compared with -> what the numbers show
    -> what that may indicate -> what to check.

It never recomputes a score, never infers a cause, and never turns
"unusual" into "incorrect". Wording thresholds below are display
conventions for choosing words such as "very unusual"; they are not
statistical tests and do not change any rank or priority.  FSU wording uses
the stored Benjamini-Hochberg q-values.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from peer_groups.config import CASUAL_WAGE_LEVELS, EARNINGS_LEVELS, HOURS_LEVELS, SOURCE_PROFILES
from survey_rules.schema import column_map
from preprocessing.config import CONTRACTS

from . import labels as L


# Display conventions only (see module docstring).
VERY_UNUSUAL, UNUSUAL, SOMEWHAT_UNUSUAL = 0.99, 0.95, 0.80
NOTABLE_Q = 0.05
GROUP_LEVELS = {"earnings_first_visit": EARNINGS_LEVELS, "hours_first_visit": HOURS_LEVELS, "casual_wage_first_visit": CASUAL_WAGE_LEVELS}

# Block 4 columns 4/5/7 (relation, sex, marital status) are not part of the
# preparation contract mapping, so they are named here per documented layout.
EXTRA_PERSON_FIELDS = {
    ("2023_24", "first_visit"): {"relation": "b4q4_perv1", "sex": "b4q5_perv1", "marital": "b4q7_perv1"},
    ("2024", "first_visit"): {"relation": "Relationship_To_Head", "sex": "Sex", "marital": "Marital_Status"},
    ("2025", "first_visit"): {"relation": "rel", "sex": "sex", "marital": "marst"},
}

IF_FEATURES = {
    "age_band_5_year": "age", "day7_hours": "hours worked", "earnings_salaried": "salaried earnings",
    "earnings_self_employed": "self-employment earnings", "sex": "sex", "education": "education",
    "cws_status": "activity status", "occupation_major_group": "occupation", "industry_division": "industry",
}

UNAVAILABLE_TEXT = {
    "statistical": "Not enough comparable information to compare this person's earnings or hours with similar records.",
    "contextual": "Not enough comparable information to assess how common the occupation is.",
    "ml": "The pattern-of-answers checks could not be applied to this record.",
    "historical": "Not enough comparable information from earlier periods to assess this aspect.",
    "pattern": "No FSU-level pattern information was available for this record's FSU.",
}

SOURCE_TITLES = {
    "statistical": "Comparison with similar records",
    "contextual": "How common the reported occupation is",
    "ml": "Pattern of answers",
    "historical": "Comparison with earlier periods",
    "pattern": "FSU-level pattern",
}

REFERENCE_PERIOD = {
    "cws_earnings_salaried": "for the preceding calendar month",
    "cws_earnings_self_employed": "for the last 30 days",
    "day7_total_hours": "on day 7 of the reference week",
    "day7_casual_wage": "for the casual work on day 7 of the reference week",
}


# ---------------------------------------------------------------------------
# small helpers


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def share_text(rank: float | None) -> str:
    """Floor a 0–1 rank to one decimal percent so the text never overstates."""
    if rank is None:
        return "—"
    value = math.floor(max(0.0, min(1.0, rank)) * 1000) / 10
    return f"{value:g}%"


def strength(rank: float | None) -> dict[str, Any]:
    if rank is None:
        return {"level": "none", "label": "Not checked"}
    if rank >= VERY_UNUSUAL:
        level, label = "very", "Very unusual"
    elif rank >= UNUSUAL:
        level, label = "high", "Unusual"
    elif rank >= SOMEWHAT_UNUSUAL:
        level, label = "some", "Somewhat unusual"
    else:
        level, label = "low", "Not notably unusual"
    return {"level": level, "label": label, "rank": rank, "share": share_text(rank)}


def group_strength(q_value: float | None, rank: float | None = None) -> dict[str, Any]:
    """FSU wording from the multiple-testing adjusted q-value, not from a rank."""
    if q_value is None:
        return {"level": "none", "label": "Not checked", "notable": False, "rank": rank}
    if q_value < 0.001:
        level, label = "very", "Clear difference"
    elif q_value < 0.01:
        level, label = "high", "Notable difference"
    elif q_value < NOTABLE_Q:
        level, label = "some", "Some difference"
    else:
        level, label = "low", "Not notably different"
    return {"level": level, "label": label, "notable": q_value < NOTABLE_Q, "q_value": q_value, "rank": rank}


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _plain_statement(text: Any) -> str:
    statement = L.clean(text)
    for key in sorted(L.VARIABLES, key=len, reverse=True):
        statement = statement.replace(key, L.VARIABLES[key]["short"])
    return statement


def _status_label(code: Any) -> str:
    text = L.clean(code)
    label = L.code_label(L.ACTIVITY_STATUS, text)
    return f"“{label}” (code {text})" if label else (f"code {text}" if text else "not recorded")


def _dimension_value(dimension: str, value: Any) -> str:
    text = L.clean(value)
    if dimension == "state":
        return L.state_name(text)
    if dimension == "sector":
        return L.sector_name(text)
    if dimension == "cws_status":
        return _status_label(text)
    if dimension == "education":
        label = L.code_label(L.EDUCATION, text, width=2)
        return label or f"code {text}"
    if dimension == "occupation_major_group":
        return f"group {text} (first digit of the occupation code)"
    if dimension == "industry_division":
        return f"industry division {text}"
    if dimension == "day7_activity1_status":
        return _status_label(text)
    if dimension == "day7_activity1_industry":
        return f"industry division {text} (work on day 7)"
    if dimension == "quarter":
        return f"the same survey quarter ({text})"
    return text


def natural_group(grouping_values: Any) -> str:
    """'people in urban Delhi with the same activity status “…” and industry division 84'."""
    values = _json(grouping_values, {})
    state = L.state_name(values["state"]) if L.clean(values.get("state")) else ""
    sector = L.sector_name(values["sector"]).lower() if L.clean(values.get("sector")) else ""
    where = " ".join(part for part in (sector, state) if part) or "the same area"
    extras = []
    if L.clean(values.get("cws_status")):
        label = L.code_label(L.ACTIVITY_STATUS, values["cws_status"])
        extras.append(f"activity status “{label}”" if label else f"activity status code {values['cws_status']}")
    if L.clean(values.get("occupation_major_group")):
        extras.append(f"occupation group {values['occupation_major_group']}")
    if L.clean(values.get("education")):
        label = L.code_label(L.EDUCATION, values["education"], width=2)
        extras.append(f"education level “{label}”" if label else f"education code {values['education']}")
    if L.clean(values.get("industry_division")):
        extras.append(f"industry division {values['industry_division']}")
    if L.clean(values.get("day7_activity1_status")):
        label = L.code_label(L.ACTIVITY_STATUS, values["day7_activity1_status"])
        extras.append(f"day-7 work “{label}”" if label else f"day-7 activity code {values['day7_activity1_status']}")
    if L.clean(values.get("day7_activity1_industry")):
        extras.append(f"day-7 industry division {values['day7_activity1_industry']}")
    sentence = f"people in {where}" + (f" with the same {_join(extras)}" if extras else "")
    if L.clean(values.get("quarter")):
        sentence += f", interviewed in the same quarter"
    return sentence


def describe_group(grouping_values: Any, grouping_dimensions: Any = None) -> list[dict[str, str]]:
    values = _json(grouping_values, {})
    order = _json(grouping_dimensions, list(values))
    return [{"label": L.DIMENSIONS.get(d, d), "value": _dimension_value(d, values.get(d))} for d in order if d in values]


def _tail_words(position: Any) -> str:
    return {"UPPER_TAIL": "above the range covering 9 in 10 comparable records",
            "LOWER_TAIL": "below the range covering 9 in 10 comparable records"}.get(position, "within the range covering 9 in 10 comparable records")


# ---------------------------------------------------------------------------
# source resolution


class SourceResolver:
    """Find the immutable source-run directories named in Fusion provenance."""

    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root)

    @lru_cache(maxsize=64)
    def run_dir(self, module: str, release: str, observation: str, run_id: str | None) -> Path | None:
        if not run_id:
            return None
        runs = self.root / module / "runs"
        expected = runs / f"{release}_{observation}_{run_id}"
        candidates = [expected] + sorted(runs.glob(f"*{run_id}")) if runs.is_dir() else []
        for candidate in candidates:
            metadata = candidate / "run_metadata.json"
            if not metadata.is_file():
                continue
            try:
                meta = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(meta.get("run_id")) == str(run_id) and str(meta.get("release")) == release and \
                    str(meta.get("observation", meta.get("observation_type"))) == observation:
                return candidate
        return None

    def directories(self, release: str, observation: str, provenance: dict[str, Any]) -> dict[str, Path | None]:
        return {module: self.run_dir(module, release, observation, provenance.get(f"{module}_run_id"))
                for module in ("preprocessing", "statistical", "contextual", "ml", "pattern", "historical", "integrity")}


def _query(path: Path | None, sql: str, values: list[Any]) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    with duckdb.connect() as connection:
        frame = connection.execute(sql, [str(path), *values]).fetchdf()
    return json.loads(frame.to_json(orient="records"))


def _file(directory: Path | None, name: str) -> Path | None:
    return directory / name if directory is not None and (directory / name).is_file() else None


# ---------------------------------------------------------------------------
# person / record context


def person_context(case: dict[str, Any], prep_dir: Path | None) -> dict[str, Any]:
    release, observation = str(case["release"]), str(case["observation_type"])
    record_key, _, person = str(case["source_observation_id"]).partition("|person=")
    key_parts = record_key.split("|")
    contract = next((c for c in CONTRACTS.values() if c.release == release and c.observation == observation), None)
    key_fields = dict(zip(contract.household_key, key_parts)) if contract and len(key_parts) == len(contract.household_key) else {}
    context: dict[str, Any] = {
        "record_key": record_key, "person": person, "household": key_fields.get("household"),
        "district": key_fields.get("district"), "quarter": key_fields.get("quarter"), "facts": [],
    }
    path = _file(prep_dir, "prepared_persons.parquet")
    if contract is None or path is None:
        return context
    profile = SOURCE_PROFILES.get((release, observation))
    fields = {
        "age": contract.person_fields.get("age"), "district": contract.person_fields.get("district"),
        **(EXTRA_PERSON_FIELDS.get((release, observation), {})),
        **({k: v for k, v in profile.context_columns.items()} if profile else {}),
    }
    serial = contract.person_fields[contract.person_serial]
    physical = column_map(path)     # stored runs may hold the legacy iospi_* names (plan W0.1)
    wanted = {name: column for name, column in fields.items() if column and column in physical}
    if serial not in physical or "MoSPI_record_key" not in physical or not wanted:
        return context
    select = ", ".join(f'"{physical[column]}" AS "{name}"' for name, column in wanted.items())
    rows = _query(path, f'SELECT {select} FROM read_parquet(?) WHERE "{physical["MoSPI_record_key"]}" = ? AND CAST("{physical[serial]}" AS VARCHAR) = ?', [record_key, person])
    if not rows:
        return context
    row = {k: L.clean(v) for k, v in rows[0].items()}
    context["district"] = row.get("district") or context["district"]
    facts = context["facts"]
    if row.get("age"):
        facts.append({"label": "Age", "value": f"{row['age']} years"})
    if row.get("sex"):
        facts.append({"label": "Sex", "value": L.code_label(L.SEX, row["sex"]) or f"code {row['sex']}"})
    if row.get("relation"):
        facts.append({"label": "Relation to head", "value": L.code_label(L.RELATION_TO_HEAD, row["relation"]) or f"code {row['relation']}"})
    if row.get("marital"):
        facts.append({"label": "Marital status", "value": L.code_label(L.MARITAL_STATUS, row["marital"]) or f"code {row['marital']}"})
    if row.get("education"):
        facts.append({"label": "General education", "value": L.code_label(L.EDUCATION, row["education"], width=2) or f"code {row['education']}"})
    if row.get("cws_status"):
        facts.append({"label": "Current weekly activity status", "value": _status_label(row["cws_status"])})
    if row.get("occupation_major_group"):
        facts.append({"label": "Occupation code (principal activity)", "value": row["occupation_major_group"]})
    if row.get("industry_division"):
        facts.append({"label": "Industry code (principal activity)", "value": row["industry_division"]})
    context["cws_status"] = row.get("cws_status")
    return context


# ---------------------------------------------------------------------------
# evidence readers


def _stat_section(case: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    assessable = [r for r in rows if (r.get("statistical_assessability_status") or r.get("assessability_status")) == "ASSESSABLE"
                  and _num(r.get("percentile_position")) is not None]
    if not assessable:
        return None, []
    lead_target = L.clean(case.get("target_variable"))
    lead = next((r for r in assessable if r["target_variable"] == lead_target), None) or \
        max(assessable, key=lambda r: abs(_num(r["percentile_position"]) - .5))
    facts = [_stat_fact(r) for r in assessable]
    rank = _num(case.get("statistical_rank"))
    unit = L.variable_unit(lead["target_variable"])
    p = _num(lead["percentile_position"]) or .5
    position = lead.get("distribution_position")
    group = describe_group(lead.get("grouping_values"), lead.get("grouping_dimensions"))
    size = int(_num(lead.get("peer_group_size")) or 0)
    meaning = f"The reported value is {_tail_words(position)}."
    backoff = int(_num(lead.get("backoff_level")) or 0)
    narrower = ""
    levels = GROUP_LEVELS.get(L.clean(lead.get("grouping_profile")))
    if backoff > 0 and levels:
        dropped = [L.DIMENSIONS.get(d, d).lower() for d in levels[0] if d not in _json(lead.get("grouping_dimensions"), [])]
        narrower = (f"A narrower comparison that also matched {' and '.join(dropped)} did not have at least "
                    f"{int(_num(lead.get('minimum_group_size')) or 0)} records, so this broader group was used.")
    period = REFERENCE_PERIOD.get(lead["target_variable"], "")
    section = {
        "id": "statistical", "source": "statistical", "level": "record", "title": SOURCE_TITLES["statistical"],
        "strength": strength(rank),
        "observed": f"{L.variable_label(lead['target_variable'])} {period}: {L.format_value(lead.get('observed_value'), unit)}".replace("  ", " "),
        "comparison": f"Compared with {L.count(size)} records of {natural_group(lead.get('grouping_values'))}.",
        "comparison_group": group, "comparison_note": narrower,
        "facts": [
            {"label": "Typical value (middle of comparable records)", "value": L.format_value(lead.get("peer_median"), unit)},
            {"label": "Middle half of comparable records", "value": f"{L.format_value(lead.get('quantile_0_25'), unit)} to {L.format_value(lead.get('quantile_0_75'), unit)}"},
            {"label": "9 in 10 comparable records fall between", "value": f"{L.format_value(lead.get('quantile_0_05'), unit)} and {L.format_value(lead.get('quantile_0_95'), unit)}"},
            {"label": "Position among comparable records", "value": _position_text(p, size)},
        ],
        "meaning": meaning,
        "matters": ("A value outside the usual range is worth confirming before the record is used. "
                    "Unusual does not mean incorrect: some people genuinely differ from their comparison group."),
        "other_values": [f for f in facts if f["target"] != lead["target_variable"]],
        "technical": {k: lead.get(k) for k in ("target_variable", "target_applicability", "peer_group_id", "peer_group_size", "grouping_profile", "backoff_level",
                                                 "percentile_position", "distribution_position", "robust_deviation", "robust_deviation_status", "mad",
                                                 "percentile_convention", "statistical_method_version")},
        "lead": lead,
    }
    return section, facts


def _position_text(p: float, size: int) -> str:
    if p >= 1.0:
        return f"Higher than all {L.count(size)} comparable records"
    if p <= 0.0:
        return f"Lower than all {L.count(size)} comparable records"
    if p >= .5:
        return f"Higher than about {share_text(p)} of {L.count(size)} comparable records"
    return f"Lower than about {share_text(1 - p)} of {L.count(size)} comparable records"


def _stat_fact(row: dict[str, Any]) -> dict[str, Any]:
    unit = L.variable_unit(row["target_variable"])
    position = row.get("distribution_position")
    return {
        "target": row["target_variable"], "label": L.variable_label(row["target_variable"]),
        "observed": L.format_value(row.get("observed_value"), unit), "typical": L.format_value(row.get("peer_median"), unit),
        "range": f"{L.format_value(row.get('quantile_0_25'), unit)} to {L.format_value(row.get('quantile_0_75'), unit)}",
        "position": {"UPPER_TAIL": "Above the usual range", "LOWER_TAIL": "Below the usual range"}.get(position, "Within the usual range"),
        "tail": position in {"UPPER_TAIL", "LOWER_TAIL"}, "comparable": int(_num(row.get("peer_group_size")) or 0),
    }


def _context_section(case: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    row = rows[0] if rows else None
    rank = _num(case.get("contextual_rank"))
    if row is None:
        return None, UNAVAILABLE_TEXT["contextual"]
    observed = L.clean(row.get("observed_value"))
    if case.get("contextual_status") != "ASSESSABLE" or rank is None:
        if not observed:
            return None, "No occupation code is recorded for this person, so the occupation check did not apply."
        return None, UNAVAILABLE_TEXT["contextual"]
    reference = int(_num(row.get("reference_count")) or 0)
    count = int(_num(row.get("category_count")) or 0)
    parent_count = _num(row.get("category_parent_count"))
    group = describe_group(_json(row.get("context_values"), {}).get("values", {}), _json(row.get("context_values"), {}).get("dimensions"))
    facts = [{"label": "Comparable records with exactly this occupation code", "value": f"{L.count(count)} of {L.count(reference)} ({_pct(count, reference)})"}]
    if parent_count is not None and L.clean(row.get("category_parent_value")):
        facts.append({"label": f"Comparable records in the same broad occupation group (first digit {row['category_parent_value']})",
                      "value": f"{L.count(int(parent_count))} of {L.count(reference)} ({_pct(parent_count, reference)})"})
    rare = rank >= SOMEWHAT_UNUSUAL
    return {
        "id": "contextual", "source": "contextual", "level": "record", "title": SOURCE_TITLES["contextual"], "strength": strength(rank),
        "observed": f"Reported occupation code: {observed}",
        "comparison": f"Compared with {L.count(reference)} records of {natural_group(_json(row.get('context_values'), {}).get('values', {}))} that have a valid occupation code.",
        "comparison_group": group, "facts": facts,
        "meaning": (f"This occupation code is uncommon among comparable records ({L.count(count)} of {L.count(reference)})." if rare
                    else "This occupation code is reasonably common among comparable records."),
        "matters": "An uncommon occupation for the person's activity status and industry can reflect a coding slip or simply an uncommon job. It is worth confirming against the work described in the schedule.",
        "technical": {k: row.get(k) for k in ("surprisal", "conditional_frequency", "category_level", "context_definition", "method_identifier", "method_version", "smoothing_method")},
        "code": observed, "rare": rare,
    }, ""


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


def _ratio_text(ratio: float) -> str:
    if ratio >= 1:
        return f"about {ratio:.1f} times the model estimate" if ratio >= 1.5 else f"about {round((ratio - 1) * 100)}% above the model estimate"
    return f"about {round((1 - ratio) * 100)}% below the model estimate"


def _ml_sections(case: dict[str, Any], ml_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    sections = []
    conditional = next((r for r in ml_rows.get("conditional", []) if r.get("assessability_status") == "ASSESSABLE"), None)
    if conditional and _num(conditional.get("predicted_value")) is not None and _num(conditional.get("observed_value")):
        target = L.clean(conditional.get("target")) or "cws_earnings_salaried"
        unit = L.variable_unit(target)
        rank = _num(conditional.get("evidence_rank"))
        observed, estimate = _num(conditional.get("observed_value")), _num(conditional.get("predicted_value"))
        ratio = _num(conditional.get("observed_to_estimate_ratio")) or (observed / estimate if estimate else None)
        sections.append({
            "id": "ml_conditional", "source": "ml", "level": "record", "title": "Model estimate for people with these characteristics",
            "strength": strength(rank),
            "observed": f"{L.variable_label(target)} {REFERENCE_PERIOD.get(target, '')}: {L.format_value(observed, unit)}",
            "comparison": (f"A statistical model estimates about {L.format_value(estimate, unit)} for a salaried worker with the same age, sex, education, activity status, "
                           "occupation group, industry division, hours, State/UT and sector. The model learns from salaried workers in other FSUs of this survey round, never from this record."),
            "facts": [{"label": "Reported value compared with the model estimate", "value": _ratio_text(ratio) if ratio else "—"},
                      {"label": "Size of the gap compared with other salaried workers", "value": f"Larger than about {share_text(rank)} of them"}],
            "meaning": ("The reported amount is far from the model estimate for people with these characteristics." if (rank or 0) >= UNUSUAL
                        else "The reported amount is broadly in line with the model estimate for people with these characteristics."),
            "matters": "A large gap suggests checking whether the amount and the person's other details fit together. The model estimate is a statistical guide, not a correct value, and it is not the typical value of any actual group.",
            "technical": {k: conditional.get(k) for k in ("method", "method_version", "feature_spec_version", "predicted_value", "log_residual", "observed_to_estimate_ratio",
                                                          "raw_model_score", "evidence_rank", "training_fold", "model_iterations", "source_reference_metadata")},
            "target": target, "expected": L.format_value(estimate, unit), "ratio": ratio,
        })
    forest = next((r for r in ml_rows.get("isolation_forest", []) if r.get("assessability_status") == "ASSESSABLE"), None)
    lof = next((r for r in ml_rows.get("lof", []) if r.get("assessability_status") == "ASSESSABLE"), None)
    if forest or lof:
        facts, ranks, features = [], [], []
        if forest:
            features = [IF_FEATURES.get(f, f) for f in L.clean(forest.get("effective_feature_columns")).split(",") if f]
            rank = _num(forest.get("evidence_rank")); ranks.append(rank or 0)
            facts.append({"label": "Compared with all records in this survey round", "value": f"A less common combination than about {share_text(rank)} of records"})
        if lof:
            rank = _num(lof.get("evidence_rank")); ranks.append(rank or 0)
            facts.append({"label": f"Compared with its {L.count(int(_num(lof.get('lof_reference_population_size')) or 0))} comparable records",
                          "value": f"Further from its nearest comparable records than about {share_text(rank)} of assessed records are from theirs"})
        best = max(ranks) if ranks else None
        sections.append({
            "id": "ml_combination", "source": "ml", "level": "record", "title": "Overall combination of answers", "strength": strength(best),
            "observed": "This person's answers taken together" + (f" ({', '.join(features)})" if forest else "") + ".",
            "comparison": "Compared with the combinations of answers given by other people in the same survey round and in the same comparison group.",
            "facts": facts,
            "meaning": ("The answers, taken together, form a combination that is uncommon." if (best or 0) >= UNUSUAL
                        else "The answers, taken together, form a fairly ordinary combination."),
            "matters": "Uncommon combinations can arise from a single mis-recorded item, or from a genuinely uncommon situation. Reading the answers side by side is the quickest way to check whether they are consistent.",
            "technical": {"isolation_forest": {k: forest.get(k) for k in ("raw_model_score", "evidence_rank", "feature_spec_version", "source_reference_metadata")} if forest else None,
                          "local_outlier_factor": {k: lof.get(k) for k in ("raw_model_score", "evidence_rank", "peer_group_id", "lof_distinct_reference_points", "feature_spec_version")} if lof else None},
        })
    return sections


def _historical_section(case: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    assessable = [r for r in rows if r.get("assessability_status") == "ASSESSABLE" and _num(r.get("historical_percentile")) is not None]
    if not assessable:
        reasons = {L.clean(r.get("assessability_reason")) for r in rows}
        if "DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD" in reasons:
            return None, "This record is from January 2025, the first month of the redesigned survey; there is no comparable earlier period to compare with."
        if "NO_EARLIER_PERIOD_SUPPLIED" in reasons:
            return None, "This record is from the earliest period available, so there is no earlier period to compare with."
        return None, UNAVAILABLE_TEXT["historical"]
    lead = max(assessable, key=lambda r: _num(r.get("historical_score")) or 0)
    unit = L.variable_unit(lead["target_variable"])
    p = _num(lead["historical_percentile"]) or .5
    size = int(_num(lead.get("reference_size")) or 0)
    others = [r for r in assessable if r is not lead]
    return {
        "id": "historical", "source": "historical", "level": "record", "title": SOURCE_TITLES["historical"], "strength": strength(_num(case.get("historical_rank"))),
        "observed": f"{L.variable_label(lead['target_variable'])} {REFERENCE_PERIOD.get(lead['target_variable'], '')}: {L.format_value(lead.get('observed_value'), unit)} ({L.clean(lead.get('period_label'))})",
        "comparison": f"Compared with {L.count(size)} records of {natural_group(lead.get('comparison_values'))} interviewed in {L.clean(lead.get('reference_periods'))}.",
        "facts": [
            {"label": "Typical value in the earlier period(s)", "value": L.format_value(lead.get("reference_median"), unit)},
            {"label": "Middle half in the earlier period(s)", "value": f"{L.format_value(lead.get('quantile_0_25'), unit)} to {L.format_value(lead.get('quantile_0_75'), unit)}"},
            {"label": "Position among earlier comparable records", "value": _position_text(p, size)},
        ] + [{"label": f"{L.variable_label(r['target_variable'])} (earlier periods)", "value": _position_text(_num(r['historical_percentile']) or .5, int(_num(r.get('reference_size')) or 0))} for r in others],
        "meaning": f"Compared with similar people interviewed earlier, the reported value is {_tail_words(lead.get('distribution_position'))}.",
        "matters": "Earlier periods show what comparable respondents usually reported. Earnings are in current rupees and are not adjusted for price changes, so a small upward drift over a year is expected.",
        "technical": {k: lead.get(k) for k in ("target_variable", "historical_percentile", "historical_score", "reference_size", "comparison_level", "comparison_dimensions", "reference_periods", "method_version")},
        "lead": lead,
    }, ""


def _rules_section(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return {
        "id": "rules", "source": "rules", "level": "record", "title": "Documented questionnaire rules",
        "strength": {"level": "very", "label": "Rule not met"},
        "observed": "; ".join(f"{L.clean(r.get('message'))}" for r in rows),
        "comparison": "Checked against the documented PLFS questionnaire rules (" + "; ".join(sorted({L.clean(r.get("source")) for r in rows})) + ").",
        "facts": [{"label": L.clean(r.get("rule_id")), "value": ", ".join(f"{k} = {v}" for k, v in _json(r.get("observed_values"), {}).items())} for r in rows],
        "meaning": "The recorded answers do not satisfy a documented questionnaire rule.",
        "matters": "A rule breach is a definite inconsistency in the recorded answers, but the schedule shows which answer is wrong. Check the filled-in schedule before correcting anything.",
        "technical": {"rules": rows},
    }


def _similarity_section(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    row = next((r for r in rows if r.get("assessability_status") == "ASSESSABLE"), None)
    if row is None:
        return None
    matches = int(_num(row.get("match_count")) or 0)
    return {
        "id": "ml_similarity", "source": "ml", "level": "record", "title": "Identical answer sets in the same FSU",
        "strength": {"level": "info", "label": "For information"},
        "observed": f"{int(_num(row.get('signature_present_field_count')) or 0)} answers compared (identifiers excluded).",
        "comparison": "Compared with every other person in the same FSU and survey period.",
        "facts": [{"label": "Other records with an identical set of answers", "value": f"{L.count(matches)}"}],
        "meaning": ("No other person in this FSU gave an identical set of answers." if matches == 0
                    else f"{matches} other record(s) in this FSU have exactly the same set of answers."),
        "matters": "Identical answers are common for people in similar situations (for example, children of the same age at school); this is shown for information and does not affect the priority.",
        "technical": {k: row.get(k) for k in ("method", "signature_hash", "match_count", "blocking_specification", "source_reference_metadata")},
        "matches": matches,
    }


def pattern_item(row: dict[str, Any]) -> dict[str, Any]:
    """Translate one stored FSU pattern row into plain language, from its stored numbers only."""
    component, variable = L.clean(row.get("pattern_component")), L.clean(row.get("variable"))
    details = _json(row.get("details_json"), {})
    short = L.VARIABLES.get(variable, {}).get("short", variable.replace("_", " "))
    unit = L.variable_unit(variable)
    n, reference_n = int(_num(row.get("n")) or 0), int(_num(row.get("reference_n")) or 0)
    text, title = _plain_statement(row.get("evidence_statement")), "FSU pattern"
    if component == "digit_heaping" and "fsu_share_ending_0_or_5" in details:
        own, ref = details["fsu_share_ending_0_or_5"], details["reference_share_ending_0_or_5"]
        title = f"Reported {short} ending in 0 or 5"
        text = (f"{own * 100:.0f}% of reported {short} values in this FSU end in 0 or 5 ({details.get('count_ending_0_or_5')} of {n} people), "
                f"compared with {ref * 100:.0f}% in comparable FSUs." + ("" if own > ref else " This is not higher than in comparable FSUs."))
    elif component == "fsu_distribution_shift" and "fsu_median" in details:
        direction = details.get("direction_of_medians")
        title = f"Typical {short} compared with comparable FSUs"
        who = "" if variable == "age" else " (among people for whom the question applies)"
        text = (f"The typical {short} in this FSU{who} is {L.format_value(details['fsu_median'], unit)} "
                f"(middle half {L.format_value(details.get('fsu_q25'), unit)} to {L.format_value(details.get('fsu_q75'), unit)}), "
                f"compared with {L.format_value(details.get('reference_median'), unit)} in comparable FSUs.")
        if direction == "equal":
            text += " The typical values are equal; the spread of values differs."
    elif component == "fsu_distribution_shift" and details.get("categories"):
        cats, own, ref = details["categories"], details.get("fsu_proportions", []), details.get("reference_proportions", [])
        if cats and len(own) == len(cats) == len(ref):
            index = max(range(len(cats)), key=lambda i: abs(own[i] - ref[i]))
            category = _category_label(variable, cats[index])
            title = f"Mix of {short} compared with comparable FSUs"
            text = f"In this FSU, {own[index] * 100:.0f}% of people have {category}, compared with {ref[index] * 100:.0f}% in comparable FSUs."
    elif component == "reduced_variance_concentration" and "fsu_share_close_to_own_median" in details:
        title = f"Spread of reported {short} compared with comparable FSUs"
        own, ref = details["fsu_share_close_to_own_median"], details["expected_share"]
        text = (f"{own * 100:.0f}% of reported {short} values in this FSU lie close to the FSU's own typical value, compared with {ref * 100:.0f}% in comparable FSUs "
                f"(middle half spans {L.format_value(details.get('fsu_iqr'), unit)} here and {L.format_value(details.get('reference_iqr'), unit)} in comparable FSUs).")
        text += " Values in this FSU vary less than usual." if own > ref else " Values in this FSU do not vary less than usual."
    elif component == "revisit_transition_patterns":
        title = f"Changes between visits ({short})"
    elif component == "temporal_drift":
        title = f"{L.variable_label(variable)} changed over time"
    q_value = _num(row.get("q_value"))
    rank = _num(row.get("evidence_rank"))
    return {
        "component": component, "variable": variable, "title": title, "text": text, "strength": group_strength(q_value, rank),
        "notable": bool(q_value is not None and q_value < NOTABLE_Q),
        "people": n, "reference_people": reference_n,
        "basis": f"Based on {L.count(n)} people in this FSU and {L.count(reference_n)} people in comparable FSUs of the same State, sector and stratum.",
        "technical": {"evidence_statement": row.get("evidence_statement"), "raw_metric": row.get("raw_metric"), "p_value": row.get("p_value"), "q_value": row.get("q_value"),
                      "evidence_rank": row.get("evidence_rank"), "reference_definition": row.get("reference_definition"), "details": details,
                      "method_version": row.get("method_version"), "evidence_id": row.get("evidence_id")},
    }


def _category_label(variable: str, value: str) -> str:
    if variable == "cws_status":
        return f"activity status “{L.code_label(L.ACTIVITY_STATUS, value) or 'code ' + value}”"
    if variable == "principal_occupation_major_group":
        return f"occupation group {value}"
    if variable == "principal_industry_division":
        return f"industry division {value}"
    return f"value {value}"


PATTERN_KEYS = ("release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum", "fsu")


def pattern_rows(pattern_dir: Path | None, keys: dict[str, Any]) -> list[dict[str, Any]]:
    clause = " AND ".join(f'COALESCE(CAST("{k}" AS VARCHAR), \'\') = ?' for k in PATTERN_KEYS)
    path = _file(pattern_dir, "pattern_evidence.parquet")
    if path is None:
        return []
    with duckdb.connect() as connection:
        has_q = "q_value" in set(connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]).fetchdf().columns)
    order = "q_value ASC NULLS LAST, evidence_rank DESC NULLS LAST" if has_q else "evidence_rank DESC NULLS LAST"
    return _query(path, f"SELECT * FROM read_parquet(?) WHERE {clause} AND assessability_status = 'ASSESSABLE' ORDER BY {order}",
                  [L.clean(keys.get(k)) for k in PATTERN_KEYS])


def _pattern_section(case: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    items = [pattern_item(r) for r in rows]
    notable = [i for i in items if i["notable"]][:4]
    shown = notable or items[:1]
    best_q = min((i["strength"].get("q_value") for i in items if i["strength"].get("q_value") is not None), default=None)
    return {
        "id": "pattern", "source": "pattern", "level": "group", "title": f"Pattern across FSU {case.get('fsu')}",
        "strength": group_strength(best_q, _num(case.get("pattern_rank"))),
        "observed": f"{len(notable)} of {len(items)} FSU-level checks show a notable difference from comparable FSUs (after allowing for the many FSUs compared)." if notable
        else f"None of the {len(items)} FSU-level checks show a notable difference from comparable FSUs.",
        "comparison": "Compared with other FSUs in the same State, sector and stratum (this FSU excluded).",
        "items": shown,
        "meaning": ("The FSU as a whole differs from comparable FSUs in the respects listed. This is context about the group; it is not evidence that this person's answers are wrong."
                    if notable else "The FSU as a whole does not stand out from comparable FSUs."),
        "matters": "Group patterns can point to how an FSU's interviews were conducted or recorded, or simply to a genuinely different place. They apply to the FSU as a whole, not specifically to this person, and they do not change this record's position in the list.",
        "technical": {"assessable_pattern_rows": len(items), "notable_rows": len(notable), "minimum_q_value": best_q},
        "notable": bool(notable),
    }


# ---------------------------------------------------------------------------
# story assembly


def build_story(case: dict[str, Any], resolver: SourceResolver, *, priority_position: int | None = None,
                priority_total: int | None = None, weight_share: float | None = None) -> dict[str, Any]:
    release, observation = str(case["release"]), str(case["observation_type"])
    provenance = _json(case.get("provenance") or case.get("provenance_json"), {})
    dirs = resolver.directories(release, observation, provenance)
    sid = case["source_observation_id"]
    person = person_context(case, dirs["preprocessing"])

    stat_rows = _query(_file(dirs["statistical"], "statistical_evidence.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    context_rows = _query(_file(dirs["contextual"], "contextual_evidence.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    ml_rows = {name: _query(_file(dirs["ml"], f"{name}_evidence.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
               for name in ("isolation_forest", "lof", "conditional_model", "similarity")}
    ml_rows["conditional"] = ml_rows.pop("conditional_model")
    history_rows = _query(_file(dirs["historical"], "historical_record_evidence.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    rule_rows = _query(_file(dirs["integrity"], "integrity_violations.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    group_rows = pattern_rows(dirs["pattern"], case) if case.get("pattern_status") != "NOT_AVAILABLE" else []

    stat, stat_facts = _stat_section(case, stat_rows)
    context, context_missing = _context_section(case, context_rows)
    ml_sections = _ml_sections(case, ml_rows)
    historical, historical_missing = _historical_section(case, history_rows) if dirs["historical"] else (None, "No historical run was supplied for this survey round.")
    rules = _rules_section(rule_rows)
    similarity = _similarity_section(ml_rows["similarity"])
    pattern = _pattern_section(case, group_rows)

    # Narrative order: documented rules, comparison with similar records, earlier
    # periods, the person's own answers, then FSU-level (group) context.
    order = {"rules": -1, "statistical": 0, "historical": 1, "ml_conditional": 2, "ml_combination": 3, "contextual": 4, "pattern": 5, "ml_similarity": 6}
    evidence = sorted([s for s in (rules, stat, historical, context, *ml_sections, pattern, similarity) if s], key=lambda s: order.get(s["id"], 9))

    unavailable = []
    if stat is None:
        unavailable.append({"source": "statistical", "title": SOURCE_TITLES["statistical"], "text": UNAVAILABLE_TEXT["statistical"]})
    if historical is None:
        unavailable.append({"source": "historical", "title": SOURCE_TITLES["historical"], "text": historical_missing})
    if context is None:
        unavailable.append({"source": "contextual", "title": SOURCE_TITLES["contextual"], "text": context_missing or UNAVAILABLE_TEXT["contextual"]})
    if not ml_sections:
        unavailable.append({"source": "ml", "title": SOURCE_TITLES["ml"], "text": UNAVAILABLE_TEXT["ml"]})
    if pattern is None:
        text = ("No compatible FSU pattern run was supplied for this survey round." if case.get("pattern_status") == "NOT_AVAILABLE"
                else UNAVAILABLE_TEXT["pattern"])
        unavailable.append({"source": "pattern", "title": SOURCE_TITLES["pattern"], "text": text})

    reasons = _reasons(rules, stat, historical, context, ml_sections, pattern)
    return {
        "details_available": any(dirs[k] is not None for k in ("statistical", "contextual", "ml")),
        "record": _record_block(case, person),
        "headline": _headline(reasons),
        "reasons": reasons,
        "unusual": _unusual_facts(stat, context, ml_sections, historical),
        "evidence": evidence,
        "other_values": stat["other_values"] if stat else [],
        "sources": _source_summary(case, stat, historical, context, ml_sections, pattern, unavailable),
        "unavailable": unavailable,
        "checks": _checks(case, person, rules, stat, historical, context, ml_sections, pattern, similarity),
        "importance": _importance(case, stat_rows, priority_position, priority_total, weight_share),
        "caveat": "The system has found this record unusual compared with similar records. It has not found the record to be incorrect. Only your review can decide that.",
        "source_runs": {k: (str(v.name) if v else None) for k, v in dirs.items()},
    }


def _record_block(case: dict[str, Any], person: dict[str, Any]) -> dict[str, Any]:
    title_parts = [f"FSU {case.get('fsu')}"]
    if person.get("household"):
        title_parts.append(f"Household {person['household']}")
    if person.get("person"):
        title_parts.append(f"Person {person['person']}")
    release = L.clean(case.get("release")).replace("_", "–")
    location = [{"label": "State/UT", "value": L.state_name(case.get("state"))},
                {"label": "District code", "value": person.get("district") or "—"},
                {"label": "Sector", "value": L.sector_name(case.get("sector"))},
                {"label": "Stratum", "value": L.clean(case.get("stratum")) or "—"},
                {"label": "FSU", "value": L.clean(case.get("fsu")) or "—"}]
    survey = [{"label": "Survey round", "value": f"PLFS {release}"},
              {"label": "Schedule", "value": "First visit" if case.get("observation_type") == "first_visit" else "Revisit"},
              {"label": "Visit", "value": L.clean(case.get("visit")) or "—"}]
    if L.clean(case.get("month")):
        survey.append({"label": "Month", "value": L.clean(case.get("month"))})
    else:
        survey.append({"label": "Quarter", "value": person.get("quarter") or "—"})
    return {"title": " · ".join(title_parts), "record_key": person.get("record_key"), "location": location, "survey": survey, "person": person.get("facts", [])}


def _reasons(rules, stat, historical, context, ml_sections, pattern) -> list[dict[str, str]]:
    reasons = []
    if rules:
        reasons.append({"source": "rules", "level": "record", "text": "the recorded answers do not satisfy a documented questionnaire rule"})
    if stat and stat["lead"].get("distribution_position") in {"UPPER_TAIL", "LOWER_TAIL"}:
        lead = stat["lead"]
        reasons.append({"source": "statistical", "level": "record",
                        "text": f"the reported {L.VARIABLES.get(lead['target_variable'], {}).get('short', 'value')} are {_tail_words(lead['distribution_position'])}"})
    if historical and historical["lead"].get("distribution_position") in {"UPPER_TAIL", "LOWER_TAIL"} and (historical["strength"].get("rank") or 0) >= UNUSUAL:
        lead = historical["lead"]
        reasons.append({"source": "historical", "level": "record",
                        "text": f"the reported {L.VARIABLES.get(lead['target_variable'], {}).get('short', 'value')} are {_tail_words(lead['distribution_position']).replace('comparable records', 'comparable records in earlier periods')}"})
    if context and (context["strength"].get("rank") or 0) >= UNUSUAL:
        reasons.append({"source": "contextual", "level": "record", "text": "the reported occupation code is uncommon among comparable records"})
    for section in ml_sections:
        if (section["strength"].get("rank") or 0) < UNUSUAL:
            continue
        if section["id"] == "ml_conditional":
            reasons.append({"source": "ml", "level": "record", "text": f"the reported {L.VARIABLES.get(section['target'], {}).get('short', 'amount')} are far from the model estimate for people with the same characteristics"})
        else:
            reasons.append({"source": "ml", "level": "record", "text": "the person's answers, taken together, form an uncommon combination"})
    if pattern and pattern.get("notable"):
        reasons.append({"source": "pattern", "level": "group", "text": "the record belongs to an FSU that, as a whole, differs from comparable FSUs (group context only)"})
    return reasons


def _headline(reasons: list[dict[str, str]]) -> str:
    record = [r["text"] for r in reasons if r["level"] == "record"]
    group = [r["text"] for r in reasons if r["level"] == "group"]
    if not record:
        sentence = ("This record is in the review list because of its combined position across the available checks. "
                    "No single record-level check finds it strongly unusual.")
        if group:
            sentence += " Separately, it " + group[0].removeprefix("the record ") + "."
        return sentence
    sentence = "This record has been brought to your attention because " + _join(record[:2]) + "."
    if group:
        sentence += " Separately, it " + group[0].removeprefix("the record ") + "."
    return sentence


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _unusual_facts(stat, context, ml_sections, historical) -> list[dict[str, str]]:
    facts = []
    if stat:
        lead, unit = stat["lead"], L.variable_unit(stat["lead"]["target_variable"])
        facts += [{"label": f"Reported {L.VARIABLES.get(lead['target_variable'], {}).get('short', 'value')}", "value": L.format_value(lead.get("observed_value"), unit), "emphasis": "observed"},
                  {"label": "Middle half of comparable records", "value": f"{L.format_value(lead.get('quantile_0_25'), unit)} – {L.format_value(lead.get('quantile_0_75'), unit)}"},
                  {"label": "Position among comparable records", "value": _position_text(_num(lead["percentile_position"]) or .5, int(_num(lead.get("peer_group_size")) or 0))}]
    if historical and historical["lead"].get("distribution_position") in {"UPPER_TAIL", "LOWER_TAIL"}:
        lead, unit = historical["lead"], L.variable_unit(historical["lead"]["target_variable"])
        facts.append({"label": f"Typical in earlier periods ({L.clean(lead.get('reference_periods'))})", "value": L.format_value(lead.get("reference_median"), unit)})
    conditional = next((s for s in ml_sections if s["id"] == "ml_conditional" and (s["strength"].get("rank") or 0) >= UNUSUAL), None)
    if conditional and conditional.get("ratio"):
        facts.append({"label": "Compared with the model estimate for similar people", "value": _ratio_text(conditional["ratio"])})
    if context and context["rare"]:
        facts.append({"label": f"Occupation code {context['code']}", "value": context["facts"][0]["value"] + " comparable records"})
    return facts


def _source_summary(case, stat, historical, context, ml_sections, pattern, unavailable) -> list[dict[str, Any]]:
    missing = {u["source"]: u["text"] for u in unavailable}
    rows = []

    def add(source, label, section_text, rank_field, strength_value=None):
        rank = _num(case.get(rank_field))
        rows.append({"source": source, "label": label, "available": source not in missing,
                     "text": section_text if source not in missing else missing[source],
                     "strength": (strength_value or strength(rank)) if source not in missing else None})
    add("statistical", "Comparison with similar records",
        (f"{stat['meaning']} {_position_text(_num(stat['lead']['percentile_position']) or .5, int(_num(stat['lead'].get('peer_group_size')) or 0))}." if stat else ""), "statistical_rank")
    add("historical", "Comparison with earlier periods", (historical["meaning"] if historical else ""), "historical_rank")
    add("contextual", "Occupation check", (f"{context['meaning']}" if context else ""), "contextual_rank")
    add("ml", "Pattern-of-answers checks", " ".join(s["meaning"] for s in ml_sections), "ml_rank")
    add("pattern", "FSU-level pattern (group context, not part of this record's priority)",
        (pattern["items"][0]["text"] + " " + pattern["meaning"]) if pattern and pattern["items"] else "", "pattern_rank",
        pattern["strength"] if pattern else None)
    return rows


def _checks(case, person, rules, stat, historical, context, ml_sections, pattern, similarity) -> list[dict[str, str]]:
    """Checks follow only from evidence that was found.  ``text`` is the short instruction; ``detail`` says how."""
    checks: list[dict[str, str]] = []

    def add(level: str, text: str, detail: str = "", source: str = "") -> None:
        if all(c["text"] != text for c in checks):
            checks.append({"level": level, "text": text, "detail": detail, "source": source})

    if rules:
        for row in rules["facts"]:
            add("record", f"Check the schedule for rule {row['label']}.", f"Recorded values: {row['value']}. Find which recorded answer is wrong before correcting anything.", "rules")
    if stat and stat["lead"].get("distribution_position") in {"UPPER_TAIL", "LOWER_TAIL"}:
        lead = stat["lead"]
        target, unit = lead["target_variable"], L.variable_unit(lead["target_variable"])
        value = L.format_value(lead.get("observed_value"), unit)
        short = L.VARIABLES.get(target, {}).get("short", "value")
        if unit == "rupees":
            add("record", f"Confirm that {value} was entered correctly.",
                f"Compare the reported {short} ({REFERENCE_PERIOD.get(target, '')}) with the filled-in schedule: look for an extra digit or misplaced zeros.", "statistical")
        else:
            add("record", f"Confirm that {value} agrees with the day-wise activity entries.", f"The reported {short} are compared with the schedule's day-wise entries.", "statistical")
        if any(g["label"] == L.DIMENSIONS["cws_status"] for g in stat.get("comparison_group", [])):
            status = _status_label(person.get("cws_status") or _json(lead.get("grouping_values"), {}).get("cws_status"))
            add("record", "Confirm the person's activity status.", f"Recorded as {status}. The comparison group depends on it.", "statistical")
    for other in (stat or {}).get("other_values", []):
        if other["tail"]:
            add("record", f"Also confirm the {other['label'].lower()} ({other['observed']}).", f"{other['position']} for comparable records.", "statistical")
    if context and context["rare"]:
        add("record", f"Check that occupation code {context['code']} matches the work the person described.", "The code is uncommon for people with the same activity status and industry.", "contextual")
    conditional = next((s for s in ml_sections if s["id"] == "ml_conditional"), None)
    if conditional and (conditional["strength"].get("rank") or 0) >= UNUSUAL and not (stat and stat["lead"]["target_variable"] == conditional["target"] and stat["lead"].get("distribution_position") != "CENTRAL_REFERENCE_RANGE"):
        add("record", f"Check whether the reported {L.VARIABLES.get(conditional['target'], {}).get('short', 'amount')} fit the person's other details.",
            "Compare the amount with the person's education, occupation, industry and hours.", "ml")
    combination = next((s for s in ml_sections if s["id"] == "ml_combination"), None)
    if combination and (combination["strength"].get("rank") or 0) >= UNUSUAL:
        add("record", "Check whether the occupation and the reported work are consistent.",
            "Read age, education, activity status, occupation, hours and earnings side by side to see whether they fit together.", "ml")
    if pattern and pattern.get("notable"):
        for item in pattern["items"]:
            if not item["notable"]:
                continue
            short = L.VARIABLES.get(item["variable"], {}).get("short", item["variable"])
            if item["component"] == "digit_heaping":
                text = f"For the FSU as a whole: look at how {short} values were recorded (for example, whether ages were estimated and rounded)."
            elif item["component"] == "reduced_variance_concentration":
                text = f"For the FSU as a whole: review how much reported {short} values vary across people."
            else:
                text = f"For the FSU as a whole: review how {short} is distributed across households in FSU {case.get('fsu')}."
            add("group", text, "This concerns the FSU as a whole, not specifically this person.", "pattern")
    if similarity and similarity.get("matches"):
        add("record", "Check that the identical answer sets in this FSU reflect genuinely similar people.", f"{similarity['matches']} other record(s) in this FSU have exactly the same answers.", "ml")
    return checks


def _level(rank: float | None) -> str | None:
    """Display wording for a 0–1 position in the review ordering (a convention, not a test)."""
    if rank is None:
        return None
    return "Very high" if rank >= VERY_UNUSUAL else "High" if rank >= UNUSUAL else "Moderate" if rank >= SOMEWHAT_UNUSUAL else "Low"


def _importance(case, stat_rows, position, total, weight_share) -> dict[str, Any]:
    band = L.clean(case.get("priority_band")) or "NOT_ASSESSABLE"
    raw_influence = _num(case.get("raw_influence"))
    target = L.clean(case.get("influence_target"))
    if case.get("rule_violation") in (True, 1, "true", "True"):
        summary = f"{L.PRIORITY_BANDS.get(band, band)} — listed first because a documented questionnaire rule is not met."
    elif band == "NOT_ASSESSABLE":
        summary = ("A review priority could not be calculated for this record: it has no applicable earnings or hours value with a comparison group "
                   "(or no survey weight), so its potential effect on a weighted total cannot be estimated.")
    else:
        summary = f"{L.PRIORITY_BANDS.get(band, band)}" + (f" — ranked {L.count(position)} of {L.count(total)} records that received a priority." if position and total else ".")
    points = []
    risk = _num(case.get("risk_score"))
    if risk is not None:
        points.append({"label": "How unusual the record-level evidence is, overall", "value": f"{strength(risk)['label']} — stronger than about {share_text(risk)} of records"})
    if weight_share is not None:
        points.append({"label": "Survey weight of this record", "value": f"Larger than about {share_text(weight_share)} of records"})
    if raw_influence is not None and target:
        short = L.VARIABLES.get(target, {}).get("short", target)
        points.append({"label": "Potential effect on a weighted total",
                       "value": f"Replacing the reported {short} by the typical value would change the weighted {short} total of its State/UT, sector and period by about {raw_influence * 100:.3g}%"})
    if raw_influence == 0:
        explanation = ("The reported values equal the typical values of comparable records, so the record's potential effect on weighted totals is nil. "
                       "That keeps it lower in the list even where other checks find it unusual.")
    else:
        explanation = ("The list is ordered by two things together: how unusual the record-level evidence is, and how much the reported value could change a weighted "
                       "total for its State/UT, sector and period if it were wrong. FSU-level patterns are shown as context and do not move a record up the list.")
    unusualness, influence = _level(risk), _level(_num(case.get("influence_score")))
    plain = None
    if unusualness and influence:
        strong = {"Very high", "High"}
        plain = (("This record is unusually different from similar records" if unusualness in strong else "This record differs only moderately from similar records")
                 + (" and could have a relatively large effect on the survey total for its area if the reported value were wrong." if influence in strong
                    else ", and its potential effect on the survey total for its area is modest."))
    return {
        "band": band, "band_label": L.PRIORITY_BANDS.get(band, band), "summary": summary, "explanation": explanation, "points": points,
        "levels": {"unusualness": unusualness, "influence": influence}, "plain": plain,
        "limitation": ("The potential effect is a provisional measure. It uses the typical value of comparable records as a stand-in for the correct value and "
                       "has not been validated as the effect on official PLFS estimates, so it should be used only to decide the order of review."),
        "position": position, "total": total,
    }


# ---------------------------------------------------------------------------
# short list summaries (queue rows)


def summarise_rows(rows: list[dict[str, Any]], resolver: SourceResolver, release: str, observation: str) -> None:
    """Attach one-line plain summaries to queue rows using batched lookups."""
    if not rows:
        return
    if "tier" in rows[0]:
        _summarise_lane_rows(rows)
        return
    provenance = _json(rows[0].get("provenance_json"), {})
    dirs = resolver.directories(release, observation, provenance)
    ids = [r["source_observation_id"] for r in rows]
    stat = _query(_file(dirs["statistical"], "statistical_evidence.parquet"),
                  "SELECT * FROM read_parquet(?) WHERE source_observation_id IN (SELECT UNNEST(?))", [ids])
    stat = [r for r in stat if (r.get("statistical_assessability_status") or r.get("assessability_status")) == "ASSESSABLE"]
    context = _query(_file(dirs["contextual"], "contextual_evidence.parquet"),
                     "SELECT source_observation_id, observed_value, category_count, reference_count FROM read_parquet(?) WHERE source_observation_id IN (SELECT UNNEST(?))", [ids])
    stat_by = {(r["source_observation_id"], r["target_variable"]): r for r in stat}
    context_by = {r["source_observation_id"]: r for r in context}
    for row in rows:
        row["location_label"] = f"{L.state_name(row.get('state'))} · {L.sector_name(row.get('sector'))}"
        key, _, person = str(row["source_observation_id"]).partition("|person=")
        parts = key.split("|")
        row["record_label"] = f"FSU {row.get('fsu')} · Household {parts[-1] if parts else '—'} · Person {person}"
        lead = stat_by.get((row["source_observation_id"], L.clean(row.get("target_variable"))))
        if row.get("rule_violation") in (True, 1):
            row["unusual"] = "A documented questionnaire rule is not met"
        elif lead:
            unit = L.variable_unit(lead["target_variable"])
            short = L.VARIABLES.get(lead["target_variable"], {}).get("short", "value")
            direction = {"UPPER_TAIL": "above the usual range; typical", "LOWER_TAIL": "below the usual range; typical"}.get(lead.get("distribution_position"), "within the usual range; typical")
            row["unusual"] = f"Reported {short} {L.format_value(lead.get('observed_value'), unit)} — {direction} {L.format_value(lead.get('peer_median'), unit)} for {L.count(int(_num(lead.get('peer_group_size')) or 0))} comparable records"
            # The same stored comparison as raw numbers, so the list can draw where the value sits.
            row["comparison"] = {"variable": lead["target_variable"], "short": short, "unit": unit,
                                 "observed": _num(lead.get("observed_value")), "typical": _num(lead.get("peer_median")),
                                 "low": _num(lead.get("quantile_0_05")), "high": _num(lead.get("quantile_0_95")),
                                 "position": lead.get("distribution_position"), "comparable": int(_num(lead.get("peer_group_size")) or 0)}
        else:
            row["unusual"] = "No applicable earnings or hours comparison was possible for this record"
        reasons = []
        c = context_by.get(row["source_observation_id"])
        if c and (_num(row.get("contextual_rank")) or 0) >= UNUSUAL and L.clean(c.get("observed_value")):
            reasons.append(f"Uncommon occupation code ({int(_num(c.get('category_count')) or 0)} of {int(_num(c.get('reference_count')) or 0)} comparable records)")
        if (_num(row.get("historical_rank")) or 0) >= UNUSUAL:
            reasons.append("Unusual compared with similar people in earlier periods")
        ml_rank = _num(row.get("ml_rank")) or 0
        if ml_rank >= UNUSUAL:
            reasons.append({
                "Reported salaried earnings differ from the model estimate for people with the same characteristics.": "Earnings far from the model estimate for similar people",
                "Local unusualness within the comparable peer population.": "Further from its nearest comparable records than most",
                "Unusual multivariate response pattern.": "Uncommon combination of answers",
            }.get(L.clean(row.get("ml_statement")), "Uncommon pattern of answers"))
        if (_num(row.get("pattern_notable_checks")) or 0) > 0:
            reasons.append("FSU-level context: " + _short_pattern(row.get("pattern_statement")))
        row["why"] = reasons
        row["band_label"] = L.PRIORITY_BANDS.get(L.clean(row.get("priority_band")), row.get("priority_band"))
        row.pop("provenance_json", None)


def _short_pattern(statement: Any) -> str:
    text = _plain_statement(statement)
    for marker, words in ((": the mix of ", "mix of {} differs from comparable FSUs"), (": the typical ", "typical {} differs from comparable FSUs")):
        if marker in text:
            variable = text.split(marker, 1)[1].split(" ", 1)[0] if marker == ": the typical " else text.split(marker, 1)[1].split(" differs", 1)[0]
            return words.format(variable)
    if " end in 0 or 5" in text:
        return "share of ages ending in 0 or 5 differs from comparable FSUs"
    if "vary less than usual" in text:
        return "values vary less than in comparable FSUs"
    return "the FSU differs from comparable FSUs"


def _summarise_lane_rows(rows: list[dict[str, Any]]) -> None:
    """One-line summaries for lane-design queue rows, from the row's stored fields only."""
    for row in rows:
        row["location_label"] = f"{L.state_name(row.get('state'))} · {L.sector_name(row.get('sector'))}"
        key, _, person = str(row["source_observation_id"]).partition("|person=")
        parts = key.removesuffix("|household").split("|")
        household = parts[-1] if parts else "—"
        row["record_label"] = (f"FSU {row.get('fsu')} · Household {household}" + (f" · Person {person}" if person else " (whole household)"))
        lanes = [x for x in str(row.get("lanes") or "").split(",") if x]
        reasons = []
        if "RULE" in lanes or "RULE_SOFT" in lanes:
            reasons.append("Questionnaire rule not met: " + str(row.get("rule_ids") or ""))
        variable = L.clean(row.get("value_lead_variable"))
        if "VALUE" in lanes and variable:
            unit = L.variable_unit(variable)
            short = L.VARIABLES.get(variable, {}).get("short", "value")
            observed, typical = _num(row.get("value_lead_observed")), _num(row.get("value_lead_typical"))
            reasons.append(f"Reported {short} {L.format_value(observed, unit)}" + (f" — typical for similar people {L.format_value(typical, unit)}" if typical is not None else ""))
            row["comparison"] = {"variable": variable, "short": short, "unit": unit, "observed": observed, "typical": typical}
        if "CODING" in lanes:
            reasons.append(f"Occupation code {L.clean(row.get('coding_code'))} is rare for comparable people")
        row["unusual"] = reasons[0] if reasons else "Not flagged by any check"
        row["why"] = reasons[1:] + (["FSU-level context: the FSU as a whole differs from comparable FSUs"] if row.get("fsu_notable") else [])
        row["lane_labels"] = [L.LANES.get(x, x) for x in lanes]
        row["band_label"] = L.PRIORITY_BANDS.get(L.clean(row.get("priority_band")), row.get("priority_band"))
        row.pop("provenance_json", None)
