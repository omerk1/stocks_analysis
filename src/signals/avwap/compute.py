"""Anchored VWAP -- a single pure function over an OHLCV frame and an
anchor date. Deliberately has no DB/config coupling (no sqlite connection,
no AvwapConfig import) so it can be unit-tested directly, independent of
anchor discovery -- anchors.py and plotting.py are the only callers, and
both just hand it a date they already picked some other way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _price(df: pd.DataFrame, price_source: str) -> pd.Series:
    if price_source == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3.0
    if price_source == "close":
        return df["close"]
    raise ValueError(f"Unknown price_source: {price_source!r}")


def anchored_vwap(df: pd.DataFrame, anchor_date, price_source: str = "hlc3") -> pd.Series:
    """Cumulative volume-weighted average price from `anchor_date`
    (inclusive) onward. Bars strictly before the anchor are NaN.

    Zero-volume bars are a no-op step in the running sum (they add 0 to
    both the price*volume and volume accumulators) rather than being
    skipped or resetting anything -- this falls out naturally from masking
    pre-anchor rows to 0 *before* taking the cumulative sum, rather than
    slicing the frame at the anchor and cumsum-ing only the tail: cum_vol
    at any bar before the anchor is therefore exactly 0 (never divides),
    and a zero-volume bar mid-series simply adds 0 to both running totals.
    """
    price = _price(df, price_source)

    on_or_after_anchor = df.index >= pd.Timestamp(anchor_date)
    pv = (price * df["volume"]).where(on_or_after_anchor, 0.0)
    vol = df["volume"].where(on_or_after_anchor, 0.0)

    cum_pv = pv.cumsum()
    cum_vol = vol.cumsum()

    # cum_vol is exactly 0 both before the anchor and during any post-anchor
    # stretch that has seen zero cumulative volume so far -- both cases want
    # an explicit NaN, not a 0/0 float that numpy would already turn into
    # NaN anyway (errstate just silences the RuntimeWarning that comes with
    # it).
    with np.errstate(divide="ignore", invalid="ignore"):
        avwap = cum_pv / cum_vol
    return avwap.where(cum_vol > 0, np.nan)


def anchored_vwap_std(df: pd.DataFrame, anchor_date, price_source: str = "hlc3") -> pd.DataFrame:
    """AVWAP plus its volume-weighted standard deviation from `anchor_date`
    (inclusive) onward, as a frame with columns `vwap` and `std` -- the
    basis for AVWAP std bands (`vwap +/- k * std`, k from
    `AvwapConfig.band_multipliers`). Same zero-lookahead and pre-anchor-NaN
    contract as `anchored_vwap`, whose values the `vwap` column matches to
    float rounding (it is recovered from the shifted mean below).

    Variance is `sum(v*p^2)/sum(v) - vwap^2` (the running, volume-weighted
    second moment minus the squared mean -- what TradingView's VWAP bands
    use). Computed on prices shifted by the first post-anchor bar's price:
    variance is shift-invariant, and without the shift the two terms are
    both ~price^2 and subtract to a tiny number, losing most of float64's
    precision on a long anchor. Tiny negative results from what rounding
    remains are clipped to 0 before the square root.
    """
    price = _price(df, price_source)
    on_or_after_anchor = df.index >= pd.Timestamp(anchor_date)

    post = price[on_or_after_anchor].dropna()
    ref = float(post.iloc[0]) if not post.empty else 0.0
    shifted = price - ref

    vol = df["volume"].where(on_or_after_anchor, 0.0)
    cum_vol = vol.cumsum()
    cum_pv = (shifted * df["volume"]).where(on_or_after_anchor, 0.0).cumsum()
    cum_pv2 = (shifted * shifted * df["volume"]).where(on_or_after_anchor, 0.0).cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        mean_shifted = cum_pv / cum_vol
        variance = cum_pv2 / cum_vol - mean_shifted * mean_shifted
    has_volume = cum_vol > 0
    vwap = (mean_shifted + ref).where(has_volume, np.nan)
    std = np.sqrt(variance.clip(lower=0.0)).where(has_volume, np.nan)
    return pd.DataFrame({"vwap": vwap, "std": std}, index=df.index)
