"""python -m src.patterns.backtest.labeler TICKER --start YYYY-MM-DD --end YYYY-MM-DD

Human-in-the-loop labeling tool for the design doc's §7.1 ground-truth set.
Nothing in this repo can generate "is this really a head-and-shoulders"
labels automatically -- precision/recall (§7.2) is meaningless without a
person looking at real charts and saying what's actually there. This tool:
renders a chart (reusing patterns.plotting, with whatever the detector
already found as of --end drawn on top for reference) to a local HTML file,
then prompts for a label and appends it to the `pattern_labels` table.

Deliberately built starting Phase 1 rather than deferred to a later
milestone -- growing the labeled set opportunistically from the first
detector onward is cheaper than one big labeling push right before §7.2
needs it. See docs/features/chart_pattern_detection_design_notes.md.

Not detection code -- schema/store functions below are pytest-testable
(see tests/test_patterns_labeler.py); the interactive `main()` loop itself
is exercised by hand, same as every other module's cli.py `main()`.
"""

from __future__ import annotations

import argparse
import sqlite3
import uuid
from dataclasses import asdict, dataclass

import pandas as pd

from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Timeframe
from src.patterns import store as pattern_store
from src.patterns.config import get_preset
from src.patterns.plotting import render_pattern_chart
from src.patterns.scanner import detect

_LABELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_labels (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    window_start TEXT, window_end TEXT,
    pattern_type TEXT,
    is_valid INTEGER,
    notes TEXT,
    labeled_at TEXT
);
"""


def create_pattern_labels_table(conn: sqlite3.Connection) -> None:
    conn.execute(_LABELS_SCHEMA)
    conn.commit()


@dataclass
class PatternLabel:
    id: str
    ticker: str
    timeframe: str
    window_start: str
    window_end: str
    # Free text, not PatternType -- a labeler needs to be able to record
    # "I see something here but it's none of the types we detect yet" or
    # "this is borderline" just as easily as a clean enum match.
    pattern_type: str
    is_valid: bool
    notes: str
    labeled_at: str


def insert_label(conn: sqlite3.Connection, label: PatternLabel) -> None:
    d = asdict(label)
    d["is_valid"] = int(d["is_valid"])
    conn.execute(
        """INSERT INTO pattern_labels
           (id, ticker, timeframe, window_start, window_end, pattern_type, is_valid, notes, labeled_at)
           VALUES (:id, :ticker, :timeframe, :window_start, :window_end, :pattern_type, :is_valid, :notes, :labeled_at)""",
        d,
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description="Hand-label a chart window for the pattern-detection ground-truth set (design doc §7.1)."
    )
    parser.add_argument("ticker")
    parser.add_argument("--timeframe", default="daily", choices=["daily", "weekly"])
    parser.add_argument("--start", required=True, help="YYYY-MM-DD window start (for review reference only)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD window end -- also used as --as-of")
    parser.add_argument("--plot", default="pattern_label_review.html", metavar="PATH")
    args = parser.parse_args()

    timeframe = Timeframe(args.timeframe)
    raw_conn, derived_conn = derived_db.bootstrap_cli(pattern_store.create_pattern_matches_table)
    create_pattern_labels_table(derived_conn)

    config = get_preset("daily" if timeframe == Timeframe.DAILY else "weekly")
    matches, _report, skip_reason = detect(raw_conn, args.ticker, timeframe, config, as_of=args.end)
    if skip_reason is not None:
        print(f"Warning: {skip_reason}")
        matches = []

    bars, _ = data_mod.load_and_validate(raw_conn, args.ticker, timeframe, as_of=args.end)
    fig = render_pattern_chart(bars, matches, ticker=args.ticker, timeframe=timeframe)
    fig.write_html(args.plot)
    print(f"Wrote {args.plot} -- open it and look at [{args.start}, {args.end}].")

    window_matches = [
        m for m in matches
        if pd.Timestamp(args.start) <= pd.Timestamp(m.formation_end) <= pd.Timestamp(args.end)
    ]
    if window_matches:
        print("Detector already found candidates in this window (for reference, not a hint to just agree with):")
        for m in window_matches:
            print(f"  {m.pattern_type.value} ({m.status.value}, confidence={m.confidence:.2f}) {m.formation_start} -> {m.formation_end}")

    pattern_type = input("Pattern type you see (free text, e.g. 'head_and_shoulders', blank = no label): ").strip()
    if not pattern_type:
        print("No label recorded.")
        raw_conn.close()
        derived_conn.close()
        return

    is_valid = input("Is this a real, textbook instance? [y/n]: ").strip().lower().startswith("y")
    notes = input("Notes (optional): ").strip()

    label = PatternLabel(
        id=str(uuid.uuid4()), ticker=args.ticker, timeframe=timeframe.value,
        window_start=args.start, window_end=args.end, pattern_type=pattern_type,
        is_valid=is_valid, notes=notes, labeled_at=pd.Timestamp.now("UTC").isoformat(),
    )
    insert_label(derived_conn, label)
    print(f"Recorded label {label.id}.")

    raw_conn.close()
    derived_conn.close()


if __name__ == "__main__":
    main()
