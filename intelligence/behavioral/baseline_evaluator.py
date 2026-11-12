"""Behavioral Baseline Evaluator for PauseGuard V2.

Computes profile-aware amount deviation and beneficiary familiarity
using mock ledger history without penalizing legitimate commercial payments.
"""

from dataclasses import dataclass, field
import statistics
from typing import Any

from intelligence.schemas.risk_signals import (
    AccountProfileType,
    BehavioralSignal,
    CalculationMethod,
    DataOrigin,
    SignalProvenance,
    SourceCategory,
)


@dataclass(frozen=True)
class PayerHistoryProfile:
    """Historical context for a payer required for baseline evaluation."""
    payer_id: str
    profile_type: AccountProfileType
    settled_amounts_paise: tuple[int, ...] = field(default_factory=tuple)
    beneficiary_history: dict[str, int] = field(default_factory=dict)


def evaluate_behavioral_baseline(
    profile: PayerHistoryProfile | None,
    beneficiary_id: str,
    amount_paise: int,
) -> BehavioralSignal:
    """Evaluate requested payment against established profile baseline.

    Returns an immutable, fully validated BehavioralSignal.
    """
    # Cold-start or missing profile: return honest uninitialized signal
    if profile is None or len(profile.settled_amounts_paise) == 0:
        return BehavioralSignal(
            status="uninitialized",
            profile_type=profile.profile_type if profile else None,
            baseline_median_paise=None,
            deviation_multiple=None,
            is_new_beneficiary=None,
            prior_transfers_count=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )

    # Calculate median baseline
    sorted_amounts = sorted(profile.settled_amounts_paise)
    median_amount = int(round(statistics.median(sorted_amounts)))

    # Compute deviation multiple
    if median_amount > 0:
        deviation = round(amount_paise / median_amount, 2)
    else:
        deviation = 1.0

    # Beneficiary familiarity
    prior_transfers = profile.beneficiary_history.get(beneficiary_id, 0)
    is_new = (prior_transfers == 0)

    return BehavioralSignal(
        status="evaluated",
        profile_type=profile.profile_type,
        baseline_median_paise=median_amount,
        deviation_multiple=deviation,
        is_new_beneficiary=is_new,
        prior_transfers_count=prior_transfers,
        provenance=SignalProvenance(
            source_category=SourceCategory.MODEL_INFERENCE,
            data_origin=DataOrigin.MOCK_LEDGER_HISTORY,
            calculation_method=CalculationMethod.STATISTICAL_BASELINE,
            is_synthetic=True,
        ),
    )
