"""Track A -- promotion-gate re-slice check for `dist_from_52w_high`/
`dist_from_52w_low` at 63d/126d (DESIGN.md Sec1.5's gate: "survives a quick
re-slice on a different universe tier or subperiod within the development
window").

Motivation: the 2026-09-16 348-cell IC sweep (EXPLORATION_LOG.md) found
these two features are the clear standouts of the entire grid, strengthening
(not weakening) at longer horizons, and independently corroborated by M2's
own ablation (criterion 7, near-52w-high, largest coefficient, negative
sign). That sweep's number is whole-dev-window only -- this is the cheap
subperiod re-slice DESIGN's own gate requires before promoting it to a
pre-registered Track B test. EXPLORATORY, no significance bar, nothing here
is a finding -- a promote/don't-promote check only.

Universe/window: same U1 as every other module (408 S&P 500 constituents,
2010-01-01 -> 2021-12-31, holdout untouched). Split at 2016-01-01 into two
~equal subperiods within the dev window.
"""

from __future__ import annotations

from pathlib import Path

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config
from src.signals.moving_averages.cli import (
    SP500_UNIVERSE_AS_OF as AS_OF,
    SP500_UNIVERSE_COVERAGE_END as COVERAGE_END,
    SP500_UNIVERSE_COVERAGE_START as COVERAGE_START,
)
from src.signals.moving_averages.data import sp500_full_coverage_tickers
from src.signals.moving_averages.features.panel import read_panel
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.cross_sectional import daily_rank_ic

DEV_START = "2010-01-01"
SPLIT = "2016-01-01"
FEATURES = ("dist_from_52w_high", "dist_from_52w_low")
HORIZONS = (63, 126)


def main() -> None:
    config = load_config()
    cache_dir = Path(config.data_paths.features) / "moving_averages" / "ma_panel"
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)
    tickers = sp500_full_coverage_tickers(conn, AS_OF, COVERAGE_START, COVERAGE_END)
    conn.close()

    panel = read_panel(cache_dir, start=DEV_START, end=AS_OF)
    panel = panel[panel["ticker"].isin(tickers)]
    print(f"panel: {panel.shape}, {panel['ticker'].nunique()} tickers")

    for h in HORIZONS:
        panel[f"fwd_ret_{h}"] = forward_return(panel, horizon=h)

    early = panel[panel["date"] < SPLIT]
    late = panel[panel["date"] >= SPLIT]
    print(f"early: {early['date'].min()}..{early['date'].max()} ({early['date'].nunique()} dates)")
    print(f"late:  {late['date'].min()}..{late['date'].max()} ({late['date'].nunique()} dates)")

    rows = []
    for feat in FEATURES:
        for h in HORIZONS:
            ret_col = f"fwd_ret_{h}"
            full_ic = daily_rank_ic(panel[["date", feat, ret_col]].dropna(), feat, ret_col).mean()
            early_ic = daily_rank_ic(early[["date", feat, ret_col]].dropna(), feat, ret_col).mean()
            late_ic = daily_rank_ic(late[["date", feat, ret_col]].dropna(), feat, ret_col).mean()
            same_sign = (early_ic > 0) == (late_ic > 0) == (full_ic > 0)
            rows.append((feat, h, full_ic, early_ic, late_ic, same_sign))
            print(f"{feat}@{h}d: full={full_ic:+.4f} early(2010-15)={early_ic:+.4f} "
                  f"late(2016-21)={late_ic:+.4f} same_sign_all_three={same_sign}")

    n_pass = sum(r[-1] for r in rows)
    print(f"\n{n_pass}/{len(rows)} cells same-signed across both subperiods and the full window.")


if __name__ == "__main__":
    main()
