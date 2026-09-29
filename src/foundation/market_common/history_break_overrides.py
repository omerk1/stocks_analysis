"""Hand-reviewed exceptions to `history_breaks.anchor_start_date`'s rule.

ticker -> None  : never reset; anchors use the full history.
ticker -> "YYYY-MM-DD" : anchors start at this date (once it has been reached).

Keep each entry's reason next to it -- the point of this file is that a
human looked at the chart and disagreed with the rule, and why.
"""

HISTORY_RESET_OVERRIDES: dict[str, str | None] = {
    # Precision Drilling: 1-for-20 in Nov 2020 while ~$0.50, to keep its NYSE
    # listing through the COVID oil crash -- an established, liquid company
    # whose pre-2020 history is real, not a zombie reset (review 2026-09-28).
    "PDS": None,
}
