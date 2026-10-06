"""Controlled-injection evaluation of MoSPI (E0-E7).

    python -m evaluation.run --release 2024
    python -m evaluation.run --release 2025

Design (deliberately small; see evaluation/README.md):
* State subset: every comparison in MoSPI is bounded by State/UT, so a State
  subset keeps comparison groups identical to the full-data groups for those
  States at a fraction of the cost.
* One full pipeline run on the injected copy per release; E0-E7 are then
  recomputed from the stored source scores with different source weights.
* Injected labels are the only known positives.  Unlabelled records may still
  contain genuine errors, so precision is a lower bound and the false-positive
  rate an upper bound.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from fusion.config import FusionParameters
from fusion.engine import FusionEngine, RunConfig as FusionConfig
from peer_groups.engine import PeerGroupEngine, RunConfig as PeerConfig
from pipeline.run import Inputs, run_pipeline

from .inject import RECORD_TYPES, InjectionPlan, write_injected

LOGGER = logging.getLogger("MoSPI.evaluation")
STATES = ("10", "27", "33", "18", "03", "07")  # Bihar, Maharashtra, Tamil Nadu, Assam, Punjab, Delhi
SETUP = {
    "2024": {"source": "preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet", "months": None, "inject_months": None,
             "history": "preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet", "history_release": "2023_24"},
    "2025": {"source": "preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet", "months": (1, 2, 3, 4, 5, 6),
             "inject_months": (2, 3, 4, 5, 6), "history": None},
}
SOURCES = ("statistical", "contextual", "ml", "historical")
EXPERIMENTS: dict[str, dict] = {
    "E0 rules only": {"rules": True, "weights": {}},
    "E1 statistical": {"rules": False, "weights": {"statistical": 1}},
    "E2 contextual": {"rules": False, "weights": {"contextual": 1}},
    "E3 machine learning": {"rules": False, "weights": {"ml": 1}},
    "E3h historical": {"rules": False, "weights": {"historical": 1}},
    "E4 statistical + contextual": {"rules": False, "weights": {"statistical": .3, "contextual": .2}},
    "E5 statistical + contextual + ML": {"rules": False, "weights": {"statistical": .3, "contextual": .2, "ml": .25}},
    "E6 full hybrid": {"rules": True, "weights": {"statistical": .3, "contextual": .2, "ml": .25, "historical": .25}},
    "E6 full hybrid, no override": {"rules": True, "weights": {"statistical": .3, "contextual": .2, "ml": .25, "historical": .25}, "override": 1.0},
}
for removed in (*SOURCES, "rules"):
    weights = {"statistical": .3, "contextual": .2, "ml": .25, "historical": .25}
    if removed in weights:
        weights.pop(removed)
    EXPERIMENTS[f"E7 full minus {removed}"] = {"rules": removed != "rules", "weights": weights}


def _score(cases: pd.DataFrame, experiment: dict) -> pd.Series:
    weights = {s: float(experiment["weights"].get(s, 0.0)) for s in SOURCES}
    if sum(weights.values()) == 0:
        risk = pd.Series(0.0, index=cases.index)
    else:
        engine = FusionEngine(FusionConfig("p", "s", "c", "m", "o", parameters=FusionParameters(source_weights=weights, override_rank_threshold=experiment.get("override", .995))))
        frame = cases[[c for c in cases if c.endswith(("_raw_score", "_status"))]].copy()
        for source in SOURCES:
            if weights[source] == 0:
                frame[f"{source}_raw_score"] = np.nan
        frame["influence_score"] = 1.0
        frame["rule_error_count"] = 0
        risk = engine.fuse(frame)["risk_score"].astype(float).fillna(-1.0)
    if experiment["rules"]:
        risk = risk.where(~cases["rule_error_count"].gt(0), 2.0)
    return risk


def _ranked(score: pd.Series, ids: pd.Series) -> pd.Series:
    """Deterministic order: score descending, ties broken by a stable hash (never by the label)."""
    tie = pd.util.hash_pandas_object(ids, index=False).astype("uint64")
    order = pd.DataFrame({"s": score.to_numpy(), "t": tie.to_numpy()}, index=score.index).sort_values(["s", "t"], ascending=[False, True], kind="mergesort")
    return pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(score.index)


def _metrics(score: pd.Series, positive: pd.Series, ids: pd.Series, types: pd.Series, extra: dict[str, pd.Series]) -> dict:
    rank = _ranked(score, ids)
    n, p = len(score), int(positive.sum())
    out = {"records": n, "injected": p}
    if p == 0 or p == n:
        return out
    out["average_precision"] = float(average_precision_score(positive, score))
    out["roc_auc"] = float(roc_auc_score(positive, score))
    out["chance_average_precision"] = p / n
    for label, k in (("1pct", max(1, round(.01 * n))), ("5pct", max(1, round(.05 * n))), ("k_eq_injected", p)):
        top = rank.le(k)
        tp = int((top & positive).sum())
        precision, recall = tp / k, tp / p
        f05 = (1.25 * precision * recall / (.25 * precision + recall)) if precision + recall else 0.0
        out[f"at_{label}"] = {"k": int(k), "precision": precision, "recall": recall, "f0_5": f05, "false_positive_rate": (k - tp) / (n - p)}
    top1 = rank.le(max(1, round(.01 * n)))
    top5 = rank.le(max(1, round(.05 * n)))
    out["recall_by_error_type_at_1pct"] = {t: float(top1[types.eq(t)].mean()) for t in sorted(types.dropna().unique())}
    out["recall_by_error_type_at_5pct"] = {t: float(top5[types.eq(t)].mean()) for t in sorted(types.dropna().unique())}
    for name, groups in extra.items():
        out[f"recall_at_5pct_by_{name}"] = {str(g): {"recall": float(top5[positive & groups.eq(g)].mean()) if (positive & groups.eq(g)).any() else None,
                                                     "injected": int((positive & groups.eq(g)).sum()), "records": int(groups.eq(g).sum())}
                                            for g in sorted(groups.dropna().unique())}
    return out


def evaluate(release: str, root: Path) -> dict:
    setup = SETUP[release]
    work = root / f"{release}_injection"
    plan = InjectionPlan()
    started = time.perf_counter()
    prepared_dir = work / "prepared" / f"eval_{release}_injected"
    if not prepared_dir.exists():
        write_injected(Path(setup["source"]), prepared_dir, release, plan, states=STATES, months=setup["months"], inject_months=setup["inject_months"])
    prepared = prepared_dir / "prepared_persons.parquet"
    history = []
    if setup["history"]:
        history_dir = work / "prepared" / f"eval_{setup['history_release']}_clean"
        if not history_dir.exists():
            write_injected(Path(setup["history"]), history_dir, setup["history_release"], plan, states=STATES, inject_errors=False)
        history = [history_dir / "prepared_persons.parquet"]
    peer_root = work / "peer_groups" / "runs"
    peer = next(peer_root.glob("*_eval"), None) if peer_root.exists() else None
    if peer is None:
        peer = PeerGroupEngine(PeerConfig(prepared, peer_root, run_id="eval")).run()
    result = run_pipeline(Inputs(prepared, peer, None, history), "eval", roots=work, contextual_rebuild=True)
    fusion_dir = Path(result["fusion"])
    cases = pd.read_parquet(fusion_dir / "fused_cases.parquet")
    labels = pd.read_parquet(prepared_dir / "injection_labels.parquet")
    record_labels = labels[labels.level.eq("record")].drop_duplicates("source_observation_id")
    types = cases["source_observation_id"].map(record_labels.set_index("source_observation_id")["error_type"])
    positive = types.notna()
    extra = {"sector": cases["sector"].map({"1": "rural", "2": "urban"}), "state": cases["state"]}
    experiments = {name: _metrics(_score(cases, spec), positive, cases["source_observation_id"], types, extra) for name, spec in EXPERIMENTS.items()}
    priority = cases["priority_score"].astype(float).fillna(-1.0)
    experiments["E6 operational queue (risk x influence)"] = _metrics(priority, positive, cases["source_observation_id"], types, extra)
    # Group level: FSU fabrication must be found by FSU alerts, and must NOT lift members' record risk.
    groups = pd.read_parquet(fusion_dir / "group_priorities.parquet")
    groups["key"] = groups["state"].astype(str) + "|" + groups["sector"].astype(str) + "|" + groups["fsu"].astype(str)
    fabricated = set(labels.loc[labels.level.eq("group"), "source_observation_id"])
    groups["fabricated"] = groups["key"].isin(fabricated)
    notable = groups["group_priority_band"].isin(["HIGH", "MEDIUM"])
    member = (cases["state"].astype(str) + "|" + cases["sector"].astype(str) + "|" + cases["fsu"].astype(str)).isin(fabricated)
    group_eval = {
        "fabricated_fsus": int(groups.fabricated.sum()), "fsus_assessed": int(groups.group_priority_score.notna().sum()),
        "recall_notable_q_lt_0_05": float((notable & groups.fabricated).sum() / max(1, groups.fabricated.sum())),
        "precision_among_notable": float((notable & groups.fabricated).sum() / max(1, notable.sum())),
        "notable_fsus": int(notable.sum()), "false_positive_rate_clean_fsus": float((notable & ~groups.fabricated).sum() / max(1, (~groups.fabricated).sum())),
        "fabricated_in_top_5pct_of_group_queue": float((groups.group_priority_rank.ge(.95) & groups.fabricated).sum() / max(1, groups.fabricated.sum())),
        "member_mean_risk_rank": float(cases.loc[member & ~positive, "risk_score"].rank(pct=True).mean()) if member.any() else None,
        "member_vs_all_mean_risk": {"fabricated_fsu_members": float(cases.loc[member, "risk_score"].mean()), "all_records": float(cases["risk_score"].mean())},
    }
    report = {"release": release, "states": list(STATES), "months": setup["months"], "plan": plan.__dict__,
              "injected_by_type": labels.error_type.value_counts().to_dict(), "records": int(len(cases)),
              "pipeline_timing_seconds": result["timing_seconds"], "fusion_run": str(fusion_dir), "experiments": experiments,
              "group_level": group_eval, "runtime_seconds": round(time.perf_counter() - started, 1)}
    results = Path(__file__).parent / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{release}.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the controlled-injection evaluation for one release.")
    parser.add_argument("--release", choices=sorted(SETUP), required=True)
    parser.add_argument("--root", type=Path, default=Path("evaluation/runs"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    report = evaluate(args.release, args.root)
    print(json.dumps({k: report[k] for k in ("release", "records", "injected_by_type", "runtime_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
