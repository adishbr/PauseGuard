"""FastAPI router for Policy Lab synthetic policy evaluation and comparative benchmarking.

Endpoints:
- POST /policy-lab/simulate: Run benchmark comparing Baseline A, Baseline B, and PauseGuard Policy C.
"""

import time
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_actor
from app.auth.schemas import PolicyLabSimulateRequest
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext
from intelligence.advisory.types import get_default_scoring_config
from intelligence.policy_lab.policy_evaluator import (
    BaselineAPolicy,
    BaselineBPolicy,
    PolicyCPauseGuard,
    PolicyLab,
    get_default_synthetic_velocity_thresholds,
)
from synthetic_data.generator import generate_scenario_dataset

router = APIRouter(prefix="/api/v2/policy-lab", tags=["policy-lab"])


@router.post("/simulate", response_model=dict[str, Any], status_code=status.HTTP_200_OK)
def simulate_policy_benchmark(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PolicyLabSimulateRequest,
) -> dict[str, Any]:
    """Execute reproducible Policy Lab simulation benchmark across fraud defense policies.

    Enforces:
    - Exclusive evaluation on held-out test split.
    - Zero payer overlap or feature leakage.
    - Analyst or Admin role authorization.
    """
    if UserRole.ANALYST not in actor.roles and UserRole.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only analysts and administrators can execute Policy Lab benchmarks",
        )

    started = time.perf_counter()
    scenarios = generate_scenario_dataset(
        seed=request.seed,
        count_per_category=max(1, (request.sample_size + 5) // 6),
    )

    policies = [
        BaselineAPolicy(threshold_paise=request.baseline_a_threshold_paise),
        BaselineBPolicy(),
        PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            personal_deviation_threshold=request.personal_deviation_threshold,
            business_deviation_threshold=request.business_deviation_threshold,
            synthetic_velocity_thresholds=get_default_synthetic_velocity_thresholds(),
        ),
    ]

    report = PolicyLab.run_comparison(
        scenarios=scenarios,
        policies=policies,
        seed=request.seed,
        split="test",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    payload = report.to_dict()
    payload["evaluation_latency_ms"] = elapsed_ms
    payload["calibration"] = {
        "baseline_a_threshold_paise": request.baseline_a_threshold_paise,
        "personal_deviation_threshold": request.personal_deviation_threshold,
        "business_deviation_threshold": request.business_deviation_threshold,
    }
    return payload
