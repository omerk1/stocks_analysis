"""Track A -- wide feature x horizon IC sweep (DESIGN.md Sec1.5).

Wide, cheap, no significance bar, nothing here is a finding. Motivation
(stated directly by the user, not just an inference): they're building a
downstream model and want a broad scan of which MA-derived features carry
any signal, across lookbacks and horizons, to pick candidate inputs -- not
a single polished claim. See EXPLORATION_LOG.md's 2026-09-16 entry for the
synthesis; this script is the reproducible source of the full table.

Sweeps (all already in the cached panel, nothing new built):
  - dist_pct / dist_atr / dist_z x {sma,ema} x {20,50,150,200}
  - above (boolean state)        x {sma,ema} x {20,50,150,200}
  - slope_log_k                  x {sma,ema} x {20,50,150,200} x k in {5,21,63}
  - dist_from_52w_high / dist_from_52w_low (single columns)
Horizons: {5,10,21,42,63,126} trading days.

Method: primary pass is mean daily rank-IC per (feature, horizon) cell,
reusing modules/cross_sectional.py::daily_rank_ic unchanged -- no
bootstrap/CI, Track A doesn't need that rigor and it would defeat "cheap."
For the top |IC| cells, a richer read (C1 top-decile spread, hit-rate
delta, win/loss ratio, skew) reusing stats/controls.py and stats/shape.py
unchanged. Plus two redundancy checks (per-date median Spearman
correlation, same convention as M4's own SMA20 finding): dist_pct vs
dist_atr vs dist_z at every lookback, and slope_log_21 vs dist_pct at the
same lookback.

Universe/window: standard U1 (408 S&P 500 constituents as of 2021-12-31),
dev window 2010-01-01 -> 2021-12-31 only (CLAUDE.md invariant #1 -- the
holdout past that date is never touched here).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.data import sp500_full_coverage_tickers
from src.signals.moving_averages.features import ma
from src.signals.moving_averages.features.panel import build_panel, read_panel, write_panel
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.cross_sectional import daily_rank_ic
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

AS_OF = "2021-12-31"
COVERAGE_START = "2010-06-01"
COVERAGE_END = "2021-12-01"
DEV_START = "2010-01-01"
HORIZONS = (5, 10, 21, 42, 63, 126)
SLOPE_K = (5, 21, 63)
N_DECILES = 10
TOP_N_ENRICH = 25

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "moving_averages"


def build_feature_list() -> list[str]:
    features: list[str] = []
    for family in ma.FAMILIES:
        for lookback in ma.LOOKBACKS:
            col = ma.ma_column_name(family, lookback)
            for norm in ("dist_pct", "dist_atr", "dist_z"):
                features.append(f"{norm}_{col}")
            features.append(f"above_{col}")
            for k in SLOPE_K:
                features.append(f"slope_log_{k}_{col}")
    features += ["dist_from_52w_high", "dist_from_52w_low"]
    return features


def is_boolean_feature(series: pd.Series) -> bool:
    vals = series.dropna().unique()
    return len(vals) > 0 and set(np.unique(vals.astype(float))) <= {0.0, 1.0}


def per_date_median_corr(panel: pd.DataFrame, col_a: str, col_b: str, date_col: str = "date") -> float:
    sub = panel[[date_col, col_a, col_b]].dropna()
    if sub.empty:
        return float("nan")

    def _corr(g: pd.DataFrame) -> float:
        if len(g) < 30:
            return float("nan")
        return g[col_a].corr(g[col_b], method="spearman")

    corrs = sub.set_index(date_col).groupby(level=0).apply(_corr)
    return corrs.median()


def enrich_cell(panel: pd.DataFrame, feature: str, horizon: int) -> dict:
    ret_col = f"fwd_ret_{horizon}"
    sub = panel[["date", "ticker", feature, ret_col]].dropna().copy()
    if sub.empty:
        return {}

    if is_boolean_feature(sub[feature]):
        sub["_event"] = sub[feature].astype(bool)
        event_rows = sub[sub["_event"]]
        c1 = c1_delta(sub, "_event", ret_col)
        hr = hit_rate_deltas(sub, "_event", ret_col)
        shape = distribution_shape(event_rows[ret_col])
        return {
            "enrich_kind": "boolean_event_vs_rest",
            "c1_read": c1,
            "hit_rate": hr["hit_rate"],
            "hit_rate_delta_c1": hr["hit_rate_delta_c1"],
            "win_loss_ratio": shape["win_loss_ratio"],
            "skew": shape["skew"],
            "n_wins": shape["n_wins"],
            "n_losses": shape["n_losses"],
        }

    sub["decile"] = cross_sectional_bucket(sub, feature, n_buckets=N_DECILES)
    sub = sub.dropna(subset=["decile"])
    if sub.empty:
        return {}
    sub["decile"] = sub["decile"].astype(int)
    sub["_is_top"] = sub["decile"] == (N_DECILES - 1)
    top_rows = sub[sub["_is_top"]]
    c1 = c1_delta(sub, "_is_top", ret_col)
    hr = hit_rate_deltas(sub, "_is_top", ret_col)
    shape = distribution_shape(top_rows[ret_col])
    return {
        "enrich_kind": "top_decile_vs_rest",
        "c1_read": c1,
        "hit_rate": hr["hit_rate"],
        "hit_rate_delta_c1": hr["hit_rate_delta_c1"],
        "win_loss_ratio": shape["win_loss_ratio"],
        "skew": shape["skew"],
        "n_wins": shape["n_wins"],
        "n_losses": shape["n_losses"],
    }


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"

    if (cache_dir / "year=2010").exists():
        panel = read_panel(cache_dir, start=DEV_START, end=AS_OF)
        print(f"panel read from cache {cache_dir} {panel.shape} t={time.time()-t0:.0f}s", flush=True)
    else:
        db_path = db.default_db_path(config.data_paths.raw)
        conn = db.get_connection(db_path)
        tickers = sp500_full_coverage_tickers(conn, AS_OF, COVERAGE_START, COVERAGE_END)
        print(f"n tickers: {len(tickers)}", flush=True)
        panel = build_panel(conn, tickers, start=DEV_START, end=AS_OF)
        conn.close()
        print(f"panel built {panel.shape} t={time.time()-t0:.0f}s", flush=True)
        write_panel(panel, cache_dir)
        print(f"panel cached to {cache_dir} t={time.time()-t0:.0f}s", flush=True)

    for h in HORIZONS:
        panel[f"fwd_ret_{h}"] = forward_return(panel, horizon=h)
    print(f"forward returns computed t={time.time()-t0:.0f}s", flush=True)

    features = build_feature_list()
    print(f"n features: {len(features)}, n cells: {len(features) * len(HORIZONS)}", flush=True)

    rows = []
    for i, feat in enumerate(features):
        for h in HORIZONS:
            ret_col = f"fwd_ret_{h}"
            sub = panel[["date", feat, ret_col]].dropna()
            if sub.empty:
                rows.append({"feature": feat, "horizon": h, "mean_ic": np.nan, "n_dates": 0, "n_rows": 0})
                continue
            ic_series = daily_rank_ic(sub, feat, ret_col)
            rows.append({
                "feature": feat,
                "horizon": h,
                "mean_ic": ic_series.mean(),
                "median_ic": ic_series.median(),
                "n_dates": int(ic_series.notna().sum()),
                "n_rows": len(sub),
            })
        if (i + 1) % 10 == 0 or i == len(features) - 1:
            print(f"  IC sweep: {i+1}/{len(features)} features done, t={time.time()-t0:.0f}s", flush=True)

    result = pd.DataFrame(rows)
    result["abs_ic"] = result["mean_ic"].abs()
    result = result.sort_values("abs_ic", ascending=False).reset_index(drop=True)

    # Checkpoint the expensive part (the 348-cell IC sweep, ~26min) before
    # attempting enrichment -- so a bug in the cheap enrichment step
    # (there was one: a float64-column dtype crash on the very first run)
    # doesn't cost a full re-run of the sweep itself.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "track_a_feature_sweep.csv"
    result.to_csv(out_path, index=False)
    print(f"checkpointed raw IC sweep to {out_path} t={time.time()-t0:.0f}s", flush=True)

    # Enrichment for the top-N cells by |IC|. `enrich_kind` is a string
    # column -- must be created with object dtype up front, not via a
    # shared `= np.nan` loop (that infers float64, and later assigning a
    # string into a float64 column raises LossySetitemError).
    numeric_cols = ["c1_read", "hit_rate", "hit_rate_delta_c1", "win_loss_ratio", "skew", "n_wins", "n_losses"]
    for col in numeric_cols:
        result[col] = np.nan
    result["enrich_kind"] = pd.array([None] * len(result), dtype="object")
    top_idx = result.head(TOP_N_ENRICH).index
    for idx in top_idx:
        feat, h = result.loc[idx, "feature"], int(result.loc[idx, "horizon"])
        try:
            enriched = enrich_cell(panel, feat, h)
        except Exception as exc:  # noqa: BLE001 -- log and continue, don't lose the sweep over one bad cell
            print(f"  enrichment FAILED for {feat}@{h}: {exc}", flush=True)
            continue
        for k, v in enriched.items():
            result.loc[idx, k] = v
    print(f"enrichment done t={time.time()-t0:.0f}s", flush=True)

    out_path = OUTPUT_DIR / "track_a_feature_sweep.csv"
    result.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(result)} rows)", flush=True)

    # --- Redundancy checks ---
    redundancy_rows = []
    for family in ma.FAMILIES:
        for lookback in ma.LOOKBACKS:
            col = ma.ma_column_name(family, lookback)
            pairs = [("dist_pct", "dist_atr"), ("dist_pct", "dist_z"), ("dist_atr", "dist_z")]
            for a, b in pairs:
                corr = per_date_median_corr(panel, f"{a}_{col}", f"{b}_{col}")
                redundancy_rows.append({"check": "norm_pair", "family": family, "lookback": lookback,
                                         "a": f"{a}_{col}", "b": f"{b}_{col}", "median_spearman": corr})
            for k in SLOPE_K:
                corr = per_date_median_corr(panel, f"dist_pct_{col}", f"slope_log_{k}_{col}")
                redundancy_rows.append({"check": "slope_vs_dist", "family": family, "lookback": lookback,
                                         "a": f"dist_pct_{col}", "b": f"slope_log_{k}_{col}", "median_spearman": corr})
    redundancy = pd.DataFrame(redundancy_rows)
    redundancy_path = OUTPUT_DIR / "track_a_redundancy_checks.csv"
    redundancy.to_csv(redundancy_path, index=False)
    print(f"wrote {redundancy_path} ({len(redundancy)} rows) t={time.time()-t0:.0f}s", flush=True)

    print("\n=== TOP 25 CELLS BY |mean IC| ===")
    print(result.head(25)[["feature", "horizon", "mean_ic", "n_dates", "c1_read", "hit_rate_delta_c1",
                            "win_loss_ratio", "skew"]].to_string())

    print("\n=== REDUNDANCY: dist_pct/atr/z pairs, median per-date Spearman ===")
    print(redundancy[redundancy["check"] == "norm_pair"].to_string())

    print("\n=== REDUNDANCY: dist_pct vs slope_log_k, median per-date Spearman ===")
    print(redundancy[redundancy["check"] == "slope_vs_dist"].to_string())

    print(f"\ntotal time {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
