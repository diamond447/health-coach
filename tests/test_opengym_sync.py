"""Unit tests for openGym ingest worker (workouts, bodyweight, catalogue, token management)."""

from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr
from sqlalchemy import Engine, text

from health_coach.config import Settings
from health_coach.ingest.opengym import (
    load_token,
    pair_and_store,
    renew_token_if_needed,
    store_token,
    sync_bodyweight,
    sync_catalogue,
    sync_workouts,
)
from health_coach.opengym.client import OpenGymClient

PRAGUE = ZoneInfo("Europe/Prague")
TOKEN_KEY = SecretStr("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")


def test_token_storage_and_encryption(owner: Engine) -> None:
    settings = Settings(token_key=TOKEN_KEY)
    token = "secret-session-token-99"

    store_token(owner, token, settings)

    # Verify token is encrypted in DB and not in plaintext
    with owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT access_token_enc, refresh_token_enc "
                "FROM oauth_tokens WHERE provider = 'opengym'"
            )
        ).one()
        assert token.encode() not in row.access_token_enc
        assert token.encode() not in row.refresh_token_enc

    # Verify decrypt
    loaded = load_token(owner, settings)
    assert loaded == token


def test_pair_and_store(owner: Engine) -> None:
    settings = Settings(
        opengym_url="http://localhost:3000",
        token_key=TOKEN_KEY,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/pair/redeem"
        return httpx.Response(200, json={"token": "paired-token-xyz", "user": {"id": "u1"}})

    pair_and_store(owner, settings, "ABCDEF12", transport=httpx.MockTransport(handler))
    loaded = load_token(owner, settings)
    assert loaded == "paired-token-xyz"


def test_renew_token_if_needed(owner: Engine) -> None:
    settings = Settings(
        opengym_url="http://localhost:3000",
        token_key=TOKEN_KEY,
    )
    store_token(owner, "old-token", settings)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer old-token"
        return httpx.Response(200, json={"user": {"id": "u1"}, "token": "new-renewed-token"})

    client = OpenGymClient(
        "http://localhost:3000", token="old-token", transport=httpx.MockTransport(handler)
    )
    renew_token_if_needed(client, owner, settings)

    assert load_token(owner, settings) == "new-renewed-token"


def test_sync_workouts_and_mirrored_deletions(owner: Engine) -> None:
    state_v1 = {
        "unit": "kg",
        "workouts": [
            {
                "id": "w1",
                "d": "2026-03-01",
                "name": "Push Day",
                "entries": [
                    {
                        "id": "bench-press",
                        "sets": [
                            {"id": "s1-1", "w": 80, "r": 8, "done": True, "rir": 2},
                            {"id": "s1-2", "w": 80, "r": 8, "done": True, "rir": 2},
                        ],
                    }
                ],
            },
            {
                "id": "w2",
                "d": "2026-03-02",
                "name": "Pull Day",
                "entries": [
                    {
                        "id": "pull-up",
                        "sets": [
                            {"id": "s2-1", "w": 0, "r": 10, "done": True},
                        ],
                    }
                ],
            },
        ],
    }

    client = OpenGymClient("http://localhost:3000")
    count = sync_workouts(client, owner, tz=PRAGUE, state_doc=state_v1)
    assert count == 2

    with owner.connect() as conn:
        sessions = conn.execute(
            text("SELECT external_id, routine_name FROM strength_sessions ORDER BY local_date")
        ).all()
        assert len(sessions) == 2
        assert sessions[0].external_id == "w1"
        assert sessions[0].routine_name == "Push Day"
        assert sessions[1].external_id == "w2"

        sets = conn.execute(
            text("SELECT external_id, weight_kg, reps FROM strength_sets ORDER BY id")
        ).all()
        assert len(sets) == 3
        assert sets[0].external_id == "s1-1"
        assert sets[0].weight_kg == Decimal("80.00")

    # Document v2: w2 removed, and s1-2 removed from w1 (mirrored deletions)
    state_v2 = {
        "unit": "kg",
        "workouts": [
            {
                "id": "w1",
                "d": "2026-03-01",
                "name": "Push Day Edited",
                "entries": [
                    {
                        "id": "bench-press",
                        "sets": [
                            {"id": "s1-1", "w": 82.5, "r": 8, "done": True, "rir": 1},
                        ],
                    }
                ],
            }
        ],
    }

    count2 = sync_workouts(client, owner, tz=PRAGUE, state_doc=state_v2)
    assert count2 == 1

    with owner.connect() as conn:
        sessions2 = conn.execute(
            text("SELECT external_id, routine_name FROM strength_sessions")
        ).all()
        assert len(sessions2) == 1
        assert sessions2[0].external_id == "w1"
        assert sessions2[0].routine_name == "Push Day Edited"

        sets2 = conn.execute(text("SELECT external_id, weight_kg FROM strength_sets")).all()
        assert len(sets2) == 1
        assert sets2[0].external_id == "s1-1"
        assert sets2[0].weight_kg == Decimal("82.50")


def test_sync_bodyweight_and_mirrored_deletions(owner: Engine) -> None:
    state_v1 = {
        "unit": "lb",
        "bodyweight": [
            {"d": "2026-03-01", "w": 180.0},
            {"d": "2026-03-02", "w": 181.0},
        ],
    }

    client = OpenGymClient("http://localhost:3000")
    count = sync_bodyweight(client, owner, tz=PRAGUE, state_doc=state_v1)
    assert count == 2

    with owner.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT external_id, weight_kg FROM body_metrics "
                "WHERE source = 'opengym' AND deleted_at IS NULL ORDER BY local_date"
            )
        ).all()
        assert len(rows) == 2
        assert rows[0].external_id == "bw:2026-03-01"
        # 180 lb * 0.45359237 = 81.646... -> 81.65 kg
        assert rows[0].weight_kg == Decimal("81.65")

    # Document v2: 2026-03-02 deleted
    state_v2 = {
        "unit": "lb",
        "bodyweight": [
            {"d": "2026-03-01", "w": 180.0},
        ],
    }
    sync_bodyweight(client, owner, tz=PRAGUE, state_doc=state_v2)

    with owner.connect() as conn:
        active = conn.execute(
            text(
                "SELECT external_id FROM body_metrics "
                "WHERE source = 'opengym' AND deleted_at IS NULL"
            )
        ).all()
        assert len(active) == 1
        assert active[0].external_id == "bw:2026-03-01"

        deleted = conn.execute(
            text(
                "SELECT external_id FROM body_metrics "
                "WHERE source = 'opengym' AND deleted_at IS NOT NULL"
            )
        ).all()
        assert len(deleted) == 1
        assert deleted[0].external_id == "bw:2026-03-02"


def test_sync_catalogue_with_customs(owner: Engine) -> None:
    custom_ex = [{"id": "custom-1", "n": "Custom Hex Bar Deadlift", "mg": "back", "eq": "hex bar"}]

    mock_js = """
    export const EXDB = [
        {"id": "bench-press", "n": "Bench Press", "mg": "chest", "eq": "barbell"},
        {"id": "squat", "n": "Squat", "mg": "quads", "eq": "barbell"}
    ];
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=mock_js)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        count = sync_catalogue(owner, version="1.4.1", custom_ex=custom_ex, http_client=http)
    assert count == 3

    with owner.connect() as conn:
        exercises = conn.execute(
            text("SELECT id, name FROM exercises WHERE source = 'opengym' ORDER BY id")
        ).all()
        ids = [e.id for e in exercises]
        assert "bench-press" in ids
        assert "squat" in ids
        assert "custom-1" in ids


def test_sync_without_workout_list_removes_nothing_and_aliases_apply(owner: Engine) -> None:
    client = OpenGymClient("http://localhost:3000")
    state = {
        "unit": "kg",
        "workouts": [
            {
                "id": "w1",
                "d": "2026-03-01",
                "entries": [{"id": "old-id", "sets": [{"w": 50, "r": 5, "done": True}]}],
            }
        ],
        "bodyweight": [{"d": "2026-03-01", "w": 80}],
    }
    sync_workouts(client, owner, tz=PRAGUE, state_doc=state, aliases={"old-id": "new-id"})
    sync_bodyweight(client, owner, tz=PRAGUE, state_doc=state)
    # A document that is not a real state (no lists) must not wipe the mirror.
    sync_workouts(client, owner, tz=PRAGUE, state_doc={})
    sync_bodyweight(client, owner, tz=PRAGUE, state_doc={})
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM strength_sessions")).scalar_one() == 1
        assert conn.execute(
            text("SELECT DISTINCT exercise_id FROM strength_sets")
        ).scalar_one() == ("new-id")
        assert (
            conn.execute(
                text("SELECT count(*) FROM body_metrics WHERE deleted_at IS NULL")
            ).scalar_one()
            == 1
        )


def test_catalogue_never_sends_the_opengym_token(owner: Engine) -> None:
    settings = Settings(opengym_url="http://localhost:3000", token_key=TOKEN_KEY)
    store_token(owner, "session-token-must-stay-home", settings)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text='export const EXDB = [{"id": "squat", "n": "Squat"}];')

    from health_coach.ingest.opengym import sync_opengym_catalogue
    from health_coach.opengym import catalogue

    catalogue._CATALOGUE_CACHE.clear()
    catalogue._ALIAS_CACHE.clear()
    sync_opengym_catalogue(owner, settings, transport=httpx.MockTransport(handler))
    assert seen and all("authorization" not in r.headers for r in seen)
    assert seen[0].url.host == "raw.githubusercontent.com"


def test_catalogue_refuses_an_authenticated_client() -> None:
    import pytest

    from health_coach.opengym.catalogue import fetch_catalogue

    client = OpenGymClient("http://localhost:3000", token="tok")
    with pytest.raises(ValueError, match="authenticated"):
        fetch_catalogue(version="9.9.9", client=client._http, use_cache=False)
