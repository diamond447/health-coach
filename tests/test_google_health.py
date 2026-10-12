import datetime as dt
import json
import urllib.parse
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

from health_coach.config import Settings
from health_coach.crypto import TokenKeyError, decrypt, encrypt
from health_coach.db.engine import Role, get_engine
from health_coach.ingest.google_health import oauth
from health_coach.ingest.google_health import sync as gh_sync
from health_coach.ingest.google_health.client import GoogleHealthClient
from health_coach.ingest.google_health.datatypes import BY_NAME, DATA_TYPES, DataTypeSpec

KEY = Fernet.generate_key().decode()


def settings() -> Settings:
    return Settings(
        token_key=SecretStr(KEY),
        google_client_id="cid",
        google_client_secret=SecretStr("csecret"),
    )


def test_encrypt_roundtrip_and_wrong_key() -> None:
    blob = encrypt("refresh-me", settings())
    assert decrypt(blob, settings()) == "refresh-me"
    other = Settings(token_key=SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(TokenKeyError):
        decrypt(blob, other)
    with pytest.raises(TokenKeyError, match="HC_TOKEN_KEY"):
        encrypt("x", Settings())


def test_chunks() -> None:
    d = dt.date(2026, 1, 1)
    assert list(gh_sync.chunks(d, d + dt.timedelta(days=30), 14)) == [
        (d, d + dt.timedelta(days=14)),
        (d + dt.timedelta(days=14), d + dt.timedelta(days=28)),
        (d + dt.timedelta(days=28), d + dt.timedelta(days=30)),
    ]
    assert list(gh_sync.chunks(d, d, 14)) == []


def test_consent_url_uses_pkce_and_offline_access() -> None:
    req = oauth.start_consent(settings())
    query = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [req.state]
    assert "googlehealth.sleep.readonly" in query["scope"][0]


def test_code_from_redirect_checks_state() -> None:
    url = "http://localhost:8765/callback?state=abc&code=xyz"
    assert oauth.code_from_redirect(url, "abc") == "xyz"
    with pytest.raises(oauth.OAuthError, match="state"):
        oauth.code_from_redirect(url, "other")
    with pytest.raises(oauth.OAuthError, match="access_denied"):
        oauth.code_from_redirect("http://localhost:8765/callback?error=access_denied", "abc")


class TokenEndpoint:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.revoked = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            self.calls.append(form)
            if self.revoked:
                return httpx.Response(400, json={"error": "invalid_grant"})
            body = {"access_token": f"at-{len(self.calls)}", "expires_in": 3599, "scope": "s1 s2"}
            if form["grant_type"] == "authorization_code":
                body["refresh_token"] = "rt-1"
            return httpx.Response(200, json=body)
        assert request.headers["Authorization"].startswith("Bearer at-")
        return httpx.Response(200, json={"dataPoints": [{"x": 1}], "nextPageToken": ""})


def test_consent_store_and_refresh(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    endpoint = TokenEndpoint()
    transport = httpx.MockTransport(endpoint.handler)
    req = oauth.start_consent(settings())
    scopes = oauth.finish_consent(
        engine,
        settings(),
        req,
        f"http://localhost:8765/callback?state={req.state}&code=c1",
        transport,
    )
    assert scopes == ["s1", "s2"]
    assert endpoint.calls[0]["code_verifier"] == req.verifier
    with owner.connect() as conn:
        stored = conn.execute(text("SELECT refresh_token_enc FROM oauth_tokens")).scalar_one()
    assert b"rt-1" not in bytes(stored)  # encrypted at rest

    # Fresh token is reused, an expiring one is refreshed with the stored refresh token.
    assert oauth.access_token(engine, settings(), transport) == "at-1"
    with owner.begin() as conn:
        conn.execute(text("UPDATE oauth_tokens SET expires_at = now()"))
    assert oauth.access_token(engine, settings(), transport) == "at-2"
    assert endpoint.calls[-1] == {
        "grant_type": "refresh_token",
        "refresh_token": "rt-1",
        "client_id": "cid",
        "client_secret": "csecret",
    }

    endpoint.revoked = True
    with owner.begin() as conn:
        conn.execute(text("UPDATE oauth_tokens SET expires_at = now()"))
    with pytest.raises(oauth.ReauthRequired, match="auth google"):
        oauth.access_token(engine, settings(), transport)


def test_no_grant_requires_reauth(owner: Engine) -> None:
    with pytest.raises(oauth.ReauthRequired):
        oauth.access_token(get_engine(Role.ingest), settings())


class FakeFetcher:
    def __init__(self, fail_on: dt.date | None = None) -> None:
        self.calls: list[tuple[str, dt.date, dt.date]] = []
        self.fail_on = fail_on

    def fetch(self, spec: DataTypeSpec, start: dt.date, end: dt.date) -> dict[str, Any]:
        if self.fail_on and start >= self.fail_on:
            raise RuntimeError("quota exceeded")
        self.calls.append((spec.name, start, end))
        return {"pages": [{"dataPoints": [{"start": start.isoformat()}]}]}


def test_sync_type_stores_raw_payloads_and_runs_mapper(
    owner: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def steps_mapper(
        conn: Connection,
        payload: dict[str, Any],
        spec: Any,
        tz: Any,
        start: Any = None,
        end: Any = None,
    ) -> int:
        return len(payload["pages"][0]["dataPoints"])

    monkeypatch.setitem(gh_sync.MAPPERS, "steps", steps_mapper)
    fetcher = FakeFetcher()
    start = dt.date(2026, 1, 1)
    result = gh_sync.sync_type(
        fetcher, get_engine(Role.ingest), BY_NAME["steps"], start, start + dt.timedelta(days=100)
    )
    assert (result.chunks, result.rows) == (2, 2)  # 90-day limit
    # Same window again: payloads are replaced, not duplicated.
    gh_sync.sync_type(
        fetcher, get_engine(Role.ingest), BY_NAME["steps"], start, start + dt.timedelta(days=100)
    )
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM raw_payloads")).scalar_one() == 2
        assert (
            conn.execute(
                text("SELECT error_count FROM sync_state WHERE data_type = 'steps'")
            ).scalar_one()
            == 0
        )
    assert gh_sync.remap(get_engine(Role.ingest)) == {"steps": 2}


def test_backfill_resumes_after_failure(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    since, today = dt.date(2026, 1, 1), dt.date(2026, 2, 28)
    spec = BY_NAME["active-minutes"]  # 14-day chunks
    errors: list[str] = []
    gh_sync.backfill(
        FakeFetcher(fail_on=dt.date(2026, 1, 29)),
        engine,
        since,
        [spec],
        today,
        on_error=lambda s, e: errors.append(str(e)),
    )
    assert errors == ["quota exceeded"]
    resumed = FakeFetcher()
    gh_sync.backfill(resumed, engine, since, [spec], today)
    assert resumed.calls[0][1] == dt.date(2026, 1, 29)  # continues where it stopped
    assert resumed.calls[-1][2] == today + dt.timedelta(days=1)


def test_client_pages_and_auth(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    endpoint = TokenEndpoint()
    transport = httpx.MockTransport(endpoint.handler)
    req = oauth.start_consent(settings())
    oauth.finish_consent(
        engine,
        settings(),
        req,
        f"http://localhost:8765/callback?state={req.state}&code=c",
        transport,
    )
    with GoogleHealthClient(engine, settings(), transport) as client:
        payload = client.fetch(BY_NAME["sleep"], dt.date(2026, 1, 1), dt.date(2026, 1, 2))
    assert payload == {"pages": [{"dataPoints": [{"x": 1}], "nextPageToken": ""}]}


def test_client_request_shapes(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    req = oauth.start_consent(settings())

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={"access_token": "at-tok", "refresh_token": "rt-tok", "expires_in": 3600},
            )
        if ":dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": []})
        return httpx.Response(200, json={"dataPoints": []})

    transport = httpx.MockTransport(handler)
    oauth.finish_consent(
        engine,
        settings(),
        req,
        f"http://localhost:8765/callback?state={req.state}&code=c",
        transport,
    )

    d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
    with GoogleHealthClient(engine, settings(), transport) as client:
        # dailyRollUp shape
        captured.clear()
        client.fetch(BY_NAME["steps"], d1, d2)
        assert len(captured) == 1
        req_steps = captured[0]
        assert req_steps.method == "POST"
        assert req_steps.url.path == "/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp"
        body = json.loads(req_steps.content.decode())
        assert body == {
            "range": {
                "start": {"date": {"year": 2026, "month": 1, "day": 1}},
                "end": {"date": {"year": 2026, "month": 1, "day": 2}},
            },
            "windowSizeDays": 1,
            "pageSize": 10000,
        }

        # Daily summary type: daily_resting_heart_rate.date
        captured.clear()
        client.fetch(BY_NAME["daily-resting-heart-rate"], d1, d2)
        q = urllib.parse.parse_qs(captured[0].url.query.decode())
        assert q["pageSize"] == ["10000"]
        assert q["filter"] == [
            'daily_resting_heart_rate.date >= "2026-01-01" AND '
            'daily_resting_heart_rate.date < "2026-01-02"'
        ]

        # Sleep session: sleep.interval.civil_end_time, pageSize 25
        captured.clear()
        client.fetch(BY_NAME["sleep"], d1, d2)
        q = urllib.parse.parse_qs(captured[0].url.query.decode())
        assert q["pageSize"] == ["25"]
        assert q["filter"] == [
            'sleep.interval.civil_end_time >= "2026-01-01" AND '
            'sleep.interval.civil_end_time < "2026-01-02"'
        ]

        # Exercise session: exercise.interval.civil_start_time, pageSize 25
        captured.clear()
        client.fetch(BY_NAME["exercise"], d1, d2)
        q = urllib.parse.parse_qs(captured[0].url.query.decode())
        assert q["pageSize"] == ["25"]
        assert q["filter"] == [
            'exercise.interval.civil_start_time >= "2026-01-01" AND '
            'exercise.interval.civil_start_time < "2026-01-02"'
        ]

        # Nutrition session: nutrition_log.interval.civil_start_time, pageSize 10000
        captured.clear()
        client.fetch(BY_NAME["nutrition-log"], d1, d2)
        q = urllib.parse.parse_qs(captured[0].url.query.decode())
        assert q["pageSize"] == ["10000"]
        assert q["filter"] == [
            'nutrition_log.interval.civil_start_time >= "2026-01-01" AND '
            'nutrition_log.interval.civil_start_time < "2026-01-02"'
        ]

        # Sample type: weight.sample_time.civil_time, pageSize 10000
        captured.clear()
        client.fetch(BY_NAME["weight"], d1, d2)
        q = urllib.parse.parse_qs(captured[0].url.query.decode())
        assert q["pageSize"] == ["10000"]
        assert q["filter"] == [
            'weight.sample_time.civil_time >= "2026-01-01" AND '
            'weight.sample_time.civil_time < "2026-01-02"'
        ]


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "google_health"


def _load_fixture(name: str) -> dict[str, Any]:
    with open(FIXTURES_DIR / f"{name}.json") as f:
        data: dict[str, Any] = json.load(f)
        return data


def test_mappers_typed_tables(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    tz = settings().tz
    d1, d2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)

    # 1. Activity rollups
    for name in (
        "steps",
        "distance",
        "floors",
        "active-minutes",
        "active-zone-minutes",
        "total-calories",
    ):
        payload = _load_fixture(name)
        with engine.begin() as conn:
            gh_sync.store_and_map(conn, BY_NAME[name], d1, d2, payload, tz)

    with owner.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT local_date, steps, distance_km, floors, active_minutes, "
                    "active_zone_minutes, calories_out "
                    "FROM daily_activity WHERE local_date = '2026-10-01'"
                )
            )
            .mappings()
            .one()
        )
        assert row["steps"] == 8540
        assert row["distance_km"] == Decimal("6.420")
        assert row["floors"] == 12
        assert row["active_minutes"] == 45
        assert row["active_zone_minutes"] == 45
        assert row["calories_out"] == 2350

    # 2. Vitals
    vitals_types = (
        "daily-resting-heart-rate",
        "daily-heart-rate-variability",
        "daily-oxygen-saturation",
        "daily-respiratory-rate",
        "daily-sleep-temperature-derivations",
        "daily-vo2-max",
    )
    for name in vitals_types:
        payload = _load_fixture(name)
        with engine.begin() as conn:
            gh_sync.store_and_map(conn, BY_NAME[name], d1, d2, payload, tz)

    with owner.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT local_date, resting_hr, hrv_rmssd_ms, spo2_avg, breathing_rate, "
                    "skin_temp_delta, cardio_fitness "
                    "FROM daily_vitals WHERE local_date = '2026-10-01'"
                )
            )
            .mappings()
            .one()
        )
        assert row["resting_hr"] == 56
        assert row["hrv_rmssd_ms"] == Decimal("45.2")
        assert row["spo2_avg"] == Decimal("96.8")
        assert row["breathing_rate"] == Decimal("14.5")
        assert row["skin_temp_delta"] == Decimal("-0.25")
        assert row["cardio_fitness"] == Decimal("46.8")

    # 3. Heart rate samples
    hr_payload = _load_fixture("heart-rate")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["heart-rate"], d1, d2, hr_payload, tz)

    with owner.connect() as conn:
        rows = (
            conn.execute(text("SELECT ts, bpm FROM heart_rate_samples ORDER BY ts"))
            .mappings()
            .all()
        )
        assert len(rows) == 2
        assert rows[0]["bpm"] == 68
        assert rows[1]["bpm"] == 71

    # 4. Sleep sessions and stages
    sleep_payload = _load_fixture("sleep")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["sleep"], d1, d2, sleep_payload, tz)

    with owner.connect() as conn:
        sessions = (
            conn.execute(
                text(
                    "SELECT id, external_id, local_date, duration_min, time_in_bed_min, "
                    "efficiency, minutes_deep, minutes_light, minutes_rem, minutes_awake, is_main "
                    "FROM sleep_sessions ORDER BY start_ts"
                )
            )
            .mappings()
            .all()
        )
        assert len(sessions) == 2
        main_s, nap = sessions[0], sessions[1]
        assert main_s["is_main"] is True
        assert main_s["local_date"] == dt.date(2026, 10, 1)
        assert main_s["duration_min"] == 420
        assert main_s["time_in_bed_min"] == 480
        assert main_s["efficiency"] == 88  # 420/480 = 87.5% -> 88%
        assert main_s["minutes_deep"] == 75
        assert main_s["minutes_light"] == 225
        assert main_s["minutes_rem"] == 120
        assert main_s["minutes_awake"] == 60

        assert nap["is_main"] is False
        assert nap["duration_min"] == 40
        assert nap["time_in_bed_min"] == 45

        # Check sleep stages
        stages = (
            conn.execute(
                text(
                    "SELECT stage, count(*) as cnt FROM sleep_stages "
                    "WHERE session_id = :sid GROUP BY stage ORDER BY stage"
                ),
                {"sid": main_s["id"]},
            )
            .mappings()
            .all()
        )
        stage_map = {r["stage"]: r["cnt"] for r in stages}
        assert stage_map == {"awake": 1, "deep": 1, "light": 1, "rem": 1}

    # 5. Exercise session
    ex_payload = _load_fixture("exercise")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["exercise"], d1, d2, ex_payload, tz)

    with owner.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT external_id, local_date, activity_type, duration_min, avg_hr, "
                    "calories, distance_km, hr_zone_minutes, notes, deleted_at "
                    "FROM exercise_sessions "
                    "WHERE external_id = 'users/me/dataTypes/exercise/dataPoints/ex-run-1'"
                )
            )
            .mappings()
            .one()
        )
        assert row["local_date"] == dt.date(2026, 10, 1)
        assert row["activity_type"] == "running"
        assert row["duration_min"] == 45
        assert row["avg_hr"] == 148
        assert row["calories"] == 450
        assert row["distance_km"] == Decimal("7.500")
        assert row["hr_zone_minutes"] == {"moderate": 15, "vigorous": 30}
        assert row["notes"] == "Morning run around the park"
        assert row["deleted_at"] is None

    # 6. Weight and Body fat
    wt_payload = _load_fixture("weight")
    bf_payload = _load_fixture("body-fat")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["weight"], d1, d2, wt_payload, tz)
        gh_sync.store_and_map(conn, BY_NAME["body-fat"], d1, d2, bf_payload, tz)

    with owner.connect() as conn:
        wt_row = (
            conn.execute(
                text(
                    "SELECT weight_kg, local_date, deleted_at FROM body_metrics "
                    "WHERE external_id = 'users/me/dataTypes/weight/dataPoints/wt-1'"
                )
            )
            .mappings()
            .one()
        )
        assert wt_row["weight_kg"] == Decimal("80.00")
        assert wt_row["local_date"] == dt.date(2026, 10, 1)
        assert wt_row["deleted_at"] is None

        bf_row = (
            conn.execute(
                text(
                    "SELECT body_fat_pct, local_date, deleted_at FROM body_metrics "
                    "WHERE external_id = 'users/me/dataTypes/body-fat/dataPoints/bf-1'"
                )
            )
            .mappings()
            .one()
        )
        assert bf_row["body_fat_pct"] == Decimal("16.8")
        assert bf_row["local_date"] == dt.date(2026, 10, 1)
        assert bf_row["deleted_at"] is None

    # 7. Nutrition log and foods
    nutr_payload = _load_fixture("nutrition-log")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["nutrition-log"], d1, d2, nutr_payload, tz)

    with owner.connect() as conn:
        n_row = (
            conn.execute(
                text(
                    "SELECT external_id, local_date, meal, food_id, description, grams, "
                    "kcal, protein_g, carbs_g, fat_g, fiber_g, source, deleted_at "
                    "FROM nutrition_entries "
                    "WHERE external_id = 'users/me/dataTypes/nutrition-log/dataPoints/nutr-1'"
                )
            )
            .mappings()
            .one()
        )
        assert n_row["local_date"] == dt.date(2026, 10, 1)
        assert n_row["meal"] == "lunch"
        assert n_row["description"] == "Chicken Rice Bowl"
        assert n_row["grams"] == Decimal("400.0")
        assert n_row["kcal"] == Decimal("650.0")
        assert n_row["protein_g"] == Decimal("45.0")
        assert n_row["carbs_g"] == Decimal("70.0")
        assert n_row["fat_g"] == Decimal("15.0")
        assert n_row["fiber_g"] == Decimal("6.0")
        assert n_row["source"] == "google_health"
        assert n_row["deleted_at"] is None

        food_id = n_row["food_id"]
        assert food_id is not None
        f_row = (
            conn.execute(
                text(
                    "SELECT name, kcal_100g, protein_100g, carbs_100g, fat_100g, "
                    "fiber_100g, source FROM foods WHERE id = :id"
                ),
                {"id": food_id},
            )
            .mappings()
            .one()
        )
        assert f_row["name"] == "Chicken Rice Bowl"
        assert f_row["source"] == "google_health"
        # 650 kcal in 400g -> 162.5 kcal / 100g
        assert f_row["kcal_100g"] == Decimal("162.5")
        # 45g protein in 400g -> 11.2g / 100g (or 11.25 -> 11.2 or 11.3)
        assert f_row["protein_100g"] in (Decimal("11.2"), Decimal("11.3"))


def test_mappers_idempotent_and_deletion(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    tz = settings().tz
    d1, d2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)

    ex_payload = _load_fixture("exercise")
    # First sync
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["exercise"], d1, d2, ex_payload, tz)

    # Re-sync same payload: stays active, row not duplicated
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["exercise"], d1, d2, ex_payload, tz)

    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM exercise_sessions WHERE deleted_at IS NULL")
            ).scalar_one()
            == 1
        )

    # Re-sync with empty payload for that window: exercise session is soft-deleted
    empty_payload: dict[str, Any] = {"dataPoints": []}
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["exercise"], d1, d2, empty_payload, tz)

    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM exercise_sessions WHERE deleted_at IS NULL")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM exercise_sessions WHERE deleted_at IS NOT NULL")
            ).scalar_one()
            == 1
        )

    # Sleep deletion test
    sleep_payload = _load_fixture("sleep")
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["sleep"], d1, d2, sleep_payload, tz)
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sleep_sessions")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM sleep_stages")).scalar_one() == 4

    # Re-sync sleep with empty payload
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["sleep"], d1, d2, empty_payload, tz)
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sleep_sessions")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM sleep_stages")).scalar_one() == 0


def test_sync_via_mock_transport(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    req = oauth.start_consent(settings())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
            )
        path = request.url.path
        for name in BY_NAME:
            if f"/dataTypes/{name}/dataPoints" in path:
                fixture = _load_fixture(name)
                return httpx.Response(200, json=fixture)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    oauth.finish_consent(
        engine,
        settings(),
        req,
        f"http://localhost:8765/callback?state={req.state}&code=c",
        transport,
    )

    with GoogleHealthClient(engine, settings(), transport) as client:
        d1, d2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)
        for spec in DATA_TYPES:
            gh_sync.sync_type(client, engine, spec, d1, d2)

    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM daily_activity")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM daily_vitals")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM heart_rate_samples")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM sleep_sessions")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM exercise_sessions")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM body_metrics")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM nutrition_entries")).scalar_one() == 1


def test_mappers_use_the_civil_date_the_api_reports(owner: Engine) -> None:
    """Abroad, the user's civil date can differ from the configured zone's date; rows
    must land on the civil date the list filter selected them by, or the next window
    would reconcile them away."""
    engine = get_engine(Role.ingest)
    tz = settings().tz
    # 23:30 in New York on Oct 1 is already Oct 2 in Prague.
    weight = {
        "dataPoints": [
            {
                "name": "users/me/dataTypes/weight/dataPoints/travel-1",
                "weight": {
                    "sampleTime": {
                        "physicalTime": "2026-10-02T03:30:00Z",
                        "utcOffset": "-14400s",
                        "civilTime": {"date": {"year": 2026, "month": 10, "day": 1}},
                    },
                    "weightGrams": 80000.0,
                },
            }
        ]
    }
    d1, d2, d3 = dt.date(2026, 10, 1), dt.date(2026, 10, 2), dt.date(2026, 10, 3)
    with engine.begin() as conn:
        gh_sync.store_and_map(conn, BY_NAME["weight"], d1, d2, weight, tz)
        # The next window (Oct 2) does not contain the sample and must not remove it.
        gh_sync.store_and_map(conn, BY_NAME["weight"], d2, d3, {"dataPoints": []}, tz)
    with owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT local_date, deleted_at FROM body_metrics WHERE external_id LIKE '%travel-1'"
            )
        ).one()
    assert row.local_date == d1
    assert row.deleted_at is None


def test_backfill_limits_heart_rate_history(owner: Engine) -> None:
    engine = get_engine(Role.ingest)
    today = dt.date(2026, 2, 28)
    fetcher = FakeFetcher()
    gh_sync.backfill(fetcher, engine, dt.date(2025, 1, 1), [BY_NAME["heart-rate"]], today)
    # one request per day, only the last 30 days (plus today, still filling up)
    assert fetcher.calls[0][1] == today + dt.timedelta(days=1) - dt.timedelta(days=30)
    assert len(fetcher.calls) == 30
    assert DATA_TYPES[-1].name == "heart-rate"  # never holds up the other types
