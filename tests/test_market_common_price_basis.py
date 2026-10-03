"""The price-basis decision (docs/decisions/price-basis.md) enforced:
every module's declared basis matches the central table, the shared
loader can't be used without one, and stored levels refuse bars on a
different basis."""

import inspect

import pandas as pd
import pytest

from src.foundation.data_processing import db as raw_db
from src.foundation.data_processing import market_cap
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Timeframe
from src.models import dataset as models_dataset
from src.foundation.market_common.price_basis import (
    MODULE_PRICE_BASIS, PriceBasis, basis_for_source, source_for,
)
from src.signals.avwap.config import AvwapConfig
from src.signals.breadth.config import BreadthConfig
from src.signals.divergences.config import DivergenceConfig
from src.signals.fibonacci.config import FibConfig
from src.signals.gaps import store as gaps_store
from src.signals.gaps.cli import run_for_ticker as gaps_run_for_ticker
from src.signals.gaps.config import GapConfig
from src.signals.market_structure.config import MarketStructureConfig
from src.signals.moving_averages import data as ma_data
from src.signals.patterns.config import PatternConfig
from src.signals.relative_strength.config import RelativeStrengthConfig
from src.signals.sr_lines.config import SRConfig
from src.signals.volume_profile.config import VolumeProfileConfig

# How each module actually exposes its basis -- one entry per row of the
# central table, so a new module must be added here (and decided) too.
DECLARED = {
    "gaps": lambda: GapConfig().price_basis,
    "avwap": lambda: AvwapConfig().price_basis,
    "volume_profile": lambda: VolumeProfileConfig().price_basis,
    "sr_lines": lambda: SRConfig().price_basis,
    "fibonacci": lambda: FibConfig().price_basis,
    "market_structure": lambda: MarketStructureConfig().price_basis,
    "patterns": lambda: PatternConfig().price_basis,
    "divergences": lambda: DivergenceConfig().price_basis,
    "market_cap": lambda: basis_for_source(market_cap.PRICE_SOURCE),
    "moving_averages": lambda: basis_for_source(
        inspect.signature(ma_data.sp500_full_coverage_tickers).parameters["source"].default
    ),
    "relative_strength": lambda: basis_for_source(RelativeStrengthConfig().price_source),
    "breadth": lambda: basis_for_source(BreadthConfig().price_source),
    "models_labels": lambda: models_dataset.LABEL_BASIS,
    "models_universe": lambda: models_dataset.UNIVERSE_BASIS,
}


def test_every_module_in_the_table_is_checked_and_nothing_else():
    assert set(DECLARED) == set(MODULE_PRICE_BASIS)


@pytest.mark.parametrize("module", sorted(MODULE_PRICE_BASIS))
def test_each_module_declares_the_basis_in_the_central_table(module):
    assert PriceBasis(DECLARED[module]()) == MODULE_PRICE_BASIS[module]


def test_current_assignment_only_market_caps_and_the_model_universe_are_traded():
    # Moving the level modules to TRADED is planned (docs/decisions/price-basis.md);
    # until then this pins today's state so a switch is a deliberate edit.
    traded = {m for m, b in MODULE_PRICE_BASIS.items() if b == PriceBasis.TRADED}
    assert traded == {"market_cap", "models_universe"}


@pytest.fixture
def raw_conn():
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    idx = pd.bdate_range("2020-01-01", periods=200)
    traded = 100.0 + pd.Series(range(200), index=idx, dtype="float64") * 0.5
    for source, scale in ((raw_db.YFINANCE_SPLIT_ONLY, 1.0), (raw_db.YFINANCE, 0.9)):  # dividends: adjusted is lower
        c_ = traded * scale
        frame = pd.DataFrame({"open": c_, "high": c_ * 1.01, "low": c_ * 0.99, "close": c_, "volume": 1000.0, "is_partial": 0})
        raw_db.upsert_bars(c, "bars_1d", "AAA", source, frame)
    yield c
    c.close()


def test_loader_requires_a_basis(raw_conn):
    with pytest.raises(TypeError):
        data_mod.load_bars(raw_conn, "AAA", Timeframe.DAILY)
    with pytest.raises(TypeError):
        data_mod.load_and_validate(raw_conn, "AAA", Timeframe.DAILY)


@pytest.mark.parametrize("timeframe", [Timeframe.DAILY, Timeframe.WEEKLY])
def test_loader_reads_only_its_basis_and_tags_the_bars(raw_conn, timeframe):
    traded, _ = data_mod.load_and_validate(raw_conn, "AAA", timeframe, basis=PriceBasis.TRADED)
    total, _ = data_mod.load_and_validate(raw_conn, "AAA", timeframe, basis=PriceBasis.TOTAL_RETURN)
    assert traded.attrs["price_basis"] == "traded" and total.attrs["price_basis"] == "total_return"
    ratio = (total["close"] / traded["close"]).round(6).unique()
    assert list(ratio) == [0.9]   # two genuinely different series, never mixed


def test_stored_gaps_refuse_bars_on_another_basis(raw_conn):
    derived = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived)
    gaps_store.create_gaps_table(derived)
    # a jumpy series so there are gaps to store
    idx = pd.bdate_range("2019-01-01", periods=300)
    close = pd.Series([100.0 * (1.03 if i % 7 == 0 else 1.0) ** (i // 7) for i in range(300)], index=idx)
    frame = pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998, "close": close, "volume": 1000.0, "is_partial": 0})
    raw_db.upsert_bars(raw_conn, "bars_1d", "JMP", raw_db.YFINANCE_SPLIT_ONLY, frame)
    raw_db.upsert_bars(raw_conn, "bars_1d", "JMP", raw_db.YFINANCE, frame)  # same prices, other basis
    gaps_run_for_ticker(raw_conn, derived, "JMP", Timeframe.DAILY, GapConfig(), as_of=None)
    own = PriceBasis(GapConfig().price_basis)
    other = next(b for b in PriceBasis if b != own)
    assert gaps_store.stored_price_bases(derived, "JMP", "daily") == {own.value}

    same, _ = data_mod.load_and_validate(raw_conn, "JMP", Timeframe.DAILY, basis=own)
    assert gaps_store.read_gaps(derived, "JMP", "daily", bars=same)
    diff, _ = data_mod.load_and_validate(raw_conn, "JMP", Timeframe.DAILY, basis=other)
    with pytest.raises(gaps_store.StaleGapsError, match="price basis"):
        gaps_store.read_gaps(derived, "JMP", "daily", bars=diff)   # identical prices, still refused


def test_source_mapping_round_trips():
    for basis in PriceBasis:
        assert basis_for_source(source_for(basis)) == basis
    with pytest.raises(ValueError):
        basis_for_source("polygon")
