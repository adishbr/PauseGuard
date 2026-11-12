"""FastAPI router for Policy Lab synthetic policy evaluation and comparative benchmarking.

Endpoints:
- POST /policy-lab/simulate: Run benchmark comparing Baseline A, Baseline B, and PauseGuard Policy C.
"""

from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_actor
from app.auth.schemas import PolicyLabSimulateRequest
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext
from intelligence.policy_lab.policy_evaluator import PolicyLab
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

    scenarios = generate_scenario_dataset(
    seed=request.seed,
    count_per_category=max(1, (request.sample_size + 5) // 6),
)
    
    report = PolicyLab.run_comparison(
        scenarios=scenarios,
        seed=request.seed,
        split="test",
    )
    return report.to_dict()

