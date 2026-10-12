"""Pre-flight checks of an uploaded delivery against the documented V2.2 dataset contracts.

Nothing here changes a file or a contract.  The checks are the same facts the preparation stage relies on
(mospi/pipeline/stages/preprocessing): a delivery is one household file and one person file of ONE registered
contract, with every documented required column; keys are built exactly as preparation builds them.

Findings are BLOCKING (validation cannot start), WARNING (shown; validation may start) or INFO.
The report holds counts, column names and file names only: never a survey value or a record key.
Record keys are kept only as keyed hashes (HMAC-SHA-256, secret ``MOSPI_KEY_HMAC_SECRET``) beside the upload,
to detect overlap with earlier deliveries.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from mospi.pipeline.stages.preprocessing.config import CONTRACTS, DatasetContract
from mospi.pipeline.stages.preprocessing.pipeline import PLFSPreprocessor, RunConfig

from .settings import UPLOADABLE_CONTRACTS, Settings

LEVELS = ("household", "person")


def finding(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def load_profiles(folder: Path) -> dict[str, dict[str, Any]]:
    """Approved column-mapping profiles (versioned JSON reviewed like code); unknown layouts are never mapped automatically."""
    profiles = {}
    for path in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else []:
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if {"profile_id", "contract", "level", "version", "status", "rename"} <= set(profile):
            profiles[str(profile["profile_id"])] = profile
    return profiles


def read_header(path: Path) -> list[str]:
    with open(path, encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle), [])


def structure_problem(path: Path, header: list[str]) -> str | None:
    """A row with more fields than the header (which preparation's full read rejects) or broken quoting; None if regular.

    Rows with fewer fields are read as blank trailing fields by preparation, so they are left to it, as for any delivery."""
    try:
        with duckdb.connect() as connection:
            connection.execute("SELECT COUNT(*) FROM read_csv(?, header=true, all_varchar=true, strict_mode=true, null_padding=true, auto_detect=false, "
                               "delim=',', quote='\"', escape='\"', columns=?)", [str(path), {name: "VARCHAR" for name in header}]).fetchone()
    except duckdb.Error as error:
        line = next((part for part in str(error).split() if part.rstrip(":").isdigit()), None)
        return ("Rows do not all have the same columns as the header" + (f" (first problem near line {line.rstrip(':')})" if line else "") +
                "; a row has extra fields or broken quoting. The file must be a regular CSV table.")
    return None


def required(contract: DatasetContract, level: str) -> set[str]:
    return set(contract.fields(level).values())


def assign_levels(contract: DatasetContract, headers: dict[str, list[str]], names: dict[str, str]) -> dict[str, str | None]:
    """File id -> 'household' / 'person' / None, from the documented required columns (file name only breaks ties)."""
    out: dict[str, str | None] = {}
    for file_id, header in headers.items():
        present = set(header)
        missing = {level: len(required(contract, level) - present) for level in LEVELS}
        full = [level for level in LEVELS if missing[level] == 0]
        if len(full) == 1:
            out[file_id] = full[0]
        elif len(full) == 2:
            hint = names[file_id].lower()
            expected = {level: Path(contract.household_path if level == "household" else contract.person_path).name.lower() for level in LEVELS}
            by_name = [level for level in LEVELS if expected[level] == hint]
            out[file_id] = by_name[0] if by_name else min(LEVELS, key=lambda lv: abs(len(header) - (contract.expected_household_columns if lv == "household" else contract.expected_person_columns)))
        else:
            out[file_id] = None
    return out


def _keys(contract_name: str, frame: pd.DataFrame, level: str) -> tuple[pd.Series, pd.Series]:
    """Canonical expected keys exactly as preparation builds them, plus a blank-component mask."""
    preparer = PLFSPreprocessor(RunConfig(Path("."), Path("."), contract_name))
    contract = preparer.contract
    key = preparer._canonical_key(frame, level)
    fields = contract.fields(level)
    blank = pd.Series(False, index=frame.index)
    for concept in contract.household_key:
        blank |= frame[fields[concept]].map(lambda v: str(v).strip() == "")
    if level == "person":
        serial = frame[fields[contract.person_serial]].map(lambda v: str(v).strip()).astype("string")
        blank |= serial.eq("")
        key = key.str.cat(serial, sep="|")
    return key, blank


def _hash_keys(keys: pd.Series, secret: bytes) -> list[str]:
    return [hmac.new(secret, str(k).encode("utf-8"), hashlib.sha256).hexdigest()[:32] for k in keys]


def run_preflight(*, dataset: dict[str, Any], files: list[dict[str, Any]], other_files: list[dict[str, Any]], other_key_files: list[Path],
                  settings: Settings, workdir: Path, profile_id: str | None = None) -> dict[str, Any]:
    """Return the report and per-file levels; writes hashed key files into ``workdir``."""
    findings: list[dict[str, Any]] = []
    contract_name = dataset["contract_name"]
    if contract_name not in CONTRACTS or contract_name not in UPLOADABLE_CONTRACTS:
        findings.append(finding("BLOCKING", "UNSUPPORTED_CONTRACT", f"The layout {contract_name!r} cannot be validated as a standalone delivery. "
                                f"Supported: {', '.join(UPLOADABLE_CONTRACTS)}."))
        return {"status": "BLOCKED", "contract": contract_name, "findings": findings, "files": [], "counts": {}}
    contract = CONTRACTS[contract_name]
    profiles = load_profiles(settings.mapping_profile_dir)
    rename: dict[str, dict[str, str]] = {"household": {}, "person": {}}
    if profile_id:
        profile = profiles.get(profile_id)
        if profile is None or profile.get("status") != "APPROVED" or profile.get("contract") != contract_name:
            findings.append(finding("BLOCKING", "MAPPING_PROFILE_NOT_APPROVED", "The selected column-mapping profile is not an approved profile for this layout."))
        else:
            rename[profile["level"]] = {str(k): str(v) for k, v in profile["rename"].items()}
    if not files:
        findings.append(finding("BLOCKING", "NO_FILES", "No file was received."))
    if len(files) > settings.max_files:
        findings.append(finding("BLOCKING", "TOO_MANY_FILES", f"{len(files)} files were received; at most {settings.max_files} are allowed."))

    headers: dict[str, list[str]] = {}
    names = {f["file_id"]: f["display_name"] for f in files}
    reports = {f["file_id"]: {"file_id": f["file_id"], "name": f["display_name"], "relative_path": f.get("relative_path"), "bytes": f["size_bytes"],
                              "sha256": f["sha256"][:12], "level": None, "columns": None} for f in files}
    for f in files:
        fid, label = f["file_id"], f["display_name"]
        if not label.lower().endswith(".csv"):
            findings.append(finding("BLOCKING", "NOT_A_CSV", "Only .csv files are accepted.", file=label)); continue
        if f["size_bytes"] == 0:
            findings.append(finding("BLOCKING", "EMPTY_FILE", "The file is empty.", file=label)); continue
        if f.get("nul_bytes"):
            findings.append(finding("BLOCKING", "BINARY_CONTENT", "The file contains NUL bytes; it is not a text CSV.", file=label)); continue
        if f["encoding"] == "not-utf-8":
            findings.append(finding("BLOCKING", "NOT_UTF8", "The file is not UTF-8 text. Export it again as UTF-8 CSV (it is never converted silently).", file=label)); continue
        if f["encoding"] == "utf-8-bom":
            findings.append(finding("BLOCKING", "UTF8_BOM", "The file starts with a byte-order mark, which would change the first column name. "
                                    "Save it as UTF-8 without BOM.", file=label)); continue
        header = read_header(Path(f["stored_path"]))
        duplicates = sorted({h for h in header if header.count(h) > 1})
        if duplicates:
            findings.append(finding("BLOCKING", "DUPLICATE_COLUMN_NAMES", "Column names occur more than once: " + ", ".join(duplicates[:20]), file=label)); continue
        if len(header) > settings.max_columns:
            findings.append(finding("BLOCKING", "TOO_MANY_COLUMNS", f"{len(header)} columns exceed the limit of {settings.max_columns}.", file=label)); continue
        headers[fid] = header
        reports[fid]["columns"] = len(header)

    # Which level is each file?  (mapping renames applied to the header only)
    mapped = {fid: [rename["household"].get(h, rename["person"].get(h, h)) for h in header] for fid, header in headers.items()}
    levels = assign_levels(contract, mapped, names)
    for fid, level in levels.items():
        reports[fid]["level"] = level
        label = names[fid]
        if level is None:
            present = set(mapped[fid])
            closest = min(LEVELS, key=lambda lv: len(required(contract, lv) - present))
            missing = sorted(required(contract, closest) - present)
            other = [name for name in UPLOADABLE_CONTRACTS if name != contract_name and any(not (required(CONTRACTS[name], lv) - present) for lv in LEVELS)]
            hint = f" Its columns match the {other[0]} layout instead; choose that layout." if other else ""
            findings.append(finding("BLOCKING", "MISSING_REQUIRED_COLUMNS", f"Not a complete {closest} file of this layout: {len(missing)} documented "
                                    f"columns are missing ({', '.join(missing[:15])}{'…' if len(missing) > 15 else ''}).{hint}", file=label))
            continue
        expected = contract.expected_household_columns if level == "household" else contract.expected_person_columns
        if len(mapped[fid]) != expected:
            findings.append(finding("WARNING", "COLUMN_COUNT_MISMATCH", f"{len(mapped[fid])} columns; the documented {level} file has {expected}. "
                                    "Preparation records the same warning; extra columns are kept, never dropped.", file=label))
    by_level: dict[str, list[str]] = {level: [fid for fid, lv in levels.items() if lv == level] for level in LEVELS}
    for level in LEVELS:
        if len(by_level[level]) > 1:
            findings.append(finding("BLOCKING", "SEVERAL_FILES_FOR_ONE_LEVEL", f"More than one {level} file: " + ", ".join(names[f] for f in by_level[level]) +
                                    ". A delivery is exactly one household and one person file."))
        elif not by_level[level] and not any(f["severity"] == "BLOCKING" and f["code"] == "MISSING_REQUIRED_COLUMNS" for f in findings):
            findings.append(finding("BLOCKING", "MISSING_FILE", f"The {level} file of this layout was not found among the uploaded files "
                                    f"(expected something like {Path(contract.household_path if level == 'household' else contract.person_path).name})."))
    unexpected = [names[fid] for fid, lv in levels.items() if lv is None]
    if unexpected and not any(f["code"] == "MISSING_REQUIRED_COLUMNS" for f in findings):
        findings.append(finding("BLOCKING", "UNEXPECTED_FILES", "Files that are not part of this layout: " + ", ".join(unexpected)))

    # Duplicate uploads (identical bytes, or the same rows re-saved).
    for f in files:
        same = [o for o in other_files if o["sha256"] == f["sha256"]]
        similar = [o for o in other_files if o.get("content_fingerprint") and o["content_fingerprint"] == f.get("content_fingerprint") and o["sha256"] != f["sha256"]]
        if same:
            findings.append(finding("BLOCKING", "DUPLICATE_FILE", f"This exact file was already received in dataset {same[0]['dataset_id'][:8]} "
                                    f"({same[0]['created_utc']:%d %b %Y}).", file=f["display_name"]))
        elif similar:
            findings.append(finding("BLOCKING", "DUPLICATE_CONTENT", f"The same rows were already received (re-saved copy) in dataset {similar[0]['dataset_id'][:8]}.",
                                    file=f["display_name"]))

    counts: dict[str, Any] = {}
    secret = os.environ.get("MOSPI_KEY_HMAC_SECRET", "").encode("utf-8")
    if not secret:
        findings.append(finding("BLOCKING", "KEY_SECRET_NOT_CONFIGURED", "MOSPI_KEY_HMAC_SECRET is not set, so overlap with earlier deliveries cannot be checked."))
    blocking_so_far = any(f["severity"] == "BLOCKING" for f in findings)
    if not blocking_so_far:
        stored = {f["file_id"]: Path(f["stored_path"]) for f in files}
        frames: dict[str, pd.DataFrame] = {}
        for level in LEVELS:
            fid = by_level[level][0]
            problem = structure_problem(stored[fid], headers[fid])
            if problem:
                findings.append(finding("BLOCKING", "MALFORMED_CSV", problem, file=names[fid]))
                continue
            inverse = {v: k for k, v in rename[level].items()}
            fields = contract.fields(level)
            wanted = list(dict.fromkeys([fields[c] for c in contract.household_key] + ([fields[contract.person_serial]] if level == "person" else [])))
            try:
                frame = pd.read_csv(stored[fid], usecols=[inverse.get(c, c) for c in wanted], dtype="string", keep_default_na=False, na_filter=False,
                                    encoding="utf-8", low_memory=False)
            except (pd.errors.ParserError, ValueError, UnicodeDecodeError) as error:
                findings.append(finding("BLOCKING", "MALFORMED_CSV", f"The file could not be read as a regular CSV table ({type(error).__name__}: "
                                        f"{str(error).splitlines()[0][:160]}).", file=names[fid]))
                continue
            frames[level] = frame.rename(columns=rename[level])
        if len(frames) == 2:
            keyed = {}
            for level, frame in frames.items():
                key, blank = _keys(contract_name, frame, level)
                duplicated = key[~blank].duplicated(keep=False)
                counts[level] = {"rows": int(len(frame)), "blank_key_rows": int(blank.sum()), "duplicate_key_rows": int(duplicated.sum())}
                if blank.any():
                    findings.append(finding("WARNING", "INCOMPLETE_KEYS", f"{int(blank.sum()):,} {level} rows have a blank key component. They are kept and "
                                            "marked not assessable by preparation, exactly as for any delivery."))
                if duplicated.any():
                    findings.append(finding("WARNING", "DUPLICATE_KEYS_IN_FILE", f"{int(duplicated.sum()):,} {level} rows share an expected key with another row. "
                                            "They are kept and marked not assessable by preparation (records are never dropped)."))
                keyed[level] = (key, blank)
            household_keys = set(keyed["household"][0][~keyed["household"][1]])
            person_household = frames["person"].pipe(lambda f: PLFSPreprocessor(RunConfig(Path("."), Path("."), contract_name))._canonical_key(f, "person"))
            unmatched = int((~person_household.isin(household_keys) & ~keyed["person"][1]).sum())
            counts["person"]["without_household"] = unmatched
            if unmatched:
                share = unmatched / max(1, counts["person"]["rows"])
                findings.append(finding("BLOCKING" if share > 0.5 else "WARNING", "PERSONS_WITHOUT_HOUSEHOLD",
                                        f"{unmatched:,} persons ({share:.1%}) have no household in the household file"
                                        + (". The two files do not belong to the same delivery." if share > 0.5 else "; preparation marks them unmatched.")))
            if counts["person"]["rows"] < settings.small_delivery_persons:
                findings.append(finding("WARNING", "SMALL_DELIVERY", f"Only {counts['person']['rows']:,} persons. Comparison groups need enough records: "
                                        "many checks may be 'not assessable' and a quality gate may stop the run."))
            if secret:
                workdir.mkdir(parents=True, exist_ok=True)
                key_file = workdir / "keys_person.parquet"
                pd.DataFrame({"k": _hash_keys(keyed["person"][0][~keyed["person"][1]], secret)}).to_parquet(key_file, index=False)
                others = [str(p) for p in other_key_files if p.is_file()]
                overlap = 0
                if others:
                    with duckdb.connect() as connection:
                        overlap = int(connection.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE k IN (SELECT k FROM read_parquet(?))",
                                                         [str(key_file), others]).fetchone()[0])
                counts["person"]["overlapping_records"] = overlap
                if overlap:
                    findings.append(finding("BLOCKING", "OVERLAPPING_RECORDS", f"{overlap:,} person records were already received in an earlier delivery of this "
                                            "layout. Overlapping deliveries are not merged or replaced automatically; revisions need a separate decision."))
    status = "BLOCKED" if any(f["severity"] == "BLOCKING" for f in findings) else "PASSED"
    return {"status": status, "contract": contract_name, "release": contract.release, "observation": contract.observation, "mapping_profile": profile_id,
            "findings": findings, "files": list(reports.values()), "counts": counts, "levels": {fid: lv for fid, lv in levels.items()}}
