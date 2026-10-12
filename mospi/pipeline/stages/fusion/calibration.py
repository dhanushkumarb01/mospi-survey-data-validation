"""Deterministic score calibration without an error-probability claim."""

from __future__ import annotations

import numpy as np
import pandas as pd


def percentile_midrank(values: pd.Series, *, higher_is_stronger: bool = True, zero_is_no_evidence: bool = False) -> pd.Series:
    """Return finite, tie-stable ranks in [0, 1] for available scores only.

    The rank is ``(below + .5 * equal) / n`` after applying documented score
    direction.  This is a within-run evidence-strength scale, never a
    probability of an erroneous response.  A constant all-zero source is
    explicitly low evidence (0); another constant finite source is assigned
    0.5 because the run contains no ordering information.

    ``zero_is_no_evidence``: an exact 0 means "no deviation at all" (e.g. a
    value equal to its peer median).  Such rows get rank 0 instead of the
    mid-rank of a large tie block, which in V1 gave "no evidence" a rank of
    about 0.3 (audit M4).
    """
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    available = numeric.dropna()
    if available.empty:
        return result
    oriented = available if higher_is_stronger else -available
    if oriented.nunique(dropna=True) == 1:
        result.loc[available.index] = 0.0 if float(oriented.iloc[0]) == 0.0 else 0.5
        return result
    # pandas average rank is 1-indexed.  Convert it to the empirical midrank.
    result.loc[available.index] = (oriented.rank(method="average") - 0.5) / len(oriented)
    if zero_is_no_evidence:
        result.loc[available.index[available.eq(0).to_numpy()]] = 0.0
    return result.clip(0.0, 1.0)


def calibrate_frame(frame: pd.DataFrame, score_column: str, *, direction: str = "higher") -> pd.DataFrame:
    """Attach a named calibrated rank while retaining the untouched raw score."""
    if direction not in {"higher", "lower"}:
        raise ValueError("Score direction must be 'higher' or 'lower'.")
    output = frame.copy()
    output["calibrated_rank"] = percentile_midrank(output[score_column], higher_is_stronger=direction == "higher")
    return output
