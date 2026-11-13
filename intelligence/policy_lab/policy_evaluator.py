"""Policy evaluation engine and Policy Lab comparison suite for PauseGuard (Member 3).

Implements the three core fraud policy strategies per docs/EXPERIMENT_PLAN_AND_METRICS.md:
1. Baseline A: Amount-only hard threshold (requires explicit threshold configuration).
2. Baseline B: Always warn on new beneficiary (familiarity heuristic).
3. Policy C: Profile-aware PauseGuard policy (combines baseline deviation, profile context,
   and advisory evaluation components).

Enforces:
- Exclusive evaluation on the held-out test split.
- Strict anti-leakage feature separation (only ScenarioFeatures passed to policies).
- Zero payer overlap between train/val and test splits.
- Explicit unavailability reporting for unconfigured policies.
"""

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from typing import Any, Optional

from intelligence.advisory.transcript_evaluator import evaluate_transcript
from intelligence.advisory.types import (
    AdvisoryScoringConfig,
    get_default_scoring_config,
)
from intelligence.advisory.velocity_evaluator import VelocityContext, evaluate_velocity
from intelligence.policy_lab.metrics import (
    PolicyEvaluationMetrics,
    calculate_evaluation_metrics,
)
from intelligence.schemas.risk_signals import AccountProfileType, VelocitySignal
from synthetic_data.generator import (
    DatasetSplits,
    ScenarioFeatures,
    SyntheticPaymentScenario,
    split_dataset,
)


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of a policy evaluation on a transaction scenario."""
    flagged: bool  # True = intervention (warn/step-up/restrict); False = allow/pass
    tier: int      # 0: allow, 1: warn, 2: step-up, 3: restrict/guardian
    policy_name: str
    reason: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BasePolicy(ABC):
    """Abstract base class for all fraud evaluation policies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the policy."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the policy is fully configured and available for evaluation."""
        pass

    @abstractmethod
    def evaluate(self, features: ScenarioFeatures) -> PolicyDecision:
        """Evaluate a scenario using only inference-time features.

        CRITICAL: Never accepts ground truth targets, labels, or scenario IDs
        to prevent predictive data leakage.
        """
        pass


class BaselineAPolicy(BasePolicy):
    """Baseline A — Amount-only hard threshold policy.

    Evaluates whether amount_paise meets or exceeds an explicitly configured threshold.
    Does NOT invent a default production threshold.
    """

    def __init__(self, threshold_paise: Optional[int] = None):
        if threshold_paise is not None:
            if type(threshold_paise) is bool or not isinstance(threshold_paise, int):
                raise ValueError("threshold_paise must be a strict integer; booleans/floats are rejected")
            if threshold_paise <= 0:
                raise ValueError("threshold_paise must be strictly positive (> 0 paise)")
        self._threshold_paise = threshold_paise

    @property
    def name(self) -> str:
        return "Baseline A (Amount-only Hard Threshold)"

    @property
    def is_available(self) -> bool:
        return self._threshold_paise is not None

    @property
    def threshold_paise(self) -> Optional[int]:
        return self._threshold_paise

    def evaluate(self, features: ScenarioFeatures) -> PolicyDecision:
        if not self.is_available or self._threshold_paise is None:
            raise ValueError(
                "Baseline A is unconfigured: threshold_paise must be explicitly supplied. "
                "Do not invent a default production threshold."
            )

        flagged = features.amount_paise >= self._threshold_paise
        tier = 2 if flagged else 0
        reason = (
            f"amount_{features.amount_paise}_paise_exceeds_threshold_{self._threshold_paise}"
            if flagged else "amount_within_threshold"
        )
        return PolicyDecision(
            flagged=flagged,
            tier=tier,
            policy_name=self.name,
            reason=reason,
            metadata={"threshold_paise": self._threshold_paise, "amount_paise": features.amount_paise},
        )


class BaselineBPolicy(BasePolicy):
    """Baseline B — Always warn on new beneficiary.

    Evaluates solely based on beneficiary familiarity.
    Per experiment plan: A new beneficiary alone is an advisory warning,
    never treated as proof of fraud.
    """

    @property
    def name(self) -> str:
        return "Baseline B (Always Warn on New Beneficiary)"

    @property
    def is_available(self) -> bool:
        return True

    def evaluate(self, features: ScenarioFeatures) -> PolicyDecision:
        flagged = features.is_new_beneficiary
        tier = 1 if flagged else 0
        reason = "new_beneficiary_warning" if flagged else "familiar_beneficiary_allowed"
        return PolicyDecision(
            flagged=flagged,
            tier=tier,
            policy_name=self.name,
            reason=reason,
            metadata={"is_new_beneficiary": features.is_new_beneficiary},
        )


@dataclass(frozen=True)
class SyntheticVelocityThresholds:
    """Explicit synthetic experiment thresholds for velocity structuring detection.

    WARNING: These thresholds are strictly for synthetic benchmark experiments
    and Policy Lab simulations. They do NOT represent approved production policy
    or regulatory thresholds.
    """
    structuring_threshold_attempts: int
    structuring_threshold_amount_paise: int
    rolling_window_minutes: int = 60
    is_synthetic: bool = field(default=True, init=False)

    def __post_init__(self):
        if self.is_synthetic is not True:
            raise ValueError("is_synthetic must be immutable True for SyntheticVelocityThresholds")

        for field_name in (
            "structuring_threshold_attempts",
            "structuring_threshold_amount_paise",
            "rolling_window_minutes",
        ):
            val = getattr(self, field_name)
            if type(val) is bool or not isinstance(val, int):
                raise ValueError(
                    f"{field_name} must be a strict integer; booleans and floats are rejected"
                )

        if self.structuring_threshold_attempts < 1:
            raise ValueError("structuring_threshold_attempts must be strictly positive (>= 1)")
        if self.structuring_threshold_amount_paise < 1:
            raise ValueError("structuring_threshold_amount_paise must be strictly positive (>= 1 paise)")
        if self.rolling_window_minutes < 1 or self.rolling_window_minutes > 1440:
            raise ValueError("rolling_window_minutes must be between 1 and 1440")


def get_default_synthetic_velocity_thresholds() -> SyntheticVelocityThresholds:
    """Return explicit synthetic experiment velocity thresholds for Policy Lab benchmarks.

    Provenance:
    - structuring_threshold_attempts: 4 (synthetic smurfing pattern: >=4 rapid transfers)
    - structuring_threshold_amount_paise: 3,000,000 paise (Rs. 30,000 synthetic structuring aggregate)
    - rolling_window_minutes: 60 (1-hour rolling observation window)

    WARNING: These thresholds are strictly for synthetic laboratory evaluation;
    NOT an approved production policy.
    """
    return SyntheticVelocityThresholds(
        structuring_threshold_attempts=4,
        structuring_threshold_amount_paise=3000000,
        rolling_window_minutes=60,
    )


class PolicyCPauseGuard(BasePolicy):
    """Policy C — Profile-aware PauseGuard policy.

    Implements the authoritative profile-aware decision matrix from docs/POLICY_MATRIX_V2.md.
    Combines behavioral baseline deviation, recipient familiarity, velocity structuring,
    and transcript coercion indicators with customer profile context.

    Profile-Awareness:
    - Personal: low baseline (₹400 - ₹1,500). High deviation (>5x) to a new payee triggers friction.
    - Business (professional, small_business, enterprise): high baseline (₹15,000 - ₹1Cr).
      Routine new supplier payments (1x-3x) are NOT flagged, minimizing business disruption.
    - Coercion transcripts, prompt injection, or structuring velocity trigger Tier 3 restrictions.
    """

    def __init__(
        self,
        scoring_config: Optional[AdvisoryScoringConfig] = None,
        personal_deviation_threshold: float = 5.0,
        business_deviation_threshold: float = 10.0,
        synthetic_velocity_thresholds: Optional[SyntheticVelocityThresholds] = None,
    ):
        self._scoring_config = scoring_config
        self._personal_deviation_threshold = personal_deviation_threshold
        self._business_deviation_threshold = business_deviation_threshold
        self._synthetic_velocity_thresholds = synthetic_velocity_thresholds

    @property
    def name(self) -> str:
        return "Policy C (Profile-Aware PauseGuard)"

    @property
    def is_available(self) -> bool:
        return self._scoring_config is not None

    @property
    def scoring_config(self) -> Optional[AdvisoryScoringConfig]:
        return self._scoring_config

    @property
    def synthetic_velocity_thresholds(self) -> Optional[SyntheticVelocityThresholds]:
        return self._synthetic_velocity_thresholds

    def evaluate_velocity_signal(self, features: ScenarioFeatures) -> VelocitySignal:
        """Evaluate velocity structuring signal safely without fabricating unknown classifications."""
        vel_ctx: Optional[VelocityContext] = None
        if (
            features.recent_attempts_in_window is not None
            and features.recent_amount_paise_in_window is not None
        ):
            thresh_attempts = None
            thresh_amount = None
            window_minutes = 60
            if self._synthetic_velocity_thresholds is not None:
                thresh_attempts = self._synthetic_velocity_thresholds.structuring_threshold_attempts
                thresh_amount = self._synthetic_velocity_thresholds.structuring_threshold_amount_paise
                window_minutes = self._synthetic_velocity_thresholds.rolling_window_minutes

            vel_ctx = VelocityContext(
                rolling_window_minutes=window_minutes,
                attempts_in_window=features.recent_attempts_in_window,
                total_amount_paise_in_window=features.recent_amount_paise_in_window,
                structuring_threshold_attempts=thresh_attempts,
                structuring_threshold_amount_paise=thresh_amount,
            )

        return evaluate_velocity(vel_ctx).signal

    def evaluate(self, features: ScenarioFeatures) -> PolicyDecision:
        if not self.is_available or self._scoring_config is None:
            raise ValueError(
                "Policy C is unconfigured: requires an explicit scoring_config "
                "(e.g. get_default_scoring_config() for synthetic benchmarking)."
            )

        # 1. Transcript Coercion Evaluation
        transcript_signal = evaluate_transcript(
            transcript_text=features.transcript_text,
            transcript_consented=features.transcript_consented,
        ).signal

        if transcript_signal.status == "evaluated":
            if transcript_signal.coercion_detected:
                return PolicyDecision(
                    flagged=True,
                    tier=3,
                    policy_name=self.name,
                    reason="coercion_detected_in_transcript",
                    metadata={"indicators": list(transcript_signal.coercion_indicators)},
                )
            if transcript_signal.suspected_prompt_injection:
                return PolicyDecision(
                    flagged=True,
                    tier=3,
                    policy_name=self.name,
                    reason="prompt_injection_suspected_in_transcript",
                    metadata={},
                )

        # 2. Velocity Structuring Evaluation
        velocity_signal = self.evaluate_velocity_signal(features)

        if velocity_signal.status == "evaluated" and velocity_signal.structuring_suspected is True:
            return PolicyDecision(
                flagged=True,
                tier=3,
                policy_name=self.name,
                reason="velocity_structuring_suspected",
                metadata={
                    "attempts": features.recent_attempts_in_window,
                    "total_amount_paise": features.recent_amount_paise_in_window,
                    "structuring_suspected": True,
                },
            )

        # 3. Behavioral Baseline & Profile-Aware Deviation
        is_business = features.profile_type in (
            AccountProfileType.PROFESSIONAL.value,
            AccountProfileType.SMALL_BUSINESS.value,
            AccountProfileType.ENTERPRISE.value,
        )

        deviation = None
        if features.payer_baseline_median_paise and features.payer_baseline_median_paise > 0:
            deviation = round(features.amount_paise / features.payer_baseline_median_paise, 2)

        if is_business:
            # Business Profile: Routine new supplier payments are normal.
            # Only extreme anomalous deviation (>= 10x) triggers intervention.
            if deviation is not None and deviation >= self._business_deviation_threshold:
                return PolicyDecision(
                    flagged=True,
                    tier=2,
                    policy_name=self.name,
                    reason="business_anomalous_deviation",
                    metadata={
                        "deviation_multiple": deviation,
                        "profile_type": features.profile_type,
                        "structuring_suspected": velocity_signal.structuring_suspected,
                    },
                )
            return PolicyDecision(
                flagged=False,
                tier=0,
                policy_name=self.name,
                reason="business_routine_supplier_payment",
                metadata={
                    "deviation_multiple": deviation,
                    "profile_type": features.profile_type,
                    "structuring_suspected": velocity_signal.structuring_suspected,
                },
            )
        else:
            # Personal Profile:
            # High deviation (>= 5x) combined with new beneficiary triggers intervention.
            # Extreme deviation (>= 10x) always triggers intervention.
            if deviation is not None:
                if deviation >= 10.0:
                    return PolicyDecision(
                        flagged=True,
                        tier=2,
                        policy_name=self.name,
                        reason="personal_extreme_deviation",
                        metadata={
                            "deviation_multiple": deviation,
                            "profile_type": features.profile_type,
                            "structuring_suspected": velocity_signal.structuring_suspected,
                        },
                    )
                if deviation >= self._personal_deviation_threshold and features.is_new_beneficiary:
                    return PolicyDecision(
                        flagged=True,
                        tier=2,
                        policy_name=self.name,
                        reason="personal_high_deviation_new_payee",
                        metadata={
                            "deviation_multiple": deviation,
                            "profile_type": features.profile_type,
                            "structuring_suspected": velocity_signal.structuring_suspected,
                        },
                    )

            return PolicyDecision(
                flagged=False,
                tier=0,
                policy_name=self.name,
                reason="personal_within_baseline",
                metadata={
                    "deviation_multiple": deviation,
                    "profile_type": features.profile_type,
                    "structuring_suspected": velocity_signal.structuring_suspected,
                },
            )


@dataclass(frozen=True)
class PolicyLabReport:
    """Structured, reproducible comparison report generated by Policy Lab."""
    seed: int
    dataset_split: str
    total_scenarios_evaluated: int
    category_counts: dict[str, int]
    profile_counts: dict[str, int]
    policy_metrics: dict[str, PolicyEvaluationMetrics]
    scam_category_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    tier_distribution: dict[str, dict[str, int]] = field(default_factory=dict)
    is_synthetic: bool = True
    declaration: str = (
        "PauseGuard Policy Lab synthetic benchmark evaluation. "
        "Strictly evaluated on held-out test split with zero payer leakage."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "dataset_split": self.dataset_split,
            "total_scenarios_evaluated": self.total_scenarios_evaluated,
            "category_counts": self.category_counts,
            "profile_counts": self.profile_counts,
            "policy_metrics": {k: v.to_dict() for k, v in self.policy_metrics.items()},
            "scam_category_breakdown": self.scam_category_breakdown,
            "tier_distribution": self.tier_distribution,
            "is_synthetic": self.is_synthetic,
            "declaration": self.declaration,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class PolicyLab:
    """Benchmark runner for evaluating and comparing fraud policies."""

    @classmethod
    def run_comparison(
        cls,
        scenarios: list[SyntheticPaymentScenario],
        policies: Optional[list[BasePolicy]] = None,
        seed: int = 42,
        split: str = "test",
    ) -> PolicyLabReport:
        """Run policy comparison benchmark exclusively on the held-out test split.

        Guarantees:
        - Evaluates strictly on splits.test (rejects non-test splits).
        - Verifies zero payer leakage across partitions.
        - Passes only ScenarioFeatures to each policy (zero ground-truth leakage).
        - Fully reproducible given the same dataset and seed.

        Args:
            scenarios: Complete list of SyntheticPaymentScenario instances.
            policies: List of BasePolicy instances to evaluate. If None, default
                      candidates with explicit synthetic configs are instantiated.
            seed: Random seed used for data splitting and reproducibility.
            split: Must be 'test' to enforce held-out evaluation.

        Returns:
            PolicyLabReport with complete metrics, rates, and comparisons.
        """
        if split != "test":
            raise ValueError(
                f"Policy Lab evaluation strictly requires split='test' (got {split!r}). "
                "Training and validation splits must not be used for final policy metrics."
            )

        if not scenarios:
            raise ValueError("Cannot run Policy Lab comparison on an empty scenario list")

        # Split dataset and enforce anti-leakage invariants
        dataset_splits: DatasetSplits = split_dataset(
            scenarios=scenarios,
            train_ratio=0.70,
            val_ratio=0.15,
            test_ratio=0.15,
            seed=seed,
        )

        test_scenarios = dataset_splits.test
        if not test_scenarios:
            raise ValueError("Test split resulted in 0 scenarios; cannot evaluate")

        # Zero payer leakage assertion
        train_payers = {s.payer_id for s in dataset_splits.train}
        val_payers = {s.payer_id for s in dataset_splits.val}
        test_payers = {s.payer_id for s in dataset_splits.test}

        if train_payers & test_payers or val_payers & test_payers:
            raise RuntimeError("Payer leakage detected between train/val and test splits!")

        # Default policy candidates if none provided
        if policies is None:
            policies = [
                BaselineAPolicy(threshold_paise=1000000),  # ₹10,000 explicit threshold
                BaselineBPolicy(),
                PolicyCPauseGuard(
                    scoring_config=get_default_scoring_config(),
                    synthetic_velocity_thresholds=get_default_synthetic_velocity_thresholds(),
                ),
            ]

        # Extract features and targets separately to enforce anti-leakage
        extracted_features = [s.to_features() for s in test_scenarios]
        ground_truth_labels = [s.ground_truth_label for s in test_scenarios]
        profile_types = [s.profile_type for s in test_scenarios]

        category_counts = dict(Counter(s.category.value for s in test_scenarios))
        profile_counts = dict(Counter(s.profile_type for s in test_scenarios))

        policy_metrics: dict[str, PolicyEvaluationMetrics] = {}
        tier_distribution: dict[str, dict[str, int]] = {}
        scam_category_breakdown: dict[str, dict[str, Any]] = {
            cat: {"total": count, "policies": {}}
            for cat, count in sorted(category_counts.items())
        }

        for pol in policies:
            if not pol.is_available:
                raise ValueError(
                    f"Policy {pol.name!r} is unconfigured. "
                    "All evaluated policies must be explicitly configured."
                )

            # Evaluate each scenario strictly using features only
            decisions = [pol.evaluate(feat) for feat in extracted_features]
            predictions = [d.flagged for d in decisions]
            tiers = [d.tier for d in decisions]

            metrics = calculate_evaluation_metrics(
                policy_name=pol.name,
                predictions=predictions,
                ground_truth_labels=ground_truth_labels,
                profile_types=profile_types,
                tiers=tiers,
            )
            policy_metrics[pol.name] = metrics

            tier_counts = Counter(tiers)
            tier_distribution[pol.name] = {
                "tier_0": int(tier_counts.get(0, 0)),
                "tier_1": int(tier_counts.get(1, 0)),
                "tier_2": int(tier_counts.get(2, 0)),
                "tier_3": int(tier_counts.get(3, 0)),
            }

            for cat in scam_category_breakdown:
                cat_flagged = sum(
                    1
                    for s, pred in zip(test_scenarios, predictions)
                    if s.category.value == cat and pred
                )
                cat_total = scam_category_breakdown[cat]["total"]
                scam_category_breakdown[cat]["policies"][pol.name] = {
                    "flagged_count": cat_flagged,
                    "flag_rate": round(cat_flagged / cat_total, 4) if cat_total > 0 else None,
                }

        return PolicyLabReport(
            seed=seed,
            dataset_split="test",
            total_scenarios_evaluated=len(test_scenarios),
            category_counts=category_counts,
            profile_counts=profile_counts,
            policy_metrics=policy_metrics,
            scam_category_breakdown=scam_category_breakdown,
            tier_distribution=tier_distribution,
            is_synthetic=True,
        )
