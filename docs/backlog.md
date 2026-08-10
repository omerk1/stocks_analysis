# Backlog

In-progress and open items. Completed work lives in `docs/done.md`
instead — append there when something finishes rather than moving it
here first.

## In progress / open questions

- **sr_lines, still open** (grouped since they're all part of the same ongoing review — full detail in `docs/sr_lines_design_notes.md`):
  - `in_play_gate` is only *partly* fixed. `regime_start` (Done #22/#24/#25) fixed averaging over a line's entire history; still not fixed: it's one flat average *within* the current regime, so it can't tell "scattered near-misses" from "one solid contiguous block of disconnection." Likely needs a max-contiguous-out-of-play penalty, not a different average.
  - Milestones 6 (`as_of` test coverage) and 7 (systematic weight-tuning pass) still ahead. Carried-forward calibration questions: `resilience`'s cap can still be hit by enough recent events; wick-fake vs. body-fake resilience credit may be inverted from real-world evidence-strength; `max_diagonal_slope_atr_per_bar`'s log-slope interpretation; why `--dedup-threshold` affects diagonal clutter much less than horizontal.
  - Penetration-depth *trend* signal (deepening = weakening, shallowing = strengthening) — the volume half is done (Done #19), this half isn't built.
  - **Weekly-bar mechanism shipped (Done #30), calibration still open**: the three bar-count-denominated config knobs (`fakeout_reclaim_bars=1`, `touch_reaction_window_bars=2`, `diagonal_min_pivot_separation_bars=4`) are a first-pass starting point, not yet validated against real weekly charts.
- **Data quality, found via sr_lines but not sr_lines-specific**: T's 2023-01-24 daily bar has a ~13% intraday spike that fully reverses same-day, uncaught by the existing validation gate (which only checks close-to-close continuity). Worth an intraday-range-vs-ATR sanity check.
- Whether/how to source quarterly financials — still gated behind an undecided Polygon paid tier.
- **Historical shares-outstanding (Done #31), two follow-ups not yet done**: the bulk backfill hasn't been run against the full active universe yet (held for explicit go-ahead — real API-cost/rate-limit operation). Separately, computing a real historical market cap needs the raw (non-split-adjusted) share counts reconciled against `bars_1d`'s split-adjusted price convention — not attempted yet.
