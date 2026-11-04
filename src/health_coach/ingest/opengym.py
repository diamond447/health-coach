"""Mirror openGym into Postgres: exercise catalogue, workout sessions and sets, body weight."""

import dataclasses
import datetime as dt
import hashlib
import json
import logging
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Connection, Engine, text

from health_coach.config import Settings, get_settings
from health_coach.crypto import decrypt, encrypt
from health_coach.ingest import state
from health_coach.opengym.catalogue import (
    canonical_id,
    fetch_aliases,
    fetch_catalogue,
    merge_custom_exercises,
)
from health_coach.opengym.client import OpenGymClient, OpenGymError
from health_coach.opengym.model import (
    LB_TO_KG,
    NormalizedSession,
    normalize_workouts,
)

log = logging.getLogger(__name__)

SOURCE = "opengym"


def load_token(engine: Engine, settings: Settings | None = None) -> str | None:
    """Load and decrypt the stored openGym bearer token."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT access_token_enc, refresh_token_enc FROM oauth_tokens WHERE provider = :p"
            ),
            {"p": SOURCE},
        ).first()
        if not row:
            return None
        enc = row.access_token_enc or row.refresh_token_enc
        if not enc:
            return None
        return decrypt(enc, settings)


def store_token(
    engine: Engine,
    token: str,
    settings: Settings | None = None,
    expires_at: dt.datetime | None = None,
) -> None:
    """Encrypt and store openGym token without printing or logging it."""
    enc = encrypt(token, settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oauth_tokens (provider, access_token_enc, refresh_token_enc, "
                "expires_at, scopes) VALUES (:p, :a, :r, :e, '{}') "
                "ON CONFLICT (provider) DO UPDATE SET "
                "access_token_enc = EXCLUDED.access_token_enc, "
                "refresh_token_enc = EXCLUDED.refresh_token_enc, "
                "expires_at = EXCLUDED.expires_at, updated_at = now()"
            ),
            {"p": SOURCE, "a": enc, "r": enc, "e": expires_at},
        )


def pair_and_store(
    engine: Engine,
    settings: Settings,
    code: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Redeem pairing code interactively and store encrypted token."""
    if not settings.opengym_url:
        raise OpenGymError("HC_OPENGYM_URL is not configured")
    with OpenGymClient(settings.opengym_url, transport=transport) as client:
        res = client.pair_redeem(code)
        token = res.get("token")
        if not token:
            raise OpenGymError("openGym did not return a token upon pairing")
        store_token(engine, token, settings)


def renew_token_if_needed(
    client: OpenGymClient,
    engine: Engine,
    settings: Settings | None = None,
) -> None:
    """Call /api/me and store renewed token if present."""
    me_res = client.me()
    renewed = me_res.get("token")
    if renewed:
        store_token(engine, str(renewed), settings)


def _to_kg_bw(weight: Any, unit: str) -> Decimal | None:
    if weight is None or weight == "":
        return None
    try:
        w = Decimal(str(weight))
        if unit.lower() == "lb":
            return (w * LB_TO_KG).quantize(Decimal("0.01"))
        return w.quantize(Decimal("0.01"))
    except Exception:
        return None


def upsert_catalogue_entries(conn: Connection, entries: list[dict[str, Any]]) -> int:
    """Upsert parsed catalogue exercises into exercises table."""
    rows: list[dict[str, Any]] = []
    for ex in entries:
        if not isinstance(ex, dict) or not ex.get("id"):
            continue
        ex_id = str(ex["id"])
        name = str(ex.get("n") or ex.get("name") or ex_id)
        cat = str(ex.get("cat") or ex.get("category") or "") or None
        primary: list[str] = []
        if ex.get("mg"):
            primary.append(str(ex["mg"]))
        elif ex.get("tg"):
            primary.append(str(ex["tg"]))
        secondary = [str(s) for s in (ex.get("sm") or ex.get("secondary_muscles") or [])]
        equipment = [str(ex["eq"])] if ex.get("eq") else []

        rows.append(
            {
                "id": ex_id,
                "name": name,
                "category": cat,
                "primary": primary,
                "secondary": secondary,
                "equipment": equipment,
            }
        )

    if rows:
        conn.execute(
            text(
                "INSERT INTO exercises (id, name, category, primary_muscles, "
                "secondary_muscles, equipment, source) "
                "VALUES (:id, :name, :category, :primary, :secondary, :equipment, 'opengym') "
                "ON CONFLICT (id) DO UPDATE SET "
                "name = EXCLUDED.name, category = EXCLUDED.category, "
                "primary_muscles = EXCLUDED.primary_muscles, "
                "secondary_muscles = EXCLUDED.secondary_muscles, "
                "equipment = EXCLUDED.equipment, updated_at = now() "
                "WHERE (exercises.name, exercises.category, exercises.primary_muscles, "
                "       exercises.secondary_muscles, exercises.equipment) "
                "IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.category, EXCLUDED.primary_muscles, "
                "                  EXCLUDED.secondary_muscles, EXCLUDED.equipment)"
            ),
            rows,
        )
    return len(rows)


def sync_catalogue(
    engine: Engine,
    version: str = "1.4.1",
    custom_ex: list[dict[str, Any]] | None = None,
    http_client: httpx.Client | None = None,
) -> int:
    """Refresh the exercise catalogue (daily job). The catalogue comes from GitHub, so
    this never uses the openGym client: its session token must not leave for GitHub."""
    catalogue = fetch_catalogue(version=version, client=http_client)
    all_entries = merge_custom_exercises(catalogue, custom_ex)
    with engine.begin() as conn:
        count = upsert_catalogue_entries(conn, all_entries)
        state.mark_success(conn, SOURCE, "catalogue")
    log.info("openGym: %d exercises cached", count)
    return count


# Upserts leave unchanged rows alone: no new row version, no updated_at bump.
_UPSERT_SESSION = """
INSERT INTO strength_sessions (
    external_id, local_date, start_ts, end_ts, routine_id, routine_name, notes, source
)
VALUES (:ext, :d, :start, :end, :rid, :rname, :notes, 'opengym')
ON CONFLICT (external_id) DO UPDATE SET
    local_date = EXCLUDED.local_date,
    start_ts = EXCLUDED.start_ts,
    end_ts = EXCLUDED.end_ts,
    routine_id = EXCLUDED.routine_id,
    routine_name = EXCLUDED.routine_name,
    notes = EXCLUDED.notes,
    updated_at = now()
WHERE (strength_sessions.local_date, strength_sessions.start_ts, strength_sessions.end_ts,
       strength_sessions.routine_id, strength_sessions.routine_name, strength_sessions.notes)
    IS DISTINCT FROM (EXCLUDED.local_date, EXCLUDED.start_ts, EXCLUDED.end_ts,
                      EXCLUDED.routine_id, EXCLUDED.routine_name, EXCLUDED.notes)
"""

_UPSERT_SET = """
INSERT INTO strength_sets (
    session_id, external_id, exercise_id, set_no, reps, weight_kg, rir, rpe, is_warmup, source
)
VALUES (:sid, :ext, :ex_id, :set_no, :reps, :weight_kg, :rir, :rpe, :warmup, 'opengym')
ON CONFLICT (external_id) DO UPDATE SET
    session_id = EXCLUDED.session_id,
    exercise_id = EXCLUDED.exercise_id,
    set_no = EXCLUDED.set_no,
    reps = EXCLUDED.reps,
    weight_kg = EXCLUDED.weight_kg,
    rir = EXCLUDED.rir,
    rpe = EXCLUDED.rpe,
    is_warmup = EXCLUDED.is_warmup,
    updated_at = now()
WHERE (strength_sets.session_id, strength_sets.exercise_id, strength_sets.set_no,
       strength_sets.reps, strength_sets.weight_kg, strength_sets.rir, strength_sets.rpe,
       strength_sets.is_warmup)
    IS DISTINCT FROM (EXCLUDED.session_id, EXCLUDED.exercise_id, EXCLUDED.set_no,
                      EXCLUDED.reps, EXCLUDED.weight_kg, EXCLUDED.rir, EXCLUDED.rpe,
                      EXCLUDED.is_warmup)
"""

# Bump when the mapping below changes, so the next run rewrites the mirror.
_WORKOUTS_FINGERPRINT_VERSION = 1


def _workouts_fingerprint(
    sessions: list[NormalizedSession], has_workouts: bool, aliases: dict[str, str]
) -> str:
    """Hash of everything sync_workouts would write. It covers the time zone, the unit
    conversion and the alias remapping, since they are applied by then."""
    doc = {
        "v": _WORKOUTS_FINGERPRINT_VERSION,
        "has_workouts": has_workouts,
        "sessions": [
            {
                **{k: v for k, v in dataclasses.asdict(s).items() if k != "sets"},
                "sets": [
                    {**dataclasses.asdict(st), "exercise_id": canonical_id(st.exercise_id, aliases)}
                    for st in s.sets
                ],
            }
            for s in sessions
        ],
    }
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _mirror_is_complete(conn: Connection, sessions: list[NormalizedSession]) -> bool:
    """Cheap check that nobody removed mirrored rows behind the sync's back."""
    row = conn.execute(
        text(
            "SELECT (SELECT count(*) FROM strength_sessions WHERE source = 'opengym') AS s, "
            "       (SELECT count(*) FROM strength_sets st JOIN strength_sessions ss "
            "          ON ss.id = st.session_id WHERE ss.source = 'opengym') AS st"
        )
    ).one()
    return bool(row.s == len(sessions) and row.st == sum(len(s.sets) for s in sessions))


def sync_workouts(
    client: OpenGymClient,
    engine: Engine,
    tz: ZoneInfo,
    state_doc: dict[str, Any] | None = None,
    aliases: dict[str, str] | None = None,
) -> int:
    """Sync workouts from openGym state into strength tables with mirrored deletions.

    Retired catalogue ids are mapped to their current id through `aliases`, so the same
    exercise is one series in the analytics. A document without a `workouts` list
    (never synced, or not a real state) removes nothing. Returns the number of sessions."""
    count, _ = sync_workouts_changed(client, engine, tz, state_doc, aliases)
    return count


def sync_workouts_changed(
    client: OpenGymClient,
    engine: Engine,
    tz: ZoneInfo,
    state_doc: dict[str, Any] | None = None,
    aliases: dict[str, str] | None = None,
) -> tuple[int, bool]:
    """sync_workouts, also saying whether anything had to be written. A state identical
    to the one of the previous run (same fingerprint, mirror intact) writes nothing."""
    if state_doc is None:
        doc = client.get_data()
        state_doc = doc.get("state") or {}
    aliases = aliases or {}

    sessions = normalize_workouts(state_doc, tz=tz)
    has_workouts = isinstance(state_doc.get("workouts"), list)
    fingerprint = _workouts_fingerprint(sessions, has_workouts, aliases)

    with engine.begin() as conn:
        previous = conn.execute(
            text("SELECT cursor FROM sync_state WHERE source = :s AND data_type = 'workouts'"),
            {"s": SOURCE},
        ).scalar()
        if previous == fingerprint and (not has_workouts or _mirror_is_complete(conn, sessions)):
            state.mark_success(conn, SOURCE, "workouts")
            return len(sessions), False

        _write_workouts(conn, sessions, has_workouts, aliases)
        state.mark_success(conn, SOURCE, "workouts", cursor=fingerprint)

    return len(sessions), True


def _write_workouts(
    conn: Connection,
    sessions: list[NormalizedSession],
    has_workouts: bool,
    aliases: dict[str, str],
) -> None:
    active_session_ids = [s.external_id for s in sessions]

    # Mirror workout deletions (sets go with their session)
    if has_workouts:
        conn.execute(
            text(
                "DELETE FROM strength_sessions WHERE source = 'opengym' "
                "AND external_id <> ALL(:active_ids)"
            ),
            {"active_ids": active_session_ids},
        )
    if not sessions:
        return

    # Referenced exercises must exist (FK); the catalogue job fills in their details.
    exercise_ids = sorted(
        {canonical_id(st.exercise_id, aliases) for s in sessions for st in s.sets}
    )
    if exercise_ids:
        conn.execute(
            text(
                "INSERT INTO exercises (id, name, source) "
                "SELECT id, id, 'opengym' FROM unnest(CAST(:ids AS text[])) AS id "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"ids": exercise_ids},
        )

    # One round trip per batch (psycopg pipelines executemany).
    conn.execute(
        text(_UPSERT_SESSION),
        [
            {
                "ext": s.external_id,
                "d": s.local_date,
                "start": s.start_ts,
                "end": s.end_ts,
                "rid": s.routine_id,
                "rname": s.routine_name,
                "notes": s.notes,
            }
            for s in sessions
        ],
    )
    session_ids: dict[str, int] = {
        r.external_id: r.id
        for r in conn.execute(
            text("SELECT external_id, id FROM strength_sessions WHERE external_id = ANY(:ids)"),
            {"ids": active_session_ids},
        )
    }

    # Mirror set deletions within the synced sessions
    conn.execute(
        text(
            "DELETE FROM strength_sets st USING strength_sessions ss "
            "WHERE st.session_id = ss.id AND ss.external_id = ANY(:sessions) "
            "AND st.external_id <> ALL(:sets)"
        ),
        {
            "sessions": active_session_ids,
            "sets": [st.external_id for s in sessions for st in s.sets],
        },
    )

    set_rows = [
        {
            "sid": session_ids[s.external_id],
            "ext": st.external_id,
            "ex_id": canonical_id(st.exercise_id, aliases),
            "set_no": st.set_no,
            "reps": st.reps,
            "weight_kg": st.weight_kg,
            "rir": st.rir,
            "rpe": st.rpe,
            "warmup": st.is_warmup,
        }
        for s in sessions
        for st in s.sets
    ]
    if set_rows:
        conn.execute(text(_UPSERT_SET), set_rows)


def sync_bodyweight(
    client: OpenGymClient,
    engine: Engine,
    tz: ZoneInfo,
    state_doc: dict[str, Any] | None = None,
) -> int:
    """Sync bodyweight entries from openGym state into body_metrics."""
    if state_doc is None:
        doc = client.get_data()
        state_doc = doc.get("state") or {}

    has_bodyweight = isinstance(state_doc.get("bodyweight"), list)
    raw_bw = state_doc.get("bodyweight") or []
    unit = str(state_doc.get("unit") or "kg")

    rows: list[dict[str, Any]] = []
    active_ext_ids: set[str] = set()

    for item in raw_bw:
        if not isinstance(item, dict) or not item.get("d"):
            continue
        d_str = str(item["d"])
        local_date = dt.date.fromisoformat(d_str)
        ext_id = f"bw:{d_str}"
        active_ext_ids.add(ext_id)

        t_val = item.get("t")
        if isinstance(t_val, (int, float)) and t_val > 10000000000:
            ts = dt.datetime.fromtimestamp(t_val / 1000.0, tz=dt.UTC)
        else:
            ts = dt.datetime.combine(local_date, dt.time(8, 0), tzinfo=tz)

        w_kg = _to_kg_bw(item.get("w"), unit)
        rows.append({"ext": ext_id, "ts": ts, "d": local_date, "kg": w_kg})

    with engine.begin() as conn:
        # Mirror removals: soft delete missing entries (only from a real document)
        if not has_bodyweight:
            pass
        elif active_ext_ids:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() "
                    "WHERE source = 'opengym' AND external_id != ALL(:active_ids) "
                    "AND deleted_at IS NULL"
                ),
                {"active_ids": list(active_ext_ids)},
            )
        else:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() "
                    "WHERE source = 'opengym' AND deleted_at IS NULL"
                )
            )

        if rows:
            conn.execute(
                text(
                    "INSERT INTO body_metrics (source, external_id, ts, local_date, weight_kg) "
                    "VALUES ('opengym', :ext, :ts, :d, :kg) "
                    "ON CONFLICT (source, external_id) DO UPDATE SET "
                    "ts = EXCLUDED.ts, local_date = EXCLUDED.local_date, "
                    "weight_kg = EXCLUDED.weight_kg, deleted_at = NULL, updated_at = now() "
                    "WHERE (body_metrics.ts, body_metrics.local_date, body_metrics.weight_kg) "
                    "IS DISTINCT FROM (EXCLUDED.ts, EXCLUDED.local_date, EXCLUDED.weight_kg) "
                    "OR body_metrics.deleted_at IS NOT NULL"
                ),
                rows,
            )

        state.mark_success(conn, SOURCE, "bodyweight")

    return len(rows)


def sync_opengym_workouts(
    engine: Engine,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """High-level runner: renews token, syncs workouts and bodyweight. Returns whether
    the workouts changed since the previous run."""
    settings = settings or get_settings()
    if not settings.opengym_url:
        raise OpenGymError("openGym is not configured (HC_OPENGYM_URL)")

    token = load_token(engine, settings)
    if not token:
        raise OpenGymError("openGym is not paired; run `health-coach auth opengym`")

    with OpenGymClient(settings.opengym_url, token=token, transport=transport) as client:
        renew_token_if_needed(client, engine, settings)
        doc = client.get_data()
        state_doc = doc.get("state") or {}
        try:
            aliases = fetch_aliases(settings.opengym_version)
        except Exception:  # catalogue host down: keep ids as logged
            log.warning("openGym catalogue unavailable; exercise aliases not applied")
            aliases = {}
        _, changed = sync_workouts_changed(
            client, engine, tz=settings.tz, state_doc=state_doc, aliases=aliases
        )
        sync_bodyweight(client, engine, tz=settings.tz, state_doc=state_doc)
        # Also sync user's custom exercises if present
        custom_ex = state_doc.get("customEx")
        if isinstance(custom_ex, list) and custom_ex:
            with engine.begin() as conn:
                upsert_catalogue_entries(conn, custom_ex)
    return changed


def sync_opengym_catalogue(
    engine: Engine,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """High-level runner: syncs catalogue."""
    settings = settings or get_settings()
    if transport is None:
        sync_catalogue(engine, version=settings.opengym_version)
        return
    with httpx.Client(transport=transport) as http:
        sync_catalogue(engine, version=settings.opengym_version, http_client=http)
