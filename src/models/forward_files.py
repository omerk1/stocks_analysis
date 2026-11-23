"""Where `score-forward` writes a date's picks, and the file's name: shared by the
command (`cli.score_forward`) and the chart UI's Picks tab (`src/ui/chart/picks.py`),
which lists them. No model libraries are imported here, so the app can use it.

`FORWARD_DIR` is relative, like the command's other defaults (`--features`,
`--labels`): run the command from the repo root, where the app looks."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

FORWARD_DIR = Path("data/models/forward")
FILE_NAME = re.compile(r"^(?P<experiment>.+)_(?P<date>\d{4}-\d{2}-\d{2})\.csv$")


def pick_file_name(experiment_id: str, as_of) -> str:
    """`<id>_<YYYY-MM-DD>.csv`, matched by `FILE_NAME`."""
    return f"{experiment_id}_{pd.Timestamp(as_of).date()}.csv"
