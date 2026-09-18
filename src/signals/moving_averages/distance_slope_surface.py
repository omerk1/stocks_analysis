"""Track A -- distance-from-MA x MA-slope interaction, generalized across
the full distance range (DESIGN.md's M6.2 "extension with slope"
sub-question, generalized from {top, bottom} decile only to all 10).

Wide, cheap, no significance bar, nothing here is a finding (DESIGN Sec1.5).
Motivation: M6.2 found two real cells (`extension_x_slope`/SMA50/top,
`touch_x_slope`/SMA50/`from_above`) using only the top/bottom distance
decile and a binary slope sign -- this asks whether the effect is a smooth
function of distance (DESIGN Sec6.7's plateau rule -- a surface, not a
lone bright pixel) or an artifact of picking the extremes. Both M6.2
findings failed the whole-grid FDR pass regardless (STATUS.md) -- this is
a fresh look, not a rebuttal of that result.

Sweep: `dist_atr` (M6.2's own choice, not `dist_pct` -- consistency with
the precedent this generalizes, and the natural ATR-based "how far away"
unit M5/M6.2 both already use) x `slope_log_21` (M6.2's own slope window)
x {sma,ema} x {20,50,150,200} -- all 8 combinations already in the cached
panel, nothing new built.

Statistic, validated against M6.2 before trusting it on the rest of the
grid (see "Two real bugs" below): per (family, lookback, distance decile),
the **rising-tercile-minus-falling-tercile delta** -- the middle slope
tercile is dropped from this specific comparison, exactly like M6.2's own
binary sign split (not a three-way "tercile vs. rest," which is a
different, not-directly-comparable statistic -- see below). `c1_delta`/
`c2_delta` (`stats/controls.py`, unchanged) do the actual averaging --
date/stratum-equal-weighted, the same primitives M1/M2/M4/M5/M6.2/M11 all
use, not reinvented here. `rev_tercile` (prior-21-day-return tercile) is
baked into the C2 match columns from the start, alongside M6.2's own
`mom_tercile`/`vol_tercile`/`sector` -- both of M6.2's confirmed cells had
"no reversal control" flagged as their live, unresolved caveat.

No bootstrap CI (unlike every Track B module) -- Track A doesn't need
that rigor (`feature_sweep.py` made the same call for its own IC sweep);
point estimates only, one per decile, meant to be read as a line across
deciles, not agonized over per-point.

**Two real bugs found and fixed while building this, in order:**
1. An early version demeaned every row by its own (date, context) stratum
   mean via a plain `groupby(...).transform("mean")`, then averaged the
   residuals. That weights each *row* equally, not each *date/stratum* --
   and rising/falling rows aren't evenly spread across dates (extended-
   and-rising vastly outnumbers extended-and-falling on most days), so it
   silently compared different sets of market days between the two
   groups. Every C1/C2 computation in this study weights dates/strata
   equally specifically to prevent this.
2. The fix above (switching to `c1_delta`/`c2_delta`) still didn't match
   M6.2 at the one directly-comparable cell (SMA50, top decile) -- because
   it computed each slope *tercile* against the *other two combined*, a
   three-way split, not M6.2's *binary* rising-vs-falling comparison. The
   third ("mid") group dilutes each tercile's "rest" differently, so
   subtracting two such deltas isn't equivalent to a direct two-group
   delta. Fixed by dropping the middle tercile from the comparison
   entirely -- verified this reproduces M6.2 almost exactly (`dist_atr`,
   SMA50, decile 9: C1 -0.407%/C2 -0.599% here vs. M6.2's own logged
   -0.398%/-0.592%) before trusting it on the other 9 deciles x 7 other
   surfaces.

Mandatory pre-check, not optional: `slope_log_21` vs. `dist_pct`
correlation per (family, lookback), reused from the 2026-09-16 sweep's own
`output/moving_averages/track_a_redundancy_checks.csv` where available
(recomputed fresh, against `dist_atr` specifically, if missing -- the
cached file only has the `dist_pct` pairing, a close proxy given the
0.94-0.98 `dist_pct`/`dist_atr` correlation but not the exact number for
this script's own axis). M6.0's identity (1-day EMA slope IS
distance-from-EMA, times a constant) means the "surface" can degenerate to
a smeared 1D one wherever this correlation is high -- read any EMA150/200
result in that light.

Explicitly out of scope for this pass: the touch-event angle (a
`touch_x_slope`-style generalization) -- different statistic, different
mechanism, kept separate rather than mixing two statistic types into one
sweep.

Universe/window: standard U1 (405 S&P 500 constituents with full
dev-window coverage), dev window 2010-01-01 -> 2021-12-31 only (CLAUDE.md
invariant #1).
"""

from __future__ import annotations

import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.cli import (
    SP500_UNIVERSE_AS_OF as AS_OF,
    SP500_UNIVERSE_COVERAGE_END as COVERAGE_END,
    SP500_UNIVERSE_COVERAGE_START as COVERAGE_START,
)
from src.signals.moving_averages.data import sp500_full_coverage_tickers
from src.signals.moving_averages.features import ma
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta, c2_delta, cross_sectional_bucket
from src.signals.moving_averages.feature_sweep import per_date_median_corr

DEV_START = "2010-01-01"
HORIZON = 21
N_DIST_DECILES = 10
N_SLOPE_TERCILES = 3
FALLING, MID, RISING = 0, 1, 2
C2_MATCH_COLS = ["mom_tercile", "vol_tercile", "sector", "rev_tercile"]

# DESIGN Sec6.9's own floor, applied per cell here too -- flagged, never dropped.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "moving_averages"
REDUNDANCY_CSV = OUTPUT_DIR / "track_a_redundancy_checks.csv"


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    working = panel.copy()
    working[f"fwd_ret_{HORIZON}"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    return working


def load_correlation(panel: pd.DataFrame, family: str, lookback: int, dist_atr_col: str, slope_col: str) -> float:
    if REDUNDANCY_CSV.exists():
        cached = pd.read_csv(REDUNDANCY_CSV)
        dist_pct_col = dist_atr_col.replace("dist_atr_", "dist_pct_")
        hit = cached[
            (cached["check"] == "slope_vs_dist") & (cached["family"] == family)
            & (cached["lookback"] == lookback) & (cached["a"] == dist_pct_col) & (cached["b"] == slope_col)
        ]
        if len(hit) == 1:
            return float(hit["median_spearman"].iloc[0])
    return per_date_median_corr(panel, dist_atr_col, slope_col)


def build_surface(panel: pd.DataFrame, family: str, lookback: int) -> tuple[pd.DataFrame, float]:
    ma_col = ma.ma_column_name(family, lookback)
    dist_col = f"dist_atr_{ma_col}"
    slope_col = f"slope_log_21_{ma_col}"
    ret_col = f"fwd_ret_{HORIZON}"

    needed = [dist_col, slope_col, ret_col, "date", "ticker", *C2_MATCH_COLS]
    sub = panel.dropna(subset=needed).copy()

    corr = load_correlation(panel, family, lookback, dist_col, slope_col)

    sub["dist_decile"] = cross_sectional_bucket(sub, dist_col, n_buckets=N_DIST_DECILES)
    sub["slope_tercile"] = cross_sectional_bucket(sub, slope_col, n_buckets=N_SLOPE_TERCILES)
    sub = sub.dropna(subset=["dist_decile", "slope_tercile"])
    sub["dist_decile"] = sub["dist_decile"].astype(int)
    sub["slope_tercile"] = sub["slope_tercile"].astype(int)

    rows = []
    for d, decile_rows in sub.groupby("dist_decile", observed=True):
        # Middle tercile dropped from THIS comparison (kept in the panel,
        # just not part of the rising-vs-falling delta) -- a direct
        # two-group split, matching M6.2's own binary sign construction,
        # not a three-way "tercile vs. rest" (see module docstring).
        extremes = decile_rows[decile_rows["slope_tercile"].isin([FALLING, RISING])].copy()
        extremes["_is_rising"] = extremes["slope_tercile"] == RISING

        rising_rows = extremes[extremes["_is_rising"]]
        falling_rows = extremes[~extremes["_is_rising"]]
        n_events = len(extremes)
        n_dates = extremes["date"].nunique()
        n_tickers = extremes["ticker"].nunique()
        n_rising, n_falling = len(rising_rows), len(falling_rows)

        c1 = c1_delta(extremes, "_is_rising", ret_col) if n_events else float("nan")
        c2 = c2_delta(extremes, "_is_rising", ret_col, match_cols=C2_MATCH_COLS) if n_events else float("nan")
        mid_rows = decile_rows[decile_rows["slope_tercile"] == MID]

        rows.append({
            "family": family, "lookback": lookback, "dist_decile": d,
            "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
            "n_rising": n_rising, "n_falling": n_falling,
            "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
            "raw_rising_mean": rising_rows[ret_col].mean() if n_rising else float("nan"),
            "raw_falling_mean": falling_rows[ret_col].mean() if n_falling else float("nan"),
            "raw_mid_mean": mid_rows[ret_col].mean() if len(mid_rows) else float("nan"),
            "c1_delta": c1,
            "c2_delta": c2,
        })
    cell_table = pd.DataFrame(rows)
    return cell_table, corr


def make_plots(cells: pd.DataFrame, correlations: pd.DataFrame) -> None:
    """CLAUDE.md Style: "Plots before tests. Look at the distribution
    before you summarise it." One 2x4 grid, one line chart per (family,
    lookback) -- C2 delta (rising minus falling slope tercile, date +
    momentum + vol + sector + reversal matched) against distance decile.
    Below-threshold points are marked, not hidden.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combos = [(family, lookback) for family in ma.FAMILIES for lookback in ma.LOOKBACKS]

    fig, axes = plt.subplots(2, 4, figsize=(20, 9), sharey=True)
    for ax, (family, lookback) in zip(axes.flat, combos):
        sub = cells[(cells["family"] == family) & (cells["lookback"] == lookback)].sort_values("dist_decile")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.plot(sub["dist_decile"], sub["c2_delta"] * 100, marker="o", color="tab:blue", label="C2")
        ax.plot(sub["dist_decile"], sub["c1_delta"] * 100, marker=".", color="tab:gray", alpha=0.6, label="C1")
        thin = sub[sub["below_threshold"]]
        if len(thin):
            ax.scatter(thin["dist_decile"], thin["c2_delta"] * 100, marker="x", color="black", zorder=5)

        corr_row = correlations[(correlations["family"] == family) & (correlations["lookback"] == lookback)]
        corr_val = corr_row["median_spearman"].iloc[0] if len(corr_row) else float("nan")
        ax.set_title(f"{family} {lookback} (slope-dist corr={corr_val:.2f})", fontsize=9)
        ax.set_xlabel("distance decile (dist_atr)", fontsize=8)
        ax.set_ylabel("rising - falling delta, %", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=6, loc="best")

    fig.suptitle("Rising-minus-falling slope delta per distance decile, all 8 (family, lookback) combinations "
                 "('x' = below min-sample threshold)", fontsize=11)
    fig.tight_layout()
    out_path = OUTPUT_DIR / "track_a_distance_slope_surface.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"plot written to {out_path}", flush=True)


def main() -> None:
    t0 = time.time()
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"

    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)
    tickers = sp500_full_coverage_tickers(conn, AS_OF, COVERAGE_START, COVERAGE_END)
    conn.close()
    print(f"n tickers: {len(tickers)}", flush=True)

    panel = read_panel(cache_dir, start=DEV_START, end=AS_OF)
    expected, cached = set(tickers), set(panel["ticker"].unique())
    if cached != expected:
        raise RuntimeError(
            f"Cached panel universe mismatch: {len(cached)} tickers cached vs. {len(expected)} expected "
            f"({len(expected - cached)} missing, {len(cached - expected)} unexpected). "
            "Rebuild the cache before trusting this sweep's numbers."
        )
    print(f"panel read {panel.shape} t={time.time()-t0:.0f}s", flush=True)

    prepared = prepare(panel)
    print(f"prepared (fwd_ret_21 + C2 match cols incl. rev_tercile) t={time.time()-t0:.0f}s", flush=True)

    all_cells = []
    corr_rows = []
    for family in ma.FAMILIES:
        for lookback in ma.LOOKBACKS:
            cells, corr = build_surface(prepared, family, lookback)
            all_cells.append(cells)
            corr_rows.append({"family": family, "lookback": lookback, "median_spearman": corr})
            print(f"  {family} {lookback}: corr={corr:.3f}, {len(cells)} deciles, "
                  f"{int(cells['below_threshold'].sum())} below threshold t={time.time()-t0:.0f}s", flush=True)

    cells = pd.concat(all_cells, ignore_index=True)
    correlations = pd.DataFrame(corr_rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cells_path = OUTPUT_DIR / "track_a_distance_slope_surface_cells.csv"
    corr_path = OUTPUT_DIR / "track_a_distance_slope_surface_correlations.csv"
    cells.to_csv(cells_path, index=False)
    correlations.to_csv(corr_path, index=False)
    print(f"wrote {cells_path} ({len(cells)} rows), {corr_path} ({len(correlations)} rows)", flush=True)

    make_plots(cells, correlations)

    print("\n=== slope_log_21 vs dist_atr correlation, by surface ===")
    print(correlations.sort_values(["family", "lookback"]).to_string(index=False))

    print("\n=== C2 delta (rising - falling), by surface x decile ===")
    wide = cells.pivot(index="dist_decile", columns=["family", "lookback"], values="c2_delta") * 100
    print(wide.round(3).to_string())

    print(f"\ndone t={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
