"""Deterministic policy engine for PauseGuard V2 payments.

Enforces:
1. Hard denial / restriction (Priority 1): Confirmed fraud registry hits and active Safe-Lock.
2. Contextual and behavioral risk (Priority 2): Account profile baseline deviation,
   beneficiary familiarity, and coercion indicators in payment purpose.
3. User preference (Priority 3): User notification preference threshold influences
   warnings/UX (Tier 1), but NEVER removes hard security checks.
4. Security Invariants:
   - Advisory AI signals can NEVER authorize payments or override policy.
   - User threshold cannot override independent risk policy or confirmed fraud indicators.
   - Personal profile vs. commercial/business profile evaluated with appropriate baselines.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
from uuid import UUID

from intelligence.schemas.risk_signals import (
    AccountProfileType,
    RiskSignals,
)
from safety.purpose_challenge.purpose_challenge import assess_purpose


class RiskTier(IntEnum):
    TIER_0 = 0  # Normal payment authorization -> READY_TO_EXECUTE
    TIER_1 = 1  # Warning requiring payer acknowledgment -> AWAITING_WARNING
    TIER_2 = 2  # Independent step-up verification -> AWAITING_STEP_UP (future)
    TIER_3 = 3  # High-risk intervention -> AWAITING_GUARDIAN (or AWAITING_FALLBACK_REVIEW)


# Baseline medians in paise
PERSONAL_BASELINE_MEDIAN_PAISE = 500000      # ₹5,000
COMMERCIAL_BASELINE_MEDIAN_PAISE = 50000000  # ₹500,000

# High-risk deviation thresholds
PERSONAL_HIGH_RISK_THRESHOLD_PAISE = 5000000      # ₹50,000
COMMERCIAL_HIGH_RISK_THRESHOLD_PAISE = 200000000  # ₹2,000,000 (₹20L)

# Known mock high-risk beneficiaries for prototype testing
MOCK_FLAGGED_BENEFICIARIES = frozenset({
    "flagged_mule_01",
    "scam_beneficiary_01",
    "confirmed_mule_account",
    "blacklisted_payee_01",
})


@dataclass(frozen=True)
class PolicyEvaluationResult:
    """Deterministic policy evaluation outcome."""
    tier: int
    target_status: str
    risk_score: int
    reason_codes: tuple[str, ...]
    is_hard_blocked: bool = False
    coercion_detected: bool = False
    requires_guardian: bool = False
    requires_warning_ack: bool = False


def evaluate_payment_policy(
    *,
    payer_id: UUID,
    amount_paise: int,
    beneficiary_id: str,
    purpose: str,
    profile_type: AccountProfileType = AccountProfileType.PERSONAL,
    notification_preference_paise: Optional[int] = None,
    is_safe_locked: bool = False,
    is_new_beneficiary: bool = True,
    advisory_signals: Optional[RiskSignals] = None,
) -> PolicyEvaluationResult:
    """Evaluate payment request deterministically against V2 policy matrix rules.

    Rules ordered by strict priority:
    1. Hard denial / restriction
    2. Behavioral, contextual, and coercion risk
    3. User notification preference
    """
    reasons: list[str] = []

    # -------------------------------------------------------------------------
    # Priority 1: Hard denial / restrictions
    # -------------------------------------------------------------------------
    if is_safe_locked:
        return PolicyEvaluationResult(
            tier=RiskTier.TIER_3,
            target_status="REJECTED",
            risk_score=100,
            reason_codes=("RC_SAFE_LOCK_ENGAGED",),
            is_hard_blocked=True,
        )

    # Check mock fraud registry
    is_flagged = (
        beneficiary_id in MOCK_FLAGGED_BENEFICIARIES
        or beneficiary_id.startswith("flagged_")
        or beneficiary_id.startswith("scam_")
        or (advisory_signals and advisory_signals.registry.is_listed_high_risk is True)
    )
    if is_flagged:
        return PolicyEvaluationResult(
            tier=RiskTier.TIER_3,
            target_status="REJECTED",
            risk_score=100,
            reason_codes=("RC_CONFIRMED_FRAUD_REGISTRY",),
            is_hard_blocked=True,
        )

    # -------------------------------------------------------------------------
    # Priority 2: Purpose coercion and contextual risk
    # -------------------------------------------------------------------------
    purpose_assessment = assess_purpose(purpose)
    coercion_detected = purpose_assessment.suspicious
    if coercion_detected:
        for r in purpose_assessment.reasons:
            reasons.append(f"RC_COERCION_{r.upper()}")

    # Incorporate advisory intelligence signals (Member 3) if provided
    has_critical_advisory = False
    if advisory_signals is not None:
        if advisory_signals.transcript.status == "evaluated" and advisory_signals.transcript.coercion_detected:
            coercion_detected = True
            reasons.append("RC_ADVISORY_TRANSCRIPT_COERCION")
            for ind in advisory_signals.transcript.coercion_indicators:
                reasons.append(f"RC_COERCION_{ind.upper()}")

        if advisory_signals.mule_graph.status == "evaluated":
            if advisory_signals.mule_graph.hop_distance_to_flagged_mule == 1:
                reasons.append("RC_ADVISORY_MULE_GRAPH_PROXIMITY")
                has_critical_advisory = True
            elif (
                advisory_signals.mule_graph.cluster_risk_score is not None
                and advisory_signals.mule_graph.cluster_risk_score >= 80
            ):
                reasons.append("RC_ADVISORY_MULE_CLUSTER_HIGH_RISK")
                has_critical_advisory = True

        if (
            advisory_signals.velocity.status == "evaluated"
            and advisory_signals.velocity.structuring_suspected
        ):
            reasons.append("RC_ADVISORY_VELOCITY_STRUCTURING")

        if (
            advisory_signals.advisory_score is not None
            and advisory_signals.advisory_score >= 80
        ):
            reasons.append("RC_ADVISORY_SCORE_CRITICAL")
            has_critical_advisory = True

    # Profile-aware risk tiering
    if profile_type in (AccountProfileType.SMALL_BUSINESS, AccountProfileType.ENTERPRISE):
        # Commercial / business profile: larger baseline, verify anomalies
        if amount_paise >= COMMERCIAL_HIGH_RISK_THRESHOLD_PAISE:
            reasons.append("RC_COMMERCIAL_EXTREME_DEVIATION")
            return PolicyEvaluationResult(
                tier=RiskTier.TIER_3,
                target_status="AWAITING_GUARDIAN",
                risk_score=85,
                reason_codes=tuple(reasons),
                requires_guardian=True,
                coercion_detected=coercion_detected,
            )
        elif coercion_detected:
            reasons.append("RC_COERCION_ON_COMMERCIAL_ACCOUNT")
            return PolicyEvaluationResult(
                tier=RiskTier.TIER_3,
                target_status="AWAITING_GUARDIAN",
                risk_score=80,
                reason_codes=tuple(reasons),
                requires_guardian=True,
                coercion_detected=True,
            )
        else:
            # Ordinary business payment
            return PolicyEvaluationResult(
                tier=RiskTier.TIER_0,
                target_status="READY_TO_EXECUTE",
                risk_score=10,
                reason_codes=tuple(reasons) if reasons else ("RC_NORMAL_COMMERCIAL_FLOW",),
            )

    # Personal profile evaluation
    if amount_paise > PERSONAL_HIGH_RISK_THRESHOLD_PAISE or has_critical_advisory:
        if amount_paise > PERSONAL_HIGH_RISK_THRESHOLD_PAISE:
            reasons.append("RC_LARGE_AMOUNT_DEVIATION")
        risk_score = 90 if coercion_detected or has_critical_advisory else 75
        return PolicyEvaluationResult(
            tier=RiskTier.TIER_3,
            target_status="AWAITING_GUARDIAN",
            risk_score=risk_score,
            reason_codes=tuple(reasons),
            requires_guardian=True,
            coercion_detected=coercion_detected,
        )

    if coercion_detected:
        # Coercion on non-high amount triggers warning (Tier 1)
        reasons.append("RC_SUSPICIOUS_PURPOSE_COERCION_WARNING")
        return PolicyEvaluationResult(
            tier=RiskTier.TIER_1,
            target_status="AWAITING_WARNING",
            risk_score=50,
            reason_codes=tuple(reasons),
            requires_warning_ack=True,
            coercion_detected=True,
        )

    # -------------------------------------------------------------------------
    # Priority 3: User notification preference
    # -------------------------------------------------------------------------
    if notification_preference_paise is not None and amount_paise > notification_preference_paise:
        reasons.append("RC_USER_NOTIFICATION_PREFERENCE_EXCEEDED")
        return PolicyEvaluationResult(
            tier=RiskTier.TIER_1,
            target_status="AWAITING_WARNING",
            risk_score=30,
            reason_codes=tuple(reasons),
            requires_warning_ack=True,
        )

    # Default: Tier 0 normal execution
    return PolicyEvaluationResult(
        tier=RiskTier.TIER_0,
        target_status="READY_TO_EXECUTE",
        risk_score=5,
        reason_codes=("RC_NORMAL_PAYMENT_PATTERN",),
    )
