import datetime as dt

from health_coach.analytics.journal import (
    JournalEntryData,
    compute_journal_insights,
)


def test_compute_journal_insights_sufficient_data() -> None:
    # 6 days with alcohol, 6 days without alcohol (logged sauna instead)
    # Total 12 logged days. Next-day recoveries are provided.
    entries: list[JournalEntryData] = []
    recovery_by_date: dict[dt.date, int] = {}

    start_date = dt.date(2026, 9, 1)

    # Days 0..5 (6 days): alcohol
    for i in range(6):
        d = start_date + dt.timedelta(days=i * 2)
        entries.append(JournalEntryData(local_date=d, behavior="alcohol", amount=2.0))
        # Next-day recovery is 55
        recovery_by_date[d + dt.timedelta(days=1)] = 55

    # Days 6..11 (6 days): sauna (no alcohol)
    for i in range(6):
        d = start_date + dt.timedelta(days=i * 2 + 1)
        entries.append(JournalEntryData(local_date=d, behavior="sauna"))
        # Next-day recovery is 75
        recovery_by_date[d + dt.timedelta(days=1)] = 75

    result = compute_journal_insights(entries, recovery_by_date)
    assert len(result.insights) == 2  # alcohol and sauna both have 6 with and 6 without
    assert len(result.insufficient) == 0

    alcohol_insight = next(i for i in result.insights if i.behavior == "alcohol")
    assert alcohol_insight.with_count == 6
    assert alcohol_insight.without_count == 6
    assert alcohol_insight.with_mean_recovery == 55.0
    assert alcohol_insight.without_mean_recovery == 75.0
    assert alcohol_insight.difference_pp == -20.0

    sauna_insight = next(i for i in result.insights if i.behavior == "sauna")
    assert sauna_insight.with_count == 6
    assert sauna_insight.without_count == 6
    assert sauna_insight.with_mean_recovery == 75.0
    assert sauna_insight.without_mean_recovery == 55.0
    assert sauna_insight.difference_pp == 20.0


def test_compute_journal_insights_insufficient_counts() -> None:
    # 3 days with magnesium, 7 days with reading (no magnesium)
    start_date = dt.date(2026, 9, 1)
    entries: list[dict[str, object]] = []
    recovery_by_date: dict[dt.date, int] = {}

    for i in range(3):
        d = start_date + dt.timedelta(days=i)
        entries.append({"local_date": d, "behavior": "magnesium"})
        recovery_by_date[d + dt.timedelta(days=1)] = 70

    for i in range(3, 10):
        d = start_date + dt.timedelta(days=i)
        entries.append({"local_date": d, "behavior": "reading"})
        recovery_by_date[d + dt.timedelta(days=1)] = 68

    result = compute_journal_insights(entries, recovery_by_date)
    # magnesium has with_count=3 (< 5), reading has without_count=3 (< 5)
    assert len(result.insights) == 0
    assert len(result.insufficient) == 2

    mag = next(i for i in result.insufficient if i.behavior == "magnesium")
    assert mag.with_count == 3
    assert mag.without_count == 7

    read = next(i for i in result.insufficient if i.behavior == "reading")
    assert read.with_count == 7
    assert read.without_count == 3


def test_unlogged_days_do_not_count_as_without() -> None:
    start_date = dt.date(2026, 9, 1)
    entries: list[JournalEntryData] = []
    recovery_by_date: dict[dt.date, int] = {}

    # Recovery is present every day for 30 days
    for i in range(30):
        recovery_by_date[start_date + dt.timedelta(days=i)] = 70

    # User only logged journal on 6 days total: 5 alcohol, 1 sauna
    # Unlogged 24 days must NOT count as "without alcohol"
    for i in range(5):
        d = start_date + dt.timedelta(days=i)
        entries.append(JournalEntryData(local_date=d, behavior="alcohol"))

    d_sauna = start_date + dt.timedelta(days=10)
    entries.append(JournalEntryData(local_date=d_sauna, behavior="sauna"))

    result = compute_journal_insights(entries, recovery_by_date)
    # Alcohol has 5 with, but only 1 without! So it is insufficient (< 5 without).
    assert len(result.insights) == 0
    alc = next(i for i in result.insufficient if i.behavior == "alcohol")
    assert alc.with_count == 5
    assert alc.without_count == 1

    sauna = next(i for i in result.insufficient if i.behavior == "sauna")
    assert sauna.with_count == 1
    assert sauna.without_count == 5


def test_missing_recovery_is_excluded() -> None:
    start_date = dt.date(2026, 9, 1)
    entries: list[JournalEntryData] = []
    recovery_by_date: dict[dt.date, int | None] = {}

    for i in range(6):
        d = start_date + dt.timedelta(days=i)
        entries.append(JournalEntryData(local_date=d, behavior="alcohol"))
        # Day 3 has no recovery on day D+1
        if i == 3:
            recovery_by_date[d + dt.timedelta(days=1)] = None
        else:
            recovery_by_date[d + dt.timedelta(days=1)] = 60

    for i in range(6, 12):
        d = start_date + dt.timedelta(days=i)
        entries.append(JournalEntryData(local_date=d, behavior="meditation"))
        recovery_by_date[d + dt.timedelta(days=1)] = 75

    result = compute_journal_insights(entries, recovery_by_date)
    # Alcohol only had 5 valid with days (since 1 had no recovery) and 6 without days
    alc = next(i for i in result.insights if i.behavior == "alcohol")
    assert alc.with_count == 5
    assert alc.without_count == 6


def test_to_dict_format() -> None:
    start_date = dt.date(2026, 9, 1)
    entries = [
        JournalEntryData(local_date=start_date, behavior="cold_exposure"),
    ]
    recovery = {start_date + dt.timedelta(days=1): 80}
    res = compute_journal_insights(entries, recovery)
    d = res.to_dict()
    assert "insights" in d
    assert "insufficient" in d
    assert d["insufficient"][0]["behavior"] == "cold_exposure"
    assert d["insufficient"][0]["with_count"] == 1
    assert d["insufficient"][0]["without_count"] == 0
