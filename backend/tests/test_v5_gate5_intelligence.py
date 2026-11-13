"""Gate 5 fraud intelligence tests: Policy Lab friction cost, scam breakdown, threshold tuning & RBAC."""

from fastapi.testclient import TestClient
import pytest

from app.auth.identities import SYNTHETIC_ADMIN_TOKEN, SYNTHETIC_ANALYST_TOKEN, SYNTHETIC_PAYER_TOKEN
from app.config import Settings
from app.main import create_app


@pytest.fixture
def intel_client():
    app = create_app(
        Settings(
            environment="local",
            mode="mock",
            allow_demo_auth=True,
            allow_demo_admin=True,
        )
    )
    with TestClient(app) as client:
        yield client


def test_acceptance_15_policy_lab_friction_cost_breakdown_and_calibration(intel_client):
    """Acceptance #15: Analyst/Admin can run Policy Lab simulation with friction score & scam breakdown."""
    # Payer forbidden
    forbidden = intel_client.post(
        "/api/v2/policy-lab/simulate",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={"sample_size": 90, "seed": 42, "baseline_a_threshold_paise": 5000000},
    )
    assert forbidden.status_code == 403

    # Analyst simulation with default thresholds
    resp1 = intel_client.post(
        "/api/v2/policy-lab/simulate",
        headers={"Authorization": f"Bearer {SYNTHETIC_ANALYST_TOKEN}"},
        json={"sample_size": 120, "seed": 42, "baseline_a_threshold_paise": 5000000},
    )
    assert resp1.status_code == 200, resp1.text
    data = resp1.json()
    assert data["dataset_split"] == "test"
    assert data["is_synthetic"] is True
    assert isinstance(data["evaluation_latency_ms"], float)
    assert data["evaluation_latency_ms"] >= 0.0

    # Policy C reports friction_cost_score and tier distribution
    policy_c = data["policy_metrics"]["Policy C (Profile-Aware PauseGuard)"]
    assert "friction_cost_score" in policy_c
    assert policy_c["friction_cost_score"] >= 0.0

    breakdown = data["scam_category_breakdown"]
    assert "app_coercion_fraud" in breakdown
    assert "mule_proximity" in breakdown
    assert "velocity_structuring" in breakdown
    assert data["tier_distribution"]["Policy C (Profile-Aware PauseGuard)"]["tier_3"] >= 0

    # Admin runs calibrated tighter threshold simulation -> reflects calibration config
    resp2 = intel_client.post(
        "/api/v2/policy-lab/simulate",
        headers={"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"},
        json={
            "sample_size": 120,
            "seed": 42,
            "baseline_a_threshold_paise": 1000000,
            "personal_deviation_threshold": 3.0,
            "business_deviation_threshold": 6.0,
        },
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["calibration"]["personal_deviation_threshold"] == 3.0
    assert data2["calibration"]["baseline_a_threshold_paise"] == 1000000
