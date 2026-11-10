"""Process health only; no persistence or payment readiness claim."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["mock"] = "mock"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
