"""Typed input and output structures for the Advisory Orchestrator.

Provides frozen dataclasses for type-safe, validated request/response
handling without untyped dictionaries.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Optional

from intelligence.schemas.risk_signals import (
    AccountProfileType,
    RiskSignals,
)
from intelligence.behavioral.baseline_evaluator import PayerHistoryProfile
from intelligence.mule_graph.graph_proximity import SyntheticTransactionGraph


@dataclass(frozen=True)
class VelocityContext:
    """Optional velocity measurement context from backend."""

    rolling_window_minutes: int
    attempts_in_window: int
    total_amount_paise_in_window: int
    structuring_threshold_attempts: Optional[int] = None
    structuring_threshold_amount_paise: Optional[int] = None

    def __post_init__(self):
        # Strict integer check rejecting booleans for required measurement fields
        for field_name in (
            "rolling_window_minutes",
            "attempts_in_window",
            "total_amount_paise_in_window",
        ):
            val = getattr(self, field_name)
            if type(val) is bool or not isinstance(val, int):
                raise ValueError(f"{field_name} must be a strict integer; booleans/floats are rejected")

        if self.rolling_window_minutes < 1 or self.rolling_window_minutes > 1440:
            raise ValueError("rolling_window_minutes must be between 1 and 1440")
        if self.attempts_in_window < 0:
            raise ValueError("attempts_in_window must be non-negative")
        if self.total_amount_paise_in_window < 0:
            raise ValueError("total_amount_paise_in_window must be non-negative")

        # Strict integer check rejecting booleans for optional threshold fields
        for field_name in (
            "structuring_threshold_attempts",
            "structuring_threshold_amount_paise",
        ):
            val = getattr(self, field_name)
            if val is not None:
                if type(val) is bool or not isinstance(val, int):
                    raise ValueError(f"{field_name} must be a strict integer if provided; booleans/floats are rejected")

        if self.structuring_threshold_attempts is not None and self.structuring_threshold_attempts < 1:
            raise ValueError("structuring_threshold_attempts must be positive if provided")
        if self.structuring_threshold_amount_paise is not None and self.structuring_threshold_amount_paise < 1:
            raise ValueError("structuring_threshold_amount_paise must be positive if provided")


@dataclass(frozen=True)
class RegistryContext:
    """Optional registry lookup context from backend."""

    check_status: str
    flagged_beneficiaries: dict
    registry_category: Optional[str] = None

    def __post_init__(self):
        valid_statuses = ("performed", "unavailable", "bypassed_in_lab")
        if self.check_status not in valid_statuses:
            raise ValueError(f"check_status must be one of {valid_statuses}")


@dataclass(frozen=True)
class AdvisoryScoringConfig:
    """Injectable advisory scoring configuration.

    Allows backend or tests to supply aggregation weights and cutoffs without
    hardcoding production thresholds in the intelligence module.
    """

    behavioral_weight: float = 1.0
    velocity_weight: float = 1.0
    registry_weight: float = 2.0
    mule_graph_weight: float = 1.0
    transcript_weight: float = 1.5

    score_low_max: int = 25
    score_medium_max: int = 50
    score_high_max: int = 75

    def __post_init__(self):
        # Strict validation: weights must be non-boolean, finite, non-negative numbers
        weights = {
            "behavioral_weight": self.behavioral_weight,
            "velocity_weight": self.velocity_weight,
            "registry_weight": self.registry_weight,
            "mule_graph_weight": self.mule_graph_weight,
            "transcript_weight": self.transcript_weight,
        }
        for name, w in weights.items():
            if type(w) is bool or not isinstance(w, (int, float)):
                raise ValueError(f"{name} must be a finite number; booleans are rejected")
            if not math.isfinite(w):
                raise ValueError(f"{name} must be a finite number (got {w})")
            if w < 0.0 or w > 10.0:
                raise ValueError(f"{name} must be non-negative and within [0.0, 10.0]")

        # Strict validation: cutoffs must be strict non-boolean integers
        cutoffs = {
            "score_low_max": self.score_low_max,
            "score_medium_max": self.score_medium_max,
            "score_high_max": self.score_high_max,
        }
        for name, c in cutoffs.items():
            if type(c) is bool or not isinstance(c, int):
                raise ValueError(f"{name} must be a strict integer; booleans/floats are rejected")

        if not (0 <= self.score_low_max <= self.score_medium_max <= self.score_high_max <= 100):
            raise ValueError("Score cutoffs must satisfy: 0 <= low <= medium <= high <= 100")


def get_default_scoring_config() -> AdvisoryScoringConfig:
    """Return a synthetic-only default scoring configuration for test harnesses.

    Explicitly labelled as synthetic to prevent production use.
    """
    return AdvisoryScoringConfig()


@dataclass(frozen=True)
class AdvisoryRequest:
    """Typed input for unified advisory evaluation.

    Compatible with future Komal backend integration.
    """

    payment_id: str
    payer_id: str
    beneficiary_id: str
    amount_paise: int

    profile: Optional[PayerHistoryProfile] = None
    transaction_graph: Optional[SyntheticTransactionGraph] = None
    velocity_context: Optional[VelocityContext] = None
    registry_context: Optional[RegistryContext] = None
    transcript_text: Optional[str] = None
    transcript_consented: bool = False
    scoring_config: Optional[AdvisoryScoringConfig] = None

    def __post_init__(self):
        if not self.payment_id:
            raise ValueError("payment_id is required")
        if not self.payer_id:
            raise ValueError("payer_id is required")
        if not self.beneficiary_id:
            raise ValueError("beneficiary_id is required")
        if not isinstance(self.amount_paise, int) or isinstance(self.amount_paise, bool):
            raise ValueError("amount_paise must be a strict integer; booleans are rejected")
        if self.amount_paise <= 0:
            raise ValueError("amount_paise must be strictly positive (> 0 paise)")

        if self.profile is not None and self.profile.profile_type not in AccountProfileType:
            raise ValueError(f"Invalid profile_type: {self.profile.profile_type}")


@dataclass(frozen=True)
class AdvisoryResponse:
    """Typed output wrapping validated RiskSignals with execution metadata."""

    risk_signals: RiskSignals
    evaluator_timings_ms: dict[str, float]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.risk_signals, RiskSignals):
            raise ValueError("risk_signals must be a RiskSignals instance")
        if not all(isinstance(v, (int, float)) and v >= 0 for v in self.evaluator_timings_ms.values()):
            raise ValueError("All evaluator_timings_ms values must be non-negative numbers")
