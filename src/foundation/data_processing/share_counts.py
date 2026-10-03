"""Cleaning rules for one company's share-count history -- shared by every
source (SEC EDGAR, yfinance) and every consumer: the SEC ingest applies
them before storing, and `market_cap.reconcile_market_cap` applies them
again at load time, so cap-weighted breadth, the Russell proxy and any
future market-cap consumer are all covered, whichever source a ticker's
counts came from.

What goes wrong in share-count data (found 2026-10-01, Done #74):

- **Scale errors.** A filing tags its count "in thousands"/"in millions"
  without the scale, so it lands ~1,000x or ~1,000,000x off -- sometimes
  for several consecutive filings (CB 2010-05 -> 2010-08 at 338 trillion
  shares; AJG 2020; GRMN 2016-2018). One such stock was 99.9% of
  cap-weighted S&P 500 breadth on ~250 dates.
- **Pre-listing placeholders.** The shell's initial 1 / 100 / 1,000 /
  25,000 shares on the filings before the real company existed (ICE 2013,
  LIN 2017, QRVO 2014, VTRS 2020).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Sorted (split-adjusted) counts are split into clusters wherever two
# neighbours are more than this far apart. Scale errors sit >=1,000x from
# the real level; real changes on a common split basis don't jump 100x.
CLUSTER_GAP = 100.0
# A filing under this fraction of its nearest trusted filing is a
# placeholder, not a share count.
PLACEHOLDER_RATIO = 1e-3
# No listed company has fewer shares than this; a cluster whose median is
# below it is never taken as the real scale.
MIN_PLAUSIBLE_SHARES = 10_000
# A cluster "agrees" with the reference when the median ratio over their
# overlap is inside this band -- wide, because it only has to tell the
# right scale from one >=100x away.
REFERENCE_BAND = (0.5, 2.0)


def scale_error(a: float, b: float) -> bool:
    """True when `a` is ~1,000x or ~1,000,000x off `b` in either direction
    (+-20%) -- the missing-scale-tag signature."""
    r = a / b
    return any(0.8 * k <= r <= 1.25 * k for k in (1e3, 1e6, 1e-3, 1e-6))


def agreement(series: pd.Series, reference: pd.Series, tolerance_days: int = 10) -> tuple[int, float | None]:
    """(number of `series` points with a `reference` point within
    `tolerance_days`, median series/reference ratio over them)."""
    if series.empty or reference.empty:
        return 0, None
    left = pd.DataFrame({"date": pd.to_datetime(series.index), "sec": series.to_numpy()}).sort_values("date")
    right = pd.DataFrame({"date": pd.to_datetime(reference.index), "ref": reference.to_numpy()}).sort_values("date")
    m = pd.merge_asof(left, right, on="date", direction="nearest",
                      tolerance=pd.Timedelta(days=tolerance_days)).dropna()
    m = m[m["ref"] > 0]
    if m.empty:
        return 0, None
    return len(m), float((m["sec"] / m["ref"]).median())


def drop_scale_runs(
    series: pd.Series,
    split_factor: pd.Series | None = None,
    reference: pd.Series | None = None,
    tolerance_days: int = 10,
) -> pd.Series:
    """Drop the filings of a date-indexed share-count `series` that can
    only be wrong -- scale errors and pre-listing placeholders (see this
    module's docstring) -- however many in a row. Returns `series` with
    those rows removed, values untouched.

    How it decides:

    1. **Common split basis.** Stored counts are as filed, not
       split-adjusted, so a company that split 40-for-1 spans 40x for real
       and a 1,000x error sits only 25x above its post-split level.
       `split_factor` (per date, the product of the ratios of every split
       after it -- `market_cap.split_factor`) puts every filing on today's
       basis first, so real history is smooth and an error stands out by
       its full factor. None means no splits known: counts are used as
       filed.
    2. **Clusters.** Sorted adjusted counts are split wherever neighbours
       are more than `CLUSTER_GAP` apart. One cluster means nothing to do.
    3. **Which cluster is real.** With a `reference` series that overlaps
       (yfinance, as-filed like `series`): the cluster whose overlapping
       filings agree with it (`REFERENCE_BAND`) -- so bad filings can't win
       by outnumbering the good ones (a recent spin-off with three shell
       filings and two real ones). If clusters overlap the reference and
       none agrees, nothing is dropped: the caller's own agreement check
       should reject the company. With no overlap at all: the largest
       cluster, ignoring any whose median is under `MIN_PLAUSIBLE_SHARES`;
       a tie means no majority scale to trust, so nothing is dropped.
    4. **Each filing outside the trusted cluster** is compared, on the
       split-adjusted basis, with the trusted filing nearest to it in
       *time*, and dropped if it is a `scale_error` away or under
       `PLACEHOLDER_RATIO` of it. Anything else outside the cluster is
       kept: a real 1-for-150 reverse split is neither.

    Limits: without a reference, a bad majority inside the plausible range
    can't be told from the truth; a genuine 1-for-1,000 reverse split with
    no split record looks exactly like a scale error; a split executed
    between a filing's cover date and its filing date mis-adjusts that one
    filing by the split ratio, which can push a scale error out of the
    +-20% band.
    """
    if len(series) < 2:
        return series
    raw = series.to_numpy(dtype="float64")
    positive = raw > 0
    if positive.sum() < 2:
        return series
    adjusted = raw.copy()
    if split_factor is not None:
        adjusted = raw * split_factor.reindex(series.index).fillna(1.0).to_numpy(dtype="float64")

    candidates = np.flatnonzero(positive)
    order = candidates[np.argsort(adjusted[candidates], kind="stable")]
    sorted_v = adjusted[order]
    clusters = np.split(order, np.flatnonzero(sorted_v[1:] / sorted_v[:-1] > CLUSTER_GAP) + 1)
    if len(clusters) == 1:
        return series
    trusted = _trusted_cluster(series, raw, clusters, reference, tolerance_days)
    if trusted is None:
        return series

    dates = series.index.to_numpy()
    trusted = np.sort(trusted)
    keep = np.ones(len(raw), dtype=bool)
    for cluster in clusters:
        for i in cluster:
            if i in trusted:
                continue
            nearest = trusted[np.argmin(np.abs(dates[trusted] - dates[i]))]
            ratio = adjusted[i] / adjusted[nearest]
            keep[i] = not (scale_error(adjusted[i], adjusted[nearest]) or ratio < PLACEHOLDER_RATIO)
    return series[keep]


def _trusted_cluster(
    series: pd.Series, raw: np.ndarray, clusters: list[np.ndarray],
    reference: pd.Series | None, tolerance_days: int,
) -> np.ndarray | None:
    """The cluster (positions into `series`) taken as the real scale, or
    None when there's nothing to trust -- see `drop_scale_runs`, step 3."""
    if reference is not None and not reference.empty:
        agreeing, overlapped = [], False
        for cluster in clusters:
            n, ratio = agreement(series.iloc[np.sort(cluster)], reference, tolerance_days)
            if n:
                overlapped = True
                if REFERENCE_BAND[0] <= ratio <= REFERENCE_BAND[1]:
                    agreeing.append(cluster)
        if overlapped:
            return max(agreeing, key=len) if agreeing else None
    plausible = [c for c in clusters if np.median(raw[c]) >= MIN_PLAUSIBLE_SHARES]
    if not plausible:
        return None
    sizes = [len(c) for c in plausible]
    if sizes.count(max(sizes)) > 1:
        return None
    return plausible[int(np.argmax(sizes))]
