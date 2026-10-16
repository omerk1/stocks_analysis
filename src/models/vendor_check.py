"""Vendor as a hidden future signal (`docs/backlog.md`; checked before E1).

The modeling dataset reads a ticker from Tiingo only when yfinance has no bars
for it at all, which in practice means it was later delisted. If Tiingo's bars
differ systematically from yfinance's, a model can learn the vendor and with it
the delisting -- a leak no perturbation gate can see, since the values don't
depend on the future, only their vendor does.

Three read-outs, from the model-feature cache plus the raw bars:
- **fingerprints** per vendor: zero-volume days, flat bars (high == low), and
  missing sessions against the common calendar -- data-quality traits with no
  economic meaning;
- **feature shift**: per model input, the standardised mean difference between
  Tiingo rows at least `FAR_DAYS` before the ticker's delisting (Tiingo's listing
  end, `tiingo_listings` -- metadata, not holdout prices) and yfinance rows on
  the same dates (far from delisting, so the run-up to it isn't the cause);
- **classifier**: a boosted model telling Tiingo rows from yfinance rows, folds
  grouped by ticker (so it can't memorise names), scored **within date**: the
  chance a Tiingo row outranks a yfinance row on the same day. Tiingo rows sit
  in earlier years, and several inputs drift with the market, so a pooled AUC
  would partly measure "which year". On all rows and on the far rows, with and
  without `sector` (sourced differently).

An AUC near 0.5 on far rows means nothing vendor-specific is learnable. A high
one is not proof of an artefact -- companies that later leave the index can
differ for real years before -- so the fingerprints and the per-column shifts
say which it is.

A fourth read-out, **same ticker** (`same_ticker`), removes that ambiguity:
live tickers stored on both vendors (Tiingo bars for comparison only; they're
still read from yfinance everywhere) get every registered feature computed
twice, once per vendor, on the same dates. Any difference is then the vendor
alone. Ranked inputs are compared raw too (each vendor is ranked only among
its own copies here, which would hide a vendor-wide level shift). It passes
when a vendor classifier can't beat `SAME_TICKER_MAX_AUC` (within date,
ticker-grouped folds) and, for every column, the median gap stays under
`SAME_TICKER_MAX_GAP_SD` cross-sectional SDs, at most
`SAME_TICKER_MAX_SHARE_OFF` of rows are off by more than 0.1 SD, and at most
`SAME_TICKER_MAX_NAN_MISMATCH` are missing on one vendor only. First full run (2026-10-07, 345 tickers, the 15
numeric model inputs plus the 6 ranked ones raw): pass, AUC 0.524, largest median gap
0.011 SD, at most 3.4% of rows off by > 0.1 SD (adx_14). Read-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from src.foundation.data_processing import db
from src.foundation.market_common.price_basis import PriceBasis
from src.models import dataset
from src.models.features import baseline, market, registry

FAR_DAYS = 730
TIINGO_SOURCES = (db.TIINGO, db.TIINGO_SPLIT_ONLY)

SAME_TICKER_MAX_AUC = 0.55
SAME_TICKER_MAX_GAP_SD = 0.05
# A tell on a minority of rows leaves the median gap at 0, so the share off
# matters too. Real data (2026-10-07) peaks at 3.4% (adx_14), from the known
# corporate-action days (`price_disputes.csv`), and 0.5% NaN mismatch.
SAME_TICKER_MAX_SHARE_OFF = 0.05
SAME_TICKER_MAX_NAN_MISMATCH = 0.01
# The level columns' sample (`same_ticker`): their detectors run fresh per vendor.
LEVEL_TICKERS = 20
LEVEL_WEEKS = 26
# Each vendor's bars on each basis, and the splits that go with them.
VENDOR_SOURCES = {
    "yfinance": {PriceBasis.TOTAL_RETURN: db.YFINANCE, PriceBasis.TRADED: db.YFINANCE_SPLIT_ONLY},
    "tiingo": {PriceBasis.TOTAL_RETURN: db.TIINGO, PriceBasis.TRADED: db.TIINGO_SPLIT_ONLY},
}
VENDOR_SPLITS = {"yfinance": db.YFINANCE, "tiingo": db.TIINGO}


def fingerprints(bars: pd.DataFrame, sources: dict[str, str], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Per vendor: share of zero-volume bars, of flat bars (high == low), and of
    sessions missing between each ticker's first and last bar."""
    rows = []
    cal = np.asarray(calendar, dtype="datetime64[ns]")
    for ticker, g in bars.groupby("ticker", sort=False):
        d = g["date"].to_numpy(dtype="datetime64[ns]")
        expected = int(((cal >= d.min()) & (cal <= d.max())).sum())
        rows.append({
            "vendor": "tiingo" if sources.get(ticker) in TIINGO_SOURCES else "yfinance", "ticker": ticker,
            "bars": len(g), "zero_volume": int((g["volume"] <= 0).sum()),
            "flat": int((g["high"] <= g["low"]).sum()), "missing": max(expected - len(g), 0), "expected": expected,
        })
    per = pd.DataFrame(rows)
    out = per.groupby("vendor").agg(tickers=("ticker", "size"), bars=("bars", "sum"), zero_volume=("zero_volume", "sum"),
                                    flat=("flat", "sum"), missing=("missing", "sum"), expected=("expected", "sum"))
    return pd.DataFrame({
        "tickers": out["tickers"], "bars": out["bars"],
        "zero_volume_share": out["zero_volume"] / out["bars"], "flat_bar_share": out["flat"] / out["bars"],
        "missing_session_share": out["missing"] / out["expected"],
    })


def tag_rows(features: pd.DataFrame, sources: dict[str, str], delisted: pd.Series) -> pd.DataFrame:
    """Adds `tiingo` (bool) and `far` (Tiingo row >= FAR_DAYS before its
    ticker's delisting date, `delisted`; every yfinance row counts as far)."""
    out = features.copy()
    out["tiingo"] = out["ticker"].map(sources).isin(TIINGO_SOURCES)
    days_left = (out["ticker"].map(pd.to_datetime(delisted)) - out["date"]).dt.days
    out["far"] = ~out["tiingo"] | (days_left >= FAR_DAYS)
    return out


def feature_shift(rows: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Standardised mean difference (Tiingo far rows minus yfinance rows on the
    dates both have), per column, with the pooled SD."""
    far = rows[rows["far"]]
    dates = set(far.loc[far["tiingo"], "date"])
    far = far[far["date"].isin(dates)]
    t, y = far[far["tiingo"]], far[~far["tiingo"]]
    out = []
    for c in columns:
        a, b = t[c].astype(float), y[c].astype(float)
        sd = np.sqrt((a.var() + b.var()) / 2)
        out.append({"column": c, "tiingo_mean": a.mean(), "yfinance_mean": b.mean(),
                    "smd": (a.mean() - b.mean()) / sd if sd > 0 else np.nan,
                    "tiingo_missing": a.isna().mean(), "yfinance_missing": b.isna().mean()})
    return pd.DataFrame(out).sort_values("smd", key=np.abs, ascending=False, ignore_index=True)


def within_date_auc(scores: np.ndarray, y: np.ndarray, dates: np.ndarray) -> float:
    """Mean over dates of each date's AUC, weighted by its (Tiingo x yfinance)
    pair count: P(a Tiingo row outscores a yfinance row on the same date)."""
    frame = pd.DataFrame({"s": scores, "y": y.astype(bool), "d": dates})
    frame["r"] = frame.groupby("d")["s"].rank()
    g = frame.groupby("d")
    n_pos, n = g["y"].sum(), g.size()
    n_neg = n - n_pos
    rank_sum = frame[frame["y"]].groupby("d")["r"].sum().reindex(n.index, fill_value=0.0)
    pairs = n_pos * n_neg
    ok = pairs > 0
    auc = (rank_sum[ok] - n_pos[ok] * (n_pos[ok] + 1) / 2) / pairs[ok]
    return float((auc * pairs[ok]).sum() / pairs[ok].sum())


def vendor_auc(rows: pd.DataFrame, columns: list[str], n_splits: int = 5, seed: int = 0) -> float:
    """Out-of-sample, within-date AUC for telling Tiingo rows from yfinance
    rows, folds grouped by ticker; only dates that have rows of both."""
    both = rows.groupby("date")["tiingo"].transform(lambda t: t.any() and not t.all())
    rows = rows[both]
    x, y, groups = rows[columns], rows["tiingo"].to_numpy(), rows["ticker"].to_numpy()
    scores = np.full(len(rows), np.nan)
    for train, test in GroupKFold(n_splits=n_splits).split(x, y, groups):
        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                               min_samples_leaf=1000, categorical_features="from_dtype",
                                               random_state=seed)
        model.fit(x.iloc[train], y[train])
        scores[test] = model.predict_proba(x.iloc[test])[:, 1]
    return within_date_auc(scores, y, rows["date"].to_numpy())


def run(features: pd.DataFrame, bars: pd.DataFrame, sources: dict[str, str], calendar: pd.DatetimeIndex,
        delisted: pd.Series) -> dict:
    """`features`: the model-feature cache; `bars`: the label-basis bars of
    the same tickers (for the fingerprints); `delisted`: ticker -> delisting
    date for the Tiingo tickers (Tiingo's listing end)."""
    inputs = [registry.model_input(s) for s in registry.model_specs()]
    missing = [c for c in inputs if c not in features.columns]
    if missing:
        raise ValueError(f"the feature cache lacks registered columns {missing}; rebuild it (build-features)")
    numeric = [c for c in inputs if c != "sector"]
    rows = tag_rows(features, sources, delisted)
    far = rows[rows["far"]]
    return {
        "n_rows": len(rows), "n_tiingo_rows": int(rows["tiingo"].sum()), "n_tiingo_far_rows": int(far["tiingo"].sum()),
        "n_tiingo_tickers": int(rows.loc[rows["tiingo"], "ticker"].nunique()),
        "fingerprints": fingerprints(bars, sources, calendar),
        "feature_shift": feature_shift(rows, numeric),
        "auc": {
            "all_rows": vendor_auc(rows, inputs), "far_rows": vendor_auc(far, inputs),
            "far_rows_without_sector": vendor_auc(far, numeric),
        },
    }


# ---------------------------------------------------------------- same ticker

def both_vendor_tickers(conn, tickers: list[str]) -> list[str]:
    """Of `tickers`, those with bars from both vendors."""
    def has(t, source):
        return conn.execute("SELECT 1 FROM bars_1d WHERE ticker = ? AND source = ? LIMIT 1", (t, source)).fetchone()
    return [t for t in tickers if has(t, db.YFINANCE) and has(t, db.TIINGO)]


def _vendor_bars(conn, tickers: list[str], source: str, start, end) -> pd.DataFrame:
    frames = []
    for i in range(0, len(tickers), 500):
        batch = tickers[i:i + 500]
        frames.append(pd.read_sql_query(
            "SELECT ticker, timestamp, open, high, low, close, volume FROM bars_1d "
            f"WHERE source = ? AND is_partial = 0 AND ticker IN ({','.join('?' * len(batch))}) "
            "AND timestamp >= ? AND timestamp <= ?",
            conn, params=[source, *batch, pd.Timestamp(start).isoformat(),
                          (pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)).isoformat()]))
    bars = pd.concat(frames, ignore_index=True)
    bars["date"] = pd.to_datetime(bars.pop("timestamp")).dt.normalize()
    return bars.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"], ignore_index=True)


def _warm_start(start) -> pd.Timestamp:
    return pd.Timestamp(start) - pd.Timedelta(days=int(1.6 * max(s.warmup_bars for s in registry.REGISTRY)) + 30)


def common_rows(conn, tickers: list[str], start, end) -> pd.DataFrame:
    """(ticker, date) rows both vendors have a bar for, warm-up included: the
    panel columns' membership, so breadth and sector peers average over the
    same names on both sides (a coverage difference isn't a value difference)."""
    rows = [_vendor_bars(conn, tickers, VENDOR_SOURCES[v][PriceBasis.TOTAL_RETURN], _warm_start(start), end)
            [["ticker", "date"]] for v in ("yfinance", "tiingo")]
    return rows[0].merge(rows[1], on=["ticker", "date"])


def vendor_features(conn, tickers: list[str], vendor: str, start, end,
                    membership: pd.DataFrame | None = None, specs=None, sources=None) -> pd.DataFrame:
    """Every registered column (or `specs`', computed by `sources`) for
    `tickers` in [start, end], from `vendor`'s bars and splits only (warm-up
    read before `start`). The panel columns treat
    `tickers` as the index -- `membership` rows of them if given (breadth and
    sector peers over them, each from this vendor) -- and read the benchmark as
    the dataset does, whatever the vendor."""
    specs = tuple(specs) if specs is not None else registry.REGISTRY
    sources = sources if sources is not None else registry.SOURCES
    warm = _warm_start(start)
    bars = {}
    for basis, source in VENDOR_SOURCES[vendor].items():
        bench = dataset.read_bars_bulk(conn, [market.BENCHMARK], basis, warm, end)
        bars[basis] = pd.concat([_vendor_bars(conn, tickers, source, warm, end), bench], ignore_index=True)
    splits = {}
    for t in tickers:
        sp = db.read_splits(conn, t, VENDOR_SPLITS[vendor])
        if not sp.empty:
            splits[t] = sp
    sectors = db.read_ticker_sector(conn).set_index("ticker")["sector"]
    f = registry.compute_registered(bars, splits, specs, sources, rank=False,
                                    context=market.PanelContext(membership=membership, sectors=sectors))
    # Ranked over the compared stocks only, as the cache ranks over its eligible rows.
    f = baseline.add_ranks(f[f["ticker"].isin(tickers)], tuple(s.name for s in specs
                                                              if s.ranked and s.source is not None))
    return f[f["date"].between(pd.Timestamp(start), pd.Timestamp(end))].reset_index(drop=True)


def feature_gaps(yf: pd.DataFrame, ti: pd.DataFrame, columns: list[str],
                 market_wide: tuple[str, ...] = ()) -> pd.DataFrame:
    """Per column, on the (ticker, date) rows both vendors have: the median
    |Tiingo - yfinance| in units of the cross-sectional SD (median over dates
    of the per-date SD of the yfinance values), the share of rows off by more
    than 0.1 SD, and the share where only one vendor is missing the value.
    A `market_wide` column is the same for every ticker on a date, so it has
    no cross-section: its SD is over time instead. A column with no spread
    (constant or empty in the window) has no SD to scale by: it's marked
    `no_spread` and counts rows that differ at all."""
    j = yf.merge(ti, on=["ticker", "date"], suffixes=("_yf", "_ti"))
    out = []
    for c in columns:
        a, b = j[f"{c}_yf"].astype(float), j[f"{c}_ti"].astype(float)
        both = a.notna() & b.notna()
        sd = a[both].std() if c in market_wide else a[both].groupby(j.loc[both, "date"]).std().median()
        diff = (b[both] - a[both]).abs()
        no_spread = not (sd > 0)
        gap = (diff > 0).astype(float) if no_spread else diff / sd
        out.append({"column": c, "median_gap_sd": float(gap.median()) if len(gap) else np.nan,
                    "share_over_0_1sd": float((gap > 0.1).mean()) if len(gap) else np.nan,
                    "nan_mismatch": float((a.isna() != b.isna()).mean()), "no_spread": no_spread})
    return pd.DataFrame(out).sort_values("median_gap_sd", ascending=False, ignore_index=True)


def gate_failures(gaps: pd.DataFrame, auc: float) -> list[str]:
    """Why the same-ticker gate fails (empty list = pass)."""
    out = [] if auc <= SAME_TICKER_MAX_AUC else [f"vendor AUC {auc:.3f} > {SAME_TICKER_MAX_AUC}"]
    for r in gaps.itertuples(index=False):
        if not r.median_gap_sd < SAME_TICKER_MAX_GAP_SD:
            out.append(f"{r.column}: median gap {r.median_gap_sd:.4f} SD")
        if not r.share_over_0_1sd <= SAME_TICKER_MAX_SHARE_OFF:
            out.append(f"{r.column}: {r.share_over_0_1sd:.1%} of rows off by > 0.1 SD")
        if not r.nan_mismatch <= SAME_TICKER_MAX_NAN_MISMATCH:
            out.append(f"{r.column}: {r.nan_mismatch:.1%} of rows missing on one vendor only")
    return out


def _compare(conn, tickers, specs, start, end, seed, sources=None) -> dict:
    """Gaps and the vendor AUC for `specs`' columns on `tickers` in [start, end]."""
    columns = [registry.model_input(s) for s in specs] + [s.name for s in specs if s.ranked]
    members = common_rows(conn, tickers, start, end)
    yf = vendor_features(conn, tickers, "yfinance", start, end, members, specs, sources)
    ti = vendor_features(conn, tickers, "tiingo", start, end, members, specs, sources)
    # Undefined on both vendors throughout (e.g. no benchmark or sectors stored):
    # nothing to compare -- reported, not failed.
    not_compared = [c for c in columns if yf[c].isna().all() and ti[c].isna().all()]
    columns = [c for c in columns if c not in not_compared]
    gaps = feature_gaps(yf, ti, columns, tuple(s.name for s in specs if s.shape == "market_wide"))
    rows = pd.concat([yf.assign(tiingo=False), ti.assign(tiingo=True)], ignore_index=True)
    # Market-wide columns stay out of the classifier: one value per date and
    # vendor, they fingerprint the date's vendor across tickers (the folds hold
    # out tickers, not dates) -- their gaps above are the check.
    market_wide = {s.name for s in specs if s.shape == "market_wide"}
    auc = vendor_auc(rows, [c for c in columns if c not in market_wide], seed=seed)
    return {"n_rows": {"yfinance": len(yf), "tiingo": len(ti)}, "gaps": gaps, "auc": auc,
            "not_compared": not_compared}


def same_ticker(conn, tickers: list[str], start, end, seed: int = 0, level_tickers: int = LEVEL_TICKERS,
                level_weeks: int = LEVEL_WEEKS) -> dict:
    """The same-ticker read-out for `tickers` (stored on both vendors) over
    [start, end]. Compares the numeric model inputs *and*, for ranked inputs,
    the raw values: each vendor is ranked only against its own copy of these
    tickers, so a vendor-wide level shift (every volume at half) leaves the
    ranks equal here -- yet in the dataset Tiingo-read tickers are ranked
    together with yfinance-read ones, where that shift would show. Sector is
    left out (one ticker has the same sector on both vendors).

    The level columns (a detector source, minutes per ticker and vendor) are
    compared on `level_tickers` of them, evenly spaced, over the last
    `level_weeks` weeks to `end`, their detectors run fresh from that window's
    start on each vendor's bars; their gaps join the others', and their own
    classifier is `auc_levels` (same pass bar). 0: not compared."""
    if not tickers:
        raise ValueError("no tickers stored on both vendors")
    specs = [s for s in registry.model_specs() if s.name != "sector"]
    detector = [s for s in specs if registry.is_detector(s)]
    r = _compare(conn, tickers, [s for s in specs if s not in detector], start, end, seed)
    gaps, not_compared, auc_levels, n_level = r["gaps"], r["not_compared"], None, 0
    if detector and level_tickers > 0:
        sample = tickers[::max(1, -(-len(tickers) // level_tickers))]
        wstart = max(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(weeks=level_weeks))
        sources = {**registry.SOURCES, "levels": registry.level_source(None, wstart)}
        lr = _compare(conn, sample, detector, wstart, end, seed, sources)
        gaps = pd.concat([gaps, lr["gaps"]], ignore_index=True)
        not_compared, auc_levels, n_level = not_compared + lr["not_compared"], lr["auc"], len(sample)
    failures = gate_failures(gaps, r["auc"])
    if auc_levels is not None and not auc_levels <= SAME_TICKER_MAX_AUC:
        failures.append(f"level columns' vendor AUC {auc_levels:.3f} > {SAME_TICKER_MAX_AUC}")
    return {
        "n_tickers": len(tickers), "n_rows": r["n_rows"], "gaps": gaps, "auc": r["auc"],
        "auc_levels": auc_levels, "n_level_tickers": n_level,
        "failures": failures, "passed": not failures, "not_compared": not_compared,
    }
