"""FastAPI router for account balance and ledger inspection.

Endpoints:
- GET /account/balance: Retrieve current mock account balance and ledger count for authenticated user.
"""

from typing import Annotated, Any
from fastapi import APIRouter, Depends, status

from app.api.payments import get_payment_engine
from app.auth.dependencies import get_current_actor
from app.auth.schemas import AccountBalanceResponse
from app.services.payment_guards import TrustedActorContext

router = APIRouter(prefix="/api/v2/account", tags=["account"])


@router.get("/balance", response_model=AccountBalanceResponse, status_code=status.HTTP_200_OK)
def get_account_balance(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> AccountBalanceResponse:
    """Retrieve current mock account balance and ledger entry count for authenticated user."""
    balance_paise, ledger_count = engine.get_account_balance_info(actor.user_id)
    return AccountBalanceResponse(
        user_id=actor.user_id,
        balance_paise=balance_paise,
        currency="INR",
        ledger_entries_count=ledger_count,
    )

