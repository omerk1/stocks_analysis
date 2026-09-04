# Pivot Breakout Validation — Design Doc

**Purpose:** Implementation brief for three "universal pivot variation" breakout behaviors layered on top of the existing pivot/S-R/pattern infrastructure: **Break of Structure (BOS) / Change of Character (CHoCH)**, **Double/Triple Top-Bottom S/R Flip**, and **1-2-3 Reversal**. Originates from an LLM-drafted spec (reviewed, contains no harmful/irrelevant content, reflects the author's actual intent) reconciled against what already exists in `src/`.

**Ground rule carried over from the original spec:** do not rewrite the core pivot detection algorithm (`market_common.pivots.detect_pivots`). Every feature below is a layer of execution/breakout logic on top of it, reusing existing primitives wherever they already do the job.

---

## 0. What already exists (codebase scan)

| Original ask | Where it lives | Status |
|---|---|---|
| Structural pivots (swing highs/lows) | `src/market_common/pivots.py::detect_pivots()`, `market_common/models.py::Pivot`/`PivotKind` | Generic ATR-adaptive ZigZag, alternating HIGH/LOW, each with `value`/`price`, `bar_index`, `confirmed_at`, `threshold_at_pivot`. Shared by every downstream module — **do not touch**. |
| Candle/volume data | Plain OHLCV `pd.DataFrame` (open/high/low/close/volume) loaded per ticker; `market_common/indicators.py` (ATR/SMA) | End-of-day bars, no live tick data. |
| Close-only break confirmation | `src/patterns/lifecycle.py::apply_lifecycle()` / `apply_lifecycle_bidirectional()` — break test is `close < level*(1-buffer)` / `close > level*(1+buffer)` (`lifecycle.py:224`, `:301-302`) | Already exactly the spec's "sharpened, no wick pierce" requirement — close-only is the *only* mode today, no wick option exists. |
| S/R flip (resistance→support) | `src/sr_lines/events.py::classify_events()` (BREAK = body-close beyond zone, not reclaimed) + `src/sr_lines/flip_status.py::break_and_flip_status()` (sticky `LineRole.SUPPORT→FLIPPED`, `LineState.ACTIVE→BROKEN→FLIPPED`) | Functionally equivalent to "reassign resistance_levels→support_levels," modeled as one `Line` object transitioning role instead of moving between two arrays — same outcome, more state history preserved (`broken_at`, `flipped_at`, reclaim pairing). |
| Double Top/Bottom pattern | `src/patterns/detectors/double_top_bottom.py` | HIGH-LOW-HIGH / LOW-HIGH-LOW 3-pivot windows, neckline trigger, `pre_breakout_invalidated_at` callback (`double_top_bottom.py:109`) already implements "invalidate if price breaches beyond the far pivot first" — the exact mechanic Feature 3 needs. No Triple variant yet. |
| Volume surge | `src/patterns/config.py::PatternConfig.breakout_volume_mult` (default `1.4`, `config.py:74`), `src/patterns/volume.py::is_breakout_volume_confirmed()` | Computed into `PatternMatch.volume_confirmed` on every breakout, but only feeds **scoring**, not a hard gate. |
| BOS / CHoCH / market regime | — | **Nothing exists.** No `trend_direction`, `is_bullish`, or market-structure state anywhere in `src/` or `docs/`. |
| Triple Top/Bottom | — | **Nothing exists.** `PatternType` enum has no TRIPLE_TOP/TRIPLE_BOTTOM. |
| 1-2-3 Reversal | — | **Nothing exists** as a named pattern, though its two building blocks (3-pivot window, breach-before-trigger invalidation) already exist in `double_top_bottom.py`. |

---

## 1. Break of Structure (BOS) / Change of Character (CHoCH)

**Goal:** Detect when the "line in the sand" — the highest structural pivot holding a downtrend, or the lowest holding an uptrend — is broken, and flip a market-regime state variable.

**New module:** `src/market_structure/` — a new top-level package, same shape as `divergences`/`gaps`/`avwap` (pure function, DB-decoupled, plain dataclasses), *not* folded into `patterns/`, because a regime flip has no price target/stop geometry and doesn't fit `PatternMatch`.

- `models.py`: `TrendState` dataclass — `direction: Direction` (reuse existing BULLISH/BEARISH/NEUTRAL from `market_common.models`), `structural_pivot: Pivot` (the currently-active line in the sand), `changed_at: pd.Timestamp | None`, `changed_bar_index: int | None`, `event: Literal["BOS", "CHOCH"] | None` (BOS = break continues the existing higher-timeframe trend; CHoCH = break reverses it — distinguish by comparing new `direction` against the *prior* regime, not just against the immediate local trend).
- `detect.py`: `track_market_structure(bars, pivots, config) -> list[TrendState]` — walks bars, maintains the current structural pivot (last confirmed swing high while in a downtrend / swing low while in an uptrend, from `pivots`), tests `close` against it every bar using the same close-only test as `lifecycle.py` (`close > pivot.value` for a bullish break, `close < pivot.value` for a bearish break — **no wick pierce**, matching the spec verbatim). On break: emit a new `TrendState`, flip `direction`, and advance the structural pivot to the next relevant swing point.
- `config.py`: `MarketStructureConfig` dataclass following the `SRConfig`/`PatternConfig` convention — likely just `require_volume_surge: bool = False` + `volume_surge_mult: float` (see §4), plus a `PRESETS` dict (`daily`/`weekly`) mirroring the others.

**Why a new package instead of extending `sr_lines`:** `sr_lines` lines are horizontal zones with touch/fakeout/break/flip *event history*; BOS/CHoCH is a single running *regime* value derived from pivot sequence + close, closer in shape to `divergences`' streaming state than to a `Line`.

---

## 2. Double / Triple Top-Bottom (S/R Flip)

**Goal:** Detect a horizontal resistance line connecting multiple peaks breaking and flipping to support (and the mirror case for bottoms), with a close-above trigger and instant relabeling.

**Two tracks, since the spec's two asks map to two different subsystems:**

1. **The S/R-flip mechanic itself** (spec's "instantly reassign resistance_levels→support_levels" + "optional: confirm subsequent candles hold above") is **already fully implemented** by `sr_lines/events.py` (close-only BREAK classification) + `sr_lines/flip_status.py` (`break_and_flip_status`, sticky flip, reclaim pairing — which is a strictly more rigorous version of the spec's "optional confirmation" step, since it already tracks bars-to-reclaim). No new work needed here; this is a case where the existing engine exceeds the spec.
2. **The named Double/Triple Top/Bottom pattern** (spec's "detect a horizontal line connecting multiple peaks") is the `patterns/` subsystem's job. Extend `src/patterns/detectors/double_top_bottom.py` (or add sibling `triple_top_bottom.py` reusing its helpers) to also scan 5-pivot HIGH-LOW-HIGH-LOW-HIGH / LOW-HIGH-LOW-HIGH-LOW windows with 3 comparable extremes (reuse the existing symmetry_pct / prior-trend gates, generalized from pairwise to all-adjacent-pairs comparison). Add `PatternType.TRIPLE_TOP` / `TRIPLE_BOTTOM`. Breakout trigger and lifecycle walk are unchanged — call `lifecycle.apply_lifecycle` exactly as `double_top_bottom.py` does today, with the neckline as `trigger_at`.

---

## 3. 1-2-3 Reversal

**Goal:** Track Point 1 (trend high/low) → Point 2 (retracement peak/valley) → Point 3 (higher low/lower high); trigger the moment a close passes Point 2's exact price; invalidate and reset if Point 1 is breached first.

**New detector:** `src/patterns/detectors/reversal_123.py`, structurally a sibling of `double_top_bottom.py`:

- Scan 3-pivot sliding windows exactly like Double Top/Bottom's `zip(pivots, pivots[1:], pivots[2:])`, but unlike Double Top (which needs two *comparable* extremes), 1-2-3 wants a monotonic Point1→Point2→Point3 shape (Point 3 doesn't need to reach Point 1's level — that's what distinguishes a 1-2-3 from a double top/bottom).
- `key_levels = {"point1": ..., "point2": ..., "point3": ...}`.
- `trigger_at(_i) -> float`: constant, Point 2's price (same shape as `double_top_bottom.py:106`).
- `pre_breakout_invalidated_at(i) -> bool`: `bars[i].close` breaching *past Point 1* — this is a direct reuse of the exact mechanism `double_top_bottom.py:109` already uses for its own far-pivot invalidation, just pointed at Point 1 instead. The one behavioral difference from the spec: `double_top_bottom.py`'s convention is invalidate-and-stop (status → `INVALIDATED`), while the spec asks to "reset the tracker" (implying the scanner should keep looking for a fresh Point 1 afterward rather than dropping the whole window). Since `scan()` re-derives candidate windows from the full pivot list on every call anyway, a fresh 1-2-3 starting at the next pivot after the invalidated Point 1 is found automatically on the next window — no special "reset" plumbing needed beyond marking the invalidated match `INVALIDATED` like every other detector.
- Reuses `lifecycle.apply_lifecycle` unchanged for the post-trigger walk (target/stop/volume confirmation/resolution horizon all come free).
- New `PatternType.REVERSAL_123` — single type, direction carried on `PatternMatch.direction` (BULLISH/BEARISH) rather than split into separate enum members. Matches the triangle family's convention (one geometric shape, direction is incidental), not the DOUBLE_TOP/DOUBLE_BOTTOM split (which exists because "top" vs. "bottom" describes genuinely different geometry, not just direction).

---

## 4. Cross-cutting config additions

- **`require_volume_surge: bool = False`** — added to `PatternConfig` (and mirrored in the new `MarketStructureConfig`). When `True`, gates `PENDING → CONFIRMED` on `is_breakout_volume_confirmed(...)` (already exists in `patterns/volume.py`) instead of leaving it as a scoring-only signal. Straightforward, additive, no conflict with existing architecture.
- **`break_confirmation_type` ("wick" vs. "close") — discarded.** The spec asked for this on every breakout function, defaulting to `"close"`. Decided not to add it at all: there's no concrete use case for wick-based triggering today, it directly contradicts the fakeout/reclaim discipline `lifecycle.py` and `sr_lines/events.py` already went through the trouble of building (a same-bar wick beyond a level is deliberately *not* a break — that's what WICK_FAKE/BODY_FAKE distinguish), and a stub parameter that only raises `NotImplementedError` is dead API surface with no payoff. Every new breakout stays close-only by construction, same as every existing one. Revisit only if a real need for wick-based confirmation shows up later.

---

## 5. Decisions (resolved)

1. **Confirmed** — `src/market_structure/` is a new top-level package (not folded into `sr_lines`/`patterns`). Separately, `src/`'s overall layout blurs two mental tiers (foundational: `market_common`/`data_processing`/`feature_engineering`/`utils`; domain detection engines: `avwap`/`divergences`/`fibonacci`/`gaps`/`sr_lines`/`patterns`/`breadth`/`relative_strength`/`market_structure`) — tracked as a separate cleanup, branch `chore/reorder-src-layout`, out of scope for this doc.
2. **Discarded** — no `break_confirmation_type` param; see §4.
3. **Confirmed** — Triple Top/Bottom is a `PatternType` extension of `double_top_bottom.py`.
4. **Resolved** — single `PatternType.REVERSAL_123`, direction on `PatternMatch.direction` (Option A); see §3.
