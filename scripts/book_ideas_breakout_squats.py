"""After a base breakout: squats and closes below the 20-day average (exploration).

Book-ideas task 10 (`docs/book-ideas/TASKS.md`, "After a breakout: squats and closes
below the 20-day average"). A cheap descriptive look; nothing here is a finding.

Events: the base-breakout finder (`src/signals/base_breakout/detect.py`, default
settings) run on each ticker's bars with the bar's HIGH in the close slot, so a
breakout is the first bar trading more than 0.25 ATR above the base ceiling. (The
finder on closes can't produce a squat at all: its breakout bar must close above the
level by construction.) Base geometry (length, depth, touches) uses only high/low, so
it is unchanged. Kept: the ticker was an S&P 500 member on the breakout date,
2010-01-01..2021-12-31, delisted members included (Tiingo bars where yfinance has none).

Groups, all entered at an open after the information is known (one-bar lag):
  squat      the breakout bar closes below the breakout level; entry next open.
  not_squat  every other breakout, entry next open: the fair comparison for squats,
             since both are known at the same bar ("neither" is picked on 10 later bars).
  below_20   not a squat, and a close below the 20-day SMA within the 10 bars after
             the breakout; entry at the open after that close (that's when it's known).
  neither    not a squat, no such close in the 10 bars; entry next open after the
             breakout, and also (neither_late) at the open 11 bars after it, the first
             bar where "neither" is actually known.

Return over h bars from entry: close of the h-th bar held / entry open - 1. A ticker
whose bars stop before then (delisted) takes its last close; a window cut by the
2021-12-31 data end is dropped. Stop: a low at or under the base's low within the h
bars. Control: same entry date, S&P 500 members in the same tercile of 12-1 month
momentum AND of 1-month return (both as of the close before entry); delta = event
return - control cell mean. CIs: 90% bootstrap over calendar months of entry.

Run: venv python scripts/book_ideas_breakout_squats.py  (writes output/breakout_squats/)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing.ticker_renames import apply_renames
from src.foundation.market_common import indicators
from src.foundation.market_common.price_basis import PriceBasis
from src.models.dataset import check_holdout, membership_rows, read_bars_bulk
from src.signals.base_breakout import detect as base_breakout

START, END = "2010-01-01", "2021-12-31"
LOAD_FROM = "2008-01-01"  # warmup: 504-bar level lookback, 252-bar momentum
HORIZONS = (21, 63)
WINDOW = 10  # bars after the breakout for the 20-day-close and new-high checks
N_BOOT = 2000
COST_BPS = 10.0
OUT = Path("output/breakout_squats")


def load(conn: sqlite3.Connection) -> pd.DataFrame:
    check_holdout(END)
    members = apply_renames(conn, db.read_index_membership(conn, "sp500"))
    end = pd.to_datetime(members["end_date"]).fillna(pd.Timestamp.max)
    tickers = sorted(members.loc[(end >= LOAD_FROM) & (pd.to_datetime(members["start_date"]) <= END),
                                 "ticker"].unique())
    bars = read_bars_bulk(conn, tickers, PriceBasis.TOTAL_RETURN, LOAD_FROM, END, fallback=True)
    print(f"bars: {len(bars):,} rows, {bars['ticker'].nunique()} tickers, sources {bars.attrs['price_sources']}")
    cal = pd.DatetimeIndex(bars["date"].unique()).sort_values()
    member = membership_rows(conn, ("sp500",), cal)[["ticker", "date"]].assign(member=True)
    bars = bars.merge(member, on=["ticker", "date"], how="left")
    bars["member"] = bars["member"].fillna(False).astype(bool)
    return bars.sort_values(["ticker", "date"], ignore_index=True)


def add_columns(bars: pd.DataFrame) -> pd.DataFrame:
    g = bars.groupby("ticker", sort=False)
    bars["pos"] = g.cumcount()
    bars["last_pos"] = g["pos"].transform("max")
    data_end = bars["date"].max()
    # A ticker whose bars stop before the data end left the market: its window is
    # completed with its last close (terminal return). One that runs to the end is cut.
    bars["delisted"] = g["date"].transform("max") < data_end - pd.Timedelta(days=7)
    bars["sma_20"] = g["close"].transform(lambda s: s.rolling(20).mean())
    close_g = g["close"]
    bars["mom_12_1"] = close_g.shift(21) / close_g.shift(252) - 1
    bars["mom_1_0"] = close_g.pct_change(21, fill_method=None)
    last_close = g["close"].transform("last")
    for h in HORIZONS:
        exit_close = close_g.shift(-(h - 1))
        exit_close = exit_close.where(exit_close.notna() | ~bars["delisted"], last_close)
        bars[f"ret_{h}"] = exit_close / bars["open"] - 1
        # The low over the h bars held, entry bar included, for the stop check.
        rev_low = bars["low"].iloc[::-1].groupby(bars["ticker"].iloc[::-1], sort=False)
        bars[f"min_low_{h}"] = rev_low.transform(lambda s: s.rolling(h, min_periods=1).min()).iloc[::-1]
    # Control strata as of the close before the entry bar (one-bar lag).
    for col in ("mom_12_1", "mom_1_0"):
        lagged = g[col].shift(1)
        bars[f"{col}_t"] = lagged.where(bars["member"]).groupby(bars["date"]).transform(
            lambda x: pd.qcut(x, 3, labels=False, duplicates="drop"))
    return bars


def find_breakouts(bars: pd.DataFrame) -> pd.DataFrame:
    config = base_breakout.BreakoutRetestConfig()
    rows = []
    offsets = bars.groupby("ticker", sort=False).indices
    for ticker, idx in offsets.items():
        frame = bars.iloc[idx]
        atr = indicators.atr(frame, 14).reset_index(drop=True)
        intraday = frame[["high", "low"]].reset_index(drop=True).assign(close=frame["high"].to_numpy())
        for ep in base_breakout.detect(intraday, atr, config):
            rows.append((idx[ep.breakout], idx[ep.base_start], ep.level, ep.base_bars, ep.depth_pct))
    ev = pd.DataFrame(rows, columns=["i", "base_start_i", "level", "base_bars", "depth_pct"])
    low = bars["low"].to_numpy()
    ev["base_low"] = [low[a:b].min() for a, b in zip(ev["base_start_i"], ev["i"])]
    ev["date"] = bars["date"].to_numpy()[ev["i"]]
    ev = ev[(ev["date"] >= START) & bars["member"].to_numpy()[ev["i"]]].reset_index(drop=True)
    return ev


def classify(bars: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    close, high = bars["close"].to_numpy(), bars["high"].to_numpy()
    below = (bars["close"] < bars["sma_20"]).to_numpy()
    remaining = (bars["last_pos"] - bars["pos"]).to_numpy()[ev["i"]]
    ev = ev[remaining >= WINDOW + 1].reset_index(drop=True)  # need the 10-bar window + an entry bar
    after = ev["i"].to_numpy()[:, None] + np.arange(1, WINDOW + 1)  # bars t+1..t+10
    ev["squat"] = close[ev["i"]] < ev["level"].to_numpy()
    ev["new_high_10"] = high[after].max(axis=1) > high[ev["i"]]
    hits = below[after]
    ev["below_20"] = ~ev["squat"] & hits.any(axis=1)
    ev["below_20_bar"] = np.where(ev["below_20"], hits.argmax(axis=1) + 1, -1)
    ev["squat_and_below_20"] = ev["squat"] & hits.any(axis=1)
    return ev


def entries(ev: pd.DataFrame) -> pd.DataFrame:
    """One row per (group, event) with its entry bar's global index."""
    parts = {
        "all": ev.assign(entry=ev["i"] + 1),
        "squat": ev[ev["squat"]].assign(entry=lambda d: d["i"] + 1),
        "not_squat": ev[~ev["squat"]].assign(entry=lambda d: d["i"] + 1),
        "below_20": ev[ev["below_20"]].assign(entry=lambda d: d["i"] + d["below_20_bar"] + 1),
        "neither": ev[~ev["squat"] & ~ev["below_20"]].assign(entry=lambda d: d["i"] + 1),
        "neither_late": ev[~ev["squat"] & ~ev["below_20"]].assign(entry=lambda d: d["i"] + WINDOW + 1),
    }
    return pd.concat([p.assign(group=k) for k, p in parts.items()], ignore_index=True)


def attach(bars: pd.DataFrame, en: pd.DataFrame) -> pd.DataFrame:
    member = bars[bars["member"]]
    cols = ["date", "mom_12_1_t", "mom_1_0_t"]
    for h in HORIZONS:
        r = f"ret_{h}"
        cell = member.dropna(subset=[r, "mom_12_1_t", "mom_1_0_t"]).groupby(cols)[r].mean().rename(f"ctl_{h}")
        en[r] = bars[r].to_numpy()[en["entry"]]
        stop = (bars[f"min_low_{h}"].to_numpy()[en["entry"]] <= en["base_low"].to_numpy()).astype(float)
        # A cut window (data end, live ticker) has no return and no complete stop check.
        en[f"stop_{h}"] = np.where(en[r].isna(), np.nan, stop)
        keys = bars[cols].iloc[en["entry"]].reset_index(drop=True)
        en[f"ctl_{h}"] = keys.merge(cell.reset_index(), on=cols, how="left")[f"ctl_{h}"].to_numpy()
        en[f"delta_{h}"] = en[r] - en[f"ctl_{h}"]
    en["entry_date"] = bars["date"].to_numpy()[en["entry"]]
    en["month"] = en["entry_date"].dt.to_period("M")
    return en


def boot_means(en: pd.DataFrame, value: str, groups: list[str], rng) -> dict[str, np.ndarray]:
    """Bootstrap draws of each group's mean `value`, resampling calendar months jointly
    across groups (so differences between groups get a CI too)."""
    d = en[en["group"].isin(groups)].dropna(subset=[value])
    months = np.sort(d["month"].unique())
    pick = rng.integers(0, len(months), size=(N_BOOT, len(months)))
    weights = np.zeros((N_BOOT, len(months)))
    np.add.at(weights, (np.arange(N_BOOT)[:, None], pick), 1)
    out = {}
    for gname in groups:
        sub = d[d["group"] == gname]
        s = sub.groupby("month")[value].agg(["sum", "count"]).reindex(months, fill_value=0)
        out[gname] = (weights @ s["sum"].to_numpy()) / (weights @ s["count"].to_numpy())
    return out


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def ci(draws: np.ndarray) -> str:
    lo, hi = np.nanpercentile(draws, [5, 95])
    return f"[{pct(lo)}, {pct(hi)}]"


def report(en: pd.DataFrame) -> str:
    rng = np.random.default_rng(0)
    groups = ["all", "squat", "not_squat", "below_20", "neither", "neither_late"]
    boots = {h: boot_means(en, f"delta_{h}", groups, rng) for h in HORIZONS}
    lines = ["| group | events | dates | 21d raw | 21d vs control [90% CI] | 63d raw | "
             "63d vs control [90% CI] | stop hit 63d | new high in 10 bars |",
             "|---|---|---|---|---|---|---|---|---|"]
    for gname in groups:
        d = en[en["group"] == gname]
        cells = [gname, f"{len(d):,}", f"{d['entry_date'].nunique():,}"]
        for h in HORIZONS:
            cells += [pct(d[f"ret_{h}"].mean()),
                      f"{pct(d[f'delta_{h}'].mean())} {ci(boots[h][gname])}"]
        cells += [f"{d['stop_63'].mean() * 100:.1f}%", f"{d['new_high_10'].mean() * 100:.1f}%"]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    for a, b in (("squat", "not_squat"), ("squat", "neither"), ("below_20", "neither"), ("below_20", "neither_late")):
        parts = []
        for h in HORIZONS:
            da, db_ = en.loc[en["group"] == a, f"delta_{h}"].mean(), en.loc[en["group"] == b, f"delta_{h}"].mean()
            parts.append(f"{h}d {pct(da - db_)} {ci(boots[h][a] - boots[h][b])}")
        lines.append(f"- {a} minus {b} (control-matched deltas): " + "; ".join(parts))
    ev = en[en["group"] == "all"]
    lines += ["",
              f"- events with a matched control at 63d: {en['delta_63'].notna().sum():,} of {len(en):,} rows",
              f"- squats that also closed under the 20-day SMA within 10 bars: "
              f"{int(ev['squat_and_below_20'].sum())} of {int(ev['squat'].sum())}",
              f"- tickers with events: {ev['ticker'].nunique()}, delisted among them: "
              f"{ev.loc[ev['delisted'], 'ticker'].nunique()}",
              f"- cost: {COST_BPS:g} bps round trip per event, against per-event deltas above"]
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db.default_db_path('data/raw')}?mode=ro", uri=True)
    bars = add_columns(load(conn))
    assert bars["date"].max() <= pd.Timestamp(END)
    ev = classify(bars, find_breakouts(bars))
    ev["ticker"] = bars["ticker"].to_numpy()[ev["i"]]
    ev["delisted"] = bars["delisted"].to_numpy()[ev["i"]]
    en = attach(bars, entries(ev))
    en.to_csv(OUT / "entries.csv", index=False)
    text = report(en)
    (OUT / "report.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
