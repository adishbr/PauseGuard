"""Basic role and resource ownership authorization policy."""

VALID_ROLES = {
    "payer",
    "guardian",
    "admin",
}


def authorize_resource_access(
    actor_id: str,
    actor_role: str,
    owner_id: str,
    allowed_roles: set[str],
) -> bool:
    """Check role and resource ownership."""

    if not all(
        isinstance(value, str) and value.strip()
        for value in (actor_id, actor_role, owner_id)
    ):
        return False

    if actor_role not in VALID_ROLES:
        return False

    if not isinstance(allowed_roles, set):
        return False

    if not allowed_roles.issubset(VALID_ROLES):
        return False

    if actor_role not in allowed_roles:
        return False

    if actor_id != owner_id:
        return False

    return True