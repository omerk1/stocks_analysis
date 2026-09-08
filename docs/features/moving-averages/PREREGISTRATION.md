# Pre-registration

Track B only (DESIGN.md §6.6). Written and committed *before* running the analysis it
describes — that ordering is the point. Once a grid entry has been run, its definition
here is frozen; a later change of scope goes in as a new, separately dated entry, not an
edit to this one (DESIGN.md §6.6's `N_tests` denominator needs the full history, not a
silently-revised one).

## M4 — Distance from MA (2026-09-08)

**Module / track:** M4, Track B (DESIGN.md §8, M4).

**Promoted from:** Track A M0.1 descriptive atlas (`EXPLORATION_LOG.md`, 2026-09-07/08)
— four of five candidate observations pointed at distance-from-MA normalisation/shape
questions. The fifth (Candidate C-1, the liquidity-decile gradient) is tracked
separately in `EXPLORATION_LOG.md` and is **not** part of this entry.

**Hypothesis:** Forward 21-day return is a non-monotonic (or otherwise structured)
function of displacement from SMA{20,50,200}, and that structure differs by
normalisation (`dist_pct` vs. `dist_atr` vs. `dist_z`) — per DESIGN §2.3(3) and the
2026-09-07 M0.1 finding that ATR-normalisation visibly changes distribution shape, not
just scale.

**This slice's scope** (a first pass, not the full DESIGN §8 M4 spec):
- Features: `dist_pct`, `dist_atr`, `dist_z` at SMA{20, 50, 200} — the Phase 2 starting
  subset. (`dist_pctile` isn't built yet; WMA/HMA/KAMA/VWMA distance isn't in scope, per
  Phase 2's own deferral.)
- Event definition: decile bucket of the distance feature, computed and lagged exactly
  as already built in `features/distance.py`/`features/panel.py` — no new event type.
- Horizon: 21 trading days only (`fwd_ret_21`) — the horizon Phase 1's synthetic gate
  already validated. The full 8-horizon term structure is deferred to a later slice.
- Universe: the 408 S&P 500 constituents (as of 2021-12-31) already cached, dev window
  2010-01-01 → 2021-12-31. Not yet run across U1/U2/U3 tiers (DESIGN §3.2) or an ER
  high/low split — both deferred.
- Controls: **C0, C1, and C2** (date + momentum-tercile + vol-tercile + sector matched —
  see "C2 note" below for tercile vs. decile). C1 is the default per DESIGN §6.1; the
  full C0→C1→C2 shrinkage waterfall is the primary output.
- **Not in this slice:** vol-neutralisation as its own separate pass (distinct from the
  C2 vol-tercile match — DESIGN's "repeat with vol-neutralisation" sub-bullet),
  ER/trend-quality conditioning, the 7.5–8× ATR exhaustion claim, and the IJECM
  0–5%-below claim. Each needs its own pre-registered follow-up entry, not silent
  inclusion here.

**Grid size (N_tests contribution):** 3 normalisations × 3 lookbacks × 10 deciles = 90
bucket-level cells, 1 horizon, 1 universe. No FDR correction applied at this slice
(DESIGN §6.6's correction denominator accumulates across the whole pre-registered grid,
not per-module) — noted here for when that accounting happens.

**Kill criterion:** if no monotonic or reliably U-shaped relationship between distance
decile and C2-adjusted `fwd_ret_21` survives at **any** of the 9 (normalisation ×
lookback) facets — i.e. every facet's decile pattern is flat/noisy after C2 matching —
report the whole slice as a strong negative per DESIGN §8 M4's own kill criterion, and
do not narrow the search for a facet that "works."

**Control tier and why:** C1 is the default read (DESIGN §6.1) — removes the shared
market-return confound via date-matching. **C2 is the tier that actually answers the
research question** (DESIGN §6.1: "the one that separates real MA information from
momentum re-encoding"), since distance-from-MA is mechanically close to trailing
momentum — a stock far above its 50-day is largely restating "this stock went up a lot
recently" (DESIGN §7.1). C0 is reported only for the shrinkage waterfall, never as the
headline.

**C2 note (tercile, not decile):** DESIGN §6.1 specifies "same rs_rank decile, same vol
decile, same sector." At today's universe size (408 tickers/date), decile × decile ×
11-sector matching yields up to 1,100 cells/date against ~400 tickers/date — too sparse
to populate reliably. This slice uses **terciles** for momentum and vol (3 × 3 × 11 = 99
cells/date) instead, logged here as a practical adaptation to the current universe size,
not a silent substitution. Revisit at decile granularity once the universe broadens
(e.g. full U2).

**Momentum control used:** `mom_12_1` (12-month return skipping the most recent month:
`close[t-21]/close[t-252] - 1`) — DESIGN §7.1's own vocabulary for the momentum control,
computed directly rather than via the fuller `relative_strength` module's rs_rating
pipeline (index-membership-scoped, sector-ETF-benchmarked — heavier machinery than a
tercile bucket needs; revisit if/when `rs_rank` itself becomes a first-class feature).

**Vol control used:** `realized_vol_63` (63-trading-day rolling std of daily returns).

**Minimum sample threshold (DESIGN §6.9):** no bucket reported below 200 events across
≥30 distinct dates and ≥30 distinct tickers; below-threshold buckets are shown flagged,
not as an interpretable number.

**Plateau check (DESIGN §6.7):** neighbouring deciles (±1) must agree in sign/rough
magnitude; the three lookbacks (20/50/200) are compared for consistency of pattern
across the grid, not treated as independent single points.

**Effective N:** reported as distinct event dates alongside raw row count, per bucket
(CLAUDE.md invariant #6) — required in the output table, not optional.
