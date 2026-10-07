"""DC-B1 / DC-B2 — executes the FROZEN pre-registration
(docs/features/divergence-context/PREREGISTRATION.md, frozen 2026-10-08).

This script is pure wiring of already-reviewed pieces: events + stored
context scalars, the control sampling frame, the frozen matching
definition, fail-closed forward returns, and the MA study's
date-block-bootstrap inference. Every number it emits is governed by the
frozen text; nothing here chooses a definition.

**Unblinding gate:** without `--unblind`, the script stops after matching
and exclusion accounting -- no outcome column is ever computed -- so the
wiring can be reviewed and dry-run without anyone seeing a result. The
registered readout (6 tests, one BH correction, three-way verdicts with
the plateau and binary-vs-continuous gates) runs only with `--unblind`,
and `--log` additionally appends the per-cell rows to the study's
EXPERIMENTS.csv.

Usage:
  python -m src.analysis.divergence_trackb_run             # blind dry run
  python -m src.analysis.divergence_trackb_run --unblind [--log]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.forward_returns import compute_forward_returns
from src.signals.divergences.matching import match_controls
from src.signals.divergences.study_universe import membership_intervals
from src.signals.moving_averages.stats.inference import block_bootstrap_delta_diff
from src.signals.moving_averages.stats.multiple_testing import (
    benjamini_hochberg,
    p_value_from_ci,
)
from src.analysis.divergence_trackb_balance import (
    DEV_END,
    MATCH_SEED,
    load_controls,
    load_events,
)

CI_LEVEL = 0.95          # frozen: 95% clustered CI
BLOCK_MONTHS = 6         # cluster = p2 calendar month; blocks of 6 months
N_BOOT = 2000
HURDLE = 0.002           # frozen: 20 bps round-trip, the kill-criterion hurdle
HURDLE_LOW = 0.001       # annotated liquid-core variant
HORIZONS = (63, 21)
# Plateau neighborhood, frozen: retrace in {0.25, 0.33, 0.50} x leg2 in {3, 5, 8}.
PLATEAU_RETRACE = (0.25, 0.33, 0.50)
PLATEAU_LEG2 = (3, 5, 8)

EXPERIMENTS_CSV = Path("docs/features/divergence-context/EXPERIMENTS.csv")
_CSV_HEADER = (
    "date,cell_id,hypothesis,statistic,point_estimate,ci_low,ci_high,p_value,"
    "bh_pass,n_dates,n_events,n_controls,cost_hurdle,cost_verdict,plateau_ok,"
    "formulations_agree,verdict,notes\n"
)


# ---- panel assembly (no outcomes) ----


def assemble_panel(events: pd.DataFrame, controls: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Matched events + their controls as one analysis frame:
    is_divergence flag, match_group = the event's id (each stratum = one
    event plus its <=3 controls, which is what makes the bootstrap's
    stratum deltas per-event-weighted). Covariates only."""
    ev = events[events["id"].isin(matches["event_id"])].copy()
    ev["is_divergence"] = True
    ev["match_group"] = ev["id"]

    ctrl_to_event = dict(zip(matches["control_id"], matches["event_id"]))
    ct = controls[controls["id"].isin(matches["control_id"])].copy()
    ct["is_divergence"] = False
    ct["match_group"] = ct["id"].map(ctrl_to_event)

    cols = [
        "id", "ticker", "p2_date", "confirmed_at", "direction", "context_class",
        "p2_month", "interpeak_retrace_frac", "leg2_bars", "is_divergence", "match_group",
    ]
    return pd.concat([ev[cols], ct[cols]], ignore_index=True)


def attach_forward_returns(panel: pd.DataFrame, raw_conn, config: DivergenceConfig) -> pd.DataFrame:
    """Per-ticker bar loads (as_of DEV_END), fail-closed returns with the
    explicit delisted flag from the tickers table. THE UNBLINDING STEP."""
    active = dict(raw_conn.execute("SELECT ticker, active FROM tickers").fetchall())
    out = []
    for ticker, grp in panel.groupby("ticker"):
        bars, _report = data_mod.load_and_validate(
            raw_conn, ticker, Timeframe.DAILY, as_of=DEV_END, basis=config.price_basis
        )
        if len(bars) == 0:
            fr = pd.DataFrame(index=grp.index)
            for h in HORIZONS:
                fr[f"fwd_log_ret_{h}"] = None
                fr[f"censored_{h}"] = None
        else:
            fr = compute_forward_returns(
                bars, grp["confirmed_at"], horizons=HORIZONS,
                data_end=DEV_END, delisted=(active.get(ticker, 1) == 0),
            )
        out.append(grp.join(fr[[c for c in fr.columns if c.startswith(("fwd_", "censored_"))]]))
    return pd.concat(out).sort_index()


# ---- registered statistics ----


def did_cell(panel: pd.DataFrame, direction: str, horizon: int, seed: int = MATCH_SEED) -> dict:
    """Binary DiD, frozen definition: (div - ctrl | extension) minus
    (div - ctrl | pullback_rebuild), stratum = match_group (one event +
    its controls), clusters = p2 months resampled in blocks."""
    sub = panel[(panel["direction"] == direction) & panel[f"fwd_log_ret_{horizon}"].notna()].copy()
    sub["month_ts"] = pd.to_datetime(sub["p2_month"] + "-01")
    ext = sub[sub["context_class"] == "extension"]
    pb = sub[sub["context_class"] == "pullback_rebuild"]
    res = block_bootstrap_delta_diff(
        ext, pb, group_col="is_divergence", value_col=f"fwd_log_ret_{horizon}",
        match_cols=["match_group"], date_col="month_ts",
        block_length=BLOCK_MONTHS, n_boot=N_BOOT, ci=CI_LEVEL, seed=seed,
    )
    res["n_events"] = int(sub.loc[sub["is_divergence"], "id"].nunique())
    res["n_controls"] = int((~sub["is_divergence"]).sum())
    return res


def cluster_robust_interaction(panel: pd.DataFrame, direction: str, horizon: int) -> dict:
    """Continuous cell, frozen: fwd_ret ~ b0 + b1*divergence + b2*retrace
    + b3*(divergence x retrace), ALL rows with defined retrace (buffer and
    deep-fast included -- this is the formulation that uses every event),
    cluster-robust (CR0 sandwich) by p2 month on b3."""
    sub = panel[
        (panel["direction"] == direction)
        & panel[f"fwd_log_ret_{horizon}"].notna()
        & panel["interpeak_retrace_frac"].notna()
    ]
    y = sub[f"fwd_log_ret_{horizon}"].to_numpy(dtype=float)
    d = sub["is_divergence"].to_numpy(dtype=float)
    r = sub["interpeak_retrace_frac"].to_numpy(dtype=float)
    X = np.column_stack([np.ones_like(d), d, r, d * r])
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta

    meat = np.zeros((4, 4))
    for _, idx in sub.groupby("p2_month").indices.items():
        Xg, ug = X[idx], resid[idx]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    cov = XtX_inv @ meat @ XtX_inv
    se = float(np.sqrt(cov[3, 3]))
    b3 = float(beta[3])
    from math import erf, sqrt

    z = b3 / se if se > 0 else float("nan")
    p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))) if np.isfinite(z) else float("nan")
    half = 1.959963984540054 * se
    return {
        "point_estimate": b3, "ci_low": b3 - half, "ci_high": b3 + half,
        "p_value": p, "n_dates": int(sub["p2_month"].nunique()), "n_rows": len(sub),
    }


def classify_with(retrace_min: float, leg2_min: int):
    def _cls(retrace, leg2):
        if retrace is None or pd.isna(retrace):
            return None
        if retrace < 0.25:
            return "extension"
        if retrace >= retrace_min and leg2 is not None and not pd.isna(leg2) and leg2 >= leg2_min:
            return "pullback_rebuild"
        return None

    return _cls


def plateau_signs(panel: pd.DataFrame, direction: str, horizon: int) -> list[float]:
    """Point-estimate DiD at each 3x3 threshold neighbor (no bootstrap --
    the frozen gate is SIGN stability). Reclassifies the pullback pole
    per neighbor; the extension pole's 0.25 edge is fixed by the frozen
    definition."""
    points = []
    for rmin in PLATEAU_RETRACE:
        for lmin in PLATEAU_LEG2:
            cls = classify_with(rmin, lmin)
            sub = panel[(panel["direction"] == direction) & panel[f"fwd_log_ret_{horizon}"].notna()].copy()
            sub["context_class"] = [
                cls(a, b) for a, b in zip(sub["interpeak_retrace_frac"], sub["leg2_bars"])
            ]
            sub = sub[sub["context_class"].notna()]
            deltas = {}
            for name, grp in sub.groupby("context_class"):
                strat = grp.groupby(["match_group", "is_divergence"])[f"fwd_log_ret_{horizon}"].mean().unstack()
                if True not in strat.columns or False not in strat.columns:
                    deltas[name] = float("nan")
                    continue
                per_event = (strat[True] - strat[False]).dropna()
                deltas[name] = float(per_event.mean()) if len(per_event) else float("nan")
            points.append(deltas.get("extension", float("nan")) - deltas.get("pullback_rebuild", float("nan")))
    return points


def verdict(cell: dict, bh_pass: bool, plateau_ok: bool, formulations_agree: bool) -> str:
    """Frozen three-way verdicts with the Alive gates."""
    lo, hi, point = cell["ci_low"], cell["ci_high"], cell["point_estimate"]
    if max(abs(lo), abs(hi)) < HURDLE:
        return "dead_demonstrated_null"
    excludes_zero = (lo > 0) or (hi < 0)
    if bh_pass and excludes_zero and abs(point) >= HURDLE:
        if plateau_ok and formulations_agree:
            return "alive"
        return "inconclusive_gate_failed"
    return "inconclusive_underpowered"


# ---- main ----


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unblind", action="store_true", help="compute outcomes and the registered readout")
    parser.add_argument("--log", action="store_true", help="append per-cell rows to the study EXPERIMENTS.csv")
    args = parser.parse_args()

    raw_conn, derived_conn = derived_db.bootstrap_cli(lambda conn: None)
    config = DivergenceConfig()

    membership = membership_intervals(raw_conn)
    events = load_events(derived_conn, raw_conn, membership)
    controls = load_controls(derived_conn, raw_conn, membership)
    matches = match_controls(events, controls, seed=MATCH_SEED)
    panel = assemble_panel(events, controls, matches)

    print(f"events: {len(events)}; matched: {matches['event_id'].nunique()}; "
          f"controls used: {matches['control_id'].nunique()}; panel rows: {len(panel)}")
    print(panel.groupby(["direction", "context_class", "is_divergence"]).size().to_string())

    if not args.unblind:
        print("\nBLIND DRY RUN -- no outcome was computed. Re-run with --unblind for the registered readout.")
        raw_conn.close(); derived_conn.close()
        return

    panel = attach_forward_returns(panel, raw_conn, config)
    for h in HORIZONS:
        n_cens = int(panel[f"censored_{h}"].fillna(False).astype(bool).sum())
        n_missing = int(panel[f"fwd_log_ret_{h}"].isna().sum()) - n_cens
        print(f"h={h}: censored at boundary {n_cens}; other missing (never-entered/data holes) {n_missing}")

    cells = []
    for direction, b in (("bearish", "DC-B1"), ("bullish", "DC-B2")):
        for suffix, h in (("a", 63), ("b", 21)):
            res = did_cell(panel, direction, h)
            cells.append({"cell_id": f"{b}{suffix}", "direction": direction, "horizon": h,
                          "kind": "did", **res,
                          "p_value": p_value_from_ci(res["point_estimate"], res["ci_low"],
                                                     res["ci_high"], ci_level=CI_LEVEL)})
        cont = cluster_robust_interaction(panel, direction, 63)
        cells.append({"cell_id": f"{b}c", "direction": direction, "horizon": 63,
                      "kind": "continuous", **cont})

    bh = benjamini_hochberg([c["p_value"] for c in cells])
    for c, passed in zip(cells, bh):
        c["bh_pass"] = bool(passed)

    for direction in ("bearish", "bullish"):
        signs = plateau_signs(panel, direction, 63)
        finite = [s for s in signs if np.isfinite(s)]
        plateau_ok = len(finite) == 9 and (all(s > 0 for s in finite) or all(s < 0 for s in finite))
        a_cell = next(c for c in cells if c["cell_id"].endswith("a") and c["direction"] == direction)
        c_cell = next(c for c in cells if c["cell_id"].endswith("c") and c["direction"] == direction)
        # Sign convention: the DiD is extension-minus-pullback; the
        # interaction b3 is the per-unit-retrace slope of the divergence
        # effect, so a POSITIVE DiD (extension arm larger) corresponds to
        # a NEGATIVE b3. formulations_agree therefore means OPPOSITE signs.
        agree = bool(np.sign(a_cell["point_estimate"]) * np.sign(c_cell["point_estimate"]) < 0)
        for c in cells:
            if c["direction"] == direction:
                c["plateau_ok"] = plateau_ok
                c["formulations_agree"] = agree
                c["verdict"] = verdict(c, c["bh_pass"], plateau_ok, agree)

    print("\n== REGISTERED READOUT (6 cells, one BH correction) ==")
    for c in cells:
        print(f"  {c['cell_id']}: {c['kind']} h={c['horizon']} "
              f"point={c['point_estimate']:+.5f} CI=[{c['ci_low']:+.5f}, {c['ci_high']:+.5f}] "
              f"p={c['p_value']:.4f} BH={'pass' if c['bh_pass'] else 'fail'} "
              f"n_dates={c['n_dates']} plateau={'ok' if c['plateau_ok'] else 'FAIL'} "
              f"agree={'ok' if c['formulations_agree'] else 'FAIL'} -> {c['verdict']}")
        print(f"      cost: hurdle {HURDLE:.4f} (20bps) / {HURDLE_LOW:.4f} (10bps) per round trip")

    if args.log:
        new_file = not EXPERIMENTS_CSV.exists()
        with EXPERIMENTS_CSV.open("a") as f:
            if new_file:
                f.write(_CSV_HEADER)
            today = pd.Timestamp.today().strftime("%Y-%m-%d")
            for c in cells:
                f.write(
                    f"{today},{c['cell_id']},context-dependent {c['direction']} regular-divergence outcomes,"
                    f"{c['kind']}_h{c['horizon']},{c['point_estimate']:.6f},{c['ci_low']:.6f},{c['ci_high']:.6f},"
                    f"{c['p_value']:.5f},{c['bh_pass']},{c['n_dates']},{c.get('n_events', '')},"
                    f"{c.get('n_controls', c.get('n_rows', ''))},{HURDLE},"
                    f"{'clears' if abs(c['point_estimate']) >= HURDLE else 'fails'},"
                    f"{c['plateau_ok']},{c['formulations_agree']},{c['verdict']},frozen 2026-10-08 run\n"
                )
        print(f"\nlogged {len(cells)} rows -> {EXPERIMENTS_CSV}")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()
