from src.sr_lines.config import get_preset


def test_weekly_preset_sets_bar_interval_and_rescales_bar_count_knobs():
    config = get_preset("long_term_weekly")

    assert config.bar_interval == "1w"
    assert config.fakeout_reclaim_bars == 1
    assert config.touch_reaction_window_bars == 2
    assert config.diagonal_min_pivot_separation_bars == 4
    # Scales the *opposite* direction from the other three -- slope is a
    # "movement per bar" rate, which grows (not shrinks) under weekly, since
    # each bar now spans ~5x the calendar time of a daily bar.
    assert config.max_diagonal_slope_atr_per_bar == 1.75


def test_weekly_preset_matches_its_daily_counterpart_on_everything_else():
    # atr_period is an idiomatic lookback regardless of timeframe, and
    # window_years/regime_gap_years/recency_half_life_years already operate
    # in real calendar time (see scoring.py), not bar counts -- none of
    # these (or anything else the preset itself sets) should differ between
    # the daily and weekly variant of the same span.
    daily = get_preset("long_term")
    weekly = get_preset("long_term_weekly")

    daily_fields = daily.to_dict()
    weekly_fields = weekly.to_dict()
    rescaled = {
        "bar_interval", "fakeout_reclaim_bars", "max_diagonal_slope_atr_per_bar",
        "touch_reaction_window_bars", "diagonal_min_pivot_separation_bars",
    }
    for field_name in daily_fields:
        if field_name in rescaled:
            continue
        assert weekly_fields[field_name] == daily_fields[field_name], field_name


def test_get_preset_returns_independent_copies():
    a = get_preset("medium_term_weekly")
    b = get_preset("medium_term_weekly")
    a.top_n = 999

    assert b.top_n != 999
