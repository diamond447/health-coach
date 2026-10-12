from starlette.testclient import TestClient

from health_coach.mcp_server.server import create_server


def test_healthz() -> None:
    app = create_server().streamable_http_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
