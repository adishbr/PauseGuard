"""Dependency-injected Member 4 purpose helper; advisory only, no raw reason codes."""

from dataclasses import dataclass
from typing import Literal, Protocol


class PurposeAssessment(Protocol):
    @property
    def suspicious(self) -> bool: ...


class PurposeAssessor(Protocol):
    def __call__(self, purpose: str) -> PurposeAssessment: ...


@dataclass(frozen=True)
class PurposeAdvice:
    suspicious: bool
    available: bool

    @property
    def can_authorize_payment(self) -> Literal[False]:
        return False


def purpose_advice(purpose: str, *, assessor: PurposeAssessor) -> PurposeAdvice:
    """Inject safety.purpose_challenge.assess_purpose; never wire it to approval.

    Helper unavailability is explicitly cautious. Helper reason strings stay in
    the owning module until reviewed canonical reason mapping is agreed.
    """
    try:
        suspicious = assessor(purpose).suspicious
        if type(suspicious) is not bool:
            return PurposeAdvice(suspicious=True, available=False)
        return PurposeAdvice(suspicious=suspicious, available=True)
    except Exception:
        return PurposeAdvice(suspicious=True, available=False)
