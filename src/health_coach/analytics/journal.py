"""Pure analytics functions for habit and behaviour journaling."""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class JournalEntryData:
    local_date: dt.date
    behavior: str
    amount: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class BehaviorInsight:
    behavior: str
    with_count: int
    without_count: int
    with_mean_recovery: float
    without_mean_recovery: float
    difference_pp: float


@dataclass(frozen=True)
class InsufficientBehavior:
    behavior: str
    with_count: int
    without_count: int


@dataclass(frozen=True)
class JournalInsightsResult:
    insights: list[BehaviorInsight]
    insufficient: list[InsufficientBehavior]

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "insights": [asdict(i) for i in self.insights],
            "insufficient": [asdict(i) for i in self.insufficient],
        }


def compute_journal_insights(
    entries: Sequence[Any],
    recovery_by_date: Mapping[dt.date, int | float | None],
    min_days: int = 5,
) -> JournalInsightsResult:
    """Analyze the relationship between evening behaviours and next-day recovery.

    For each behaviour present in the journal entries:
    - computes mean recovery on the day AFTER the behaviour day (day D+1) when the
      behaviour occurred vs when it did not occur.
    - a day counts as "without" only when the journal has at least one entry that
      day (unlogged days do not count as "without").
    - days without a recovery score on day D+1 are excluded.
    - only behaviours with >= min_days (default 5) days "with" and >= min_days
      days "without" are included in `insights`.
    - other behaviours are listed under `insufficient` with their counts.
    """
    journal_by_date: dict[dt.date, set[str]] = {}
    for entry in entries:
        if isinstance(entry, Mapping):
            d = entry["local_date"]
            b = str(entry["behavior"])
        else:
            d = entry.local_date
            b = str(entry.behavior)
        if isinstance(d, str):
            d = dt.date.fromisoformat(d)
        journal_by_date.setdefault(d, set()).add(b)

    all_behaviors = sorted({b for b_set in journal_by_date.values() for b in b_set})

    # Only days with at least one journal entry AND valid recovery on day D+1 count
    valid_days: list[tuple[dt.date, float]] = []
    for d in sorted(journal_by_date.keys()):
        next_d = d + dt.timedelta(days=1)
        rec = recovery_by_date.get(next_d)
        if rec is not None:
            valid_days.append((d, float(rec)))

    insights: list[BehaviorInsight] = []
    insufficient: list[InsufficientBehavior] = []

    for b in all_behaviors:
        with_recs = [rec for d, rec in valid_days if b in journal_by_date[d]]
        without_recs = [rec for d, rec in valid_days if b not in journal_by_date[d]]

        with_count = len(with_recs)
        without_count = len(without_recs)

        if with_count >= min_days and without_count >= min_days:
            with_mean = sum(with_recs) / with_count
            without_mean = sum(without_recs) / without_count
            diff = with_mean - without_mean
            insights.append(
                BehaviorInsight(
                    behavior=b,
                    with_count=with_count,
                    without_count=without_count,
                    with_mean_recovery=round(with_mean, 1),
                    without_mean_recovery=round(without_mean, 1),
                    difference_pp=round(diff, 1),
                )
            )
        else:
            insufficient.append(
                InsufficientBehavior(
                    behavior=b,
                    with_count=with_count,
                    without_count=without_count,
                )
            )

    # Sort insights by magnitude of difference descending, then behavior
    insights.sort(key=lambda x: (-abs(x.difference_pp), x.behavior))
    insufficient.sort(key=lambda x: x.behavior)

    return JournalInsightsResult(insights=insights, insufficient=insufficient)
