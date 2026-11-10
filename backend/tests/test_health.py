import pytest
from fastapi.testclient import TestClient


def test_health_is_public_and_contains_only_mock_liveness(application):
    with TestClient(application) as client:
        response = client.get("/api/v2/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock"}


@pytest.mark.parametrize("path", ["/health", "/api/v1/health", "/ready", "/api/v2/ready"])
def test_no_legacy_or_readiness_routes(application, path):
    with TestClient(application) as client:
        assert client.get(path).status_code == 404


def test_health_does_not_request_a_session(application):
    def forbidden_session():
        pytest.fail("Liveness must not request a database session.")

    application.state.session_factory = forbidden_session
    with TestClient(application) as client:
        assert client.get("/api/v2/health").status_code == 200
