"""Versioned read boundary for stored MoSPI artefacts (plan W0.1).

The platform's own columns were renamed from ``iospi_*`` to ``MoSPI_*``.
Every run stored before the rename still holds ``iospi_*`` and those runs are
evidence that must never be rewritten (re-running preparation would change
run IDs and break audit provenance).  Code therefore always asks for the
*canonical* name (``MoSPI_*``) and this module resolves it to whatever the
file physically holds.

Rules
-----
* Legacy names are aliased at read time only; nothing on disk is changed.
* A requested column that is absent under every known name raises
  :class:`SchemaError` naming the file, the column and the detected schema
  version.  Nothing is silently filled (plan W0.2).
* A file holding the same column under two names is ambiguous and refused.

Raw survey columns (e.g. ``Age``, ``b4q6_perv1``) are not prefixed and pass
through unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import pyarrow.parquet as pq

CANONICAL_PREFIX = "MoSPI_"
LEGACY_PREFIXES = ("iospi_",)
# Written by preprocessing into run_metadata.json from this version onward.
PREPARED_SCHEMA_VERSION = "mospi-prepared-2"
LEGACY_SCHEMA_VERSION = "iospi-prepared-1"


class SchemaError(RuntimeError):
    """A stored artefact does not provide a required column."""


def canonical_name(name: str) -> str:
    for prefix in LEGACY_PREFIXES:
        if name.startswith(prefix):
            return CANONICAL_PREFIX + name[len(prefix):]
    return name


@lru_cache(maxsize=256)
def _physical_names(path: str, mtime_ns: int) -> tuple[str, ...]:  # mtime keys the cache
    return tuple(pq.ParquetFile(path).schema_arrow.names)


def physical_names(path: Path | str) -> tuple[str, ...]:
    path = Path(path)
    return _physical_names(str(path), path.stat().st_mtime_ns)


def column_map(path: Path | str) -> dict[str, str]:
    """``{canonical name: physical name}`` for one Parquet file."""
    mapping: dict[str, str] = {}
    for physical in physical_names(path):
        canonical = canonical_name(physical)
        if canonical in mapping and mapping[canonical] != physical:
            raise SchemaError(f"{path} holds {canonical} under two names ({mapping[canonical]}, {physical}); refusing an ambiguous read.")
        mapping[canonical] = physical
    return mapping


def available_columns(path: Path | str) -> set[str]:
    return set(column_map(path))


def schema_version(path: Path | str) -> str:
    names = physical_names(path)
    if any(name.startswith(LEGACY_PREFIXES) for name in names):
        return LEGACY_SCHEMA_VERSION
    if any(name.startswith(CANONICAL_PREFIX) for name in names):
        return PREPARED_SCHEMA_VERSION
    return "unprefixed"


def physical_name(path: Path | str, canonical: str) -> str:
    mapping = column_map(path)
    if canonical not in mapping:
        raise SchemaError(f"{path} lacks required column {canonical} (schema {schema_version(path)}).")
    return mapping[canonical]


def canonicalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename legacy-prefixed columns of an in-memory frame to canonical names."""
    renames = {name: canonical_name(name) for name in frame.columns if canonical_name(name) != name}
    clashes = set(renames.values()) & (set(frame.columns) - set(renames))
    if clashes:
        raise SchemaError(f"Frame holds both legacy and canonical names for {sorted(clashes)}.")
    return frame.rename(columns=renames) if renames else frame


def read_parquet(path: Path | str, columns: Sequence[str] | Iterable[str] | None = None, *, optional: Iterable[str] = (),
                 filters: list[tuple[str, str, object]] | None = None) -> pd.DataFrame:
    """Read a stored Parquet artefact using canonical column names.

    ``columns`` are required; ``optional`` columns are read only when present
    (the caller must then handle their absence explicitly).  ``filters`` use
    canonical names.
    """
    mapping = column_map(path)
    if columns is None:
        physical = None
    else:
        wanted = list(dict.fromkeys(columns))
        missing = [name for name in wanted if name not in mapping]
        if missing:
            raise SchemaError(f"{path} lacks required column(s) {missing} (schema {schema_version(path)}).")
        wanted += [name for name in dict.fromkeys(optional) if name in mapping and name not in wanted]
        physical = [mapping[name] for name in wanted]
    translated = None
    if filters:
        translated = []
        for name, operator, value in filters:
            if name not in mapping:
                raise SchemaError(f"{path} lacks filter column {name} (schema {schema_version(path)}).")
            translated.append((mapping[name], operator, value))
    frame = pd.read_parquet(path, columns=physical, filters=translated)
    return canonicalise(frame)
