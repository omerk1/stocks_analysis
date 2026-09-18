"""M5 -- touch/test/bounce event extraction (DESIGN.md §5;
PREREGISTRATION.md, 2026-09-17).

Builds the ex-ante "first touch after being away" event DESIGN §5 requires
-- **never** select on the outcome (a bounce is only identifiable ex post;
selecting on it guarantees a beautiful, meaningless result). The event day
is fully determined by data through that day's own close: an "away" run
(|dist_atr| >= AWAY_THRESHOLD) followed by the first day, within
MAX_DAYS_TO_TOUCH trading days, where |dist_atr| <= TOUCH_THRESHOLD. Only
the *outcome*, measured OUTCOME_HORIZON trading days after the touch day,
looks forward -- the same "state known as of day t, label measured
forward from t" shape every other module in this study uses
(`labels/forward_returns.py::forward_return`), not a new lag convention.

Operates on an already one-bar-lagged `dist_atr` column (i.e. the output
of `features/placebo_ma.py::build_placebo_panel`, or the main cached
panel) -- the same convention M1's `above_sma_k`-based state columns use:
a row's `dist_atr` is "the state as of that row's tradeable day," already
lagged centrally, not re-lagged here.

Run detection reuses `features/state.py::state_run_id`/`days_in_run`
(the same primitives M1's run-length buckets use) rather than a hand-
rolled shift/cumsum -- called per ticker (`panel.groupby("ticker")`,
matching every other per-ticker feature builder in this study, e.g.
`features/panel.py::_build_ticker_features`), not a raw per-row Python
loop.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import state

AWAY_THRESHOLD = 1.0
TOUCH_THRESHOLD = 0.25
MAX_DAYS_TO_TOUCH = 10
OUTCOME_HORIZON = 5
RESOLVE_THRESHOLD = 0.5

FROM_ABOVE = "from_above"
FROM_BELOW = "from_below"

HOLD = "hold"
SLICE_THROUGH = "slice_through"
CHOP = "chop"


def _touch_events_one_ticker(
    frame: pd.DataFrame,
    dist_atr_col: str,
    date_col: str,
    away_threshold: float,
    touch_threshold: float,
    max_days_to_touch: int,
    outcome_horizon: int,
    resolve_threshold: float,
) -> pd.DataFrame:
    """One ticker's rows, already sorted by date. Returns one row per
    qualifying touch event (empty frame if none). `frame` is not mutated.
    """
    dist_atr = frame[dist_atr_col]
    away = (dist_atr.abs() >= away_threshold).astype("boolean").mask(dist_atr.isna())
    touch = (dist_atr.abs() <= touch_threshold).astype("boolean").mask(dist_atr.isna())

    run_id = state.state_run_id(away)
    valid = run_id.notna()
    if not valid.any():
        return frame.iloc[0:0][[date_col]].assign(
            direction=pd.Series(dtype="string"), dist_atr_at_touch=pd.Series(dtype="float64"),
            dist_atr_at_outcome=pd.Series(dtype="float64"), outcome=pd.Series(dtype="string"),
            hold_flag=pd.Series(dtype="boolean"),
        )
    days = state.days_in_run(away, run_id=run_id)

    # Direction: sign of dist_atr at the last row of each "away" (True)
    # run -- the state right before the ticker re-entered the "not away"
    # zone. `away_run_id` is a simple per-ticker flip counter (increments
    # by exactly 1 at every True<->False transition), so a "not away" run
    # with id `k` is always immediately preceded by the "away" run with id
    # `k - 1` -- reindexing the away-runs' last values by `+1` aligns them
    # onto the following not-away run with no explicit merge/loop needed.
    is_away = away.fillna(False).to_numpy(dtype=bool)
    away_last_value = (
        pd.DataFrame({"run_id": run_id[valid & away.fillna(False)], "dist_atr": dist_atr[valid & away.fillna(False)]})
        .groupby("run_id")["dist_atr"].last()
    )
    direction_by_notaway_run = away_last_value.copy()
    direction_by_notaway_run.index = direction_by_notaway_run.index + 1

    days_since_away_end = days.where(~is_away)
    candidate = (
        (~is_away) & touch.fillna(False).to_numpy(dtype=bool)
        & (days_since_away_end.to_numpy() <= max_days_to_touch)
        & valid.to_numpy()
    )
    if not candidate.any():
        return frame.iloc[0:0][[date_col]].assign(
            direction=pd.Series(dtype="string"), dist_atr_at_touch=pd.Series(dtype="float64"),
            dist_atr_at_outcome=pd.Series(dtype="float64"), outcome=pd.Series(dtype="string"),
            hold_flag=pd.Series(dtype="boolean"),
        )

    # Plain numpy arrays throughout (not the underlying Series' own index) --
    # `run_id`/`days_since_away_end` carry positional (RangeIndex) labels
    # from `frame`, which would silently misalign against `pos`'s fresh
    # 0..k-1 index if any of these were passed into the DataFrame
    # constructor as Series.
    candidates = pd.DataFrame({
        "run_id": run_id.to_numpy()[candidate],
        "pos": np.flatnonzero(candidate),
        "days_since_away_end": days_since_away_end.to_numpy()[candidate],
    })
    # First qualifying touch per not-away run only (ex ante: at most one
    # event per away-run, no re-selection on later, possibly cleaner,
    # touches of the same run).
    first_touch = candidates.loc[candidates.groupby("run_id")["days_since_away_end"].idxmin()]
    event_positions = first_touch["pos"].to_numpy()
    event_run_ids = first_touch["run_id"].to_numpy()

    direction_sign = direction_by_notaway_run.reindex(event_run_ids).to_numpy()
    # A not-away run with no preceding away run at all (the ticker's very
    # first, left-censored run happens to already be "not away") has no
    # defined direction -- dropped, not guessed.
    has_direction = ~pd.isna(direction_sign)

    outcome_pos = event_positions + outcome_horizon
    n = len(frame)
    in_range = outcome_pos < n
    keep = has_direction & in_range
    if not keep.any():
        return frame.iloc[0:0][[date_col]].assign(
            direction=pd.Series(dtype="string"), dist_atr_at_touch=pd.Series(dtype="float64"),
            dist_atr_at_outcome=pd.Series(dtype="float64"), outcome=pd.Series(dtype="string"),
            hold_flag=pd.Series(dtype="boolean"),
        )

    event_positions = event_positions[keep]
    outcome_pos = outcome_pos[keep]
    direction_sign = direction_sign[keep]

    dist_atr_values = dist_atr.to_numpy()
    dist_atr_at_touch = dist_atr_values[event_positions]
    dist_atr_at_outcome = dist_atr_values[outcome_pos]
    direction = np.where(direction_sign > 0, FROM_ABOVE, FROM_BELOW)

    # from_above (support test): hold = bounced back up past the resolve
    # band; slice_through = broke down past it the other way. from_below
    # (resistance test): mirrored.
    resolved_up = dist_atr_at_outcome >= resolve_threshold
    resolved_down = dist_atr_at_outcome <= -resolve_threshold
    outcome = np.full(len(direction), CHOP, dtype=object)
    from_above_mask = direction == FROM_ABOVE
    outcome[from_above_mask & resolved_up] = HOLD
    outcome[from_above_mask & resolved_down] = SLICE_THROUGH
    outcome[~from_above_mask & resolved_down] = HOLD
    outcome[~from_above_mask & resolved_up] = SLICE_THROUGH

    return pd.DataFrame({
        date_col: frame[date_col].to_numpy()[event_positions],
        "direction": pd.array(direction, dtype="string"),
        "dist_atr_at_touch": dist_atr_at_touch,
        "dist_atr_at_outcome": dist_atr_at_outcome,
        "outcome": pd.array(outcome, dtype="string"),
        "hold_flag": pd.array(outcome == HOLD, dtype="boolean"),
    })


def touch_events(
    panel: pd.DataFrame,
    dist_atr_col: str,
    ticker_col: str = "ticker",
    date_col: str = "date",
    away_threshold: float = AWAY_THRESHOLD,
    touch_threshold: float = TOUCH_THRESHOLD,
    max_days_to_touch: int = MAX_DAYS_TO_TOUCH,
    outcome_horizon: int = OUTCOME_HORIZON,
    resolve_threshold: float = RESOLVE_THRESHOLD,
) -> pd.DataFrame:
    """One row per qualifying touch event across every ticker in `panel`:
    `ticker`, `date` (the touch day), `direction` (`from_above`/
    `from_below`), `dist_atr_at_touch`, `dist_atr_at_outcome`, `outcome`
    (`hold`/`slice_through`/`chop`), `hold_flag` (bool). `panel` must be
    sorted by (`ticker_col`, `date_col`) and carry `dist_atr_col` already
    one-bar-lagged (see module docstring).
    """
    working = panel[[ticker_col, date_col, dist_atr_col]].sort_values([ticker_col, date_col])

    results = []
    for ticker, frame in working.groupby(ticker_col, sort=False):
        frame = frame.reset_index(drop=True)
        events = _touch_events_one_ticker(
            frame, dist_atr_col, date_col, away_threshold, touch_threshold,
            max_days_to_touch, outcome_horizon, resolve_threshold,
        )
        if len(events):
            events.insert(0, ticker_col, ticker)
            results.append(events)

    if not results:
        return pd.DataFrame(columns=[ticker_col, date_col, "direction", "dist_atr_at_touch",
                                      "dist_atr_at_outcome", "outcome", "hold_flag"])
    return pd.concat(results, ignore_index=True)
