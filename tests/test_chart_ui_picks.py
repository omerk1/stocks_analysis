from pathlib import Path

import pandas as pd

from src.ui.chart import app as app_mod
from src.ui.chart import picks as picks_mod


def pick_frame(date="2026-08-18"):
    rows = []
    for (h, u, d) in [(63, 2.0, 1.0), (21, 1.5, 1.0)]:
        for rank, (ticker, score) in enumerate([("AAPL", 0.31), ("MSFT", -0.02)], start=1):
            rows.append({"date": date, "horizon": h, "upper_atr": u, "lower_atr": d, "rank": rank, "ticker": ticker,
                         "score": score, "p_up": 0.5, "p_down": 0.3, "p_neither": 0.2, "close_t": 100.0,
                         "atr": 2.0, "target_px": 100 + u * 2, "stop_px": 100 - d * 2})
    return pd.DataFrame(rows)


def write(folder: Path, name: str, frame: pd.DataFrame) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    frame.to_csv(path, index=False)
    return path


def test_columns_are_what_score_forward_writes():
    from src.models.forward import PICK_COLUMNS
    assert set(picks_mod.COLUMNS) <= set(PICK_COLUMNS)


def test_files_listed_newest_first_and_only_default_names(tmp_path):
    for name in ["HT1_2026-08-18.csv", "HT1_2026-08-19.csv", "F2_2021-06-30.csv", "mine.csv", "HT1_2026-8-1.csv"]:
        write(tmp_path, name, pick_frame())
    files = picks_mod.list_files(tmp_path)
    assert [f.label for f in files] == ["HT1 · 2026-08-19", "HT1 · 2026-08-18", "F2 · 2021-06-30"]
    assert picks_mod.list_files(tmp_path / "missing") == []
    assert picks_mod.find_file(tmp_path, "HT1_2026-08-18.csv").date == "2026-08-18"
    assert picks_mod.find_file(tmp_path, "mine.csv") is None          # only listed files are read
    assert picks_mod.find_file(tmp_path, "../HT1_2026-08-18.csv") is None


def test_bad_files_give_a_message(tmp_path):
    bad = picks_mod.PickFile("HT1", "2026-08-18", write(tmp_path, "HT1_2026-08-18.csv",
                                                        pick_frame().drop(columns="score")))
    assert "lacks score" in picks_mod.read_picks(bad)
    other_date = picks_mod.PickFile("HT1", "2026-08-19", write(tmp_path, "HT1_2026-08-19.csv", pick_frame()))
    assert "dated 2026-08-18, not 2026-08-19" in picks_mod.read_picks(other_date)
    empty = picks_mod.PickFile("HT1", "2026-08-20", write(tmp_path, "HT1_2026-08-20.csv", pick_frame().iloc[:0]))
    assert "no picks" in picks_mod.read_picks(empty)
    (tmp_path / "HT1_2026-08-21.csv").write_bytes(b"")
    assert "Can't read" in picks_mod.read_picks(picks_mod.PickFile("HT1", "2026-08-21", tmp_path / "HT1_2026-08-21.csv"))


def test_cells_sorted_and_rows_by_rank():
    frame = pick_frame().sample(frac=1, random_state=0)
    cells = picks_mod.cells(frame)
    assert [c.key for c in cells] == ["21|1.5|1", "63|2|1"]
    assert cells[0].label == "21 days · target +1.5 ATR · stop −1 ATR"
    assert list(picks_mod.cell_rows(frame, cells[1])["ticker"]) == ["AAPL", "MSFT"]
    assert picks_mod.find_cell(frame, "63|2|1") == cells[1]
    assert picks_mod.find_cell(frame, "nope") == cells[0]


def test_picks_view_header_rows_and_click(tmp_path):
    write(tmp_path, "HT1_2026-08-18.csv", pick_frame())
    options, key, header, rows = app_mod.picks_view(tmp_path, "HT1_2026-08-18.csv", "63|2|1")
    assert [o["value"] for o in options] == ["21|1.5|1", "63|2|1"] and key == "63|2|1"
    assert header.startswith("HT1, decision close 2026-08-18: top 2 per cell")
    assert [r["id"] for r in rows] == ["AAPL", "MSFT"] and rows[0]["target_px"] == 104.0
    assert set(rows[0]) == {"id", *(c["id"] for c in app_mod.pick_columns())}
    assert app_mod.picks_view(tmp_path, "HT1_2026-08-18.csv", None)[1] == "21|1.5|1"   # first cell by default
    assert app_mod.picks_view(tmp_path, None, None) == ([], None, app_mod.NO_PICKS, [])
    assert app_mod.clicked_row({"row_id": "AAPL", "column_id": "ticker"}) == "AAPL"


def test_selected_file_keeps_the_pick_else_the_newest(tmp_path):
    for name in ["HT1_2026-08-18.csv", "HT1_2026-08-19.csv"]:
        write(tmp_path, name, pick_frame())
    files = picks_mod.list_files(tmp_path)
    assert app_mod.selected_file(files, "HT1_2026-08-18.csv") == "HT1_2026-08-18.csv"
    assert app_mod.selected_file(files, "gone.csv") == "HT1_2026-08-19.csv"
    assert app_mod.selected_file([], None) is None


def test_app_opens_on_the_picks_tab_with_no_files(tmp_path):
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"),
                             picks_dir=tmp_path / "none")
    app = app_mod.create_app(data=data, page="picks")
    assert app.layout["page"].value == "picks"
    assert picks_mod.list_files(data.picks_dir) == []
