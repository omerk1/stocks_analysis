"""Synthetic data for the harness gates (`docs/modeling/VALIDATION_HARNESS.md` §8).
Not used by real analysis.

Two generators:

- `planted_panel` -- one barrier cell's rows with labels **drawn from known
  probabilities** (gates 1 and 2). A per-ticker feature `x` (AR(1), mean 0,
  variance 1) raises P(+1) by `delta` whenever it is above 0, taking it from
  P(-1). Because the probabilities are known, the gain a perfect model would
  have over B0 is an exact number (`oracle_brier_gain`), not an estimate. A
  market-wide `regime` moves every ticker's base rates together, slowly over
  dates, so outcomes are correlated within and across dates and the
  date-block bootstrap has real work to do; no feature carries it. Tickers
  join late and delist early, as in the point-in-time universe; a label
  whose window runs past its ticker's last bar is `truncated` and ends on
  that bar, as `labels/barriers.py` does.
- `synthetic_bars` -- OHLCV random walks on the same kind of calendar, for
  the gates that run production code on bars (3, leakage; 4, purge).

The calendar is weekdays minus US federal holidays: not the exchange
calendar, but irregular in the same way, so "t + H trading days" is never
"t + 7H/5 calendar days".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

PANEL_START = "2011-01-03"
PANEL_END = "2021-12-31"


def trading_days(start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DatetimeIndex:
    days = pd.bdate_range(start, end)
    return days.difference(USFederalHolidayCalendar().holidays(start, end))


def ar1(n_steps: int, n_series: int, rho: float, rng: np.random.Generator, sd: float = 1.0) -> np.ndarray:
    """(n_steps, n_series) stationary AR(1) paths with marginal sd `sd`."""
    out = np.empty((n_steps, n_series))
    out[0] = rng.normal(0.0, sd, n_series)
    shock_sd = sd * math.sqrt(1.0 - rho ** 2)
    for i in range(1, n_steps):
        out[i] = rho * out[i - 1] + rng.normal(0.0, shock_sd, n_series)
    return out


def _lifetimes(days: pd.DatetimeIndex, n_tickers: int, late_share: float, delist_share: float,
               rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """First and last calendar position per ticker: a `late_share` join in the
    first 60% of the calendar, a `delist_share` leave between 25% and 90%."""
    n = len(days)
    first = np.where(rng.uniform(size=n_tickers) < late_share, rng.integers(0, int(0.6 * n), n_tickers), 0)
    leave = rng.integers(int(0.25 * n), int(0.9 * n), n_tickers)
    last = np.where(rng.uniform(size=n_tickers) < delist_share, np.maximum(leave, first + 260), n - 1)
    return first, np.minimum(last, n - 1)


# ---------------------------------------------------------------- planted panel

@dataclass(frozen=True)
class PlantedSpec:
    n_tickers: int = 200
    start: str = PANEL_START
    end: str = PANEL_END
    horizon: int = 21
    upper: float = 2.0
    lower: float = 1.5
    delta: float = 0.10          # P(+1) uplift when x > 0, taken from P(-1)
    rho: float = 0.7             # day-to-day persistence of x (and of `noise`)
    p_up: float = 0.30           # base rates at regime 0 with x <= 0
    p_down: float = 0.40
    regime_sd: float = 0.04      # market-wide shift of P(+1) vs P(-1), same for every ticker
    regime_rho: float = 0.98
    late_share: float = 0.15
    delist_share: float = 0.25
    seed: int = 0


def oracle_brier_gain(delta: float) -> float:
    """Expected (model - B0) three-class Brier for the true P(class | x): each
    of the up and down classes contributes -delta^2 * Var(1[x > 0]) =
    -delta^2 / 4. Holds whatever the regime does, since x doesn't see it."""
    return -0.5 * delta ** 2


def oracle_stale_brier_gain(delta: float, rho: float) -> float:
    """The same for a model that only sees x one bar late. Its best guess of
    1[x_t > 0] is g = Phi(c * x_{t-1}) with c = rho / sqrt(1 - rho^2), and
    the gain is -2 * delta^2 * Var(g), where Var(g) = arcsin(c^2 / (1 + c^2)) / (2 pi)."""
    c2 = rho ** 2 / (1.0 - rho ** 2)
    var_g = math.asin(c2 / (1.0 + c2)) / (2.0 * math.pi)
    return -2.0 * delta ** 2 * var_g


def expected_uplift(delta: float, rho: float, stale: bool) -> float:
    """Mean P(+1) where the model's feature is above 0 minus where it's below,
    for the true conditional probabilities: `delta` for x itself; for x one
    bar late, delta * 2 * arcsin(rho) / pi (E[Phi(c x) | x > 0] = 1/2 + arcsin(rho) / pi)."""
    return delta * 2.0 * math.asin(rho) / math.pi if stale else delta


def planted_panel(spec: PlantedSpec = PlantedSpec()) -> pd.DataFrame:
    """One row per (ticker, date) a ticker is listed. Columns:

        ticker, date
        x, noise, x_stale     the planted feature, an unrelated one with the same
                              persistence, and x one bar late (NaN on a ticker's first row)
        p_up_true, p_down_true, p_neither_true
        hit, ret              the drawn label and its trade return
        atr, close_t          ATR and decision close (close_t = 1, so atr is ATR %)
        label_end_date, truncated

    Labels are NaN where the window runs past the calendar's end (as the
    labeler does at the holdout boundary) and on a delisted ticker's last
    row (no bar to enter on).
    """
    rng = np.random.default_rng(spec.seed)
    days = trading_days(spec.start, spec.end)
    n_days, n = len(days), spec.n_tickers
    first, last = _lifetimes(days, n, spec.late_share, spec.delist_share, rng)

    x = ar1(n_days, n, spec.rho, rng)
    noise = ar1(n_days, n, spec.rho, rng)
    regime = ar1(n_days, 1, spec.regime_rho, rng, sd=spec.regime_sd)
    atr_pct = rng.uniform(0.01, 0.04, n)

    pos = np.arange(n_days)[:, None]
    listed = (pos >= first) & (pos <= last)
    ti, di = np.nonzero(listed.T)  # ticker-major order
    frame = pd.DataFrame({
        "ticker": np.array([f"SYN{i:04d}" for i in range(n)])[ti],
        "date": days[di],
        "x": x[di, ti],
        "noise": noise[di, ti],
    })
    frame["x_stale"] = frame.groupby("ticker")["x"].shift(1)

    up = spec.p_up + regime[di, 0] + spec.delta * (frame["x"].to_numpy() > 0)
    down = spec.p_down - regime[di, 0] - spec.delta * (frame["x"].to_numpy() > 0)
    up, down = np.clip(up, 0.01, 0.98), np.clip(down, 0.01, 0.98)  # never binds at the defaults
    neither = 1.0 - up - down
    u = rng.uniform(size=len(frame))
    hit = np.where(u < up, 1.0, np.where(u < up + down, -1.0, 0.0))
    a = atr_pct[ti]
    ret = np.where(hit == 1, spec.upper * a, np.where(hit == -1, -spec.lower * a, rng.normal(0.0, 0.5 * a)))

    end_pos = di + spec.horizon
    ticker_last = last[ti]
    delisted = ticker_last < n_days - 1
    truncated = delisted & (end_pos > ticker_last) & (di < ticker_last)
    valid = (end_pos <= np.minimum(ticker_last, n_days - 1)) | truncated
    end_pos = np.where(truncated, ticker_last, np.minimum(end_pos, n_days - 1))

    frame["p_up_true"], frame["p_down_true"], frame["p_neither_true"] = up, down, neither
    frame["hit"] = np.where(valid, hit, np.nan)
    frame["ret"] = np.where(valid, ret, np.nan)
    frame["atr"] = a
    frame["close_t"] = 1.0
    frame["label_end_date"] = pd.Series(days[end_pos]).where(valid).to_numpy()
    frame["truncated"] = truncated
    return frame


def shuffle_within_date(panel: pd.DataFrame, columns: tuple[str, ...] = ("hit", "ret"), seed: int = 0) -> pd.DataFrame:
    """Permute `columns` (together, as one outcome) among the rows of each
    date. Each date keeps its own outcome mix; which ticker got which outcome
    is lost."""
    rng = np.random.default_rng(seed)
    out = panel.copy()
    order = np.lexsort((rng.uniform(size=len(out)), out["date"].to_numpy()))
    by_date = np.argsort(out["date"].to_numpy(), kind="stable")
    for col in columns:
        values = out[col].to_numpy()
        shuffled = values.copy()
        shuffled[by_date] = values[order]
        out[col] = shuffled
    return out


# ---------------------------------------------------------------- bars

def synthetic_bars(
    n_tickers: int = 30, start: str = "2010-01-04", end: str = PANEL_END,
    late_share: float = 0.15, delist_share: float = 0.25, seed: int = 0,
) -> pd.DataFrame:
    """Long OHLCV bars (ticker, date, open, high, low, close, volume), random
    walks with gaps at the open, only while each ticker is listed."""
    rng = np.random.default_rng(seed)
    days = trading_days(start, end)
    first, last = _lifetimes(days, n_tickers, late_share, delist_share, rng)
    parts = []
    for i in range(n_tickers):
        d = days[first[i]:last[i] + 1]
        m = len(d)
        close = 50.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.012 + 0.0005 * i, m)))
        open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.006, m))
        high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.008, m)))
        low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.008, m)))
        parts.append(pd.DataFrame({
            "ticker": f"SYN{i:04d}", "date": d, "open": open_, "high": high, "low": low, "close": close,
            "volume": rng.lognormal(14.5, 0.4, m),
        }))
    return pd.concat(parts, ignore_index=True)
