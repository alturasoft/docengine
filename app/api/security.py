"""DocEngine — API Security and Role-Based Access Control (RBAC).

Provides optional API Key authentication via `X-API-Key` header with
three privilege tiers:
- readonly: Read operations and search endpoints only.
- writer: Individual document uploads and read operations.
- admin: Full administrative access, envelope and document deletion.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

RoleType = Literal["readonly", "writer", "admin"]

ROLE_HIERARCHY: dict[RoleType, int] = {
    "readonly": 1,
    "writer": 2,
    "admin": 3,
}


def _get_configured_api_keys() -> dict[str, RoleType]:
    """Load API Keys mapping from environment or settings.

    Format in env `DOCENGINE_API_KEYS`:
    JSON string: {"key_read_123": "readonly", "key_write_456": "writer", "key_admin_789": "admin"}
    """
    raw_keys = os.environ.get("DOCENGINE_API_KEYS")
    if not raw_keys:
        return {}
    try:
        keys_dict = json.loads(raw_keys)
        return {k: v.lower() for k, v in keys_dict.items() if v.lower() in ROLE_HIERARCHY}
    except Exception as exc:
        logger.error("Failed to parse DOCENGINE_API_KEYS environment variable", error=str(exc))
        return {}


def is_security_enabled() -> bool:
    """Check if API Key security is globally enabled."""
    val = os.environ.get("DOCENGINE_SECURITY_ENABLED", "false").strip().lower()
    return val in {"true", "1", "yes", "enabled"}


class AuthenticatedClient:
    """Represents an authenticated API consumer."""

    def __init__(self, api_key: str, role: RoleType) -> None:
        self.api_key = api_key
        self.role = role

    def has_role(self, required_role: RoleType) -> bool:
        """Check if client role satisfies required minimum role."""
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


def get_current_client(
    api_key: str | None = Security(API_KEY_HEADER),
) -> AuthenticatedClient:
    """Authenticate request using the X-API-Key header.

    If DOCENGINE_SECURITY_ENABLED is False and no key is provided, allows anonymous access
    with admin privileges (backward compatibility for local dev/testing).
    """
    configured_keys = _get_configured_api_keys()
    security_enabled = is_security_enabled() or bool(configured_keys)

    # If security is not active and no key is supplied, default to permissive admin mode
    if not security_enabled and not api_key:
        return AuthenticatedClient(api_key="anonymous", role="admin")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera 'X-API-Key' requerida para acceder a este recurso.",
        )

    role = configured_keys.get(api_key)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial 'X-API-Key' inválida o no registrada.",
        )

    return AuthenticatedClient(api_key=api_key, role=role)


def require_role(min_role: RoleType):
    """FastAPI dependency factory enforcing a minimum role level."""

    def _role_checker(
        client: AuthenticatedClient = Depends(get_current_client),
    ) -> AuthenticatedClient:
        if not client.has_role(min_role):
            user_role = client.role
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Permisos insuficientes. El perfil '{user_role}' no está autorizado "
                    f"para esta operación (requiere al menos perfil '{min_role}')."
                ),
            )
        return client

    return _role_checker
