"""DC-B1 / DC-B2 — executes the FROZEN pre-registration
(docs/features/divergence-context/PREREGISTRATION.md, frozen 2026-10-08,
plus its pre-unblinding Addendum 2026-10-09 on the agreement-gate sign
convention, the c-cell cost-band scaling, and plateau scoping).

Pure wiring of already-reviewed pieces; every number is governed by the
frozen text + addendum. Nothing here chooses a definition.

**Unblinding gate:** without `--unblind`, stops after matching and
exclusion accounting -- no outcome column is ever computed. `--log`
additionally appends the per-cell rows to the study's EXPERIMENTS.csv.

Usage:
  python -m src.analysis.divergence_trackb_run             # blind dry run
  python -m src.analysis.divergence_trackb_run --unblind [--log]
"""

from __future__ import annotations

import argparse
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.forward_returns import compute_forward_returns
from src.signals.divergences.matching import classify_context, match_controls
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

# Repo-root anchored: a cwd-relative path would let --log silently write a
# fresh CSV somewhere else and report success while the study's real log
# never receives the registered rows.
EXPERIMENTS_CSV = (
    Path(__file__).resolve().parents[2] / "docs" / "features" / "divergence-context" / "EXPERIMENTS.csv"
)
# shape_basis names what the a/b shape columns hold per row -- DiD rows
# log matched ARM-DELTA stats (ext, pb), continuous rows log RAW group
# returns (div, ctrl): same columns, different quantities, so the basis
# is part of the record (a raw group return is a bare conditional
# statistic, invariant #5 -- never comparable to the controlled one).
_CSV_HEADER = (
    "date,cell_id,hypothesis,statistic,point_estimate,ci_low,ci_high,p_value,bh_pass,"
    "arm_extension,arm_pullback,n_event_dates,n_months,n_events,n_controls,"
    "shape_basis,hit_a,wl_a,skew_a,hit_b,wl_b,skew_b,"
    "cost_hurdle,cost_point,cost_verdict,plateau_ok,plateau_finite,formulations_agree,"
    "verdict,notes\n"
)


# ---- frames and panels ----


def load_full_frames(derived_conn, raw_conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Events and control pool WITHOUT the pole filter (classify-but-keep):
    the frozen c-cells use every event including the buffer band and
    deep-fast; the binary path re-filters to the poles itself."""
    membership = membership_intervals(raw_conn)
    events = load_events(derived_conn, raw_conn, membership, require_class=False)
    controls = load_controls(derived_conn, raw_conn, membership, require_class=False)
    return events.assign(is_divergence=True), controls.assign(is_divergence=False)


def pole_frames(ev_all: pd.DataFrame, ct_all: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return ev_all[ev_all["context_class"].notna()], ct_all[ct_all["context_class"].notna()]


def assemble_panel(
    events: pd.DataFrame, controls: pd.DataFrame, matches: pd.DataFrame
) -> pd.DataFrame:
    """Matched events + their controls: match_group = the event's id (one
    stratum per event, which makes stratum deltas per-event-weighted)."""
    ev = events[events["id"].isin(matches["event_id"])].copy()
    ev["match_group"] = ev["id"]
    ctrl_to_event = dict(zip(matches["control_id"], matches["event_id"]))
    ct = controls[controls["id"].isin(matches["control_id"])].copy()
    ct["match_group"] = ct["id"].map(ctrl_to_event)
    return pd.concat([ev, ct], ignore_index=True)


def attach_forward_returns(frame: pd.DataFrame, raw_conn, config: DivergenceConfig) -> pd.DataFrame:
    """Per-ticker bar loads (as_of DEV_END), fail-closed returns. The
    delisted flag comes from the tickers table; a ticker MISSING from it
    passes delisted=None so the tolerance inference applies -- never a
    forced 'active' (which would censor away delisting-terminal returns,
    the invariant-#4 bias). THE UNBLINDING STEP."""
    info = {
        t: (a, d)
        for t, a, d in raw_conn.execute("SELECT ticker, active, delisted_utc FROM tickers")
    }
    out = []
    for ticker, grp in frame.groupby("ticker"):
        bars, _report = data_mod.load_and_validate(
            raw_conn, ticker, Timeframe.DAILY, as_of=DEV_END, basis=config.price_basis
        )
        if len(bars) == 0:
            fr = pd.DataFrame(index=grp.index)
            for h in HORIZONS:
                fr[f"fwd_log_ret_{h}"] = None
                fr[f"censored_{h}"] = None
                fr[f"truncated_{h}"] = None
        else:
            # WHEN the ticker delisted matters, not just whether: active=0
            # with a post-DEV_END delisting means the ticker was ALIVE at
            # the boundary -- its series end there is censoring, and
            # passing delisted=True would smuggle shortened holds into the
            # late-window cells as fake terminal returns.
            if ticker in info:
                act, dl = info[ticker]
                if act == 0 and dl is not None and str(dl)[:10] <= DEV_END:
                    delisted = True
                elif act == 0 and dl is None:
                    delisted = None  # dead, timing unknown: tolerance inference
                else:
                    delisted = False  # alive at the boundary (or delisted after it)
            else:
                delisted = None
            fr = compute_forward_returns(
                bars, grp["confirmed_at"], horizons=HORIZONS,
                data_end=DEV_END, delisted=delisted,
            )
        out.append(
            grp.join(fr[[c for c in fr.columns if c.startswith(("fwd_", "censored_", "truncated_"))]])
        )
    return pd.concat(out).sort_index()


# ---- registered statistics ----


def per_event_deltas(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """One row per matched event: its return minus the mean of its own
    controls', with the event's context class. The unit the DiD, the
    plateau points, and the invariant-#10 shape stats all share."""
    col = f"fwd_log_ret_{horizon}"
    sub = panel[panel[col].notna()]
    strat = sub.groupby(["match_group", "is_divergence"])[col].mean().unstack()
    if True not in strat.columns or False not in strat.columns:
        return pd.DataFrame(columns=["match_group", "context_class", "delta"])
    delta = (strat[True] - strat[False]).dropna().rename("delta").reset_index()
    ev_class = sub[sub["is_divergence"]][["match_group", "context_class"]].drop_duplicates()
    return delta.merge(ev_class, on="match_group", how="left")


def shape_stats(deltas: pd.Series) -> dict:
    """Invariant #10: hit rate, win/loss magnitude ratio, skew --
    descriptive only, no CI, no N_tests contribution."""
    d = deltas.dropna()
    if d.empty:
        return {"hit": float("nan"), "wl": float("nan"), "skew": float("nan")}
    wins, losses = d[d > 0], d[d < 0]
    wl = (
        float(wins.mean() / abs(losses.mean()))
        if len(wins) and len(losses) and losses.mean() != 0
        else float("nan")
    )
    return {"hit": float((d > 0).mean()), "wl": wl, "skew": float(d.skew())}


def did_cell(panel: pd.DataFrame, direction: str, horizon: int, seed: int = MATCH_SEED) -> dict:
    """Binary DiD, frozen: (div - ctrl | extension) - (div - ctrl | pullback)."""
    col = f"fwd_log_ret_{horizon}"
    sub = panel[(panel["direction"] == direction) & panel[col].notna()].copy()
    sub["month_ts"] = pd.to_datetime(sub["p2_month"] + "-01")
    ext = sub[sub["context_class"] == "extension"]
    pb = sub[sub["context_class"] == "pullback_rebuild"]
    res = block_bootstrap_delta_diff(
        ext, pb, group_col="is_divergence", value_col=col,
        match_cols=["match_group"], date_col="month_ts",
        block_length=BLOCK_MONTHS, n_boot=N_BOOT, ci=CI_LEVEL, seed=seed,
    )
    deltas = per_event_deltas(sub, horizon)
    res["shape_ext"] = shape_stats(deltas.loc[deltas["context_class"] == "extension", "delta"])
    res["shape_pb"] = shape_stats(deltas.loc[deltas["context_class"] == "pullback_rebuild", "delta"])
    ev_rows = sub[sub["is_divergence"]]
    res["n_event_dates"] = int(ev_rows["p2_date"].nunique())  # invariant #6: distinct DATES
    res["n_months"] = int(sub["p2_month"].nunique())
    res["n_events"] = int(ev_rows["id"].nunique())
    res["n_controls"] = int((~sub["is_divergence"]).sum())
    return res


def cluster_robust_interaction(frame: pd.DataFrame, direction: str, horizon: int) -> dict:
    """Continuous cell, frozen: fwd ~ b0 + b1*div + b2*retrace + b3*div*retrace
    over EVERY row with a defined retrace (buffer band and deep-fast
    included, matched or not -- the 'uses every event' formulation),
    CR0-sandwich clustered by p2 month."""
    col = f"fwd_log_ret_{horizon}"
    sub = frame[
        (frame["direction"] == direction)
        & frame[col].notna()
        & frame["interpeak_retrace_frac"].notna()
    ]
    y = sub[col].to_numpy(dtype=float)
    d = sub["is_divergence"].to_numpy(dtype=float)
    r = sub["interpeak_retrace_frac"].to_numpy(dtype=float)
    X = np.column_stack([np.ones_like(d), d, r, d * r])
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((4, 4))
    for idx in sub.groupby("p2_month").indices.values():
        s = X[idx].T @ resid[idx]
        meat += np.outer(s, s)
    cov = XtX_inv @ meat @ XtX_inv
    se = float(np.sqrt(cov[3, 3]))
    b3 = float(beta[3])
    z = b3 / se if se > 0 else float("nan")
    p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))) if np.isfinite(z) else float("nan")
    half = 1.959963984540054 * se
    ev_rows = sub[sub["is_divergence"]]
    return {
        "point_estimate": b3, "ci_low": b3 - half, "ci_high": b3 + half, "p_value": p,
        "n_event_dates": int(ev_rows["p2_date"].nunique()),
        "n_months": int(sub["p2_month"].nunique()),
        "n_events": int(ev_rows["id"].nunique()), "n_controls": int((~sub["is_divergence"]).sum()),
        "shape_ext": shape_stats(sub.loc[sub["is_divergence"], col]),
        "shape_pb": shape_stats(sub.loc[~sub["is_divergence"], col]),
    }


def retrace_pole_gap(ev_all: pd.DataFrame, ct_all: pd.DataFrame) -> dict[str, float]:
    """Addendum 2026-10-09 item 2: the blind (covariates-only) scale that
    converts a c-cell's b3 slope to return units -- median retrace of the
    pullback pole minus median of the extension pole, pooled
    events+controls, per direction."""
    pooled = pd.concat([ev_all, ct_all], ignore_index=True)
    out = {}
    for direction, grp in pooled.groupby("direction"):
        med_pb = grp.loc[grp["context_class"] == "pullback_rebuild", "interpeak_retrace_frac"].median()
        med_ext = grp.loc[grp["context_class"] == "extension", "interpeak_retrace_frac"].median()
        out[direction] = float(med_pb - med_ext)
    return out


def classify_with(retrace_min: float, leg2_min: int):
    """Thin binding of the ONE canonical classifier
    (matching.classify_context) to a plateau neighbor's thresholds --
    never a re-implementation, so the plateau can't silently classify
    with different pole definitions than the main panel."""
    return lambda retrace, leg2: classify_context(
        retrace, leg2, retrace_min=retrace_min, leg2_min=leg2_min
    )


def plateau_points(
    ev_all: pd.DataFrame, ct_all: pd.DataFrame, direction: str,
    horizons: tuple[int, ...] = HORIZONS, seed: int = MATCH_SEED,
) -> dict[int, list[float]]:
    """Each 3x3 neighbor is a FULL re-classify AND re-match from the
    unfiltered frames (addendum item 3) -- reclassifying the
    frozen-threshold panel would deny widening neighbors the band and
    deep-fast events their definitions include. Classification and
    matching are horizon-independent, so each neighbor's panel is built
    ONCE and evaluated at every horizon. Point estimates only: the
    frozen gate is sign stability."""
    ev_d = ev_all[ev_all["direction"] == direction]
    ct_d = ct_all[ct_all["direction"] == direction]
    points: dict[int, list[float]] = {h: [] for h in horizons}
    for rmin in PLATEAU_RETRACE:
        for lmin in PLATEAU_LEG2:
            cls = classify_with(rmin, lmin)
            ev = ev_d.copy()
            ev["context_class"] = [cls(a, b) for a, b in zip(ev["interpeak_retrace_frac"], ev["leg2_bars"])]
            ev = ev[ev["context_class"].notna()]
            ct = ct_d.copy()
            ct["context_class"] = [cls(a, b) for a, b in zip(ct["interpeak_retrace_frac"], ct["leg2_bars"])]
            ct = ct[ct["context_class"].notna()]
            if ev.empty or ct.empty:
                for h in horizons:
                    points[h].append(float("nan"))
                continue
            m = match_controls(ev, ct, seed=seed)
            if m.empty:
                for h in horizons:
                    points[h].append(float("nan"))
                continue
            panel = assemble_panel(ev, ct, m)
            for h in horizons:
                deltas = per_event_deltas(panel, h)
                ext = deltas.loc[deltas["context_class"] == "extension", "delta"]
                pb = deltas.loc[deltas["context_class"] == "pullback_rebuild", "delta"]
                points[h].append(
                    float(ext.mean() - pb.mean()) if (len(ext) and len(pb)) else float("nan")
                )
    return points


def plateau_gate(points: list[float]) -> tuple[bool, int]:
    """Addendum item 3: finite neighbors must agree in sign; an
    incomputable neighbor is absence of evidence, not disagreement. The
    finite count is reported alongside."""
    finite = [p for p in points if np.isfinite(p) and p != 0]
    if not finite:
        return False, 0
    ok = all(p > 0 for p in finite) or all(p < 0 for p in finite)
    return ok, len(finite)


def verdict(cell: dict, bh_pass: bool, plateau_ok: bool, formulations_agree: bool) -> str:
    """Frozen three-way verdicts. `cell` carries the values the cost band
    applies to -- for c-cells the caller passes the RETURN-UNIT scaled
    point/CI (addendum item 2), never the raw slope."""
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

    ev_all, ct_all = load_full_frames(derived_conn, raw_conn)
    ev_b, ct_b = pole_frames(ev_all, ct_all)
    matches = match_controls(ev_b, ct_b, seed=MATCH_SEED)
    gaps = retrace_pole_gap(ev_all, ct_all)

    print(f"events: {len(ev_all)} total / {len(ev_b)} in poles; matched: {matches['event_id'].nunique()}; "
          f"controls: {len(ct_all)} total / {len(ct_b)} in poles, used: {matches['control_id'].nunique()}")
    print(f"c-cell samples (every defined retrace): "
          f"{(ev_all['interpeak_retrace_frac'].notna()).sum()} events + "
          f"{(ct_all['interpeak_retrace_frac'].notna()).sum()} controls")
    print(f"blind b3->return scale (median retrace pole gap): { {k: round(v, 3) for k, v in gaps.items()} }")

    if not args.unblind:
        print("\nBLIND DRY RUN -- no outcome was computed. Re-run with --unblind for the registered readout.")
        raw_conn.close(); derived_conn.close()
        return

    full = attach_forward_returns(pd.concat([ev_all, ct_all], ignore_index=True), raw_conn, config)
    for h in HORIZONS:
        n_cens = int(full[f"censored_{h}"].fillna(False).astype(bool).sum())
        n_trunc = int(full[f"truncated_{h}"].fillna(False).astype(bool).sum())
        n_missing = int(full[f"fwd_log_ret_{h}"].isna().sum()) - n_cens
        print(f"h={h}: censored at boundary {n_cens}; delisting-truncated KEPT {n_trunc}; "
              f"other missing (never-entered/data holes) {n_missing}")

    ev_full = full[full["is_divergence"]]
    ct_full = full[~full["is_divergence"]]
    binary_panel = assemble_panel(
        ev_full[ev_full["context_class"].notna()], ct_full[ct_full["context_class"].notna()], matches
    )

    cells = []
    for direction, b in (("bearish", "DC-B1"), ("bullish", "DC-B2")):
        for suffix, h in (("a", 63), ("b", 21)):
            res = did_cell(binary_panel, direction, h)
            cells.append({"cell_id": f"{b}{suffix}", "direction": direction, "horizon": h,
                          "kind": "did", **res,
                          "p_value": p_value_from_ci(res["point_estimate"], res["ci_low"],
                                                     res["ci_high"], ci_level=CI_LEVEL)})
        cont = cluster_robust_interaction(full, direction, 63)
        cells.append({"cell_id": f"{b}c", "direction": direction, "horizon": 63,
                      "kind": "continuous", **cont})

    bh = benjamini_hochberg([c["p_value"] for c in cells])
    for c, passed in zip(cells, bh):
        c["bh_pass"] = bool(passed)

    plateau_by = {}
    for direction in ("bearish", "bullish"):
        pts = plateau_points(ev_full, ct_full, direction, HORIZONS)
        for h in HORIZONS:
            plateau_by[(direction, h)] = plateau_gate(pts[h])
        a_cell = next(c for c in cells if c["cell_id"].endswith("a") and c["direction"] == direction)
        c_cell = next(c for c in cells if c["cell_id"].endswith("c") and c["direction"] == direction)
        # Addendum item 1: the DiD is extension-minus-pullback while b3 is
        # the per-unit-retrace slope of the divergence effect, so a real
        # effect produces OPPOSITE signs -- agreement means sign product < 0.
        # A NaN or exactly-zero point estimate leaves the gate UNDEFINED --
        # by the addendum's own principle an incomputable formulation is
        # absence of evidence, never disagreement, so None here does not
        # demote (verdict treats None as not-failed; readout prints n/a).
        sa, sc = a_cell["point_estimate"], c_cell["point_estimate"]
        if not (np.isfinite(sa) and np.isfinite(sc)) or sa == 0 or sc == 0:
            agree = None
        else:
            agree = bool(np.sign(sa) * np.sign(sc) < 0)
        for c in cells:
            if c["direction"] == direction:
                c["plateau_ok"], c["plateau_finite"] = plateau_by[(direction, c["horizon"])]
                c["formulations_agree"] = agree

    for c in cells:
        if c["kind"] == "continuous":
            scale = gaps[c["direction"]]
            c["cost_point"] = c["point_estimate"] * scale
            band = {"point_estimate": c["point_estimate"] * scale,
                    "ci_low": c["ci_low"] * scale, "ci_high": c["ci_high"] * scale}
            if scale < 0:
                band["ci_low"], band["ci_high"] = band["ci_high"], band["ci_low"]
        else:
            c["cost_point"] = c["point_estimate"]
            band = c
        gate_agree = c["formulations_agree"] if c["formulations_agree"] is not None else True
        c["verdict"] = verdict(band, c["bh_pass"], c["plateau_ok"], gate_agree)

    print("\n== REGISTERED READOUT (6 cells, one BH correction) ==")
    for c in cells:
        arms = (f" arms ext={c.get('point_a', float('nan')):+.5f} pb={c.get('point_b', float('nan')):+.5f}"
                if c["kind"] == "did" else "")
        print(f"  {c['cell_id']}: {c['kind']} h={c['horizon']} "
              f"point={c['point_estimate']:+.5f} CI=[{c['ci_low']:+.5f}, {c['ci_high']:+.5f}] "
              f"p={c['p_value']:.4f} BH={'pass' if c['bh_pass'] else 'fail'}{arms}")
        print(f"      n: {c['n_event_dates']} event dates / {c['n_months']} months / "
              f"{c['n_events']} events / {c['n_controls']} control rows; "
              f"plateau={'ok' if c['plateau_ok'] else 'FAIL'}({c['plateau_finite']}/9 finite) "
              f"agree={'n/a' if c['formulations_agree'] is None else ('ok' if c['formulations_agree'] else 'FAIL')}"
              f" -> {c['verdict']}")
        se, sp = c["shape_ext"], c["shape_pb"]
        label = ("ext-arm deltas", "pb-arm deltas") if c["kind"] == "did" else ("event returns", "control returns")
        print(f"      shape {label[0]}: hit={se['hit']:.2f} wl={se['wl']:.2f} skew={se['skew']:.2f}; "
              f"{label[1]}: hit={sp['hit']:.2f} wl={sp['wl']:.2f} skew={sp['skew']:.2f}")
        print(f"      cost: point-in-return-units {c['cost_point']:+.5f} vs hurdle {HURDLE:.4f} (20bps) "
              f"/ {HURDLE_LOW:.4f} (10bps)")

    if args.log:
        new_file = not EXPERIMENTS_CSV.exists()
        with EXPERIMENTS_CSV.open("a") as f:
            if new_file:
                f.write(_CSV_HEADER)
            today = pd.Timestamp.today().strftime("%Y-%m-%d")
            for c in cells:
                se, sp = c["shape_ext"], c["shape_pb"]
                arm_ext = f"{c['point_a']:.6f}" if c["kind"] == "did" else ""
                arm_pb = f"{c['point_b']:.6f}" if c["kind"] == "did" else ""
                basis = "matched_arm_deltas(ext;pb)" if c["kind"] == "did" else "raw_group_returns(div;ctrl)"
                agree_s = "" if c["formulations_agree"] is None else str(c["formulations_agree"])
                f.write(
                    f"{today},{c['cell_id']},context-dependent {c['direction']} regular-divergence outcomes,"
                    f"{c['kind']}_h{c['horizon']},{c['point_estimate']:.6f},{c['ci_low']:.6f},{c['ci_high']:.6f},"
                    f"{c['p_value']:.5f},{c['bh_pass']},{arm_ext},{arm_pb},"
                    f"{c['n_event_dates']},{c['n_months']},{c['n_events']},{c['n_controls']},"
                    f"{basis},{se['hit']:.3f},{se['wl']:.3f},{se['skew']:.3f},"
                    f"{sp['hit']:.3f},{sp['wl']:.3f},{sp['skew']:.3f},"
                    f"{HURDLE},{c['cost_point']:.6f},"
                    f"{'clears' if abs(c['cost_point']) >= HURDLE else 'fails'},"
                    f"{c['plateau_ok']},{c['plateau_finite']},{agree_s},"
                    f"{c['verdict']},frozen 2026-10-08 + addendum 2026-10-09 run\n"
                )
        print(f"\nlogged {len(cells)} rows -> {EXPERIMENTS_CSV}")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()
