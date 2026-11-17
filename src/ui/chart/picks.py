"""The Picks tab's data: the combined model's top picks on one date, read from the
files `python -m src.models.cli score-forward <id> --as-of DATE` writes
(`data/models/forward/<id>_<date>.csv`, `src/models/forward_files.py`). The UI only reads
those files: it never fits or scores a model, and never reads a cache. Whatever
holdout gate applies is the command's (`forward.check_can_score`), so a file dated
past 2021 exists only once that gate let it through.

One file is one scorecard on one decision date: for each horizon and barrier cell,
the top k rows by EV in ATR units, with the calibrated probabilities, the decision
close and ATR, and the target / stop put at that close (the trade enters at the
next open, so they're a guide until it's known).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.models.forward_files import FILE_NAME

# The columns the page reads, a subset of `forward.PICK_COLUMNS` (a test checks it;
# importing `src.models.forward` here would pull the model libraries into the app).
COLUMNS = ["date", "horizon", "upper_atr", "lower_atr", "rank", "ticker", "score", "p_up", "p_down", "p_neither",
           "close_t", "atr", "target_px", "stop_px"]
_KEYS = ["horizon", "upper_atr", "lower_atr", "rank"]  # must be numbers on every row: they group and order the table
_WHOLE = ["horizon", "rank"]  # and these whole numbers (a horizon is cast to int for its cell)


@dataclass(frozen=True)
class PickFile:
    experiment: str
    date: str  # the decision date, YYYY-MM-DD
    path: Path

    @property
    def label(self) -> str:
        return f"{self.experiment} · {self.date}"


@dataclass(frozen=True, order=True)
class Cell:
    horizon: int
    upper_atr: float
    lower_atr: float

    @property
    def key(self) -> str:
        return f"{self.horizon}|{self.upper_atr:g}|{self.lower_atr:g}"

    @property
    def label(self) -> str:
        return f"{self.horizon} days · target +{self.upper_atr:g} ATR · stop −{self.lower_atr:g} ATR"


def list_files(folder: Path) -> list[PickFile]:
    """The pick files in `folder`, newest decision date first, then by scorecard A–Z.
    Only the command's default names (`forward_files.FILE_NAME`) are listed; a file
    written elsewhere with `--out` isn't."""
    if not folder.is_dir():
        return []
    files = []
    for path in folder.glob("*.csv"):
        m = FILE_NAME.match(path.name)
        if m:
            files.append(PickFile(m["experiment"], m["date"], path))
    return sorted(files, key=lambda f: (-int(f.date.replace("-", "")), f.experiment))


def find_file(folder: Path, name: str | None) -> PickFile | None:
    """The listed file called `name` (a dropdown value), else None: only a listed file
    is ever read."""
    return next((f for f in list_files(folder) if f.path.name == name), None)


def read_picks(file: PickFile) -> pd.DataFrame | str:
    """A pick file's rows, or a message saying why it can't be shown; never raises.
    Its rows must all be on the date its name says."""
    name = file.path.name
    try:
        frame = pd.read_csv(file.path)
    except Exception as e:  # noqa: BLE001 -- a bad file mustn't take the app down
        return f"Can't read {name}: {type(e).__name__}: {e}"
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        return f"{name} lacks {', '.join(missing)}: not a score-forward file"
    if frame.empty:
        return f"{name} has no picks"
    numbers = frame[_KEYS].apply(pd.to_numeric, errors="coerce")
    blank = [c for c in _KEYS if numbers[c].isna().any()]
    if blank:
        return f"{name}: {', '.join(blank)} not a number on every row"
    fractional = [c for c in _WHOLE if (numbers[c] % 1 != 0).any()]
    if fractional:
        return f"{name}: {', '.join(fractional)} not a whole number on every row"
    if frame["ticker"].isna().any() or (frame["ticker"].astype(str).str.strip() == "").any():
        return f"{name}: a row has no ticker"
    frame[_KEYS] = numbers
    dates = set(pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d"))
    if dates != {file.date}:
        return f"{name}: its rows are dated {', '.join(sorted(map(str, dates)))}, not {file.date}"
    return frame


def cells(frame: pd.DataFrame) -> list[Cell]:
    """The file's barrier cells, by horizon, then target, then stop."""
    keys = frame[["horizon", "upper_atr", "lower_atr"]].drop_duplicates()
    return sorted(Cell(int(h), float(u), float(d)) for h, u, d in keys.itertuples(index=False))


def cell_rows(frame: pd.DataFrame, cell: Cell) -> pd.DataFrame:
    """One cell's picks, by rank."""
    match = ((frame["horizon"] == cell.horizon) & (frame["upper_atr"] == cell.upper_atr)
             & (frame["lower_atr"] == cell.lower_atr))
    return frame[match].sort_values("rank")


def find_cell(frame: pd.DataFrame, key: str | None) -> Cell | None:
    """The cell with `key`, else the first; None for no cells."""
    found = cells(frame)
    return next((c for c in found if c.key == key), found[0] if found else None)
