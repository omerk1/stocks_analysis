"""Triple-barrier labels: the target of the modeling harness
(`docs/modeling/VALIDATION_HARNESS.md` §3).

For a decision at the close of day t, the position is entered at the **open of
t+1** (`P0`). Barriers sit `U` and `D` ATRs away from `P0` -- in the v1 grid
scaled by sqrt(H / 21), so a longer horizon gets proportionally wider barriers
(`BarrierCell.upper_atr`; why: `v1_grid`) -- using ATR(14) as known
at the close of t (computed here from raw bars, not the MA panel's lagged
`atr_14`, which is one bar older). The label is which barrier the price reaches
first within the next `H` bars (t+1 … t+H):

    hit = +1  target first      (long: upper; short: lower)
          -1  stop first        (long: lower; short: upper)
           0  neither by t+H

Rules (fixed by the design, tested in `tests/test_models_barriers.py`):
- **Same-bar tie** (one bar's range covers both barriers, open between them):
  counted as the stop -- daily bars can't say which came first, so the
  conservative reading. `tie` flags it.
- **Gap through a barrier** at a bar's open: the fill is the open, not the barrier
  (a gap down through the stop loses more than D; a gap up through the target
  gains more than U).
- **Neither hit**: exit at the close of t+H.
- **Incomplete windows**: if bar t+H is past the dataset's `data_end`, the label
  is NaN -- the caller truncates bars at the holdout boundary, so a window that
  would read the holdout never resolves. If instead the *ticker's* history ends
  more than `DELISTING_GAP` trading days before the dataset's last trading day
  (a delisting), the window resolves on its last bar and `truncated` is set.

Every price path is scanned per ticker with numpy (sliding windows), not row by
row. `ret` is the realised return of the trade in the position's direction.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from src.foundation.market_common import indicators

ATR_PERIOD = 14
DELISTING_GAP = 5  # trading days; see `barrier_labels`
LONG = "long"
SHORT = "short"

# Barrier widths in the v1 grid are quoted at this horizon and scale with sqrt(H / it).
REFERENCE_HORIZON = 21

OUTPUT_COLUMNS = [
    "ticker", "date", "horizon", "upper", "lower", "upper_atr", "lower_atr", "side",
    "entry_price", "atr", "hit", "hit_day", "exit_price", "ret", "tie", "truncated",
    "mfe_atr", "mae_atr", "label_end_date",
]


@dataclass(frozen=True)
class BarrierCell:
    """`upper`/`lower`: the cell's nominal target and stop in ATRs (long: above /
    below entry; short: mirrored). With `reference_horizon` set, the actual
    distances are those times sqrt(horizon / reference_horizon)
    (`upper_atr`, `lower_atr`); without it, they are `upper`/`lower` as-is."""
    horizon: int
    upper: float
    lower: float
    reference_horizon: int | None = None

    @property
    def scale(self) -> float:
        return 1.0 if self.reference_horizon is None else float(np.sqrt(self.horizon / self.reference_horizon))

    @property
    def upper_atr(self) -> float:
        return self.upper * self.scale

    @property
    def lower_atr(self) -> float:
        return self.lower * self.scale


def v1_grid() -> list[BarrierCell]:
    """The design's v1 grid (`VALIDATION_HARNESS.md` §3, revised 2026-10-06 before any
    fit): H {5, 10, 21, 42, 63} x U {2, 3, 4} x D {1, 1.5, 2}, distances scaled by
    sqrt(H / 21). Time to reach a barrier grows with the square of its distance, so
    fixed-ATR barriers made every horizon >= 21 the same few-day question (1/1
    resolved in ~3.4 days at H=21, 42 and 63 alike); scaled, each horizon resolves
    in about its first third. U=1 is out: decided by days of noise, and costs eat
    a 1-ATR target. H=5 is a diagnostic only (scaled barriers are ~0.5 ATR, ties 5%)."""
    return [
        BarrierCell(h, u, d, REFERENCE_HORIZON)
        for h in (5, 10, 21, 42, 63)
        for u in (2.0, 3.0, 4.0)
        for d in (1.0, 1.5, 2.0)
    ]


def barrier_labels(
    bars: pd.DataFrame,
    cells: list[BarrierCell],
    data_end: str | pd.Timestamp | None = None,
    side: str = LONG,
    calendar: pd.DatetimeIndex | np.ndarray | None = None,
) -> pd.DataFrame:
    """Labels for every (ticker, date) in `bars` and every cell, long format
    (`OUTPUT_COLUMNS`).

    `bars`: columns ticker, date, open, high, low, close (one row per ticker per
    trading day; split/dividend-adjusted prices are fine -- everything here is a
    ratio within one window). `data_end`: the last date the dataset is allowed
    to contain (default: the latest date in `bars`); windows past it are NaN.
    `calendar`: the whole dataset's trading days, for callers that label
    tickers in chunks (default: the dates in `bars`) -- a chunk of tickers
    that all ended early would otherwise measure delisting against its own
    last date and miss it.
    """
    if side not in (LONG, SHORT):
        raise ValueError(f"side must be {LONG!r} or {SHORT!r}, got {side!r}")
    # Convert before sorting: date strings like "1/9/2020" sort as text.
    frame = bars.assign(date=pd.to_datetime(bars["date"])).sort_values(["ticker", "date"]).reset_index(drop=True)
    end = pd.Timestamp(data_end) if data_end is not None else frame["date"].max()
    if (frame["date"] > end).any():
        raise ValueError(f"bars contain dates after data_end {end.date()}; truncate them first")

    # A ticker counts as ended (delisted) only if its last bar is more than
    # DELISTING_GAP trading days before the dataset's last actual trading day --
    # not merely before `data_end`, which may be a weekend or holiday, and not a
    # live ticker missing a session or two at the end.
    if calendar is None:
        calendar = frame["date"].unique()
    calendar = np.sort(np.asarray(pd.DatetimeIndex(calendar), dtype="datetime64[ns]"))
    calendar = calendar[calendar <= np.datetime64(end)]
    delisted_before = calendar[max(len(calendar) - 1 - DELISTING_GAP, 0)]

    out = []
    for ticker, group in frame.groupby("ticker", sort=False):
        ticker_ended_early = group["date"].iloc[-1] < delisted_before
        atr = indicators.atr(group, ATR_PERIOD).to_numpy(dtype=float)
        for cell in cells:
            out.append(_ticker_cell(group, atr, cell, side, ticker_ended_early).assign(ticker=ticker))
    if not out:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.concat(out, ignore_index=True)[OUTPUT_COLUMNS]


def _ticker_cell(
    group: pd.DataFrame, atr: np.ndarray, cell: BarrierCell, side: str, ticker_ended_early: bool
) -> pd.DataFrame:
    h = cell.horizon
    n = len(group)
    o = group["open"].to_numpy(dtype=float)
    hi = group["high"].to_numpy(dtype=float)
    lo = group["low"].to_numpy(dtype=float)
    cl = group["close"].to_numpy(dtype=float)
    dates = group["date"].to_numpy()

    # Pad the future with NaN so every decision row t has a full window of bars
    # t+1 .. t+h; rows whose window runs off the end are resolved below.
    pad = np.full(h, np.nan)
    wo = sliding_window_view(np.concatenate([o[1:], pad]), h)[:n]
    wh = sliding_window_view(np.concatenate([hi[1:], pad]), h)[:n]
    wl = sliding_window_view(np.concatenate([lo[1:], pad]), h)[:n]
    wc = sliding_window_view(np.concatenate([cl[1:], pad]), h)[:n]
    available = np.minimum(np.arange(n - 1, -1, -1), h)  # future bars that exist per row

    p0 = wo[:, 0]
    a = atr
    if side == LONG:
        target, stop = p0 + cell.upper_atr * a, p0 - cell.lower_atr * a
        reach_target = wh >= target[:, None]
        reach_stop = wl <= stop[:, None]
        gap_target = wo >= target[:, None]
        gap_stop = wo <= stop[:, None]
    else:
        target, stop = p0 - cell.upper_atr * a, p0 + cell.lower_atr * a
        reach_target = wl <= target[:, None]
        reach_stop = wh >= stop[:, None]
        gap_target = wo <= target[:, None]
        gap_stop = wo >= stop[:, None]

    # First bar where each barrier is reached (h = never).
    first_target = np.where(reach_target.any(axis=1), reach_target.argmax(axis=1), h)
    first_stop = np.where(reach_stop.any(axis=1), reach_stop.argmax(axis=1), h)
    same_bar = (first_target == first_stop) & (first_target < h)
    rows = np.arange(n)
    idx = np.minimum(first_target, h - 1)
    # On a shared bar, an open already beyond one barrier decides it; otherwise
    # the tie goes to the stop.
    target_by_gap = same_bar & gap_target[rows, idx]
    tie = same_bar & ~gap_target[rows, idx] & ~gap_stop[rows, idx]
    target_first = (first_target < first_stop) | target_by_gap
    stop_first = (first_stop < first_target) | (same_bar & ~target_by_gap)

    hit = np.where(target_first, 1.0, np.where(stop_first, -1.0, 0.0))
    hit_bar = np.where(target_first, first_target, np.where(stop_first, first_stop, np.nan))

    # Exit price: the barrier, or the open if the bar gapped through it.
    t_open = wo[rows, np.minimum(first_target, h - 1)]
    s_open = wo[rows, np.minimum(first_stop, h - 1)]
    if side == LONG:
        target_fill = np.where(t_open >= target, t_open, target)
        stop_fill = np.where(s_open <= stop, s_open, stop)
    else:
        target_fill = np.where(t_open <= target, t_open, target)
        stop_fill = np.where(s_open >= stop, s_open, stop)
    last_idx = np.clip(available - 1, 0, h - 1)
    last_close = wc[rows, last_idx]
    exit_price = np.where(target_first, target_fill, np.where(stop_first, stop_fill, last_close))

    with warnings.catch_warnings():
        # The last rows' windows are all padding; they're masked out below.
        warnings.simplefilter("ignore", RuntimeWarning)
        mfe_price = np.nanmax(wh, axis=1) if side == LONG else np.nanmin(wl, axis=1)
        mae_price = np.nanmin(wl, axis=1) if side == LONG else np.nanmax(wh, axis=1)
    sign = 1.0 if side == LONG else -1.0
    ret = sign * (exit_price / p0 - 1.0)
    mfe = sign * (mfe_price - p0) / a
    mae = sign * (p0 - mae_price) / a

    # Incomplete windows resolve only when the ticker's own history ended
    # (delisting). Windows that run into the dataset's end are NaN even if a
    # barrier was already hit: keeping only the early hits would bias hit rates
    # near the boundary.
    complete = available >= h
    truncated = ~complete & ticker_ended_early & (available > 0)
    valid = (complete | truncated) & np.isfinite(a) & np.isfinite(p0) & (a > 0)

    end_pos = np.where(complete, rows + h, rows + np.maximum(available, 1))
    end_pos = np.clip(end_pos, 0, n - 1)
    label_end = np.where(valid, dates[end_pos], np.datetime64("NaT", "ns"))

    def masked(x):
        return np.where(valid, x, np.nan)

    return pd.DataFrame({
        "date": dates,
        "horizon": h,
        "upper": cell.upper,
        "lower": cell.lower,
        "upper_atr": cell.upper_atr,
        "lower_atr": cell.lower_atr,
        "side": side,
        "entry_price": masked(p0),
        "atr": masked(a),
        "hit": masked(hit),
        "hit_day": masked(hit_bar + 1),
        "exit_price": masked(exit_price),
        "ret": masked(ret),
        "tie": valid & tie,
        "truncated": valid & truncated,
        "mfe_atr": masked(mfe),
        "mae_atr": masked(mae),
        "label_end_date": pd.to_datetime(label_end),
    })
