"""What did big winners look like before their run? An exploration: descriptive
numbers only, never findings (`docs/book-ideas/TASKS.md`, task 3).

A "big winner" start date is an S&P 500 stock-date (the model's eligible rows)
whose next-252-trading-day return is +100% or more. Entry is the next day's
open (one-bar lag: the inputs on date t use t's close); exit is the close 252
market trading days after t, or the last close before that if the stock stopped
trading (delisted names keep their terminal return). Start dates stop at
2020-12-31, so no exit reads past 2021-12-31.

For every model input in the cached feature files, each row gets its
cross-sectional percentile within its date. The gap is a winner's percentile
minus the mean percentile of the non-winners on the same date, averaged over
winner rows and divided by the input's percentile SD in that sub-period. The
momentum-adjusted gap compares against non-winners on the same date AND in the
same 12-1 month momentum decile.

Reads the feature caches and the market database read-only; writes only to
`output/book_ideas_big_winners/`.

    venv/bin/python scripts/book_ideas_big_winners.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.models import dataset

FEATURES = Path("data/models/features")
CACHES = ("sp500_fund", "sp500_levels")  # fund: non-level inputs incl. valuation; levels: the level inputs
RAW_DB = Path("data/raw/market_data.sqlite")
OUT = Path("output/book_ideas_big_winners")
LAST_START = pd.Timestamp("2020-12-31")
DATA_END = pd.Timestamp("2021-12-31")
HORIZON, WIN, LOSE = 252, 1.0, -0.5
PERIODS = {"2010-13": ("2010-01-01", "2013-12-31"), "2014-17": ("2014-01-01", "2017-12-31"),
           "2018-20": ("2018-01-01", "2020-12-31")}
THRESHOLD_SD = 0.3


def load_inputs() -> tuple[pd.DataFrame, list[str]]:
    frames, cols = [], []
    for name in CACHES:
        manifest = json.loads((FEATURES / name / "model_features.json").read_text())
        assert manifest["end"] <= str(DATA_END.date()) and not manifest["open_holdout"]
        new = [c for c in manifest["columns"] if c != "sector" and c not in cols]
        f = pd.read_parquet(FEATURES / name / "model_features.parquet", columns=["ticker", "date", *new])
        frames.append(f[f["date"] <= LAST_START].set_index(["ticker", "date"]))
        cols += new
    return frames[0].join(frames[1], how="inner").reset_index(), cols


def forward_returns(rows: pd.DataFrame) -> pd.DataFrame:
    conn = db.get_connection(f"file:{RAW_DB.resolve()}?mode=ro", uri=True)
    tickers = sorted(rows["ticker"].unique())
    bars = dataset.read_bars_bulk(conn, tickers, dataset.LABEL_BASIS, rows["date"].min(), DATA_END,
                                  fallback=dataset.LABEL_FALLBACK)
    conn.close()
    assert bars["date"].max() <= DATA_END
    cal = pd.DatetimeIndex(np.sort(bars["date"].unique()))
    pos = pd.Series(np.arange(len(cal)), index=cal)
    out = rows[["ticker", "date"]].copy()
    i = pos.reindex(out["date"]).to_numpy()
    assert not np.isnan(i).any() and i.max() + HORIZON < len(cal)
    i = i.astype(int)
    out["entry_date"] = cal[i + 1]
    out["exit_date"] = cal[i + HORIZON]
    b = bars[["ticker", "date", "open", "close"]]
    out = out.merge(b[["ticker", "date", "open"]].rename(columns={"date": "entry_date"}),
                    on=["ticker", "entry_date"], how="left")
    last_bar = bars.groupby("ticker")["date"].max().rename("last_bar")
    out = out.merge(last_bar, left_on="ticker", right_index=True, how="left")
    out = out.sort_values("exit_date")
    out = pd.merge_asof(out, b[["ticker", "date", "close"]].sort_values("date"), left_on="exit_date",
                        right_on="date", by="ticker", direction="backward", suffixes=("", "_exit"))
    out["fwd_252"] = out["close"] / out["open"] - 1
    out["terminal"] = out["last_bar"] < out["exit_date"]
    return out[["ticker", "date", "fwd_252", "terminal"]]


def gaps(pct: pd.DataFrame, win: pd.Series, keys: list[pd.Series], sd: pd.Series) -> pd.Series:
    """Mean over winner rows of (percentile - mean of non-winners in the same
    `keys` cell), in units of `sd`."""
    others_mean = pct.where(~win).groupby(keys).transform("mean")
    return (pct[win] - others_mean[win]).mean() / sd


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    inputs, cols = load_inputs()
    labels = forward_returns(inputs)
    df = inputs.merge(labels, on=["ticker", "date"], how="inner")
    df = df[df["fwd_252"].notna()].reset_index(drop=True)
    df["winner"] = df["fwd_252"] >= WIN

    pct = df[cols].astype("float64").groupby(df["date"]).rank(pct=True)
    decile = np.ceil(pct["mom_12_1"] * 10).clip(1, 10)

    results, counts = [], []
    for period, (a, b) in PERIODS.items():
        m = df["date"].between(a, b).to_numpy()
        p, w, d = pct[m], df.loc[m, "winner"], df.loc[m, "date"]
        sd = p.std()
        raw = gaps(p, w, [d], sd)
        has_mom = decile[m].notna()
        adj = gaps(p[has_mom], w[has_mom], [d[has_mom], decile[m][has_mom]], sd)
        n_w = p[w].notna().sum()
        # The same raw gap for big losers (-50% or worse): an input that marks both
        # tails marks big moves, not big winners.
        loser = df.loc[m, "fwd_252"] <= LOSE
        lose = gaps(p, loser, [d], sd)
        results.append(pd.DataFrame({"period": period, "input": cols, "raw_sd": raw.to_numpy(),
                                     "mom_adj_sd": adj.to_numpy(), "loser_raw_sd": lose.to_numpy(),
                                     "winner_rows": n_w.to_numpy(),
                                     "winner_dates": [d[w & p[c].notna()].nunique() for c in cols]}))
        sub = df[m]
        counts.append({"period": period, "rows": len(sub), "dates": sub["date"].nunique(),
                       "winner_rows": int(sub["winner"].sum()), "winner_dates": sub.loc[sub["winner"], "date"].nunique(),
                       "winner_tickers": sub.loc[sub["winner"], "ticker"].nunique(),
                       "winner_share": float(sub["winner"].mean()),
                       "loser_rows": int((sub["fwd_252"] <= LOSE).sum()),
                       "loser_tickers": sub.loc[sub["fwd_252"] <= LOSE, "ticker"].nunique(),
                       "winner_terminal_rows": int((sub["winner"] & sub["terminal"]).sum()),
                       "terminal_rows": int(sub["terminal"].sum())})
    res = pd.concat(results, ignore_index=True)
    res.to_csv(OUT / "gaps_by_period.csv", index=False)
    pd.DataFrame(counts).to_csv(OUT / "counts.csv", index=False)

    wide = res.pivot(index="input", columns="period", values=["raw_sd", "mom_adj_sd", "loser_raw_sd"])
    raw_pass = (wide["raw_sd"].abs() >= THRESHOLD_SD).all(axis=1) & (np.sign(wide["raw_sd"]).nunique(axis=1) == 1)
    adj_pass = (wide["mom_adj_sd"].abs() >= THRESHOLD_SD).all(axis=1) & (np.sign(wide["mom_adj_sd"]).nunique(axis=1) == 1)
    wide[("pass", "raw")], wide[("pass", "mom_adj")] = raw_pass, adj_pass
    wide.to_csv(OUT / "gaps_wide.csv")
    pd.set_option("display.width", 250, "display.max_rows", 200)
    print(pd.DataFrame(counts).to_string(index=False))
    print(wide.sort_values(("raw_sd", "2014-17")).round(2).to_string())
    top = df.loc[df["winner"]].groupby("ticker")["fwd_252"].agg(["max", "size"])
    print("winner tickers by best 252-day return:\n", top.sort_values("max").tail(10).round(2).to_string())
    print("winner rows by start year:\n", df.loc[df["winner"], "date"].dt.year.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
