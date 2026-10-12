"""openGym client, state model, and catalogue."""

from health_coach.opengym.client import (
    OpenGymAuthError,
    OpenGymClient,
    OpenGymConflictError,
    OpenGymError,
)
from health_coach.opengym.model import (
    CompactRoutine,
    ExerciseSpec,
    NormalizedSession,
    NormalizedSet,
    RoutineSpec,
    add_or_update_routine,
    make_uid,
    normalize_workouts,
    plan_routine,
    read_routines,
)

__all__ = [
    "CompactRoutine",
    "ExerciseSpec",
    "NormalizedSession",
    "NormalizedSet",
    "OpenGymAuthError",
    "OpenGymClient",
    "OpenGymConflictError",
    "OpenGymError",
    "RoutineSpec",
    "add_or_update_routine",
    "make_uid",
    "normalize_workouts",
    "plan_routine",
    "read_routines",
]
