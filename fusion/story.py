"""Supervisor case story for lane-design runs (fusion v2.1), from stored values only.

Order (plan §11): what was recorded -> comparison with similar people now ->
comparison with earlier periods -> expected value for similar people -> group
context -> importance -> what to check.  Every number shown is read from the
fusion run's ``value_evidence.parquet`` (which carries the statistical,
historical and model values it was built from), the integrity findings, the
contextual row or the FSU summary.  Nothing is recomputed except plain
ratios between two stored numbers (e.g. "about 10x the typical value"),
which are labelled as possible explanations to check, never as findings.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import labels as L
from .explain import (REFERENCE_PERIOD, SourceResolver, _file, _json, _num, _query, _status_label, describe_group, natural_group,
                      pattern_item, pattern_rows, person_context)

GROUP_SENTENCE = "This describes the FSU as a whole. It does not mean that any answer of this person or household is wrong."


def evidence_strength(p: float | None) -> dict[str, Any]:
    """Plain wording for a tail probability (display convention; the queue uses the numbers)."""
    if p is None:
        return {"level": "none", "label": "Not checked"}
    if p <= 0.001:
        level, label, plain = "very", "Very rare", "fewer than 1 in 1,000 comparable records"
    elif p <= 0.01:
        level, label, plain = "high", "Rare", "fewer than 1 in 100 comparable records"
    elif p <= 0.05:
        level, label, plain = "some", "Uncommon", "fewer than 1 in 20 comparable records"
    else:
        level, label, plain = "low", "Not unusual", "common among comparable records"
    return {"level": level, "label": label, "p": p, "plain": plain}


def _fmt(value: Any, variable: str) -> str:
    return L.format_value(value, L.variable_unit(variable))


def keying_hints(observed: float | None, typical: float | None, low: float | None, high: float | None, variable: str) -> list[str]:
    """Possible recording slips consistent with two stored numbers.  Suggestions to check, not findings."""
    hints: list[str] = []
    if observed is None or observed <= 0:
        return hints
    unit = L.variable_unit(variable)
    usual = (lambda x: low <= x <= high) if low is not None and high is not None else None
    outside = usual is not None and not usual(observed)
    if unit == "rupees" and outside:
        # A slip is suggested only when the corrected value would sit inside the usual range of comparable people.
        for factor, text in ((10, "an extra zero"), (100, "two extra zeros"), (12, "a yearly amount recorded instead of a monthly one")):
            if usual(observed / factor):
                hints.append(f"The value divided by {factor} ({_fmt(observed / factor, variable)}) is in the usual range: check for {text}.")
        if usual(observed * 10):
            hints.append(f"The value multiplied by 10 ({_fmt(observed * 10, variable)}) is in the usual range: check for a missing zero.")
        text = str(int(round(observed)))
        if len(text) >= 3 and text[0] != text[1] and low is not None and high is not None:
            swapped = float(text[1] + text[0] + text[2:])
            if low <= swapped <= high and not (low <= observed <= high):
                hints.append(f"Swapping the first two digits gives {_fmt(swapped, variable)}, which is in the usual range: check for swapped digits.")
    elif unit == "hours" and observed >= 10 and low is not None and high is not None and low <= observed - 10 <= high and observed > high:
        hints.append(f"Without a leading 1 the value would be {observed - 10:g} hours, which is usual: check for a keying slip.")
    return hints


def _variable_section(row: dict[str, Any], lead: bool) -> dict[str, Any]:
    variable = L.clean(row.get("target_variable"))
    observed = _num(row.get("observed_value"))
    p = _num(row.get("p_variable"))
    period = REFERENCE_PERIOD.get(variable, "")
    comparisons, technical = [], {}
    if _num(row.get("p_current")) is not None:
        comparisons.append({
            "kind": "current", "title": "Similar people in this survey round",
            "text": f"{L.count(int(_num(row.get('current_n')) or 0))} records of {natural_group(row.get('grouping_values'))} (this person excluded).",
            "facts": [{"label": "Typical value", "value": _fmt(row.get("peer_median"), variable)},
                      {"label": "Middle half", "value": f"{_fmt(row.get('current_q25'), variable)} to {_fmt(row.get('current_q75'), variable)}"},
                      {"label": "9 in 10 fall between", "value": f"{_fmt(row.get('current_q05'), variable)} and {_fmt(row.get('current_q95'), variable)}"}],
            "strength": evidence_strength(_num(row.get("p_current"))), "group": describe_group(row.get("grouping_values"), row.get("grouping_dimensions"))})
    if _num(row.get("p_history")) is not None:
        facts = [{"label": "Typical value then", "value": _fmt(row.get("history_median"), variable)},
                 {"label": "9 in 10 fell between", "value": f"{_fmt(row.get('history_q05'), variable)} and {_fmt(row.get('history_q95'), variable)}"}]
        if _num(row.get("p_same_season")) is not None:
            facts.append({"label": f"Same season a year earlier ({L.clean(row.get('same_season_period'))})",
                          "value": f"typical {_fmt(row.get('same_season_median'), variable)}"})
        comparisons.append({
            "kind": "history", "title": "The same group in earlier periods",
            "text": f"{L.count(int(_num(row.get('history_n')) or 0))} comparable records interviewed in {L.clean(row.get('reference_periods'))}.",
            "facts": facts, "strength": evidence_strength(_num(row.get("p_history")))})
    if _num(row.get("p_model")) is not None:
        scheme = L.clean(row.get("model_training_scheme"))
        source = ("learned only from earlier survey periods" if scheme == "TRAINED_ON_EARLIER_PERIODS"
                  else "learned from other FSUs of this period (no earlier period exists)")
        comparisons.append({
            "kind": "model", "title": "Expected value for a person with these characteristics",
            "text": f"A statistical model {source} expects about {_fmt(row.get('model_estimate'), variable)}; its usual range for such a person is "
                    f"{_fmt(row.get('model_low'), variable)} to {_fmt(row.get('model_high'), variable)}. This is a guide, not a correct value.",
            "facts": [], "strength": evidence_strength(_num(row.get("p_model")))})
    for key in ("p_current", "p_history", "p_same_season", "p_model", "p_reference", "p_variable", "mechanisms", "strongest_mechanism",
                "model_training_scheme", "model_training_periods", "current_direction", "impact_se", "estimate_change", "effective_se"):
        technical[key] = row.get(key)
    typical = _num(row.get("peer_median")) or _num(row.get("history_median")) or _num(row.get("model_estimate"))
    low = _num(row.get("current_q05")) if _num(row.get("current_q05")) is not None else _num(row.get("history_q05"))
    high = _num(row.get("current_q95")) if _num(row.get("current_q95")) is not None else _num(row.get("history_q95"))
    return {"id": f"value_{variable}", "source": "value", "level": "record", "lead": lead, "variable": variable,
            "title": L.variable_label(variable), "observed": f"{L.variable_label(variable)} {period}: {_fmt(observed, variable)}".replace("  ", " "),
            "strength": evidence_strength(p), "comparisons": comparisons, "hints": keying_hints(observed, typical, low, high, variable),
            "typical": typical, "technical": technical}


def build_lane_story(case: dict[str, Any], resolver: SourceResolver, fusion_dir: Path) -> dict[str, Any]:
    release, observation = str(case["release"]), str(case["observation_type"])
    provenance = _json(case.get("provenance") or case.get("provenance_json"), {})
    dirs = resolver.directories(release, observation, provenance)
    sid = str(case["source_observation_id"])
    household_case = case.get("case_level") == "HOUSEHOLD"
    person = person_context(case, dirs["preprocessing"]) if not household_case else {"record_key": sid.removesuffix("|household"), "facts": []}
    values = _query(_file(fusion_dir, "value_evidence.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ? ORDER BY p_variable NULLS LAST", [sid])
    rules = _query(_file(dirs["integrity"], "integrity_violations.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    if not household_case and person.get("record_key"):
        rules += _query(_file(dirs["integrity"], "integrity_violations.parquet"), "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?",
                        [f"{person['record_key']}|household"])
    context = [] if household_case else _query(_file(dirs["contextual"], "contextual_evidence.parquet"),
                                               "SELECT * FROM read_parquet(?) WHERE source_observation_id = ?", [sid])
    lead_variable = L.clean(case.get("value_lead_variable"))
    assessed = [r for r in values if _num(r.get("p_variable")) is not None]
    value_sections = [_variable_section(r, L.clean(r.get("target_variable")) == lead_variable) for r in assessed]
    evidence: list[dict[str, Any]] = []
    if rules:
        evidence.append({"id": "rules", "source": "rules", "level": "household" if all(r.get("level") == "household" for r in rules) else "record",
                         "title": "Documented questionnaire rules", "strength": {"level": "very", "label": "Rule not met"},
                         "observed": "; ".join(L.clean(r.get("message")) for r in rules),
                         "facts": [{"label": f"{L.clean(r.get('rule_id'))} (v{L.clean(r.get('rule_version')) or '1'}, {'household' if r.get('level') == 'household' else 'person'})",
                                    "value": ", ".join(f"{k} = {v}" for k, v in _json(r.get("observed_values"), {}).items())} for r in rules],
                         "comparison": "Source: " + "; ".join(sorted({L.clean(r.get("source")) for r in rules})),
                         "meaning": "The recorded answers do not satisfy a documented questionnaire rule. The schedule shows which answer is wrong.",
                         "technical": {"rules": rules}})
    evidence += value_sections
    coding = None
    row = context[0] if context else None
    if row is not None and row.get("contextual_assessability_status") == "ASSESSABLE" and _num(row.get("coding_tail_p")) is not None:
        count, reference = int(_num(row.get("category_count")) or 0), int(_num(row.get("reference_count")) or 0)
        values_json = _json(row.get("context_values"), {})
        coding = {"id": "coding", "source": "coding", "level": "record", "title": "How common the recorded occupation code is",
                  "strength": evidence_strength(_num(row.get("coding_tail_p"))), "code": L.clean(row.get("observed_value")),
                  "observed": f"Recorded occupation code: {L.clean(row.get('observed_value'))}",
                  "comparison": f"Among {L.count(reference)} {natural_group(values_json.get('values', {}))} with a valid occupation code, "
                                f"{L.count(count)} have this code.",
                  "facts": [{"label": "Comparable people with this code", "value": f"{L.count(count)} of {L.count(reference)}"}],
                  "meaning": "An occupation code that is rare for the person's activity status and industry can be a coding slip or simply an uncommon job.",
                  "technical": {k: row.get(k) for k in ("coding_tail_p", "smoothed_probability", "conditional_frequency", "smoothing_method", "smoothing_parameters", "method_version")}}
        evidence.append(coding)
    group = None
    group_rows = pattern_rows(dirs["pattern"], case) if dirs.get("pattern") else []
    if group_rows or _num(case.get("fsu_q_value")) is not None:
        items = [pattern_item(r) for r in group_rows]
        notable = bool(case.get("fsu_notable"))
        group = {"id": "pattern", "source": "pattern", "level": "group", "title": f"FSU {case.get('fsu')} as a whole",
                 "strength": {"level": "high" if notable else "low", "label": "FSU differs from comparable FSUs" if notable else "FSU does not stand out",
                              "q_value": _num(case.get("fsu_q_value"))},
                 "observed": L.clean(case.get("fsu_statement")) or "", "items": [i for i in items if i["notable"]][:4] or items[:1],
                 "meaning": GROUP_SENTENCE, "notable": notable,
                 "technical": {"fsu_q_value": case.get("fsu_q_value"), "method": "Cauchy combination of the FSU's checks, Benjamini-Hochberg across FSUs"}}
    unavailable = _unavailable(case, values, coding, household_case)
    checks = _checks(case, rules, value_sections, coding, group)
    importance = _importance(case)
    lanes = [x for x in (L.clean(case.get("lanes")) or "").split(",") if x]
    return {
        "method": "lanes", "details_available": True,
        "record": _record(case, person),
        "headline": _headline(case, rules, value_sections, coding),
        "queue": {"tier": case.get("tier"), "band_label": L.PRIORITY_BANDS.get(L.clean(case.get("priority_band")), case.get("priority_band")),
                  "reason": case.get("tier_reason"), "lanes": [{"code": x, "label": L.LANES.get(x, x)} for x in lanes],
                  "position": case.get("queue_position")},
        "evidence": evidence, "group": group, "unavailable": unavailable, "checks": checks, "importance": importance,
        "caveat": "The system has found something rare for comparable people, or a documented rule that is not met. It has not found the record to be incorrect. Only your review can decide that.",
        "source_runs": {k: (str(v.name) if v else None) for k, v in dirs.items()},
    }


def _record(case: dict[str, Any], person: dict[str, Any]) -> dict[str, Any]:
    household_case = case.get("case_level") == "HOUSEHOLD"
    key_parts = str(person.get("record_key") or "").split("|")
    title = [f"FSU {case.get('fsu')}", f"Household {person.get('household') or (key_parts[-1] if key_parts else '—')}"]
    if not household_case and person.get("person"):
        title.append(f"Person {person['person']}")
    location = [{"label": "State/UT", "value": L.state_name(case.get("state"))}, {"label": "District code", "value": L.clean(case.get("district")) or person.get("district") or "—"},
                {"label": "Sector", "value": L.sector_name(case.get("sector"))}, {"label": "Stratum", "value": L.clean(case.get("stratum")) or "—"},
                {"label": "FSU", "value": L.clean(case.get("fsu")) or "—"}]
    survey = [{"label": "Survey round", "value": f"PLFS {L.clean(case.get('release')).replace('_', '–')}"},
              {"label": "Schedule", "value": "First visit" if case.get("observation_type") == "first_visit" else "Revisit"},
              {"label": "Month" if L.clean(case.get("month")) else "Quarter", "value": L.clean(case.get("month")) or L.clean(case.get("quarter")) or "—"}]
    return {"title": " · ".join(title), "level": "household" if household_case else "person", "record_key": person.get("record_key"),
            "location": location, "survey": survey, "person": person.get("facts", [])}


def _headline(case, rules, value_sections, coding) -> str:
    parts = []
    if rules:
        parts.append("a documented questionnaire rule is not met")
    lead = next((s for s in value_sections if s["lead"] and s["strength"]["level"] in ("very", "high", "some")), None)
    if lead:
        parts.append(f"the reported {L.VARIABLES.get(lead['variable'], {}).get('short', 'value')} ({lead['observed'].rsplit(': ', 1)[-1]}) is {lead['strength']['plain']}")
    if coding and coding["strength"]["level"] in ("very", "high", "some"):
        parts.append("the occupation code is rare for comparable people")
    if not parts:
        return "No check finds this record unusual; it is shown for completeness."
    return "This case is in the list because " + (parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]) + "."


def _unavailable(case, values, coding, household_case) -> list[dict[str, str]]:
    if household_case:
        return [{"source": "value", "title": "Value and coding checks", "text": "This is a household-level case: only household rules apply."}]
    missing = []
    by_variable = {L.clean(r.get("target_variable")): r for r in values}
    applicable = [v for v, r in by_variable.items() if r.get("applicable")]
    if not applicable:
        missing.append({"source": "value", "title": "Value checks", "text": "No earnings, wage or hours item applies to this person's activity status, so no value could be compared."})
    for variable in applicable:
        row = by_variable[variable]
        short = L.VARIABLES.get(variable, {}).get("short", variable)
        if _num(row.get("p_history")) is None:
            text = ("January 2025 is the first month of the redesigned survey; there is no comparable earlier period."
                    if L.clean(case.get("design_period")) == "post_2025" and L.clean(case.get("month")) in ("1", "1.0")
                    else f"No earlier period with enough comparable records for {short}.")
            missing.append({"source": "history", "title": f"Earlier periods ({short})", "text": text})
        if _num(row.get("p_current")) is None:
            missing.append({"source": "current", "title": f"Similar people now ({short})", "text": f"Fewer than 30 comparable records for {short}."})
    if coding is None:
        missing.append({"source": "coding", "title": "Occupation code check", "text": "No valid occupation code with enough comparable records."})
    if L.clean(case.get("pattern_status")) != "ASSESSABLE":
        missing.append({"source": "pattern", "title": "FSU pattern", "text": "No FSU-level check could be made for this FSU."})
    missing.append({"source": "related", "title": "Related surveys", "text": "Not available: no related-survey data has been supplied (needs HSD approval)."})
    return missing


def _checks(case, rules, value_sections, coding, group) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(level: str, text: str, detail: str = "", source: str = "") -> None:
        if all(c["text"] != text for c in checks):
            checks.append({"level": level, "text": text, "detail": detail, "source": source})

    for rule in rules:
        add("household" if rule.get("level") == "household" else "record", f"Check the schedule for rule {L.clean(rule.get('rule_id'))}.",
            f"{L.clean(rule.get('message'))} Recorded: " + ", ".join(f"{k} = {v}" for k, v in _json(rule.get("observed_values"), {}).items()), "rules")
    for section in value_sections:
        if section["strength"]["level"] not in ("very", "high", "some"):
            continue
        add("record", f"Confirm the {L.variable_label(section['variable']).lower()}: {section['observed'].rsplit(': ', 1)[-1]}.",
            " ".join(section["hints"]) or "Compare it with the filled-in schedule and the person's other answers (activity, occupation, hours).", "value")
        for hint in section["hints"]:
            add("record", hint, "", "value")
    if coding and coding["strength"]["level"] in ("very", "high", "some"):
        add("record", f"Check that occupation code {coding['code']} matches the work the person described.", coding["comparison"], "coding")
    if group and group.get("notable"):
        add("group", "For the FSU as a whole: look at how its interviews were conducted and recorded.", GROUP_SENTENCE, "pattern")
    return checks


def _importance(case) -> dict[str, Any]:
    impact = _num(case.get("impact_se"))
    variable = L.clean(case.get("value_lead_variable"))
    short = L.VARIABLES.get(variable, {}).get("short", "value")
    if impact is None:
        plain = "The effect on published estimates could not be calculated for this case (no applicable value with an expected value and survey weight)."
    else:
        plain = (f"On its own, replacing this {short} by the typical value would move the average {short} of its State/UT and sector for this period by "
                 f"{impact:.2f} standard errors of that estimate.")
    return {"band": case.get("priority_band"), "band_label": L.PRIORITY_BANDS.get(L.clean(case.get("priority_band")), case.get("priority_band")),
            "summary": case.get("tier_reason") or L.PRIORITY_BANDS.get(L.clean(case.get("priority_band")), ""), "plain": plain,
            "impact_se": impact, "position": case.get("queue_position"),
            "explanation": ("Cases are placed in 'Check now' or 'Check if time' by how rare the evidence is, within the batch's review budget. "
                            "Within a group, cases that would move published estimates most come first. FSU patterns never move a case."),
            "limitation": "The effect uses the typical value as a stand-in for the correct value; it orders the review and is not an official estimate."}
