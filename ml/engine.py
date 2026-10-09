"""Orchestrate separate, provenance-checked PLFS ML evidence components."""
from __future__ import annotations

import json
import time
import uuid
import gc
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from peer_groups.config import COMPATIBLE_SPECIFICATION_VERSIONS
from survey_rules import period_index
from survey_rules.schema import read_parquet

from .conditional_models import run_conditional_models
from .config import LOF_REFERENCE_TARGET, ML_METHOD_VERSION, Parameters, READY_STATUS, SOURCE_FIELDS
from .isolation_forest import run_isolation_forest
from .lof import run_peer_lof
from .reporting import utc_now, write_json, write_markdown
from .similarity import run_similarity


class MLFailure(RuntimeError):
    """Unsafe input provenance, contract, or reference population."""


@dataclass(frozen=True)
class RunConfig:
    prepared_person_path: Path
    peer_group_run_path: Path
    output_root: Path
    run_id: str | None = None
    parameters: Parameters = Parameters()
    # Earlier prepared releases of the same design period: the conditional
    # models are trained on strictly earlier periods (plan W3.5).
    history: tuple[Path, ...] = ()


def _clean(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


class MLEngine:
    def __init__(self, config: RunConfig) -> None:
        self.config = replace(config, prepared_person_path=Path(config.prepared_person_path), peer_group_run_path=Path(config.peer_group_run_path),
                              output_root=Path(config.output_root), history=tuple(Path(p) for p in config.history))

    @staticmethod
    def _metadata(path: Path) -> dict[str, object]:
        if not path.is_file():
            raise MLFailure(f"Required metadata is absent: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise MLFailure(f"Invalid JSON metadata: {path}") from error

    def _validate(self) -> tuple[dict[str, object], dict[str, object]]:
        if not self.config.prepared_person_path.is_file():
            raise MLFailure(f"Prepared person input does not exist: {self.config.prepared_person_path}")
        for name in ("peer_group_assignments.parquet", "peer_group_references.parquet", "run_metadata.json"):
            if not (self.config.peer_group_run_path / name).is_file():
                raise MLFailure(f"Peer-group run lacks required {name}")
        prepared = self._metadata(self.config.prepared_person_path.parent / "run_metadata.json")
        peer = self._metadata(self.config.peer_group_run_path / "run_metadata.json")
        for field in ("release", "observation", "design_period"):
            if str(prepared.get(field)) != str(peer.get(field)):
                raise MLFailure(f"Prepared and peer metadata disagree on {field}")
        if str(prepared.get("run_id", "")) != str(peer.get("input_preprocessing_run_id", "")):
            raise MLFailure("Peer-group run was not built from this prepared-person run")
        if (str(prepared.get("release")), str(prepared.get("observation"))) not in SOURCE_FIELDS:
            raise MLFailure("No approved ML source-field mapping for prepared provenance")
        return prepared, peer

    def _base(self, prepared: dict[str, object], path: Path | None = None) -> pd.DataFrame:
        path = path or self.config.prepared_person_path
        source = SOURCE_FIELDS[(str(prepared["release"]), str(prepared["observation"]))]
        required = {
            "MoSPI_record_key", "MoSPI_source_row", "MoSPI_release", "MoSPI_observation", "MoSPI_design_period", "MoSPI_visit",
            "MoSPI_state", "MoSPI_sector", "MoSPI_fsu", "MoSPI_prepared_status", source.serial, source.age, source.sex,
            source.education, source.cws_status, source.earnings_salaried, source.earnings_self_employed,
        }
        for optional in (source.occupation, source.industry, source.day7_hours, source.day7_activity1_status, source.day7_activity1_industry, source.casual_wage):
            if optional:
                required.add(optional)
        required.add("MoSPI_quarter")
        if str(prepared["release"]) == "2025":
            required.add("MoSPI_month")
        try:
            frame = read_parquet(path, columns=sorted(required))
        except Exception as error:
            raise MLFailure(f"Could not read required prepared ML columns: {error}") from error
        missing = required - set(frame.columns)
        if missing:
            raise MLFailure(f"Prepared input lacks ML contract columns: {sorted(missing)}")
        for field, expected in (("MoSPI_release", prepared["release"]), ("MoSPI_observation", prepared["observation"]), ("MoSPI_design_period", prepared["design_period"])):
            if set(_clean(frame[field]).unique()) != {str(expected)}:
                raise MLFailure(f"Prepared input has mixed or unexpected {field}")
        serial = _clean(frame[source.serial])
        fallback = _clean(frame["MoSPI_source_row"])
        source_id = _clean(frame["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), fallback), sep="|person=")
        if source_id.duplicated().any():
            raise MLFailure("Prepared input cannot provide unique source observation IDs")
        result = pd.DataFrame({"source_observation_id": source_id, "record_id": _clean(frame["MoSPI_record_key"]), "release": _clean(frame["MoSPI_release"]), "observation_type": _clean(frame["MoSPI_observation"]), "design_period": _clean(frame["MoSPI_design_period"]), "visit": _clean(frame["MoSPI_visit"]), "month": _clean(frame["MoSPI_month"]) if "MoSPI_month" in frame else "", "state": _clean(frame["MoSPI_state"]), "sector": _clean(frame["MoSPI_sector"]), "fsu": _clean(frame["MoSPI_fsu"]), "preprocessing_run_id": str(prepared["run_id"]), "prepared_ready": _clean(frame["MoSPI_prepared_status"]).eq(READY_STATUS)})
        for name, column in (("age", source.age), ("sex", source.sex), ("education", source.education), ("cws_status", source.cws_status), ("earnings_salaried", source.earnings_salaried), ("earnings_self_employed", source.earnings_self_employed)):
            result[name] = _clean(frame[column])
        result["occupation"] = _clean(frame[source.occupation]) if source.occupation else ""
        result["industry"] = _clean(frame[source.industry]) if source.industry else ""
        result["day7_hours"] = _clean(frame[source.day7_hours]) if source.day7_hours else pd.NA
        result["occupation_major_group"] = result["occupation"].where(result["occupation"].str.fullmatch(r"\d{3}"), "").str.slice(0, 1)
        result["industry_division"] = result["industry"].where(result["industry"].str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2)
        result["day7_activity1_status"] = _clean(frame[source.day7_activity1_status]) if source.day7_activity1_status else ""
        day_industry = _clean(frame[source.day7_activity1_industry]) if source.day7_activity1_industry else pd.Series("", index=frame.index, dtype="string")
        valid_day_industry = day_industry.str.fullmatch(r"\d{1,2}")
        result["day7_activity1_industry"] = day_industry.where(valid_day_industry, "").str.zfill(2).where(valid_day_industry, "")
        result["casual_wage"] = _clean(frame[source.casual_wage]) if source.casual_wage else pd.NA
        quarter = _clean(frame["MoSPI_quarter"])
        month = _clean(frame["MoSPI_month"]) if "MoSPI_month" in frame else pd.Series("", index=frame.index, dtype="string")
        result["period_index"] = pd.array([period_index(str(prepared["release"]), q, m) for q, m in zip(quarter, month)], dtype="Int64")
        # Keep the large real-data working table bounded: these are low or
        # moderate-cardinality coded fields, not free text. Source/record IDs
        # intentionally stay as strings for traceability and stable hashing.
        for column in result.columns:
            if column not in {"source_observation_id", "record_id", "preprocessing_run_id", "prepared_ready", "period_index"}:
                result[column] = result[column].astype("category")
        return result

    def _history(self, prepared: dict[str, object], base: pd.DataFrame) -> pd.DataFrame:
        """Earlier periods of the same design period, one copy of each period (as in the historical layer)."""
        frames, self._history_runs = [], []
        for path in self.config.history:
            meta = self._metadata(path.parent / "run_metadata.json")
            if str(meta.get("design_period")) != str(prepared["design_period"]) or str(meta.get("observation")) != str(prepared["observation"]):
                raise MLFailure(f"History {path} is not the same design period and observation route; models never cross the January-2025 redesign.")
            if (str(meta.get("release")), str(meta.get("observation"))) not in SOURCE_FIELDS:
                raise MLFailure(f"No ML source-field mapping for history {path}")
            frames.append(self._base(meta, path))
            self._history_runs.append({"release": meta.get("release"), "run_id": meta.get("run_id")})
        taken: set[int] = set()
        parts = []
        for frame in [*frames, base]:   # earlier releases first; the target supplies only periods they lack
            periods = set(pd.to_numeric(frame["period_index"], errors="coerce").dropna().astype(int)) - taken
            parts.append(frame[pd.to_numeric(frame["period_index"], errors="coerce").isin(periods)])
            taken |= periods
        pool = pd.concat(parts, ignore_index=True)
        for column in pool.columns:
            if isinstance(pool[column].dtype, pd.CategoricalDtype):
                pool[column] = pool[column].astype("string")
        return pool

    def _lof_assignments(self, prepared: dict[str, object], peer: dict[str, object]) -> pd.DataFrame:
        columns = ["source_observation_id", "peer_group_id", "peer_group_size", "assessability_status", "not_assessable_reason", "reference_run_id", "specification_version", "release", "observation", "design_period", "visit", "month"]
        assigned = pd.read_parquet(self.config.peer_group_run_path / "peer_group_assignments.parquet", columns=columns, filters=[("target_variable", "=", LOF_REFERENCE_TARGET)])
        if assigned.empty or assigned["source_observation_id"].duplicated().any():
            raise MLFailure("Existing peer assignments lack one unique day7-hours assignment per source observation")
        for column, expected in (("release", prepared["release"]), ("observation", prepared["observation"]), ("design_period", prepared["design_period"])):
            if set(_clean(assigned[column]).unique()) != {str(expected)}:
                raise MLFailure(f"Peer assignments have mixed or mismatched {column}")
        if not assigned["reference_run_id"].astype(str).eq(str(prepared["run_id"])).all():
            raise MLFailure("LOF peer assignment provenance does not match preprocessing run")
        if str(peer.get("specification_version", "")) not in COMPATIBLE_SPECIFICATION_VERSIONS:
            raise MLFailure("Unexpected peer-group specification version")
        return assigned

    @staticmethod
    def _separate(base: pd.DataFrame, function, *args):
        outputs = []
        for _, subset in base.groupby(["release", "observation_type", "design_period", "visit", "month"], sort=True, dropna=False, observed=True):
            outputs.append(function(subset.copy(), *args))
        return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()

    @staticmethod
    def _summary(table: pd.DataFrame) -> dict[str, int]:
        assessable = int(table["assessability_status"].eq("ASSESSABLE").sum())
        return {"records": int(len(table)), "assessable": assessable, "not_assessable": int(len(table) - assessable)}

    @staticmethod
    def _parquet_table(table: pd.DataFrame) -> pa.Table:
        """Normalise category dictionaries before appending boundary batches."""
        for column in table.columns:
            if isinstance(table[column].dtype, pd.CategoricalDtype):
                table[column] = table[column].astype("string")
        return pa.Table.from_pandas(table, preserve_index=False)

    def _write_component(self, destination: Path, filename: str, builder, *, separated: bool) -> dict[str, int]:
        writer = None
        records = assessable = 0
        try:
            inputs = (
                (subset for _, subset in self._base_cache.groupby(["release", "observation_type", "design_period", "visit", "month"], sort=True, dropna=False, observed=True))
                if separated else (self._base_cache,)
            )
            for subset in inputs:
                table = builder(subset)
                table.sort_values("source_observation_id", kind="mergesort", inplace=True, ignore_index=True)
                records += len(table)
                assessable += int(table["assessability_status"].eq("ASSESSABLE").sum())
                arrow = self._parquet_table(table)
                if writer is None:
                    writer = pq.ParquetWriter(destination / filename, arrow.schema, compression="snappy")
                # Boundary batches can infer different types for the same column (e.g. a month with only whole values).
                writer.write_table(arrow.select(writer.schema.names).cast(writer.schema))
                del arrow, table, subset
                gc.collect()
        finally:
            if writer is not None:
                writer.close()
        return {"records": int(records), "assessable": int(assessable), "not_assessable": int(records - assessable)}

    def run(self) -> Path:
        started = time.perf_counter()
        prepared, peer = self._validate()
        base = self._base(prepared)
        history = self._history(prepared, base)
        assignments = self._lof_assignments(prepared, peer)
        run_id = self.config.run_id or str(uuid.uuid4())
        destination = self.config.output_root / f"{prepared['release']}_{prepared['observation']}_{run_id}"
        destination.mkdir(parents=True, exist_ok=False)
        self._base_cache = base
        registry: list[dict] = []

        def conditional(subset: pd.DataFrame) -> pd.DataFrame:
            table, entries = run_conditional_models(subset, self.config.parameters, history)
            registry.extend(entries)
            return table

        builders = {
            "conditional_model_evidence.parquet": (conditional, True),
            "similarity_evidence.parquet": (lambda subset: run_similarity(subset, self.config.parameters).assign(decision_path="INFORMATION_ONLY"), False),
        }
        if self.config.parameters.run_research_models:
            # Research comparison only: never read by fusion (plan W2.4).
            builders["isolation_forest_evidence.parquet"] = (lambda subset: run_isolation_forest(subset, self.config.parameters).assign(decision_path="RESEARCH_ONLY"), True)
            builders["lof_evidence.parquet"] = (lambda subset: run_peer_lof(subset, assignments, self.config.parameters).assign(decision_path="RESEARCH_ONLY"), False)
        summaries: dict[str, dict[str, int]] = {}
        component_names = {
            "isolation_forest_evidence.parquet": "isolation_forest", "lof_evidence.parquet": "peer_scoped_lof",
            "conditional_model_evidence.parquet": "conditional_models", "similarity_evidence.parquet": "similarity",
        }
        # Persist each component before building the next.  On real PLFS files
        # each wide provenance table is substantial; retaining four at once is
        # unnecessary and violates the CPU-friendly, bounded-memory intent.
        for name, (builder, separated) in builders.items():
            summaries[component_names[name]] = self._write_component(destination, name, builder, separated=separated)
            gc.collect()
        write_json(destination / "model_registry.json", {"models": registry})
        report = {"records_processed": int(len(base)), "runtime_seconds": round(time.perf_counter() - started, 3), "components": summaries,
                  "conditional_models": {"fitted": len(registry), "trained_on_earlier_periods": sum(1 for r in registry if r["training_scheme"] == "TRAINED_ON_EARLIER_PERIODS"),
                                         "in_round_cross_fit_fallback": sum(1 for r in registry if r["training_scheme"] != "TRAINED_ON_EARLIER_PERIODS")},
                  "decision_path": {"conditional_models": "VALUE_CHECK", "similarity": "INFORMATION_ONLY",
                                    "isolation_forest": "RESEARCH_ONLY" if self.config.parameters.run_research_models else "NOT_RUN",
                                    "peer_scoped_lof": "RESEARCH_ONLY" if self.config.parameters.run_research_models else "NOT_RUN"},
                  "warnings": ["Exact-signature similarity is informational; near-duplicate households are an FSU-level pattern check.",
                               "Isolation Forest and LOF are research outputs only and never affect the supervisor queue.",
                               "Conditional models apply to first-visit records; revisit records are explicitly not assessable for them."]}
        metadata = {"run_id": run_id, "processing_timestamp_utc": utc_now(), "software_version": "0.1.0", "ml_method_version": ML_METHOD_VERSION, "input_preprocessing_run_id": prepared["run_id"], "input_prepared_person_path": str(self.config.prepared_person_path), "peer_group_run_id": peer["run_id"], "peer_group_run_path": str(self.config.peer_group_run_path), "peer_group_specification_version": peer["specification_version"], "release": prepared["release"], "observation": prepared["observation"], "design_period": prepared["design_period"], "parameters": self.config.parameters.__dict__, "history_preprocessing_runs": self._history_runs, "model_registry": "model_registry.json", "outputs": list(builders) + ["model_registry.json", "ml_report.json", "ml_report.md", "run_metadata.json"]}
        write_json(destination / "ml_report.json", report)
        write_json(destination / "run_metadata.json", metadata)
        write_markdown(destination / "ml_report.md", metadata, report)
        del self._base_cache
        return destination
