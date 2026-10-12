"""Group 5: exercises and the local workout log mirror."""

import datetime as dt
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import text

from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server.common import (
    READ,
    audited,
    date_range,
    tabular,
)


def search_exercises(
    query: Annotated[str | None, Field(description="Part of the name, e.g. 'bench'")] = None,
    muscle: Annotated[str | None, Field(description="e.g. chest, quads, lats, biceps")] = None,
    equipment: Annotated[str | None, Field(description="e.g. barbell, dumbbell")] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Find openGym exercises in the local catalogue cache."""
    if not (query or muscle or equipment):
        raise ToolError("give at least one of query, muscle, equipment")
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id AS exercise_id, name, category, primary_muscles, "
                "secondary_muscles, equipment FROM exercises "
                "WHERE (CAST(:q AS text) IS NULL OR name ILIKE '%' || :q || '%') "
                "AND (CAST(:m AS text) IS NULL OR lower(:m) = ANY(primary_muscles) "
                "     OR lower(:m) = ANY(secondary_muscles)) "
                "AND (CAST(:e AS text) IS NULL OR lower(:e) = ANY(equipment)) "
                "ORDER BY (lower(:m) = ANY(primary_muscles)) DESC NULLS LAST, length(name), name "
                "LIMIT :limit"
            ),
            {"q": query, "m": muscle, "e": equipment, "limit": limit},
        ).all()
        cached = conn.execute(text("SELECT count(*) FROM exercises")).scalar_one()
    result = tabular(rows)
    if cached == 0:
        result["warnings"] = ["exercise cache is empty: the openGym sync has not run yet"]
    return result


def get_workout_log(
    start: Annotated[dt.date | None, Field(description="YYYY-MM-DD")] = None,
    end: Annotated[dt.date | None, Field(description="YYYY-MM-DD")] = None,
) -> dict[str, Any]:
    """Strength sessions with all sets from the local mirror of openGym (default: last 7
    days). Warm-up sets are flagged."""
    s, e = date_range(start, end)
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT s.local_date, s.routine_name, s.day_name, x.name AS exercise, ss.set_no, "
                "ss.reps, ss.weight_kg, ss.rir, ss.is_warmup, s.notes "
                "FROM strength_sets ss JOIN strength_sessions s ON s.id = ss.session_id "
                "JOIN exercises x ON x.id = ss.exercise_id "
                "WHERE s.local_date BETWEEN :s AND :e "
                "ORDER BY s.local_date, s.start_ts NULLS LAST, s.id, ss.exercise_id, ss.set_no"
            ),
            {"s": s, "e": e},
        ).all()
    return tabular(rows)


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(search_exercises))
    server.tool(annotations=READ)(audited(get_workout_log))
