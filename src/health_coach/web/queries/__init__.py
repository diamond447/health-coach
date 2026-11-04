"""Database queries for the healthstats web API, one module per screen.

Connects with Role.ro only. All dates are local calendar dates in HC_TIMEZONE.
Missing data returns None / empty lists; endpoints never manufacture fake values.
"""

from health_coach.web.queries.activity import query_activity
from health_coach.web.queries.calendar import query_calendar
from health_coach.web.queries.day import query_day
from health_coach.web.queries.healthspan import query_healthspan
from health_coach.web.queries.journal import query_journal
from health_coach.web.queries.nutrition import query_nutrition
from health_coach.web.queries.recovery import query_night, query_recovery
from health_coach.web.queries.report import query_report
from health_coach.web.queries.sleep import query_sleep
from health_coach.web.queries.strain import query_strain
from health_coach.web.queries.trends import query_trends

__all__ = [
    "query_activity",
    "query_calendar",
    "query_day",
    "query_healthspan",
    "query_journal",
    "query_night",
    "query_nutrition",
    "query_recovery",
    "query_report",
    "query_sleep",
    "query_strain",
    "query_trends",
]
