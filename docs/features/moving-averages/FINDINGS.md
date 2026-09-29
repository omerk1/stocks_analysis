# Findings register — Tier 1, 2 and 3

Track B only. One entry per current Tier 1–3 cell; robustness companions sit inside their
parent entry. Withdrawn or Tier-4 cells are in `EXPERIMENTS.csv` only.

Conventions: effects are C2-matched (date + momentum tercile + vol tercile + sector).
CIs are 90% date-block bootstraps. Effective N is distinct dates. Cost is annualised
linearly at 10 bps round trip, shown at both CI ends against the cell's own
turnover-based hurdle. Every cell carries the universe caveat in `STATUS.md`'s open
items: U1 has no delisted history, which flatters weak-state buckets.

---

## Tier 2

### M6.3 `slope_pctile_21_sma_50` — extreme 50-day slope beats flat slope

- **Hypothesis**: 21d return is non-monotonic in the per-date percentile of
  `slope_log_21_sma_50`. DESIGN expected a hump ("too much trend is exhaustion").
- **Why plausible**: trend-following folklore and the exhaustion story predict opposite
  shapes; the magnitude of slope is untested by M6.1's linear test.
- **Run**: middle deciles {4,5} vs tail deciles {0,1,8,9}, C2.
- **Result**: **U-shaped.** Middle minus tails −0.248% [−0.354%, −0.153%] per 21d.
  Most of the lift sits in deciles 0 and 9 alone.
  - Rising tail alone: −0.254% [−0.429%, −0.085%].
  - Falling tail alone: −0.244% [−0.413%, −0.096%].
  - With a reversal control: −0.282%.
  - Excluding recent large moves: −0.264%.
  - Stable across seeds 0–3.
- **Effective N**: 2,747 dates, 219,700 rows.
- **Cost**: −1.83% / −4.25% per year at the CI ends vs a 0.77% hurdle. Clears, and also
  clears at 20 bps.
- **FDR**: p=0.00005, rank 2 of 107, survives at q=0.05.
- **Tier 2**: it lacks only a holdout and a second universe.
- **Would change**: a 2022+ holdout or a point-in-time universe with delisted names. The
  rising-tail result already rules out a delisted-only artefact.

---

## Tier 3

### M6.6 `ribbon_agreement_extreme_drawdown` — all-agree slopes, shallower drawdown

- **Hypothesis**: when the {10,20,50,100,200}-day SMA slopes all agree, forward 21d max
  drawdown differs from when all disagree.
- **Result**: +0.654pp shallower drawdown [+0.438, +0.887]. With a reversal control:
  +0.535pp. Signed 21d return on the same restriction spans zero.
- **Effective N**: 2,747 dates.
- **Cost**: +5.25% / +10.64% per year vs a 0.54% hurdle. This is an avoided-loss reading,
  not a return.
- **FDR**: survives, rank 1.
- **Tier 3**: a drawdown effect with no signed-return counterpart.
- **Would change**: a barrier or stop-based test showing the drawdown difference turns into
  realised P&L.

### M12 `reclaim_durability_dollar_volume_sma50` — low-volume reclaims outperform

- **Hypothesis**: SMA50 reclaims on high dollar volume outperform those on low. DESIGN's
  direction was the opposite of what came out.
- **Result**: top minus bottom tercile −0.870% [−1.381%, −0.402%]. With a reversal
  control: −0.574% [−1.132%, −0.069%].
- **Effective N**: 2,468 event dates, 866 bootstrap-contributing.
- **Cost**: −4.82% / −16.57% per year vs a 0.29% hurdle.
- **FDR**: misses (p=0.0035 vs 0.0028).
- **Tier 3**: dollar volume is a size proxy, and no point-in-time market cap exists.
- **Would change**: a size-matched rerun.

### M12 `reclaim_hold_rate_relative_volume_sma200` — high-volume reclaims hold

- **Result**: top relative-volume SMA200 reclaims are still above the MA 21 days later
  +3.35pp more often [+0.44, +6.37].
- **Effective N**: 2,177 dates.
- **Tier 3**: a mechanism reading, companion cell, single lookback.

### M18 `dist_from_52w_low` — distance above the 52-week low

- **Hypothesis**: position in the trailing 252-day range predicts 63d and 126d return.
- **Result**:
  - 126d: +2.50% [+1.10%, +4.02%]; with a reversal control +2.64%.
  - 63d: +0.96% [+0.13%, +1.84%].
  - Near-52w-high: spans zero at both horizons. Its uncontrolled effect was momentum.
- **Effective N**: 2,643 / 2,706 dates. The 126d cell has only about 10 bootstrap blocks.
- **Cost**: 126d gives +2.21% / +8.03% per year vs 0.83% (clears); 63d gives +0.51% /
  +7.37% vs 0.82% (fails).
- **FDR**: 126d misses (p=0.0047 vs 0.0037).
- **Tier 3**: tercile momentum matching leaves residual momentum in a feature built from
  the same price path, and the cell is survivorship-exposed.
- **Would change**: a decile momentum match, or residualising against `mom_12_1`.

### M7 `ribbon_direction_magnitude` — compression predicts move size

- **Hypothesis**: ribbon compression predicts forward realised vol. That was killed.
  Compression predicts forward \|return\| instead.
- **Result**: dispersed minus compressed −0.247% [−0.398%, −0.093%] on \|21d return\|.
  With a reversal control: −0.266%.
- **Effective N**: 2,549 dates.
- **Cost**: −1.11% / −4.77% per year vs 0.32%, but this measures magnitude, not direction.
- **FDR**: misses.
- **Tier 3**: not a directional claim.

### M2 `stack_fully_bearish` — price < SMA20 < 50 < 150 < 200

- **Hypothesis**: the full bearish stack carries information beyond `above_sma_50`.
- **Result**:
  - Standalone: +0.474% [+0.161%, +0.776%].
  - Incremental over `above_sma_50`: +1.055% [+0.419%, +1.740%].
  - With a reversal control: +0.319% [+0.044%, +0.598%].
  - Shape: hit rate 63.9%, skew +0.99.
- **Effective N**: 2,696 dates.
- **Cost**: standalone +1.93% / +9.31% per year vs 0.29%; the reversal-controlled near
  edge +0.53% fails at 20 bps.
- **FDR**: misses.
- **Tier 3**: a beaten-down bucket in a universe with no delistings (DESIGN §7.3).

### M6.2 `extension_x_slope`, SMA50 top decile — extended and rising is worse

- **Hypothesis**: among the most extended names (top `dist_atr_sma_50` decile), slope
  direction changes forward return.
- **Result**: rising minus falling −0.592% [−1.047%, −0.175%]. With a reversal control:
  −0.550%.
- **Effective N**: 2,747 dates. The falling subgroup is 7.1% of the decile.
- **Cost**: −2.10% / −12.56% per year vs 0.81%.
- **FDR**: misses (p=0.025).
- **Tier 3**: Track A found no gradient across neighbouring deciles, so this is a lone
  pixel.

### M6.2 `touch_x_slope`, SMA50 from above

- **Result**: hold rate −5.75pp [−10.22, −1.94] when the 50-day is rising.
- **Effective N**: 2,410 dates.
- **Tier 3**: with a reversal control the CI spans zero (−3.33pp [−8.18, +1.25]), so this
  is close to a dead end.

### M6.3 `slope_pctile_21` at SMA20 and SMA200

- **SMA20**: −0.117% [−0.229%, −0.006%]. Fails cost (near edge −0.08% vs a 1.34%
  hurdle) and fails the large-move exclusion.
- **SMA200**: −0.193% [−0.337%, −0.056%]. Clears cost, but with a reversal control it is
  −0.038% and spans zero.
- **Tier 3**: same sign as SMA50; both are weaker copies of it.

### M1 `above_sma_20`, `above_sma_50`

- **Result**: −0.215% [−0.350%, −0.079%] and −0.183% [−0.341%, −0.031%] per 21d.
- **Shrinkage**: roughly 60–70% of the pooled effect disappears under C1/C2.
- **Effective N**: 2,744 / 2,746 dates.
- **Cost**: −0.95% / −4.19% vs a 3.04% hurdle, and −0.37% / −4.09% vs 1.80%. Both fail.
- **Tier 3**: fails cost.

### M4 / M11 distance from SMA20

- **Result**:
  - M4 decile spread: −0.464% [−0.776%, −0.137%]. `dist_atr` and `dist_z` are 0.94–0.98
    correlated with `dist_pct` and give the same answer.
  - M11's neutralised spread recomputes M4's numbers; its rank-IC adds nothing new.
  - M11 5-day cell: rank-IC −0.0138 [−0.0225, −0.0041].
- **Effective N**: 2,747 / 2,996 dates.
- **Cost**:
  - 21d: −1.64% / −9.31% vs 2.46%, fails.
  - 5d: −3.45% / −17.6% vs 2.47%, clears, but the shortest horizon clearing is what
    short-term reversal would produce.
- **Tier 3**: fails cost at 21d; confounded at 5d.

### M13 `context_vix_bottom`, `context_breadth_top`

- **Result**: `above_sma_200` in a low-VIX regime −0.318% [−0.551%, −0.073%]; in a
  high-breadth regime −0.388% [−0.690%, −0.074%].
- **Effective N**: 1,195 / 882 dates.
- **Cost**: near edge −0.87% / −0.88% vs a 0.69% / 0.64% hurdle.
- **Tier 3**: all four regime slices sit near M1's whole-sample −0.215%. This reads as the
  baseline effect, not an interaction.

### M17 MACD histogram, incremental IC over the MA block

- **Result**: +0.0089 [+0.00002, +0.0187]. Correlation with `dist_pct_sma_50` is 0.30,
  and with `slope_log_21_sma_50` −0.25.
- **Effective N**: 2,747 dates.
- **FDR**: misses (p=0.115).
- **Tier 3**: marginal, and no reversal control was run.

### M6.4 efficiency-ratio companion (not counted)

- **Result**: against a direction-matched GBM null, the top efficiency-ratio tercile's
  slope runs outlast it at SMA20 (+0.109) and SMA50 (+0.060). The bottom tercile falls
  short at the same two lookbacks. SMA150/200 do not depart.
- **Tier 3**: mechanical only. Efficiency ratio at entry measures how straight the path
  already was, so persistence is close to restating the conditioning variable.
