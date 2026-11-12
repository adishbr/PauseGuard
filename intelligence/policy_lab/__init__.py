"""PauseGuard Policy Lab Package (Member 3 - Fraud Intelligence & Policy Lab).

Provides reproducible simulation, evaluation, and comparison of fraud policy strategies:
- Baseline A (Amount-only hard threshold)
- Baseline B (Always warn on new beneficiary)
- Policy C (Profile-aware PauseGuard policy)

Includes zero-division-safe evaluation metrics, confusion matrices, profile-aware
false-positive breakdowns, and held-out test split enforcement.
"""

from intelligence.policy_lab.metrics import (
    ConfusionMatrix,
    MetricRate,
    PolicyEvaluationMetrics,
    ProfileCohortBreakdown,
    UnavailableMetricDetail,
    calculate_evaluation_metrics,
    get_standard_unavailable_metrics,
)
from intelligence.policy_lab.policy_evaluator import (
    BasePolicy,
    BaselineAPolicy,
    BaselineBPolicy,
    PolicyCPauseGuard,
    PolicyDecision,
    PolicyLab,
    PolicyLabReport,
)

__all__ = [
    "BasePolicy",
    "BaselineAPolicy",
    "BaselineBPolicy",
    "ConfusionMatrix",
    "MetricRate",
    "PolicyCPauseGuard",
    "PolicyDecision",
    "PolicyEvaluationMetrics",
    "PolicyLab",
    "PolicyLabReport",
    "ProfileCohortBreakdown",
    "UnavailableMetricDetail",
    "calculate_evaluation_metrics",
    "get_standard_unavailable_metrics",
]
