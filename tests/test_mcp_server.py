import json

from starlette.testclient import TestClient

from health_coach.mcp_server.server import create_server, without_titles


def test_healthz() -> None:
    app = create_server().streamable_http_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_tool_list_is_lean() -> None:
    from mcp import Client

    async with Client(create_server()) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) > 30
    for tool in tools:
        assert tool.output_schema is None, tool.name
        schema = json.dumps(tool.input_schema)
        # Only a property that is really called "title" may remain.
        assert '"title": "' not in schema, tool.name
    log_session = next(t for t in tools if t.name == "log_exercise_session")
    assert "activity_type" in log_session.input_schema["properties"]


def test_without_titles_keeps_properties_named_title() -> None:
    schema = {
        "title": "Args",
        "type": "object",
        "properties": {
            "title": {"title": "Title", "type": "string"},
            "day": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Day"},
        },
    }
    assert without_titles(schema) == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "day": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
