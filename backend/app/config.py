"""Typed non-secret settings. This module never loads dotenv files."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigurationError(ValueError):
    """Invalid configuration, with no input values in the public message."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    environment: Literal["local", "test"] = "local"
    mode: Literal["mock"] = "mock"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read only the two supported, non-secret variables; allow injected mappings.

    Database environment variables and backend/.env are deliberately not read.
    Production operation is outside this foundation's scope.
    """
    source = os.environ if environ is None else environ
    values = {
        "environment": source.get("PAUSEGUARD_ENVIRONMENT", "local"),
        "mode": source.get("PAUSEGUARD_MODE", "mock"),
    }
    try:
        return Settings.model_validate(values)
    except ValidationError:
        raise ConfigurationError(
            "Invalid PauseGuard configuration: environment must be local or test; "
            "mode must be mock."
        ) from None
