"""M3 -- crossover event detection (DESIGN.md Sec "M3 -- Crossovers: state vs
transition", lines ~753-762; PREREGISTRATION.md, 2026-09-23).

A crossover event is the first day a fast MA's "fast above slow" state
differs from the previous day's state -- day 0 of a golden cross (state
flips False->True) or death cross (True->False). Reuses
`features/state.py::state_run_id`/`days_in_run` (the same primitives M1's
run-length buckets and M5's touch events use) rather than a hand-rolled
diff -- the left-censored first run (`run_id == 0`, in progress when the
ticker's observation window starts) is excluded, same convention
`features/panel.py`'s own `run_length_bucket_*` columns use: its true start
is unobserved, so it has no observed event day.

`fast_above_slow_state` is a pure elementwise comparison
(`features/distance.py::above`) and is safe to compute vectorized across
the whole panel. `crossover_events` still requires a per-ticker loop
(`state_run_id`/`days_in_run` use `.shift(1)`, which must not bleed across
ticker boundaries) -- same per-ticker groupby shape
`features/touch.py::touch_events` uses for its own event extraction.

If `fast_col`/`slow_col` are columns already in the cached panel (e.g.
`sma_50`/`sma_200`), they are already one-bar-lagged by
`features/panel.py::apply_lag` -- this module does not re-lag them. A
caller adding a *new* MA column not in the cached panel (this module's own
`ema_8`/`ema_10`/`ema_21`, see `modules/crossover_state.py`) is responsible
for lagging it the same way (`features/panel.py::apply_lag`) before calling
this.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import state
from src.signals.moving_averages.features.distance import above

GOLDEN = "golden"
DEATH = "death"


def fast_above_slow_state(panel: pd.DataFrame, fast_col: str, slow_col: str) -> pd.Series:
    """`1[fast_col > slow_col]`, NA-safe (see `features/distance.py::above`).
    Vectorized across the whole panel -- a pure elementwise comparison, not
    a rolling window, so no per-ticker grouping is needed here.
    """
    return above(panel[fast_col], panel[slow_col])


def crossover_events(
    panel: pd.DataFrame,
    state_col: str,
    ticker_col: str = "ticker",
    date_col: str = "date",
) -> pd.DataFrame:
    """One row per qualifying crossover event: `ticker`, `date` (the event
    day), `crossover_type` (`golden`/`death`). `panel[state_col]` must
    already be the fast-above-slow boolean state (see
    `fast_above_slow_state`); this function sorts defensively by
    (`ticker_col`, `date_col`) within each ticker, same convention
    `features/touch.py::touch_events` follows.

    An event is the first day of a *non-left-censored* run of `state_col`
    -- i.e. `state.state_run_id(...)` is neither NA nor 0, and
    `state.days_in_run(...) == 1`. The left-censored run (id 0) has no
    observed event day, same exclusion `run_length_bucket` applies.
    """
    working = panel[[ticker_col, date_col, state_col]].sort_values([ticker_col, date_col])

    results = []
    for ticker, frame in working.groupby(ticker_col, sort=False):
        frame = frame.reset_index(drop=True)
        s = frame[state_col]
        run_id = state.state_run_id(s)
        days = state.days_in_run(s, run_id=run_id)
        is_event = (run_id.notna() & (run_id != 0) & (days == 1)).to_numpy()
        if not is_event.any():
            continue
        event_rows = frame.loc[is_event, [date_col]].copy()
        event_type = s.loc[is_event].map({True: GOLDEN, False: DEATH}).astype("string")
        event_rows["crossover_type"] = event_type.to_numpy()
        event_rows.insert(0, ticker_col, ticker)
        results.append(event_rows)

    if not results:
        return pd.DataFrame(columns=[ticker_col, date_col, "crossover_type"])
    return pd.concat(results, ignore_index=True)
