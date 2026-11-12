from datetime import datetime, timedelta, timezone

from safety.access_control.authorization import authorize_resource_access
from safety.anti_smurfing.rolling_detector import RollingSmurfingDetector
from safety.audit.audit_chain import AuditChain
from safety.evidence.redacted_export import export_redacted_evidence
from safety.guardian_alerts.guardian_alert import build_guardian_alert
from safety.guardian_timeout.timeout_policy import evaluate_guardian_timeout
from safety.purpose_challenge.purpose_challenge import assess_purpose
from safety.safe_lock.safe_lock_policy import assess_safe_lock


def test_authorization_allows_owner_with_allowed_role():
    assert authorize_resource_access(
        actor_id="payer-1",
        actor_role="payer",
        owner_id="payer-1",
        allowed_roles={"payer"},
    ) is True


def test_authorization_rejects_access_to_another_users_resource():
    assert authorize_resource_access(
        actor_id="user-2",
        actor_role="payer",
        owner_id="user-1",
        allowed_roles={"payer"},
    ) is False


def test_anti_smurfing_counts_unique_attempts_only():
    detector = RollingSmurfingDetector(
        window_seconds=600,
        minimum_attempts=3,
        amount_threshold_paise=100_000,
    )
    now = datetime.now(timezone.utc)

    first = detector.record_attempt("user-1", "attempt-1", 10_000, now)
    duplicate = detector.record_attempt("user-1", "attempt-1", 10_000, now)
    second = detector.record_attempt(
        "user-1", "attempt-2", 10_000, now + timedelta(seconds=1)
    )
    third = detector.record_attempt(
        "user-1", "attempt-3", 10_000, now + timedelta(seconds=2)
    )

    assert first.attempt_count == 1
    assert duplicate.attempt_count == 1
    assert second.attempt_count == 2
    assert third.attempt_count == 3
    assert third.suspicious is True


def test_audit_chain_detects_record_data_tampering():
    chain = AuditChain()
    chain.append("PAYMENT_REVIEWED", {"case_id": "case-1"})

    assert chain.verify() is True

    # AuditRecord is frozen, but its data dictionary is mutable.
    chain.records[0].data["case_id"] = "changed-case"

    assert chain.verify() is False


def test_evidence_export_omits_unapproved_fields():
    exported = export_redacted_evidence({
        "case_id": "case-1",
        "event_type": "RISK_REVIEW",
        "risk_level": "high",
        "phone_number": "9876543210",
        "password": "synthetic-secret",
        "recipient": "Synthetic Recipient",
        "unknown_internal_field": "must-not-export",
    })

    assert exported["case_id"] == "case-1"
    assert exported["event_type"] == "RISK_REVIEW"
    assert "phone_number" not in exported
    assert "password" not in exported
    assert "recipient" not in exported
    assert "unknown_internal_field" not in exported
    assert exported["redaction_applied"] is True
    assert exported["review_required_before_sharing"] is True


def test_guardian_alert_is_private_and_does_not_request_approval():
    alert = build_guardian_alert("case-1", "kn-IN")

    assert alert["locale"] == "kn"
    assert alert["contains_payment_details"] is False
    assert alert["approval_requested"] is False
    assert "message" in alert


def test_guardian_timeout_never_authorizes_or_executes():
    started = datetime.now(timezone.utc)
    checked = started + timedelta(seconds=30)

    result = evaluate_guardian_timeout(started, checked)

    assert result["expired"] is True
    assert result["recommended_action"] == "AWAITING_FALLBACK_REVIEW"
    assert result["can_authorize_payment"] is False
    assert result["can_execute_payment"] is False


def test_purpose_challenge_detects_coercion_indicators():
    result = assess_purpose(
        "Police say act immediately and do not tell anyone"
    )

    assert result.suspicious is True
    assert "urgency" in result.reasons
    assert "secrecy" in result.reasons
    assert "authority_impersonation" in result.reasons


def test_safe_lock_restricts_amount_above_configured_limit():
    result = assess_safe_lock(
        safe_lock_enabled=True,
        amount_paise=50_001,
        max_amount_paise=50_000,
        allowed_categories={"utilities"},
        payment_category="utilities",
    )

    assert result.restricted is True
    assert "amount_exceeds_safe_lock_limit" in result.reasons


def test_safety_modules_work_together_in_a_synthetic_review():
    # This is a test-harness composition of standalone modules.
    # It does not represent a connected backend application workflow.
    purpose = assess_purpose("Urgent payment; keep it secret")
    safe_lock = assess_safe_lock(
        safe_lock_enabled=True,
        amount_paise=75_000,
        max_amount_paise=50_000,
    )

    started = datetime.now(timezone.utc)
    timeout = evaluate_guardian_timeout(
        started,
        started + timedelta(seconds=30),
    )

    audit = AuditChain()
    audit.append(
        "SAFETY_REVIEW",
        {
            "purpose_suspicious": purpose.suspicious,
            "safe_lock_restricted": safe_lock.restricted,
            "guardian_timeout_expired": timeout["expired"],
        },
    )

    alert = build_guardian_alert("synthetic-case-1", "en")

    assert purpose.suspicious is True
    assert safe_lock.restricted is True
    assert timeout["can_authorize_payment"] is False
    assert timeout["can_execute_payment"] is False
    assert audit.verify() is True
    assert alert["approval_requested"] is False
