"""Controlled-injection evaluation of the V2 platform (plan §12; protocol in evaluation/PROTOCOL.md).

    python -m evaluation.run --release 2024 --seeds 1-5 --fold A          # development
    python -m evaluation.run --release 2024 --seeds 6-20 --fold B         # confirmation (after the design is frozen)
    python -m evaluation.run --verify evaluation/results/protocol_v1/2024_A_seed1.json

Design
* State folds A/B: States/UTs sorted by size and assigned alternately
  (A, B, B, A, ...), so folds are balanced; every comparison in the platform
  is State-bounded, so folds are independent.
* One full pipeline run per (release, fold, seed) on an injected copy; every
  stage artefact is kept under evaluation/runs/<protocol>/<release>_<fold>_seed<k>/
  so every number can be re-derived (audit N3).
* Rankings compared (§8.4, §12.2): A0 = the superseded V2.0 priority
  reconstructed from the same stage outputs; each lane alone (current peers,
  earlier periods, expected-value model, coding); B = references only;
  D = the full value lane; E6 = the operational queue order.
* Headline metrics on the CAPI-pass population; rule findings scored separately.

Nothing in this module has been run for the current method at the time of
writing; see docs/10_10_IMPROVEMENT_PLAN.md (implementation status).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fusion.legacy import LegacyParameters, legacy_domain_share_influence, legacy_fuse
from fusion.calibration import percentile_midrank
from pipeline.run import Inputs, code_version, run_pipeline

from .inject import CATALOGUE_VERSION, InjectionPlan, write_injected
from .metrics import capi_pass_mask, paired_bootstrap_difference, ranking_metrics, rule_list_metrics

LOGGER = logging.getLogger("MoSPI.evaluation")
PROTOCOL = "protocol_v1"
SETUP = {
    "2024": {"source": "preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet", "months": None, "inject_months": None,
             "history": "preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet", "history_release": "2023_24"},
    "2025": {"source": "preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet", "months": None,
             "inject_months": tuple(range(2, 13)), "history": None},
}


def state_folds(source: Path) -> dict[str, tuple[str, ...]]:
    from survey_rules.schema import read_parquet
    sizes = read_parquet(source, columns=["MoSPI_state"])["MoSPI_state"].astype(str).value_counts().sort_values(ascending=False)
    folds = {"A": [], "B": []}
    for position, state in enumerate(sizes.index):
        folds["A" if position % 4 in (0, 3) else "B"].append(state)
    return {k: tuple(sorted(v)) for k, v in folds.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _neglog(p: pd.Series) -> pd.Series:
    return -np.log10(pd.to_numeric(p, errors="coerce").clip(lower=1e-300))


def _per_record(values: pd.DataFrame, column: str) -> pd.Series:
    """Strongest (smallest) tail probability over a record's variables, as -log10 p (higher = stronger)."""
    return _neglog(values.groupby("source_observation_id")[column].min())


def rankings(fusion_dir: Path, stage_dirs: dict[str, Path], prepared: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Scores per record for every compared design, from stored artefacts only; and the rule-breach flag."""
    cases = pd.read_parquet(fusion_dir / "fused_cases.parquet")
    persons = cases.loc[cases["case_level"].eq("PERSON")].set_index("source_observation_id")
    values = pd.read_parquet(fusion_dir / "value_evidence.parquet")
    scores = pd.DataFrame(index=persons.index)
    scores["E1_current_peers"] = _per_record(values, "p_current")
    scores["E2_earlier_periods"] = _per_record(values, "p_history")
    scores["E4_expected_value_model"] = _per_record(values, "p_model")
    scores["B_references_only"] = _per_record(values, "p_reference")
    scores["D_value_lane"] = _neglog(persons["value_p"])
    scores["E3_coding_lane"] = _neglog(persons["coding_p"])
    scores["E6_operational_queue"] = -persons["queue_position"].astype(float)
    scores["A0_superseded_v2_0"] = _legacy_scores(stage_dirs, prepared, persons.index)
    rule_breach = persons["rule_error_count"].gt(0)
    return scores.reindex(persons.index), rule_breach


def _legacy_scores(stage_dirs: dict[str, Path], prepared: Path, ids: pd.Index) -> pd.Series:
    """The V2.0 priority (risk x influence) rebuilt from the same stage outputs, for baseline A0."""
    stat = pd.read_parquet(stage_dirs["statistical"] / "statistical_evidence.parquet",
                           columns=["source_observation_id", "target_variable", "statistical_assessability_status", "percentile_position", "observed_value", "peer_median", "target_applicability"])
    usable = stat["statistical_assessability_status"].eq("ASSESSABLE")
    frame = pd.DataFrame(index=ids)
    frame["statistical_raw_score"] = ((stat.loc[usable, "percentile_position"] - .5).abs() * 2).groupby(stat.loc[usable, "source_observation_id"]).max()
    hist = pd.read_parquet(stage_dirs["historical"] / "historical_record_evidence.parquet", columns=["source_observation_id", "assessability_status", "historical_score"])
    frame["historical_raw_score"] = hist.loc[hist.assessability_status.eq("ASSESSABLE")].groupby("source_observation_id").historical_score.max()
    context = pd.read_parquet(stage_dirs["contextual"] / "contextual_evidence.parquet", columns=["source_observation_id", "contextual_assessability_status", "surprisal"])
    frame["contextual_raw_score"] = context.loc[context.contextual_assessability_status.eq("ASSESSABLE")].set_index("source_observation_id").surprisal
    ranks = []
    for name in ("isolation_forest_evidence.parquet", "lof_evidence.parquet", "conditional_model_evidence.parquet"):
        path = stage_dirs["ml"] / name
        if path.is_file():
            part = pd.read_parquet(path, columns=["source_observation_id", "assessability_status", "evidence_rank"])
            ranks.append(part.loc[part.assessability_status.eq("ASSESSABLE")])
    if ranks:
        frame["ml_raw_score"] = pd.concat(ranks).groupby("source_observation_id").evidence_rank.max()
    weights = pd.read_parquet(stage_dirs["fusion"] / "fused_cases.parquet", columns=["source_observation_id", "final_weight", "release", "period_index", "state", "sector"]).set_index("source_observation_id")
    shares = stat.merge(weights, left_on="source_observation_id", right_index=True, how="left")
    shares["applicable"] = shares["target_applicability"].eq("APPLICABLE")
    shares["peer_median"] = shares["peer_median"].where(usable)
    shares["domain"] = shares["release"].astype(str) + "|" + shares["period_index"].astype(str) + "|" + shares["state"].astype(str) + "|" + shares["sector"].astype(str)
    shares["local"] = legacy_domain_share_influence(shares)
    frame["influence_score"] = percentile_midrank(shares.groupby("source_observation_id")["local"].max().reindex(ids), zero_is_no_evidence=True)
    frame["rule_error_count"] = 0
    return legacy_fuse(frame, LegacyParameters())["priority_score"]


def evaluate(release: str, fold: str, seed: int, root: Path) -> dict:
    setup = SETUP[release]
    started = time.perf_counter()
    folds = state_folds(Path(setup["source"]))
    states = folds[fold]
    plan = InjectionPlan(seed=20261003 + seed)
    work = root / PROTOCOL / f"{release}_{fold}_seed{seed}"
    prepared_dir = work / "preprocessing" / "runs" / f"eval_{release}_{fold}_seed{seed}"
    if not prepared_dir.exists():
        write_injected(Path(setup["source"]), prepared_dir, release, plan, states=states, months=setup["months"], inject_months=setup["inject_months"])
    prepared = prepared_dir / "prepared_persons.parquet"
    history = []
    if setup["history"]:
        history_dir = work / "preprocessing" / "runs" / f"eval_{setup['history_release']}_{fold}_clean"
        if not history_dir.exists():
            write_injected(Path(setup["history"]), history_dir, setup["history_release"], plan, states=states, inject_errors=False)
        history = [history_dir / "prepared_persons.parquet"]
    result = run_pipeline(Inputs(prepared, history=history), "eval", roots=work)
    stage_dirs = {k: Path(v) for k, v in result.items() if k not in ("timing_seconds", "qa")}
    labels = pd.read_parquet(prepared_dir / "injection_labels.parquet")
    record_labels = labels[labels.level.eq("record")].drop_duplicates("source_observation_id").set_index("source_observation_id")
    scores, rule_breach = rankings(stage_dirs["fusion"], stage_dirs, prepared)
    error_type = scores.index.to_series().map(record_labels["error_type"])
    positive_all = error_type.notna()
    capi = capi_pass_mask(rule_breach, error_type)
    ids = scores.index.to_series()
    cases = pd.read_parquet(stage_dirs["fusion"] / "fused_cases.parquet").set_index("source_observation_id")
    subgroups = {"state": cases["state"].reindex(scores.index), "sector": cases["sector"].reindex(scores.index)}
    budget = int(json.loads((stage_dirs["fusion"] / "run_metadata.json").read_text())["queue"]["budget_cases"])
    designs = {name: ranking_metrics(scores.loc[capi, name], positive_all[capi], ids[capi], error_type[capi], budget=budget,
                                     subgroups={k: v[capi] for k, v in subgroups.items()}) for name in scores.columns}
    comparisons = {f"{a}_minus_{b}": paired_bootstrap_difference(scores.loc[capi, a], scores.loc[capi, b], positive_all[capi], ids[capi], seed=seed)
                   for a, b in (("D_value_lane", "A0_superseded_v2_0"), ("D_value_lane", "E2_earlier_periods"), ("D_value_lane", "B_references_only"),
                                ("E6_operational_queue", "A0_superseded_v2_0"))}
    groups = pd.read_parquet(stage_dirs["fusion"] / "group_priorities.parquet")
    groups["key"] = groups["state"].astype(str) + "|" + groups["sector"].astype(str) + "|" + groups["fsu"].astype(str)
    alerts = groups["group_priority_band"].isin(["HIGH", "MEDIUM"])
    group_eval = {}
    for kind in ("fsu_fabrication", "copied_household", "fsu_short_interviews", "fsu_one_day"):
        injected = set(labels.loc[labels.level.eq("group") & labels.error_type.eq(kind), "source_observation_id"])
        flagged = groups["key"].isin(injected)
        group_eval[kind] = {"injected_fsus": int(len(injected)), "recall": float((alerts & flagged).sum() / max(1, len(injected)))}
    clean = ~groups["key"].isin(set(labels.loc[labels.level.eq("group"), "source_observation_id"]))
    group_eval["clean_fsu_alert_rate"] = float((alerts & clean).sum() / max(1, clean.sum()))
    report = {
        "protocol": PROTOCOL, "release": release, "fold": fold, "states": list(states), "seed": seed, "plan": plan.__dict__,
        "catalogue_version": CATALOGUE_VERSION, "code_version": code_version(),
        "input_sha256": {"prepared_source": _sha256(Path(setup["source"])), "injected": _sha256(prepared), "labels": _sha256(prepared_dir / "injection_labels.parquet")},
        "artefacts": {k: str(v) for k, v in stage_dirs.items()}, "records": int(len(scores)), "capi_pass_records": int(capi.sum()),
        "injected_by_type": labels.error_type.value_counts().to_dict(), "rule_list": rule_list_metrics(rule_breach, error_type),
        "designs_capi_pass": designs, "paired_comparisons_recall_at_1pct": comparisons, "group_level": group_eval,
        "pipeline_timing_seconds": result["timing_seconds"], "runtime_seconds": round(time.perf_counter() - started, 1),
    }
    results = Path(__file__).parent / "results" / PROTOCOL
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{release}_{fold}_seed{seed}.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    return report


def verify(result_path: Path) -> bool:
    """Recompute every design metric from the stored artefacts and compare with the stored JSON."""
    stored = json.loads(Path(result_path).read_text(encoding="utf-8"))
    stage_dirs = {k: Path(v) for k, v in stored["artefacts"].items()}
    prepared = Path(stored["artefacts"]["fusion"]).parents[2] / "preprocessing" / "runs"
    prepared_dir = next(prepared.glob(f"eval_{stored['release']}_{stored['fold']}_seed{stored['seed']}"))
    labels = pd.read_parquet(prepared_dir / "injection_labels.parquet")
    record_labels = labels[labels.level.eq("record")].drop_duplicates("source_observation_id").set_index("source_observation_id")
    scores, rule_breach = rankings(stage_dirs["fusion"], stage_dirs, prepared_dir / "prepared_persons.parquet")
    error_type = scores.index.to_series().map(record_labels["error_type"])
    capi = capi_pass_mask(rule_breach, error_type)
    ok = True
    for name, metrics in stored["designs_capi_pass"].items():
        again = ranking_metrics(scores.loc[capi, name], error_type.notna()[capi], scores.index.to_series()[capi], error_type[capi])
        for share in ("at_0.01", "at_0.05"):
            if share in metrics and abs(again[share]["recall"] - metrics[share]["recall"]) > 1e-12:
                ok = False
                print(f"MISMATCH {name} {share}: stored {metrics[share]['recall']} recomputed {again[share]['recall']}")
    print("VERIFIED" if ok else "NOT VERIFIED")
    return ok


def _seeds(text: str) -> list[int]:
    if "-" in text:
        low, high = map(int, text.split("-"))
        return list(range(low, high + 1))
    return [int(x) for x in text.split(",")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run (or verify) the controlled-injection evaluation.")
    parser.add_argument("--release", choices=sorted(SETUP))
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--fold", choices=("A", "B"), default="A")
    parser.add_argument("--root", type=Path, default=Path("evaluation/runs"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.verify:
        return 0 if verify(args.verify) else 1
    if not args.release:
        parser.error("--release is required unless --verify is given")
    for seed in _seeds(args.seeds):
        report = evaluate(args.release, args.fold, seed, args.root)
        print(json.dumps({k: report[k] for k in ("release", "fold", "seed", "records", "capi_pass_records", "runtime_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
