import numpy as np
import pandas as pd

from fusion.calibration import percentile_midrank


def test_midrank_is_tie_stable_and_directional():
    ranks = percentile_midrank(pd.Series([1.0, 2.0, 2.0, 4.0]))
    assert ranks.tolist() == [0.125, 0.5, 0.5, 0.875]
    assert percentile_midrank(pd.Series([1.0, 2.0]), higher_is_stronger=False).tolist() == [0.75, 0.25]


def test_missing_nonfinite_and_constant_scores_are_explicit():
    ranks = percentile_midrank(pd.Series([np.nan, np.inf, -np.inf, 0.0]))
    assert ranks.isna().iloc[:3].all() and ranks.iloc[3] == 0.0
    assert percentile_midrank(pd.Series([2.0, 2.0])).tolist() == [0.5, 0.5]
    assert percentile_midrank(pd.Series([], dtype=float)).empty
