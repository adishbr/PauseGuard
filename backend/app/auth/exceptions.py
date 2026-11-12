"""Authentication and authorization HTTP exceptions."""

from fastapi import HTTPException, status


class AuthenticationError(HTTPException):
    """Raised when authentication credentials are missing, malformed, or invalid."""

    def __init__(self, detail: str = "Invalid or missing authentication credentials") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthorizationError(HTTPException):
    """Raised when an authenticated actor lacks the required role or permission."""

    def __init__(self, detail: str = "Forbidden: Insufficient privileges for requested operation") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class CrossAccountAccessError(HTTPException):
    """Raised when an actor attempts to access an account or resource owned by another user."""

    def __init__(self, detail: str = "Forbidden: Cross-account access is prohibited") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class GuardianAssignmentError(HTTPException):
    """Raised when an actor is not the enrolled, assigned guardian for a specific transaction."""

    def __init__(self, detail: str = "Forbidden: Actor is not the assigned guardian for this transaction") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

