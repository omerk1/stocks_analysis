"""Blind sizing for the DC-B3/B4 draft registration (PREREGISTRATION.md,
"DC-B3 / DC-B4 — DRAFT"): counts and covariate definedness ONLY — no
outcome column is read anywhere in this script.

Event side: hidden-form divergences, PIT S&P 500 + NDX members at p2,
p2 inside the dev window. Control side: no-divergence pivot pairs with
STRICT hidden geometry (bearish: p2_price < p1_price; bullish:
p2_price > p1_price — `regular_geometry = 0` alone also admits
equal-extreme pairs, which are neither), `has_divergence = 0` (which the
builder computes against REGULAR stored divergences), and additionally no
stored HIDDEN divergence of the same direction (any indicator) with p2
within +/-5 calendar days — an approximation of the registration's
+/-3-bar exclusion, used for sizing only; the build applies the exact
bar-distance rule.

Usage: python -m src.analysis.divergence_dcb3b4_sizing
"""

from __future__ import annotations

import pandas as pd

from src.analysis.divergence_hidden_prep import TREND_LEG_EPS
from src.foundation.market_common import derived_db
from src.signals.divergences.study_universe import (
    DEV_END,
    DEV_START,
    membership_intervals,
    pit_member_mask,
)

# Sizing-only approximation of the registered +/-3-bar hidden-divergence
# exclusion (calendar days; the build uses exact bar distance).
HIDDEN_EXCLUSION_DAYS = 5


def _frac_defined(frame: pd.DataFrame) -> pd.Series:
    """Definedness of the hidden-fit retrace fraction on rows that are
    hidden-geometry by construction: same inputs-NaN and trend-leg-eps
    discipline as divergence_hidden_prep.hidden_fit_retrace_frac, without
    its form-domain mask (control pairs have no `form`)."""
    r = frame["interpeak_retrace_pct"]
    return r.notna() & frame["leg2_gain_pct"].notna() & (r > TREND_LEG_EPS)


def main() -> None:
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    intervals = membership_intervals(raw_conn)

    ev = pd.read_sql_query(
        """SELECT d.ticker, d.direction, d.indicator, d.p2_date,
                  c.interpeak_retrace_pct, c.leg2_gain_pct
           FROM divergences d LEFT JOIN divergence_context c ON c.divergence_id = d.id
           WHERE d.timeframe='daily' AND d.form='hidden' AND d.confirmed_at <= ?""",
        derived_conn, params=[DEV_END + "T23:59:59"],
    )
    ev["p2_ts"] = pd.to_datetime(ev["p2_date"])
    ev = ev[(ev["p2_ts"] >= DEV_START) & pit_member_mask(ev, intervals)]
    ev["frac_defined"] = _frac_defined(ev)

    print("== hidden events, PIT members, p2 in dev window (no outcomes read) ==")
    print(ev.groupby(["direction", "indicator"]).agg(
        rows=("ticker", "size"), dates=("p2_date", "nunique"),
        frac_defined=("frac_defined", "mean")).to_string())

    cp = pd.read_sql_query(
        """SELECT ticker, direction, p2_date,
                  interpeak_retrace_pct, leg2_gain_pct
           FROM divergence_control_pairs
           WHERE timeframe='daily' AND has_divergence=0 AND confirmed_at <= ?
             AND ((direction='bearish' AND p2_price < p1_price)
                  OR (direction='bullish' AND p2_price > p1_price))""",
        derived_conn, params=[DEV_END + "T23:59:59"],
    )
    cp["p2_ts"] = pd.to_datetime(cp["p2_date"])
    cp = cp[(cp["p2_ts"] >= DEV_START) & pit_member_mask(cp, intervals)]
    cp["frac_defined"] = _frac_defined(cp)

    # The builder's has_divergence covers REGULAR divergences only
    # (controls.flag_divergences), so hidden treatment structures would
    # pass it; exclude pairs near a stored same-direction hidden event.
    hidden_all = pd.read_sql_query(
        "SELECT ticker, direction, p2_date FROM divergences "
        "WHERE timeframe='daily' AND form='hidden'",
        derived_conn,
    )
    hidden_all["p2_ts"] = pd.to_datetime(hidden_all["p2_date"])
    tol = pd.Timedelta(days=HIDDEN_EXCLUSION_DAYS)
    keep = pd.Series(True, index=cp.index)
    hid_by_key = {k: g["p2_ts"].sort_values().to_numpy()
                  for k, g in hidden_all.groupby(["ticker", "direction"])}
    import numpy as np
    for key, grp in cp.groupby(["ticker", "direction"]):
        hid = hid_by_key.get(key)
        if hid is None:
            continue
        pts = grp["p2_ts"].to_numpy()
        lo = np.searchsorted(hid, pts - tol.to_timedelta64())
        hi = np.searchsorted(hid, pts + tol.to_timedelta64(), side="right")
        keep.loc[grp.index] = hi == lo

    print(f"\n== strict hidden-geometry no-div control pairs, PIT, dev window ==")
    print("  before hidden-divergence exclusion:")
    print(cp.groupby("direction").agg(
        rows=("ticker", "size"), dates=("p2_date", "nunique"),
        frac_defined=("frac_defined", "mean")).to_string())
    print(f"  after excluding pairs with a same-direction hidden divergence "
          f"within +/-{HIDDEN_EXCLUSION_DAYS} calendar days (sizing approximation):")
    print(cp[keep].groupby("direction").agg(
        rows=("ticker", "size"), dates=("p2_date", "nunique"),
        frac_defined=("frac_defined", "mean")).to_string())

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()
