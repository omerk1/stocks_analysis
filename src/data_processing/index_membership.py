import argparse
import datetime
import sqlite3

import pandas as pd
import requests
from nasdaq_100_ticker_history import changes as _n100_changes
from nasdaq_100_ticker_history import tickers_as_of as _n100_tickers_as_of

from src.data_processing import db
from src.utils.config_loader import load_config

SP500 = "sp500"
NASDAQ100 = "nasdaq100"

# fja05680/sp500 (MIT) -- a community-maintained, point-in-time S&P 500
# membership dataset since 1996, already shaped exactly as ticker/start_date/
# end_date intervals (see docs/limitations.md for why this was chosen over
# Polygon's paid ETF Global add-on).
_SP500_CSV_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
)

# nasdaq-100-ticker-history (MIT, git-only -- not published to PyPI) has
# accurate coverage from this date onward (per its README); it has no
# baseline snapshot before this, so it's used as an extra anchor point below,
# not just derived from the package's own change-event dates.
_NASDAQ100_COVERAGE_START = datetime.date(2015, 1, 1)

# Both sources are unpaid, single-maintainer GitHub projects with no SLA (see
# docs/limitations.md) -- if one goes quiet, our refresh just keeps re-storing
# the same (increasingly stale) data with no error, since "no new changes"
# and "source abandoned" look identical from here. This turns that into a
# visible signal instead: how long since each repo was last pushed to.
_SOURCE_REPOS = {
    SP500: "fja05680/sp500",
    NASDAQ100: "jmccarrell/n100tickers",
}
_STALENESS_THRESHOLD_DAYS = 90


def fetch_sp500_membership() -> pd.DataFrame:
    """Download the S&P 500 point-in-time membership dataset. Already shaped
    as ticker/start_date/end_date intervals -- no reconstruction needed."""
    df = pd.read_csv(_SP500_CSV_URL)
    return df[["ticker", "start_date", "end_date"]]


def fetch_nasdaq100_membership() -> pd.DataFrame:
    """Reconstruct Nasdaq-100 membership intervals from
    nasdaq_100_ticker_history's `tickers_as_of` (the ground truth) rather than
    interpreting its `changes` module's additions/removals directly.

    This matters: `changes_before()` describes events walking *backward* from
    BASELINE_DATE, and its additions/removals are relative to that backward
    walk -- confirmed by testing directly (e.g. the earliest changes_before
    entry lists EQIX as an "addition" and WBA as a "removal" effective
    2015-03-23, but `tickers_as_of(2015, 1, 1)` -- a date *before* that event --
    already has EQIX in and WBA out, the opposite of naively reading
    additions/removals as forward-time deltas). Sampling `tickers_as_of` at
    every distinct change date sidesteps that ambiguity entirely.
    """
    change_dates = {_n100_changes.BASELINE_DATE, _NASDAQ100_COVERAGE_START}
    change_dates.update(c.effective_date for c in _n100_changes.changes_since())
    change_dates.update(c.effective_date for c in _n100_changes.changes_before())
    change_dates = sorted(change_dates)

    snapshots = [
        (d, frozenset(_n100_tickers_as_of(d.year, d.month, d.day))) for d in change_dates
    ]

    all_tickers = set().union(*(members for _, members in snapshots))

    rows = []
    for ticker in all_tickers:
        presence = [ticker in members for _, members in snapshots]
        i = 0
        while i < len(presence):
            if not presence[i]:
                i += 1
                continue
            start = snapshots[i][0]
            j = i
            while j + 1 < len(presence) and presence[j + 1]:
                j += 1
            end = snapshots[j + 1][0] - datetime.timedelta(days=1) if j + 1 < len(presence) else None
            rows.append((ticker, start, end))
            i = j + 1

    return pd.DataFrame(rows, columns=["ticker", "start_date", "end_date"])


def refresh_index_membership(conn: sqlite3.Connection) -> None:
    db.replace_index_membership(conn, SP500, fetch_sp500_membership())
    db.replace_index_membership(conn, NASDAQ100, fetch_nasdaq100_membership())


def check_source_freshness(threshold_days: int = _STALENESS_THRESHOLD_DAYS) -> dict[str, str | None]:
    """For each index's source repo, check how long it's been since the last
    push. Returns {index_name: warning_message_or_None}.

    This can't distinguish "the source genuinely had no changes" from "the
    source stopped being maintained" -- it's a coarse, one-sided signal (only
    ever raises a flag, never confirms freshness means correctness), but it's
    strictly better than the current silence.
    """
    warnings: dict[str, str | None] = {}
    for index_name, repo in _SOURCE_REPOS.items():
        try:
            response = requests.get(f"https://api.github.com/repos/{repo}", timeout=10)
            response.raise_for_status()
            pushed_at = pd.Timestamp(response.json()["pushed_at"])
        except Exception as e:
            warnings[index_name] = f"Could not check {repo}'s freshness: {e}"
            continue

        age_days = (pd.Timestamp.now("UTC") - pushed_at).days
        if age_days > threshold_days:
            warnings[index_name] = (
                f"{repo} hasn't been pushed to in {age_days} days "
                f"(last: {pushed_at.date()}) -- source may be stale or abandoned."
            )
        else:
            warnings[index_name] = None
    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Refresh point-in-time S&P 500 / Nasdaq-100 index membership"
    )
    parser.parse_args()

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    refresh_index_membership(conn)

    for index_name in (SP500, NASDAQ100):
        current = db.read_index_membership(conn, index_name, as_of=datetime.date.today().isoformat())
        print(f"{index_name}: {len(current)} current members")

    for index_name, warning in check_source_freshness().items():
        if warning:
            print(f"WARNING [{index_name}]: {warning}")

    conn.close()


if __name__ == "__main__":
    main()
