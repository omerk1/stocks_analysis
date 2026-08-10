"""Anchored VWAP -- a single pure function over an OHLCV frame and an
anchor date. Deliberately has no DB/config coupling (no sqlite connection,
no AvwapConfig import) so it can be unit-tested directly, independent of
anchor discovery -- anchors.py and plotting.py are the only callers, and
both just hand it a date they already picked some other way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


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
    if price_source == "hlc3":
        price = (df["high"] + df["low"] + df["close"]) / 3.0
    elif price_source == "close":
        price = df["close"]
    else:
        raise ValueError(f"Unknown price_source: {price_source!r}")

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
