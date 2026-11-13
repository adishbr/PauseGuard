"""Provider-agnostic bank pre-execution & settlement interfaces with local MockBankRailAdapter.

SECURITY INVARIANTS:
1. MockBankRailAdapter is strictly for local/test mock mode and MUST fail closed in production or real mode.
2. External bank webhooks MUST pass constant-time HMAC-SHA256 verification and replay protection.
3. Bank settlement reconciliation NEVER bypasses PauseGuard's payment state machine; settlement
   cannot mark an unapproved or unconfirmed payment as settled.
4. Live NPCI/UPI bank integrations remain out of scope (RealBankRailStubAdapter fails closed).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import os
import secrets
from uuid import UUID


_LOCAL_DEFAULT_WEBHOOK_SECRET = "pg_local_mock_bank_webhook_secret_v5"


class BankAdapterError(RuntimeError):
    """Raised when a bank adapter operation violates mode, configuration, or security invariants."""


@dataclass(frozen=True)
class BankIntentResult:
    intent_id: str
    payment_id: str
    payer_id: UUID
    amount_paise: int
    rail: str
    adapter: str
    settlement_status: str
    is_mock: bool
    created_at: datetime


@dataclass(frozen=True)
class BankSettlementResult:
    event_id: str
    intent_id: str
    payment_id: str
    settlement_status: str
    duplicate: bool
    adapter: str


class PaymentIntentProvider(ABC):
    """Abstract pre-execution payment intent interface for bank/PSP rails."""

    @abstractmethod
    def create_intent(
        self,
        *,
        payment_id: str,
        payer_id: UUID,
        amount_paise: int,
        rail: str,
        settings: object | None = None,
    ) -> BankIntentResult:
        """Create a pre-execution hold/intent reference for an authorized payment."""


class PaymentExecutionProvider(ABC):
    """Abstract bank execution & settlement reconciliation provider."""

    @abstractmethod
    def verify_webhook_signature(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        settings: object | None = None,
    ) -> bool:
        """Verify inbound bank webhook signature using constant-time HMAC comparison."""


class BankAdapter(PaymentIntentProvider, PaymentExecutionProvider, ABC):
    """Combined banking rail adapter contract."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Stable identifier of the bank rail adapter."""


def _assert_mock_rail_allowed(settings: object | None) -> None:
    env = getattr(settings, "environment", "local")
    mode = getattr(settings, "mode", "mock")
    if env == "production" or mode != "mock":
        raise BankAdapterError(
            "MockBankRailAdapter is disabled outside local/test mock mode."
        )


def resolve_mock_bank_webhook_secret(settings: object | None = None) -> str:
    """Resolve mock bank webhook HMAC secret strictly in local/test mock mode."""
    _assert_mock_rail_allowed(settings)
    env_secret = os.environ.get("PAUSEGUARD_MOCK_BANK_WEBHOOK_SECRET", "").strip()
    return env_secret or _LOCAL_DEFAULT_WEBHOOK_SECRET


def compute_bank_webhook_hmac(raw_body: bytes, secret: str) -> str:
    """Compute lowercase hex HMAC-SHA256 signature for mock bank webhook payloads."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


class MockBankRailAdapter(BankAdapter):
    """Local synthetic pre-execution UPI/IMPS bank adapter (fail-closed outside mock mode)."""

    @property
    def adapter_name(self) -> str:
        return "mock_bank_rail"

    def create_intent(
        self,
        *,
        payment_id: str,
        payer_id: UUID,
        amount_paise: int,
        rail: str,
        settings: object | None = None,
    ) -> BankIntentResult:
        _assert_mock_rail_allowed(settings)
        if type(amount_paise) is bool or not isinstance(amount_paise, int) or amount_paise <= 0:
            raise ValueError("amount_paise must be a positive integer")
        return BankIntentResult(
            intent_id=f"bnk_int_{secrets.token_hex(8)}",
            payment_id=payment_id,
            payer_id=payer_id,
            amount_paise=amount_paise,
            rail=rail,
            adapter=self.adapter_name,
            settlement_status="HOLD_PENDING",
            is_mock=True,
            created_at=datetime.now(timezone.utc),
        )

    def verify_webhook_signature(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        settings: object | None = None,
    ) -> bool:
        _assert_mock_rail_allowed(settings)
        if not raw_body or not isinstance(signature_header, str):
            return False
        candidate = signature_header.strip().lower()
        if len(candidate) != 64:
            return False
        try:
            bytes.fromhex(candidate)
        except ValueError:
            return False
        secret = resolve_mock_bank_webhook_secret(settings)
        expected = compute_bank_webhook_hmac(raw_body, secret)
        return hmac.compare_digest(expected, candidate)


class RealBankRailStubAdapter(BankAdapter):
    """Fail-closed placeholder representing real regulated NPCI/bank endpoints (out of scope)."""

    @property
    def adapter_name(self) -> str:
        return "real_bank_unconfigured"

    def create_intent(self, **kwargs) -> BankIntentResult:
        raise BankAdapterError(
            "Live bank / NPCI UPI intent creation requires licensed partner onboarding and is not enabled."
        )

    def verify_webhook_signature(self, **kwargs) -> bool:
        return False
