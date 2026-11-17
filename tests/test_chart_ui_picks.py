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


def test_the_tab_lists_what_score_forward_writes(tmp_path, monkeypatch):
    """The command's default file, run from a repo root (here tmp_path), is one the tab lists."""
    from src.models import cli, forward, trading
    from src.models.features import cache
    sc = trading.PREREGISTERED["F2"]
    monkeypatch.setattr(forward, "check_can_score", lambda *a, **k: None)
    monkeypatch.setattr(cache, "read_feature_cache", lambda *a, **k: pd.DataFrame(columns=list(sc.model_columns)))
    monkeypatch.setattr(forward, "score_date", lambda *a, **k: pick_frame("2021-06-30"))
    monkeypatch.chdir(tmp_path)
    assert cli.score_forward("F2", "2021-06-30", Path("f"), Path("l"), None, None) == 0
    [listed] = picks_mod.list_files(tmp_path / "data" / "models" / "forward")
    assert listed.label == "F2 · 2021-06-30"
    assert isinstance(picks_mod.read_picks(listed), pd.DataFrame)
    assert app_mod.PICKS_DIR == app_mod._ROOT / "data" / "models" / "forward"   # the app's own repo root


def test_files_listed_newest_first_and_only_default_names(tmp_path):
    for name in ["HT1_2026-08-18.csv", "HT1_2026-08-19.csv", "F2_2026-08-19.csv", "F2_2021-06-30.csv", "mine.csv",
                 "HT1_2026-8-1.csv"]:
        write(tmp_path, name, pick_frame())
    files = picks_mod.list_files(tmp_path)
    assert [f.label for f in files] == ["F2 · 2026-08-19", "HT1 · 2026-08-19", "HT1 · 2026-08-18", "F2 · 2021-06-30"]
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
    blank = pick_frame()
    blank.loc[1, "horizon"] = None
    blank_file = picks_mod.PickFile("HT1", "2026-08-18", write(tmp_path, "HT1_2026-08-18.csv", blank))
    assert "horizon not a number on every row" in picks_mod.read_picks(blank_file)
    half = pick_frame().astype({"horizon": float})
    half.loc[1, "horizon"] = 21.5
    write(tmp_path, "HT1_2026-08-18.csv", half)
    assert "horizon not a whole number on every row" in picks_mod.read_picks(blank_file)
    no_ticker = pick_frame()
    no_ticker.loc[1, "ticker"] = None
    write(tmp_path, "HT1_2026-08-18.csv", no_ticker)
    assert "a row has no ticker" in picks_mod.read_picks(blank_file)


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


def test_a_click_on_a_member_or_a_pick_opens_its_chart():
    cell = {"row_id": "AAPL", "column_id": "ticker"}
    nu = app_mod.no_update
    assert app_mod.open_chart("picks", None, cell) == ("AAPL", "chart", nu, None)
    assert app_mod.open_chart("members", cell, None) == ("AAPL", "chart", None, nu)
    assert app_mod.open_chart("picks", None, None) == (nu, nu, nu, nu)   # a cleared cell


def test_selected_file_keeps_the_pick_else_the_newest(tmp_path):
    for name in ["HT1_2026-08-18.csv", "HT1_2026-08-19.csv"]:
        write(tmp_path, name, pick_frame())
    files = picks_mod.list_files(tmp_path)
    assert app_mod.selected_file(files, "HT1_2026-08-18.csv") == "HT1_2026-08-18.csv"
    assert app_mod.selected_file(files, "gone.csv") == "HT1_2026-08-19.csv"
    assert app_mod.selected_file([], None) is None


def _call(client, deps, output_part, inputs, state=(), changed=0):
    """One callback through Dash's own endpoint, as the browser calls it; `changed` is
    the index of the input that fired."""
    output = next(d["output"] for d in deps if output_part in d["output"])
    outputs = [dict(zip(("id", "property"), part.split("@")[0].rsplit(".", 1)))
               for part in output.strip(".").split("...")]
    fired = inputs[changed]
    body = {"output": output, "outputs": outputs, "inputs": inputs, "state": list(state),
            "changedPropIds": [f'{fired["id"]}.{fired["property"]}']}
    response = client.post("/_dash-update-component", json=body)
    assert response.status_code == 200, response.data
    return response.get_json()["response"]


def test_the_tab_s_callbacks(tmp_path):
    write(tmp_path, "HT1_2026-08-18.csv", pick_frame())
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"), picks_dir=tmp_path)
    app = app_mod.create_app(data=data, page="picks")
    assert app.layout["page"].value == "picks"
    client = app.server.test_client()
    deps = client.get("/_dash-dependencies").get_json()
    files = _call(client, deps, "picks-file.options", [{"id": "page", "property": "value", "value": "picks"},
                                                       {"id": "picks-reload", "property": "n_clicks", "value": 0}],
                  [{"id": "picks-file", "property": "value", "value": None}])
    assert files["picks-file"]["value"] == "HT1_2026-08-18.csv"
    view = _call(client, deps, "picks.data", [
        {"id": "picks-file", "property": "value", "value": "HT1_2026-08-18.csv"},
        {"id": "picks-cell", "property": "value", "value": "63|2|1"},
        {"id": "picks-reload", "property": "n_clicks", "value": 0}], [{"id": "page", "property": "value",
                                                                       "value": "picks"}])
    assert view["picks-cell"]["value"] == "63|2|1"
    assert [r["ticker"] for r in view["picks"]["data"]] == ["AAPL", "MSFT"]
    opened = _call(client, deps, "picks.active_cell", [
        {"id": "members", "property": "active_cell", "value": None},
        {"id": "picks", "property": "active_cell", "value": {"row_id": "MSFT", "row": 1, "column": 1,
                                                             "column_id": "ticker"}}], changed=1)
    assert opened["ticker"]["value"] == "MSFT" and opened["page"]["value"] == "chart"


def test_the_tab_says_how_to_make_picks_without_files(tmp_path):
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"),
                             picks_dir=tmp_path / "none")
    client = app_mod.create_app(data=data, page="picks").server.test_client()
    deps = client.get("/_dash-dependencies").get_json()
    view = _call(client, deps, "picks.data", [
        {"id": "picks-file", "property": "value", "value": None}, {"id": "picks-cell", "property": "value",
                                                                  "value": None},
        {"id": "picks-reload", "property": "n_clicks", "value": 0}], [{"id": "page", "property": "value",
                                                                       "value": "picks"}])
    assert view["picks-head"]["children"] == app_mod.NO_PICKS and view["picks"]["data"] == []
