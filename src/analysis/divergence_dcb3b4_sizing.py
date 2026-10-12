"""Blind sizing for the DC-B3/B4 draft registration (PREREGISTRATION.md,
"DC-B3 / DC-B4 — DRAFT"): counts and covariate definedness ONLY — no
outcome column is read anywhere in this script.

Event side: hidden-form divergences, PIT S&P 500 + NDX members at p2,
p2 inside the dev window (the shared study loader). Control side:
no-divergence pivot pairs with STRICT hidden geometry (bearish:
p2_price < p1_price; bullish: p2_price > p1_price — `regular_geometry = 0`
alone also admits equal-extreme pairs, which are neither),
`has_divergence = 0` (which the builder computes against REGULAR stored
divergences), and additionally no stored HIDDEN divergence of the same
direction (any indicator, `confirmed_at <= DEV_END` — the dev-window
truncation every study loader applies; the exclusion must not consult
holdout-era rows) with p2 within +/-5 calendar days — an approximation of
the registration's +/-3-bar exclusion, used for sizing only; the build
applies the exact bar-distance rule.

Usage: python -m src.analysis.divergence_dcb3b4_sizing
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.divergence_hidden_prep import hidden_fit_undefined_reasons
from src.analysis.divergence_study_common import attach_pit_membership, load_dev_events
from src.foundation.market_common import derived_db
from src.signals.divergences.study_universe import DEV_END, DEV_START

# Sizing-only approximation of the registered +/-3-bar hidden-divergence
# exclusion (calendar days; the build uses exact bar distance).
HIDDEN_EXCLUSION_DAYS = 5


def _frac_defined(frame: pd.DataFrame) -> pd.Series:
    """Definedness of the hidden-fit retrace fraction on rows that are
    hidden-geometry by construction: the scalar's own mask components
    (hidden_fit_undefined_reasons, the single source of truth), minus its
    form-domain column — control pairs carry no `form`, so the frame is
    tagged hidden for the call."""
    reasons = hidden_fit_undefined_reasons(frame.assign(form="hidden"))
    return ~(reasons["inputs_nan"] | reasons["trend_leg_degenerate"])


def main() -> None:
    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)

    ev = load_dev_events(derived_conn)
    ev = ev[(ev["form"] == "hidden") & (ev["p2_ts"] >= DEV_START)]
    ev = attach_pit_membership(ev, raw_conn)
    ev = ev[ev["pit_member"]]
    ev["frac_defined"] = _frac_defined(ev)

    print("== hidden events, PIT members, p2 in dev window (no outcomes read) ==")
    print(ev.groupby(["direction", "indicator"]).agg(
        rows=("ticker", "size"), dates=("p2_date", "nunique"),
        frac_defined=("frac_defined", "mean")).to_string())

    cp = pd.read_sql_query(
        """SELECT ticker, direction, p2_date,
                  interpeak_retrace_pct, leg2_gain_pct
           FROM divergence_control_pairs
           WHERE timeframe='daily' AND has_divergence=0
             AND confirmed_at <= ? AND p2_date >= ?
             AND ((direction='bearish' AND p2_price < p1_price)
                  OR (direction='bullish' AND p2_price > p1_price))""",
        derived_conn, params=[DEV_END + "T23:59:59", DEV_START],
    )
    cp["p2_ts"] = pd.to_datetime(cp["p2_date"])
    cp = attach_pit_membership(cp, raw_conn)
    cp = cp[cp["pit_member"]]
    cp["frac_defined"] = _frac_defined(cp)

    # The builder's has_divergence covers REGULAR divergences only
    # (controls.flag_divergences), so hidden treatment structures would
    # pass it; exclude pairs near a stored same-direction hidden event.
    # Dev-window truncated: the pool definition must not read holdout rows.
    hidden_all = pd.read_sql_query(
        "SELECT ticker, direction, p2_date FROM divergences "
        "WHERE timeframe='daily' AND form='hidden' AND confirmed_at <= ?",
        derived_conn, params=[DEV_END + "T23:59:59"],
    )
    hidden_all["p2_ts"] = pd.to_datetime(hidden_all["p2_date"])
    tol = pd.Timedelta(days=HIDDEN_EXCLUSION_DAYS).to_timedelta64()
    keep = pd.Series(True, index=cp.index)
    hid_by_key = {k: g["p2_ts"].sort_values().to_numpy()
                  for k, g in hidden_all.groupby(["ticker", "direction"])}
    for key, grp in cp.groupby(["ticker", "direction"]):
        hid = hid_by_key.get(key)
        if hid is None:
            continue
        pts = grp["p2_ts"].to_numpy()
        lo = np.searchsorted(hid, pts - tol)
        hi = np.searchsorted(hid, pts + tol, side="right")
        keep.loc[grp.index] = hi == lo

    print("\n== strict hidden-geometry no-div control pairs, PIT, dev window ==")
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
