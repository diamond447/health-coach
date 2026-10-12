"""openGym exercise catalogue fetching, parsing, and search."""

import json
import logging
import re
from typing import Any

import httpx

from health_coach.ingest.http import retrying

log = logging.getLogger(__name__)

DEFAULT_OPENGYM_VERSION = "1.4.1"
CATALOGUE_URL_TEMPLATE = "https://raw.githubusercontent.com/DuarteSantos8/openGym/v{version}/frontend/src/lib/exercises-data.js"

# In-memory caches of parsed catalogues and alias maps, keyed by version
_CATALOGUE_CACHE: dict[str, list[dict[str, Any]]] = {}
_ALIAS_CACHE: dict[str, dict[str, str]] = {}


def _export_literal(js_content: str, name: str) -> Any:
    """JSON literal assigned by `export const <name>=` in a generated module (the file
    holds several exports, so the literal is decoded from its start, not sliced)."""
    match = re.search(rf"export\s+const\s+{name}\s*=\s*", js_content)
    if match is None:
        raise ValueError(f"export {name} not found in catalogue JS content")
    value, _ = json.JSONDecoder().raw_decode(js_content, match.end())
    return value


def parse_catalogue_js(js_content: str) -> list[dict[str, Any]]:
    """Parse the EXDB array of openGym's exercises-data.js."""
    try:
        data = _export_literal(js_content, "EXDB")
    except json.JSONDecodeError as exc:
        raise ValueError(f"EXDB is not a JSON literal: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("EXDB did not parse as a list")
    return data


def parse_aliases_js(js_content: str) -> dict[str, str]:
    """Parse EXALIAS (retired exercise id -> current id); empty when absent."""
    try:
        data = _export_literal(js_content, "EXALIAS")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def canonical_id(exercise_id: str, aliases: dict[str, str]) -> str:
    """Follow alias chains (bounded, in case of a cycle)."""
    seen = 0
    while exercise_id in aliases and seen < 10:
        exercise_id = aliases[exercise_id]
        seen += 1
    return exercise_id


@retrying
def _fetch_url(url: str, client: httpx.Client | None = None) -> str:
    if client is not None:
        # The catalogue host is public; a client carrying a credential (the openGym
        # session token) would hand it to GitHub.
        if "authorization" in client.headers:
            raise ValueError("catalogue fetch must not use an authenticated client")
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text
    with httpx.Client(timeout=30.0) as http:
        resp = http.get(url)
        resp.raise_for_status()
        return resp.text


def fetch_catalogue(
    version: str = DEFAULT_OPENGYM_VERSION,
    client: httpx.Client | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch and parse the openGym catalogue for a given version tag."""
    if use_cache and client is None and version in _CATALOGUE_CACHE:
        return list(_CATALOGUE_CACHE[version])

    url = CATALOGUE_URL_TEMPLATE.format(version=version)
    log.info("Fetching openGym catalogue from %s", url)
    content = _fetch_url(url, client=client)
    parsed = parse_catalogue_js(content)

    if use_cache:
        _CATALOGUE_CACHE[version] = parsed
        _ALIAS_CACHE[version] = parse_aliases_js(content)
    return list(parsed)


def fetch_aliases(
    version: str = DEFAULT_OPENGYM_VERSION, client: httpx.Client | None = None
) -> dict[str, str]:
    """Alias map of a catalogue version (fetched with the catalogue, then cached)."""
    if version not in _ALIAS_CACHE:
        fetch_catalogue(version, client=client, use_cache=True)
    return dict(_ALIAS_CACHE.get(version, {}))


def merge_custom_exercises(
    catalogue: list[dict[str, Any]],
    custom_ex: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge user custom exercises with catalogue. Customs come first matching openGym."""
    if not custom_ex:
        return list(catalogue)

    # Put custom exercises first, then builtin exercises not shadowed by custom id
    custom_ids = {str(c.get("id")) for c in custom_ex if isinstance(c, dict) and c.get("id")}
    filtered_catalogue = [e for e in catalogue if str(e.get("id")) not in custom_ids]
    return list(custom_ex) + filtered_catalogue


def search_catalogue(
    exercises: list[dict[str, Any]],
    query: str | None = None,
    muscle: str | None = None,
    equipment: str | None = None,
) -> list[dict[str, Any]]:
    """Search catalogue entries by name/query, muscle, and equipment."""
    q_lower = query.strip().lower() if query else None
    m_lower = muscle.strip().lower() if muscle else None
    eq_lower = equipment.strip().lower() if equipment else None

    results: list[dict[str, Any]] = []

    for ex in exercises:
        if not isinstance(ex, dict):
            continue

        name = str(ex.get("n") or ex.get("name") or "").lower()
        target = str(ex.get("tg") or ex.get("target") or "").lower()
        body_part = str(ex.get("bp") or ex.get("body_part") or "").lower()
        muscle_grp = str(ex.get("mg") or ex.get("muscle_group") or "").lower()
        equip = str(ex.get("eq") or ex.get("equipment") or "").lower()
        sec_muscles = [str(m).lower() for m in (ex.get("sm") or ex.get("secondary_muscles") or [])]

        if q_lower and q_lower not in name and q_lower not in target and q_lower not in body_part:
            continue

        if m_lower:
            matched_muscle = (
                m_lower in target
                or m_lower in muscle_grp
                or m_lower in body_part
                or any(m_lower in sm for sm in sec_muscles)
            )
            if not matched_muscle:
                continue

        if eq_lower and eq_lower not in equip:
            continue

        results.append(ex)

    return results
