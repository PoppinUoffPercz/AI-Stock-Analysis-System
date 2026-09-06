from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig, SessionConfig
from stock_analysis.market_analytics.models import (
    AggressorSide,
    BarEvent,
    InstrumentSpec,
    Provenance,
    TradeEvent,
    VolumeInputMode,
)
from stock_analysis.market_analytics.profiles import (
    RollingVolumeProfileEngine,
    TPOEngine,
    VolumeProfileEngine,
)
from tests.market_analytics.support import T0


def add_tpo_rows(engine, rows):
    for row, brackets in rows.items():
        for bracket_index, _ in enumerate(sorted(brackets)):
            engine.consume_bar(
                BarEvent(
                    "AAA",
                    T0 + timedelta(minutes=30 * bracket_index),
                    "fixture",
                    "bars",
                    float(row),
                    float(row),
                    float(row),
                    float(row),
                    1.0,
                )
            )


def test_tpo_poc_tie_breaks_to_closest_midpoint_then_lower_row():
    profile = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    add_tpo_rows(profile, {100: {"a"}, 101: {"a", "b"}, 102: {"a", "b"}, 103: {"a"}})

    result = profile.finalize_session("2026-01-02", T0)

    assert result.metrics["tpo_poc"].value == 101.0


def test_single_print_is_unconfirmed_while_developing_and_confirmed_at_close():
    profile = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    add_tpo_rows(profile, {100: {"a", "b"}, 101: {"a"}, 102: {"a", "b"}})
    developing = profile.snapshot(T0)
    assert developing.single_prints[0].confirmed is False
    closed = profile.finalize_session("2026-01-02", T0 + timedelta(hours=6))
    assert closed.single_prints[0].confirmed is True


def test_rolling_volume_profile_contains_only_completed_sessions():
    engine = RollingVolumeProfileEngine(
        InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig()
    )
    engine.finalize_session("s1", {100: 10.0}, exact=True, as_of=T0)
    engine.finalize_session(
        "s2", {101: 20.0}, exact=True, as_of=T0 + timedelta(hours=6)
    )

    before_close = engine.snapshot(as_of=T0)
    assert before_close[60].total_volume == 30.0
    assert before_close[60].vpoc == 101.0

    engine.finalize_session("s3", {99: 100.0}, exact=True, as_of=T0 + timedelta(days=1))
    after_close = engine.snapshot(as_of=T0 + timedelta(days=1))
    assert after_close[60].total_volume == 130.0


def test_rolling_finalization_uses_supplied_session_timestamp():
    engine = RollingVolumeProfileEngine(
        InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig()
    )
    expected = T0 + timedelta(hours=6)

    finalized = engine.finalize_session(
        "2026-01-02", {100: 10.0}, exact=True, as_of=expected
    )

    assert finalized[14].metadata.as_of == expected


def test_bar_profile_is_approximate_and_value_area_uses_highest_volume_row():
    config = replace(AnalyticsConfig(), volume_input_mode=VolumeInputMode.BARS)
    result = VolumeProfileEngine(
        InstrumentSpec("AAA", "XNAS", 1.0, 0), config
    ).consume_bar(BarEvent("AAA", T0, "fixture", "bars", 99, 103, 98, 102, 10))
    assert result.exact_or_approximate == "approximate"
    assert result.metadata.observed_or_modeled is Provenance.APPROXIMATE


def test_exact_volume_profile_aggregates_normalized_trade_ticks():
    engine = VolumeProfileEngine(
        InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig()
    )
    engine.consume_trade(
        TradeEvent("AAA", T0, "fixture", "trades", 100.0, 2.0, AggressorSide.BUY, "1")
    )
    result = engine.consume_trade(
        TradeEvent("AAA", T0, "fixture", "trades", 101.0, 3.0, AggressorSide.SELL, "2")
    )

    assert result.total_volume == 5.0
    assert result.vpoc == 101.0
    assert result.exact_or_approximate == "exact"


def test_rolling_volume_profile_subtracts_evicted_sessions():
    config = replace(
        AnalyticsConfig(),
        profile=replace(AnalyticsConfig().profile, rolling_windows=(2,)),
    )
    engine = RollingVolumeProfileEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), config)
    engine.finalize_session("s1", {100: 10.0}, exact=True, as_of=T0)
    engine.finalize_session("s2", {101: 20.0}, exact=True, as_of=T0 + timedelta(days=1))
    engine.finalize_session("s3", {102: 30.0}, exact=True, as_of=T0 + timedelta(days=2))

    result = engine.snapshot(T0)[2]

    assert result.window_sessions == 2
    assert result.total_volume == 50.0
    assert result.profile_low == 101.0


def test_profiles_accept_only_configured_regular_session_hours():
    instrument = InstrumentSpec("AAA", "XNAS", 1.0, 0)
    config = AnalyticsConfig()
    tpo = TPOEngine(instrument, config)
    volume = VolumeProfileEngine(instrument, config)
    timestamps = (
        datetime(2026, 1, 2, 8, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(
            T0.tzinfo
        ),
        datetime(2026, 1, 2, 10, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(
            T0.tzinfo
        ),
        datetime(2026, 1, 2, 17, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(
            T0.tzinfo
        ),
    )
    for timestamp in timestamps:
        tpo.consume_bar(
            BarEvent("AAA", timestamp, "fixture", "bars", 100, 100, 100, 100, 10)
        )
        volume.consume_trade(
            TradeEvent(
                "AAA", timestamp, "fixture", "trades", 100, 10, None, str(timestamp)
            )
        )

    tpo_result = tpo.snapshot(timestamps[1])
    volume_result = volume.snapshot(timestamps[1])

    assert tpo_result.metrics["tpo_total_count"].value == 1
    assert volume_result.total_volume == 10


def test_profiles_use_local_session_date_when_extended_hours_are_enabled():
    session = SessionConfig(include_extended_hours=True)
    config = replace(AnalyticsConfig(), session=session)
    timestamp = datetime(
        2026, 1, 2, 23, 0, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(T0.tzinfo)

    result = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), config).consume_bar(
        BarEvent("AAA", timestamp, "fixture", "bars", 100, 100, 100, 100, 1)
    )

    assert timestamp.date().isoformat() == "2026-01-03"
    assert result.session_id == "2026-01-02"


def test_volume_value_area_expands_across_gapped_observed_rows():
    engine = VolumeProfileEngine(
        InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig()
    )
    engine.consume_trade(
        TradeEvent("AAA", T0, "fixture", "trades", 100.0, 100.0, None, "100")
    )
    result = engine.consume_trade(
        TradeEvent("AAA", T0, "fixture", "trades", 110.0, 90.0, None, "110")
    )

    assert result.total_volume == 190.0
    assert result.val == 100.0
    assert result.vah == 110.0


def test_rolling_retention_is_bounded_and_uses_only_configured_window_keys():
    config = replace(
        AnalyticsConfig(),
        profile=replace(AnalyticsConfig().profile, rolling_windows=(2, 3)),
    )
    engine = RollingVolumeProfileEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), config)
    for index in range(10):
        engine.finalize_session(
            f"session-{index}",
            {100 + index: 1.0},
            exact=True,
            as_of=T0 + timedelta(days=index),
        )

    snapshots = engine.snapshot(T0 + timedelta(days=10))

    assert set(snapshots) == {2, 3}
    assert len(engine._buffers[2]) == 2
    assert len(engine._buffers[3]) == 3
    assert not hasattr(engine, "_sessions")
    with pytest.raises(KeyError):
        snapshots[0]


def test_confirmed_single_print_lifecycle_survives_retest_and_fill():
    profile = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    add_tpo_rows(profile, {100: {"a", "b"}, 101: {"a"}, 102: {"a", "b"}})
    first = profile.finalize_session("2026-01-02", T0 + timedelta(hours=6))
    zone = first.single_prints[0]

    session_two = T0 + timedelta(days=1)
    retest = profile.consume_bar(
        BarEvent("AAA", session_two, "fixture", "bars", 101, 101.2, 100.9, 101, 1)
    )
    retested_zone = next(item for item in retest.single_prints if item.confirmed)

    session_three = T0 + timedelta(days=2)
    filled = profile.consume_bar(
        BarEvent("AAA", session_three, "fixture", "bars", 101, 102, 100, 101, 1)
    )
    filled_zone = next(item for item in filled.single_prints if item.confirmed)

    assert zone.confirmed is True
    assert zone.age_sessions == 0
    assert zone.first_retest_time is None
    assert retested_zone.age_sessions == 1
    assert retested_zone.first_retest_time == session_two
    assert retested_zone.filled is False
    assert filled_zone.age_sessions == 2
    assert filled_zone.filled is True
