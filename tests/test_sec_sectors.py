import json
import zipfile

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_sectors as ss


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _submissions(tmp_path, companies):
    """{cik: (name, sic, description)} -> a tiny submissions.zip."""
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for cik, (name, sic, desc) in companies.items():
            zf.writestr(f"CIK{cik:010d}.json", json.dumps(
                {"name": name, "sic": sic, "sicDescription": desc, "formerNames": []}))
    return path


def _stored(conn, ticker, cik, name):
    db.upsert_ticker_rename(conn, {"old_ticker": ticker, "status": "no_current_ticker", "cik": cik, "old_name": name})
    db.upsert_tiingo_listing(conn, {"ticker": ticker, "status": "stored", "tiingo_name": name})


def test_predict_uses_the_most_specific_prefix_with_enough_companies():
    train = pd.DataFrame({"cik": range(6), "sic": ["2834"] * 3 + ["2835", "2836", "2836"],
                          "sector": ["Healthcare"] * 3 + ["Healthcare", "Healthcare", "Basic Materials"]})
    mapping = ss.learn_mapping(train)

    assert ss.predict(mapping, "2834") == ("Healthcare", 1.0)
    assert ss.predict(mapping, "2836") == ("Healthcare", pytest.approx(0.833, abs=1e-3))  # 283x group
    assert ss.predict(mapping, "9999") == (None, None)


def test_run_derives_checks_the_cik_name_and_never_overwrites_yfinance(conn, tmp_path):
    active = {f"P{i}": 100 + i for i in range(3)}
    db.upsert_ticker_sector(conn, pd.DataFrame(
        {"ticker": list(active), "sector": "Healthcare", "industry": "Drug Manufacturers"}))
    _stored(conn, "PHRM", 1, "Old Pharma Inc")
    _stored(conn, "WRONG", 2, "Real Company Inc")       # Polygon CIK belongs to someone else
    _stored(conn, "HASIT", 3, "Has Sector Inc")
    db.upsert_ticker_sector(conn, pd.DataFrame({"ticker": ["HASIT"], "sector": "Technology", "industry": "x"}))
    zip_path = _submissions(tmp_path, {
        **{cik: (f"Pharma {cik}", "2834", "Pharmaceutical Preparations") for cik in active.values()},
        1: ("OLD PHARMA INC", "2834", "Pharmaceutical Preparations"),
        2: ("Unrelated Petroleum Corp", "1311", "Crude Petroleum"),
        3: ("Has Sector Inc", "2834", "Pharmaceutical Preparations"),
    })

    result = ss.run(conn, active, zip_path).set_index("ticker")

    assert result.loc["PHRM", "status"] == "derived" and result.loc["PHRM", "sector"] == "Healthcare"
    assert result.loc["WRONG", "status"] == "needs_review"
    assert "HASIT" not in result.index
    stored = db.read_ticker_sector(conn).set_index("ticker")
    assert stored.loc["PHRM", "source"] == db.SEC_SIC
    assert stored.loc["PHRM", "industry"] == "SEC SIC: Pharmaceutical Preparations"
    assert stored.loc["HASIT", "sector"] == "Technology" and stored.loc["HASIT", "source"] == db.YFINANCE
    assert "WRONG" not in stored.index


def test_reviewed_rows_do_not_keep_a_wrong_ciks_industry(conn, tmp_path):
    _stored(conn, "YHOO", 2, "Yahoo Inc")
    zip_path = _submissions(tmp_path, {2: ("FieldPoint Petroleum", "1311", "Crude Petroleum")})

    ss.run(conn, {}, zip_path)

    row = db.read_ticker_sector(conn, "YHOO").iloc[0]
    assert row["sector"] == "Communication Services" and row["industry"] == "reviewed by hand"
