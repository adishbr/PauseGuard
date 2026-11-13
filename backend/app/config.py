"""Typed non-secret settings. This module never loads dotenv files."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError


class ConfigurationError(ValueError):
    """Invalid configuration, with no input values in the public message."""


class Settings(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    environment: Literal["local", "test"] = "local"
    mode: Literal["mock"] = "mock"
    allow_demo_auth: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_demo_auth", "enable_demo_auth"),
    )
    allow_demo_admin: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_demo_admin", "enable_demo_admin"),
    )

    @property
    def enable_demo_auth(self) -> bool:
        return self.allow_demo_auth

    @property
    def enable_demo_admin(self) -> bool:
        return self.allow_demo_admin


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read supported, non-secret variables; allow injected mappings.

    Database environment variables and backend/.env are deliberately not read.
    Production operation is outside this foundation's scope.
    """
    source = os.environ if environ is None else environ
    demo_auth_raw = source.get("PAUSEGUARD_ALLOW_DEMO_AUTH")
    if demo_auth_raw is None:
        demo_auth_raw = source.get("PAUSEGUARD_ENABLE_DEMO_AUTH")

    demo_admin_raw = source.get("PAUSEGUARD_ALLOW_DEMO_ADMIN")
    if demo_admin_raw is None:
        demo_admin_raw = source.get("PAUSEGUARD_ENABLE_DEMO_ADMIN")

    values = {
        "environment": source.get("PAUSEGUARD_ENVIRONMENT", "local"),
        "mode": source.get("PAUSEGUARD_MODE", "mock"),
        "allow_demo_auth": _parse_bool(demo_auth_raw),
        "allow_demo_admin": _parse_bool(demo_admin_raw),
    }
    try:
        return Settings.model_validate(values)
    except ValidationError:
        raise ConfigurationError(
            "Invalid PauseGuard configuration: environment must be local or test; "
            "mode must be mock."
        ) from None
