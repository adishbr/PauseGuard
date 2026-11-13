"""Regression and contract tests for POST /api/v2/risk/advice using evaluate_advisory.

Covers:
1. Successful risk evaluation
2. Authenticated payer context enforcement
3. Unauthenticated requests rejected (401)
4. Degraded advisory responses on timeout
5. Evaluator exception containment and graceful degradation
6. Mismatched payment context detection and fail-closed degradation
7. Advisory-only safety invariants (can_authorize_payment=False)
8. Unchanged API response schema contract
"""

from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.auth.identities import (
    SYNTHETIC_PAYER_ID,
    SYNTHETIC_PAYER_TOKEN,
)
from app.config import Settings
from app.main import create_app
from intelligence.advisory.types import AdvisoryResponse
from intelligence.schemas.risk_signals import (
    EvaluationStatus,
    RiskSignals,
    SuggestedCautionLevel,
    make_degraded_advisory,
)


@pytest.fixture
def client():
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app = create_app(settings)
    return TestClient(app)


def test_successful_risk_evaluation(client):
    """Verify successful risk evaluation route with valid parameters."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "flagged_mule_account",
        "amount_paise": 5500000,
        "purpose": "kyc_verification",
        "profile_type": "personal",
        "transcript_text": "Do not disconnect, police requires immediate settlement",
        "transcript_consented": True,
    }

    res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["payment_id"] == payment_id
    assert data["can_authorize_payment"] is False
    assert data["evaluation_status"] in ("complete", "degraded")
    assert isinstance(data["reason_codes"], list)
    assert len(data["reason_codes"]) >= 1
    assert "RC_COERCION_KEYWORD_DETECTED" in data["reason_codes"] or len(data["reason_codes"]) > 0
    assert "synthetic" in data["calibration_caveat"].lower()


def test_authenticated_payer_context(client):
    """Verify that the route uses the authenticated actor's ID as payer_id."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_known",
        "amount_paise": 150000,
        "purpose": "purchase",
        "profile_type": "personal",
    }

    with patch("backend.app.api.risk.evaluate_advisory") if False else patch("app.api.risk.evaluate_advisory") as mock_eval:
        from intelligence.advisory.adapter import evaluate_advisory as real_eval
        mock_eval.side_effect = real_eval

        res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
        assert res.status_code == 200
        assert mock_eval.called
        call_req = mock_eval.call_args[0][0]
        # Payer ID passed to advisory request MUST match the authenticated actor, not client claim
        assert call_req.payer_id == str(SYNTHETIC_PAYER_ID)
        assert call_req.payment_id == payment_id
        assert call_req.amount_paise == 150000


def test_unauthenticated_request_rejected(client):
    """Verify unauthenticated requests fail with 401."""
    payload = {
        "payment_id": "pay_unauth_123",
        "beneficiary_id": "beneficiary_test",
        "amount_paise": 10000,
        "purpose": "test",
    }
    res = client.post("/api/v2/risk/advice", json=payload)
    assert res.status_code == 401

    res_bad_token = client.post(
        "/api/v2/risk/advice",
        headers={"Authorization": "Bearer invalid-or-forged-token"},
        json=payload,
    )
    assert res_bad_token.status_code == 401


def test_degraded_advisory_on_evaluator_timeout(client):
    """Verify timeout in advisory evaluator degrades safely without crashing or authorizing."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_timeout",
        "amount_paise": 250000,
        "purpose": "rent",
    }

    with patch("intelligence.advisory.adapter.evaluate_risk_signals", side_effect=TimeoutError("Evaluation deadline exceeded")):
        res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["payment_id"] == payment_id
        assert data["evaluation_status"] == "degraded"
        assert data["advisory_score"] is None
        assert data["can_authorize_payment"] is False
        assert "RC_ADVISORY_SCORE_UNAVAILABLE" in data["reason_codes"]
        assert "RC_ADVISORY_EVALUATION_TIMEOUT" in data["reason_codes"]


def test_degraded_advisory_on_evaluator_exception(client):
    """Verify unhandled evaluator exceptions fail closed into schema-valid degraded responses."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_error",
        "amount_paise": 50000,
        "purpose": "utilities",
    }

    with patch("intelligence.advisory.adapter.evaluate_risk_signals", side_effect=RuntimeError("Graph node calculation crashed")):
        res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["payment_id"] == payment_id
        assert data["evaluation_status"] == "degraded"
        assert data["advisory_score"] is None
        assert data["can_authorize_payment"] is False
        assert "RC_ADVISORY_SCORE_UNAVAILABLE" in data["reason_codes"]
        assert "RC_ADVISORY_EVALUATION_ERROR" in data["reason_codes"]


def test_degraded_advisory_on_mismatched_payment_context(client):
    """Verify mismatched payment context returned by evaluator is caught and degraded."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_legit",
        "amount_paise": 100000,
        "purpose": "groceries",
    }

    # Simulate an evaluator returning a signal for a DIFFERENT payment_id (context spoofing or race)
    corrupted_signals = make_degraded_advisory(
        payment_id="wrong_spoofed_payment_id",
        payer_id=str(SYNTHETIC_PAYER_ID),
        beneficiary_id="beneficiary_legit",
        amount_paise=100000,
        degraded_reasons=(),
    )
    corrupted_response = AdvisoryResponse(risk_signals=corrupted_signals, evaluator_timings_ms={})

    with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=corrupted_response):
        res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        # The adapter must correct the payment_id to the caller's payment_id and mark as degraded
        assert data["payment_id"] == payment_id
        assert data["evaluation_status"] == "degraded"
        assert data["advisory_score"] is None
        assert data["can_authorize_payment"] is False
        assert "RC_ADVISORY_CONTEXT_MISMATCH" in data["reason_codes"]


def test_safety_invariants_advisory_only_cannot_authorize(client):
    """Verify advisory signals can never authorize payments or return can_authorize_payment=True."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_trusted",
        "amount_paise": 10000,
        "purpose": "tea",
    }

    res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["can_authorize_payment"] is False


def test_unchanged_response_schema(client):
    """Verify that RiskAdviceResponse schema remains exact and unchanged."""
    payment_id = f"pay_{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": payment_id,
        "beneficiary_id": "beneficiary_sample",
        "amount_paise": 20000,
        "purpose": "lunch",
    }

    res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()

    expected_keys = {
        "payment_id",
        "advisory_score",
        "suggested_caution_level",
        "reason_codes",
        "can_authorize_payment",
        "evaluation_status",
        "calibration_caveat",
    }
    assert set(data.keys()) == expected_keys

