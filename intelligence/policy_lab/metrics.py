"""Evaluation metrics engine for PauseGuard Policy Lab (Member 3).

Implements rigorous, zero-division-safe evaluation metrics following
docs/EXPERIMENT_PLAN_AND_METRICS.md.

Invariants:
- Exposes explicit numerator and denominator for every calculated rate.
- Explicitly handles zero denominators (rate=None) without fabrication.
- Handles optional unavailable metrics (payer friction, guardian workload,
  recovery lag) with transparent explanations.
- Distinguishes personal versus business false-positive rates and disruption.
- Declares synthetic lab origin on all outputs.
"""

from dataclasses import asdict, dataclass
import json
from typing import Any, Optional


@dataclass(frozen=True)
class MetricRate:
    """A fractional rate exposing its explicit numerator and denominator.

    Prevents zero-division errors and avoids fabricating false 0.0 rates
    when no relevant samples exist in the evaluated cohort.

    Invariants:
    - When denominator is zero (or <= 0), rate is None (serialized as JSON null).
    - Clearly indicates undefined status via `is_undefined`.
    - Preserves numerator and denominator counts.
    - Never substitutes 0.0 for an undefined rate.
    - Strict integer types for counts (rejects booleans and floats).
    """
    rate: Optional[float]
    numerator: int
    denominator: int

    def __post_init__(self):
        if type(self.numerator) is bool or not isinstance(self.numerator, int):
            raise ValueError("numerator must be a strict integer; booleans and floats are rejected")
        if type(self.denominator) is bool or not isinstance(self.denominator, int):
            raise ValueError("denominator must be a strict integer; booleans and floats are rejected")
        if self.rate is not None:
            if type(self.rate) is bool or not isinstance(self.rate, (int, float)):
                raise ValueError("rate must be a float, int, or None")

    @property
    def is_undefined(self) -> bool:
        """True if the rate is mathematically undefined (denominator is zero)."""
        return self.denominator == 0 or self.rate is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "is_undefined": self.is_undefined,
        }

    @classmethod
    def compute(cls, numerator: int, denominator: int) -> "MetricRate":
        """Compute rate safely, returning rate=None when denominator is zero.

        Args:
            numerator: Non-negative integer count.
            denominator: Integer denominator count.

        Returns:
            MetricRate with calculated ratio, or rate=None if denominator <= 0.
        """
        if type(numerator) is bool or not isinstance(numerator, int):
            raise ValueError("numerator must be a strict integer; booleans and floats are rejected")
        if type(denominator) is bool or not isinstance(denominator, int):
            raise ValueError("denominator must be a strict integer; booleans and floats are rejected")

        if denominator <= 0:
            return cls(rate=None, numerator=numerator, denominator=0)
        return cls(
            rate=round(numerator / denominator, 4),
            numerator=numerator,
            denominator=denominator,
        )


@dataclass(frozen=True)
class ConfusionMatrix:
    """Binary confusion matrix counts."""
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    total_evaluated: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileCohortBreakdown:
    """Confusion counts and rates specific to a profile cohort (e.g. personal, business)."""
    cohort_name: str
    legitimate_total: int
    flagged_legitimate_count: int  # False positives in cohort
    false_positive_rate: MetricRate

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_name": self.cohort_name,
            "legitimate_total": self.legitimate_total,
            "flagged_legitimate_count": self.flagged_legitimate_count,
            "false_positive_rate": self.false_positive_rate.to_dict(),
        }


@dataclass(frozen=True)
class UnavailableMetricDetail:
    """Transparent placeholder for unavailable dataset metrics."""
    status: str = "unavailable"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyEvaluationMetrics:
    """Comprehensive evaluation metrics for a policy comparison experiment."""
    policy_name: str
    total_scenarios: int
    confusion_matrix: ConfusionMatrix
    precision: MetricRate
    recall: MetricRate
    specificity: MetricRate
    false_positive_rate: MetricRate
    false_negative_rate: MetricRate
    personal_cohort: ProfileCohortBreakdown
    business_cohort: ProfileCohortBreakdown
    business_disruption_rate: MetricRate
    unavailable_metrics: dict[str, UnavailableMetricDetail]
    is_synthetic: bool = True
    synthetic_caveat: str = (
        "Synthetic lab evaluation only. Metrics derived from synthetic test fixtures "
        "do not represent real-world fraud detection accuracy or bank-wide performance."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "total_scenarios": self.total_scenarios,
            "confusion_matrix": self.confusion_matrix.to_dict(),
            "precision": self.precision.to_dict(),
            "recall": self.recall.to_dict(),
            "specificity": self.specificity.to_dict(),
            "false_positive_rate": self.false_positive_rate.to_dict(),
            "false_negative_rate": self.false_negative_rate.to_dict(),
            "personal_cohort": self.personal_cohort.to_dict(),
            "business_cohort": self.business_cohort.to_dict(),
            "business_disruption_rate": self.business_disruption_rate.to_dict(),
            "unavailable_metrics": {
                k: v.to_dict() for k, v in self.unavailable_metrics.items()
            },
            "is_synthetic": self.is_synthetic,
            "synthetic_caveat": self.synthetic_caveat,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def get_standard_unavailable_metrics() -> dict[str, UnavailableMetricDetail]:
    """Return documented explanations for optional metrics not supported by the dataset."""
    return {
        "payer_friction": UnavailableMetricDetail(
            status="unavailable",
            reason=(
                "Payer friction measurement (duration of warnings, review calls per 1000 payments) "
                "is unavailable because the synthetic scenario fixture does not model user interaction "
                "durations or review call logs."
            ),
        ),
        "guardian_workload": UnavailableMetricDetail(
            status="unavailable",
            reason=(
                "Guardian workload (alerts/day, unanswered response rates) is unavailable because "
                "the synthetic dataset does not model time-series guardian notification queues or caregiver responses."
            ),
        ),
        "recovery_lag": UnavailableMetricDetail(
            status="unavailable",
            reason=(
                "Recovery lag is unavailable because the synthetic dataset models pre-execution transaction risk "
                "and does not simulate post-transaction fraud reporting or law enforcement recovery times."
            ),
        ),
    }


def calculate_evaluation_metrics(
    policy_name: str,
    predictions: list[bool],
    ground_truth_labels: list[str],
    profile_types: list[str],
) -> PolicyEvaluationMetrics:
    """Calculate complete policy evaluation metrics safely.

    Args:
        policy_name: Name of evaluated policy strategy.
        predictions: List of bool predictions (True = flagged/intercepted, False = allowed).
        ground_truth_labels: List of ground truth labels ('fraud' vs 'legitimate').
        profile_types: List of profile types ('personal', 'professional', 'small_business', 'enterprise').

    Returns:
        PolicyEvaluationMetrics with complete rates, cohort breakdowns, and unavailable explanations.

    Raises:
        ValueError: If input lists have mismatched lengths.
    """
    n = len(predictions)
    if len(ground_truth_labels) != n or len(profile_types) != n:
        raise ValueError(
            f"Input lists must have identical lengths: predictions={len(predictions)}, "
            f"ground_truth_labels={len(ground_truth_labels)}, profile_types={len(profile_types)}"
        )

    tp = 0
    fp = 0
    tn = 0
    fn = 0

    personal_legit_total = 0
    personal_fp = 0

    business_legit_total = 0
    business_fp = 0

    for pred, truth, profile in zip(predictions, ground_truth_labels, profile_types):
        is_fraud = (truth.lower() == "fraud")
        is_business = (profile.lower() in ("professional", "small_business", "enterprise"))

        if is_fraud:
            if pred:
                tp += 1
            else:
                fn += 1
        else:
            # Legitimate payment
            if pred:
                fp += 1
            else:
                tn += 1

            # Profile cohort accounting
            if is_business:
                business_legit_total += 1
                if pred:
                    business_fp += 1
            else:
                personal_legit_total += 1
                if pred:
                    personal_fp += 1

    confusion = ConfusionMatrix(
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        total_evaluated=n,
    )

    precision = MetricRate.compute(numerator=tp, denominator=tp + fp)
    recall = MetricRate.compute(numerator=tp, denominator=tp + fn)
    specificity = MetricRate.compute(numerator=tn, denominator=tn + fp)
    false_positive_rate = MetricRate.compute(numerator=fp, denominator=fp + tn)
    false_negative_rate = MetricRate.compute(numerator=fn, denominator=fn + tp)

    personal_cohort = ProfileCohortBreakdown(
        cohort_name="personal",
        legitimate_total=personal_legit_total,
        flagged_legitimate_count=personal_fp,
        false_positive_rate=MetricRate.compute(numerator=personal_fp, denominator=personal_legit_total),
    )

    business_cohort = ProfileCohortBreakdown(
        cohort_name="business",
        legitimate_total=business_legit_total,
        flagged_legitimate_count=business_fp,
        false_positive_rate=MetricRate.compute(numerator=business_fp, denominator=business_legit_total),
    )

    # Per docs/EXPERIMENT_PLAN_AND_METRICS.md:
    # Business disruption = legitimate business payments requiring review / total legitimate business payments
    business_disruption_rate = MetricRate.compute(
        numerator=business_fp,
        denominator=business_legit_total,
    )

    return PolicyEvaluationMetrics(
        policy_name=policy_name,
        total_scenarios=n,
        confusion_matrix=confusion,
        precision=precision,
        recall=recall,
        specificity=specificity,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        personal_cohort=personal_cohort,
        business_cohort=business_cohort,
        business_disruption_rate=business_disruption_rate,
        unavailable_metrics=get_standard_unavailable_metrics(),
        is_synthetic=True,
    )
