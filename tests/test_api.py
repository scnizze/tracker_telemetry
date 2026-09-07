"""
Basic smoke tests for the telemetry API.

Uses FastAPI's TestClient, which runs the app in-process (no real network
call, no server process) -- fast, and exactly what CI will run on every
push and pull request.

Note: without DATABASE_URL set, this uses the SQLite fallback, writing to
a local telemetry.db in whatever directory the tests run from. Fine for
a learning project; a more mature test suite would isolate this with a
temp database per test run.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Using TestClient as a context manager triggers FastAPI's startup
    # event (which calls init_db()) before any requests are made, and
    # the shutdown event afterward -- without `with`, startup never runs
    # and the "telemetry" table won't exist yet.
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_and_read_back(client):
    # Unique device_id per test run so repeated runs don't collide.
    device_id = f"test-{uuid.uuid4().hex[:8]}"
    payload = {
        "device_id": device_id,
        "ts": "2026-09-04T00:00:00Z",
        "lat": 51.169,
        "lon": 71.449,
        "battery_pct": 95.0,
        "satellites": 7,
    }

    post_response = client.post("/telemetry", json=payload)
    assert post_response.status_code == 201

    get_response = client.get(f"/telemetry/{device_id}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert len(body) == 1
    assert body[0]["device_id"] == device_id
    assert body[0]["battery_pct"] == 95.0


def test_unknown_device_returns_404(client):
    response = client.get("/telemetry/does-not-exist-device")
    assert response.status_code == 404
