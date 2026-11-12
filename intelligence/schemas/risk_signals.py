"""Typed advisory RiskSignals contract for PauseGuard V2 (Revision 2 - Validated).

This module defines the structured advisory payload returned by Member 3's
intelligence service. It is consumed by Komal's authoritative backend policy.
Advisory compute CANNOT authorize, reject, or execute payments.
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Annotated, Any, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    NonNegativeInt,
    PositiveInt,
)


class SourceCategory(str, Enum):
    """High-level classification of evidence origin."""
    USER_CLAIM = "user_claim"
    TRUSTED_SOURCE = "trusted_source"
    MODEL_INFERENCE = "model_inference"


class DataOrigin(str, Enum):
    """Specific system or fixture from which input data was acquired."""
    USER_INPUT = "user_input"
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    MOCK_LEDGER_HISTORY = "mock_ledger_history"
    CONSENTED_AUDIO_TRANSCRIPT = "consented_audio_transcript"
    MOCK_REGISTRY_TABLE = "mock_registry_table"
    UNAVAILABLE = "unavailable"


class CalculationMethod(str, Enum):
    """Algorithmic technique used to compute the signal."""
    DETERMINISTIC_LOOKUP = "deterministic_lookup"
    STATISTICAL_BASELINE = "statistical_baseline"
    HEURISTIC_RULE_ENGINE = "heuristic_rule_engine"
    GRAPH_TRAVERSAL = "graph_traversal"
    NLP_REGEX_COERCION = "nlp_regex_coercion"
    UNPERFORMED = "unperformed"


class AccountProfileType(str, Enum):
    """Payer profile category under evaluation."""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    SMALL_BUSINESS = "small_business"
    ENTERPRISE = "enterprise"


class EvaluationStatus(str, Enum):
    """Execution status of the advisory pipeline."""
    COMPLETE = "complete"
    DEGRADED = "degraded"
    TIMEOUT = "timeout"
    MISSING_INPUTS = "missing_inputs"


class SuggestedCautionLevel(str, Enum):
    """Advisory caution level for the deterministic policy."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SignalProvenance(BaseModel):
    """Explicit provenance metadata attached to every signal."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_category: SourceCategory
    data_origin: DataOrigin
    calculation_method: CalculationMethod
    is_synthetic: bool = Field(
        default=True,
        description="True for all lab prototype data; prevents claiming real-world origin.",
    )


class BehavioralSignal(BaseModel):
    """Deviation of transaction from verified profile baseline."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["evaluated", "uninitialized", "unavailable"]
    profile_type: AccountProfileType | None = Field(
        default=None,
        description="None if profile is unknown or unverified.",
    )
    baseline_median_paise: NonNegativeInt | None = Field(
        default=None,
        description="Payer's established median payment in paise. None if baseline is uninitialized.",
    )
    deviation_multiple: Annotated[float, Field(ge=0.0)] | None = Field(
        default=None,
        description="Multiple of baseline median (amount / baseline_median). None if no baseline.",
    )
    is_new_beneficiary: bool | None = Field(
        default=None,
        description="None if payee history is unavailable.",
    )
    prior_transfers_count: NonNegativeInt | None = Field(
        default=None,
        description="Prior settled transfers count to this recipient. None if history unavailable.",
    )
    provenance: SignalProvenance

    @model_validator(mode="after")
    def validate_behavioral_consistency(self) -> "BehavioralSignal":
        if self.status in ("uninitialized", "unavailable"):
            if self.baseline_median_paise is not None:
                raise ValueError(f"baseline_median_paise must be None when status is '{self.status}'.")
            if self.deviation_multiple is not None:
                raise ValueError(f"deviation_multiple must be None when status is '{self.status}'.")
            if self.is_new_beneficiary is not None:
                raise ValueError(f"is_new_beneficiary must be None when status is '{self.status}'.")
            if self.prior_transfers_count is not None:
                raise ValueError(f"prior_transfers_count must be None when status is '{self.status}'.")
        return self


class VelocitySignal(BaseModel):
    """Short-term frequency and structuring (smurfing) indicators."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["evaluated", "unavailable"]
    rolling_window_minutes: Annotated[int, Field(ge=1, le=1440)] | None = Field(
        default=None,
        description="Lookback window duration in minutes. None if velocity service unavailable.",
    )
    attempts_in_window: NonNegativeInt | None = Field(
        default=None,
        description="Attempts in window. None if velocity service unavailable.",
    )
    total_amount_paise_in_window: NonNegativeInt | None = Field(
        default=None,
        description="Cumulative amount in paise. None if velocity service unavailable.",
    )
    structuring_suspected: bool | None = Field(
        default=None,
        description="Advisory signal for smurfing. None if velocity service unavailable.",
    )
    provenance: SignalProvenance

    @model_validator(mode="after")
    def validate_velocity_consistency(self) -> "VelocitySignal":
        if self.status == "unavailable":
            if any(v is not None for v in (
                self.rolling_window_minutes,
                self.attempts_in_window,
                self.total_amount_paise_in_window,
                self.structuring_suspected,
            )):
                raise ValueError("All measured velocity fields must be None when status is 'unavailable'.")
        elif self.status == "evaluated":
            if self.attempts_in_window is None or self.total_amount_paise_in_window is None:
                raise ValueError("attempts_in_window and total_amount_paise_in_window must be provided when status is 'evaluated'.")
        return self


class RegistrySignal(BaseModel):
    """Deterministic lookup against verified mock high-risk beneficiaries."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_status: Literal["performed", "unavailable", "bypassed_in_lab"]
    is_listed_high_risk: bool | None = Field(
        default=None,
        description="True/False if lookup succeeded; None if check_status != 'performed'.",
    )
    registry_category: str | None = Field(
        default=None,
        description="Category if listed (e.g., 'confirmed_mule', 'impersonation_scam').",
    )
    provenance: SignalProvenance

    @model_validator(mode="after")
    def validate_registry_consistency(self) -> "RegistrySignal":
        if self.check_status == "performed":
            if self.is_listed_high_risk is None:
                raise ValueError("is_listed_high_risk must be True or False when registry check_status is 'performed'.")
        elif self.check_status in ("unavailable", "bypassed_in_lab"):
            if self.is_listed_high_risk is not None:
                raise ValueError(
                    f"is_listed_high_risk must be None when check_status is '{self.check_status}'. Cannot claim a negative match."
                )
            if self.registry_category is not None:
                raise ValueError(f"registry_category must be None when check_status is '{self.check_status}'.")
        return self


class MuleGraphSignal(BaseModel):
    """Proximity to synthetic mule accounts in network graph."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["evaluated", "unperformed", "unavailable"]
    in_degree_incoming_unique_payers: NonNegativeInt | None = Field(
        default=None,
        description="Recent unique payer count. None if unperformed or unavailable.",
    )
    hop_distance_to_flagged_mule: Annotated[int, Field(ge=0)] | None = Field(
        default=None,
        description="Shortest hop distance to mule node. None if no path or unavailable.",
    )
    cluster_risk_score: Annotated[int, Field(ge=0, le=100)] | None = Field(
        default=None,
        description="Synthetic graph community risk index. None if unperformed or unavailable.",
    )
    provenance: SignalProvenance

    @model_validator(mode="after")
    def validate_graph_consistency(self) -> "MuleGraphSignal":
        if self.status in ("unperformed", "unavailable"):
            if any(v is not None for v in (
                self.in_degree_incoming_unique_payers,
                self.hop_distance_to_flagged_mule,
                self.cluster_risk_score,
            )):
                raise ValueError(f"All graph metric fields must be None when mule_graph status is '{self.status}'.")
        elif self.status == "evaluated":
            if self.cluster_risk_score is None:
                raise ValueError("cluster_risk_score must be provided when mule_graph status is 'evaluated'.")
        return self


class TranscriptCoercionSignal(BaseModel):
    """Analysis of explicitly provided, consented call transcript or message."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["evaluated", "unconsented", "absent", "unavailable"]
    coercion_detected: bool | None = Field(
        default=None,
        description="None if status != 'evaluated'.",
    )
    coercion_indicators: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Detected categories (e.g., 'urgency', 'authority_impersonation', 'secrecy').",
    )
    suspected_prompt_injection: bool | None = Field(
        default=None,
        description="None if transcript was not evaluated; True/False if evaluated.",
    )
    provenance: SignalProvenance

    @model_validator(mode="after")
    def validate_transcript_consistency(self) -> "TranscriptCoercionSignal":
        if self.status != "evaluated":
            if self.coercion_detected is not None:
                raise ValueError(
                    f"coercion_detected must be None when transcript status is '{self.status}'. Cannot claim analyzed results."
                )
            if self.suspected_prompt_injection is not None:
                raise ValueError(
                    f"suspected_prompt_injection must be None when transcript status is '{self.status}'. Cannot claim analyzed results."
                )
            if len(self.coercion_indicators) > 0:
                raise ValueError(f"coercion_indicators must be empty when transcript status is '{self.status}'.")
        else:
            if self.coercion_detected is None:
                raise ValueError("coercion_detected must be True or False when transcript status is 'evaluated'.")
            if self.suspected_prompt_injection is None:
                raise ValueError("suspected_prompt_injection must be True or False when transcript status is 'evaluated'.")
        return self


class RiskSignals(BaseModel):
    """Canonical V2 advisory risk envelope.

    Produced by Member 3's intelligence service and consumed by Member 1's backend.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Contract metadata
    schema_version: Literal["2.0.0"] = "2.0.0"
    data_environment: Literal["synthetic_lab", "verified_production"] = Field(
        default="synthetic_lab",
        description="Declaration of runtime environment. Always synthetic_lab for PauseGuard prototype.",
    )
    model_name: str = Field(
        default="pauseguard-heuristics-engine",
        description="Identifier of the evaluator engine.",
    )
    model_version: str = Field(
        default="0.1.0-alpha",
        description="SemVer of the evaluator ruleset/model.",
    )
    generated_at: datetime = Field(
        description="Timezone-aware UTC timestamp of evaluation generation.",
    )
    evaluation_latency_ms: Annotated[float, Field(ge=0.0)] = Field(
        description="Execution wall-clock latency in milliseconds.",
    )
    evaluation_status: EvaluationStatus = Field(
        description="Operational state of the intelligence pipeline.",
    )
    degraded_reasons: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Explicit diagnostic reasons when evaluation_status != COMPLETE.",
    )

    # Context identifiers
    payment_id: str = Field(
        description="Namespaced payment identifier under evaluation (e.g., 'pg_...')."
    )
    payer_id: str = Field(
        description="Pseudonymous payer identifier."
    )
    beneficiary_id: str = Field(
        description="Pseudonymous beneficiary identifier."
    )
    amount_paise: PositiveInt = Field(
        description="Requested transaction amount in integer paise."
    )

    # Core Advisory Signals
    advisory_score: Annotated[int, Field(ge=0, le=100)] | None = Field(
        default=None,
        description="Composite heuristic risk index (0-100). None if evaluation is degraded/unavailable.",
    )
    calibrated_fraud_probability: Annotated[float, Field(ge=0.0, le=1.0)] | None = Field(
        default=None,
        description="Statistical posterior probability. MUST be None for synthetic models.",
    )
    calibration_caveat: str = Field(
        default="Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
        description="Mandatory caveat preventing inflated efficacy claims.",
    )
    suggested_caution_level: SuggestedCautionLevel | None = Field(
        default=None,
        description="Advisory caution suggestion. None if evaluation is degraded/unavailable.",
    )
    reason_codes: tuple[str, ...] = Field(
        description="Normalized reason codes explaining the advisory evaluation.",
    )

    # Sub-signal components
    behavioral: BehavioralSignal
    velocity: VelocitySignal
    registry: RegistrySignal
    mule_graph: MuleGraphSignal
    transcript: TranscriptCoercionSignal

    # MANDATORY SECURITY INVARIANTS
    can_authorize_payment: Literal[False] = Field(
        default=False,
        description="Security invariant: AI advisory signals can never authorize payment.",
    )
    can_execute_payment: Literal[False] = Field(
        default=False,
        description="Security invariant: AI advisory signals can never execute payment.",
    )
    advisory_only: Literal[True] = Field(
        default=True,
        description="Explicit flag declaring this payload as non-authoritative compute.",
    )

    @field_validator("amount_paise", mode="before")
    @classmethod
    def validate_amount_paise_strict(cls, v: Any) -> int:
        """Reject booleans, floats, strings, zero, and negative values."""
        if isinstance(v, bool):
            raise ValueError("amount_paise must be a strict integer; booleans are rejected.")
        if not isinstance(v, int):
            raise ValueError("amount_paise must be a strict integer; floats and strings are rejected.")
        if v <= 0:
            raise ValueError("amount_paise must be strictly positive (> 0 paise).")
        return v

    @field_validator("generated_at", mode="after")
    @classmethod
    def validate_and_normalize_utc(cls, v: datetime) -> datetime:
        """Enforce timezone awareness, reject naive datetime, and normalize to UTC."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "generated_at must be timezone-aware (rejecting naive datetime)."
            )
        normalized = v.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if normalized > now_utc + timedelta(minutes=5):
            raise ValueError(
                "generated_at cannot be in the future beyond acceptable clock skew."
            )
        return normalized

    @model_validator(mode="after")
    def validate_risk_signals_envelope(self) -> "RiskSignals":
        """Enforce synthetic calibration, degraded consistency, and registry priority."""
        # 1. Synthetic calibration enforcement
        if self.data_environment == "synthetic_lab":
            if self.calibrated_fraud_probability is not None:
                raise ValueError(
                    "calibrated_fraud_probability must be None in synthetic_lab environment."
                )
            if not self.calibration_caveat.strip():
                raise ValueError("calibration_caveat must not be empty.")

        # 2. Degraded evaluation consistency
        if self.evaluation_status in (
            EvaluationStatus.DEGRADED,
            EvaluationStatus.TIMEOUT,
            EvaluationStatus.MISSING_INPUTS,
        ):
            if self.advisory_score is not None:
                raise ValueError(
                    f"advisory_score must be None when evaluation_status is '{self.evaluation_status.value}'."
                )
            if self.suggested_caution_level is not None:
                raise ValueError(
                    f"suggested_caution_level must be None when evaluation_status is '{self.evaluation_status.value}'."
                )
        elif self.evaluation_status == EvaluationStatus.COMPLETE:
            if self.advisory_score is None:
                raise ValueError("advisory_score must be provided when evaluation_status is 'complete'.")
            if self.suggested_caution_level is None:
                raise ValueError("suggested_caution_level must be provided when evaluation_status is 'complete'.")

        # 3. Registry priority: positive match cannot be overridden with low/medium caution
        if self.registry.is_listed_high_risk is True:
            if self.suggested_caution_level in (SuggestedCautionLevel.LOW, SuggestedCautionLevel.MEDIUM):
                raise ValueError(
                    "A confirmed high-risk registry hit cannot have low or medium caution level. Advisory signals cannot override registry hits."
                )

        # 4. Mandatory safety invariants defense-in-depth
        if self.can_authorize_payment is not False:
            raise ValueError("can_authorize_payment must be False.")
        if self.can_execute_payment is not False:
            raise ValueError("can_execute_payment must be False.")
        if self.advisory_only is not True:
            raise ValueError("advisory_only must be True.")

        return self


def make_degraded_advisory(
    payment_id: str,
    payer_id: str,
    beneficiary_id: str,
    amount_paise: int,
    degraded_reasons: tuple[str, ...],
    reason_codes: tuple[str, ...] = ("RC_ADVISORY_SCORE_UNAVAILABLE",),
) -> RiskSignals:
    """Build an honest degraded-mode advisory signal without fabricating scores."""
    return RiskSignals(
        schema_version="2.0.0",
        data_environment="synthetic_lab",
        model_name="pauseguard-heuristics-engine",
        model_version="0.1.0-alpha",
        generated_at=datetime.now(timezone.utc),
        evaluation_latency_ms=0.5,
        evaluation_status=EvaluationStatus.DEGRADED,
        degraded_reasons=degraded_reasons,
        payment_id=payment_id,
        payer_id=payer_id,
        beneficiary_id=beneficiary_id,
        amount_paise=amount_paise,
        advisory_score=None,
        calibrated_fraud_probability=None,
        calibration_caveat="Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
        suggested_caution_level=None,
        reason_codes=reason_codes,
        behavioral=BehavioralSignal(
            status="uninitialized",
            profile_type=None,
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
        ),
        velocity=VelocitySignal(
            status="unavailable",
            rolling_window_minutes=None,
            attempts_in_window=None,
            total_amount_paise_in_window=None,
            structuring_suspected=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.TRUSTED_SOURCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        ),
        registry=RegistrySignal(
            check_status="unavailable",
            is_listed_high_risk=None,
            registry_category=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.TRUSTED_SOURCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        ),
        mule_graph=MuleGraphSignal(
            status="unavailable",
            in_degree_incoming_unique_payers=None,
            hop_distance_to_flagged_mule=None,
            cluster_risk_score=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        ),
        transcript=TranscriptCoercionSignal(
            status="absent",
            coercion_detected=None,
            coercion_indicators=(),
            suspected_prompt_injection=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        ),
        can_authorize_payment=False,
        can_execute_payment=False,
        advisory_only=True,
    )
