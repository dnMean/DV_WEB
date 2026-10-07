"""JWT (HS256) issuing/decoding and FastAPI dependencies.

Two secrets:
- JWT_SECRET signs normal user tokens (customer/staff) issued by the Auth service.
- SYSTEM_TOKEN_SECRET signs `system` tokens that only the Gateway mints when executing an
  approved ticket. A `system` role claim signed with JWT_SECRET is rejected.
"""
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import AppError

SYSTEM_ROLE = "system"
ON_BEHALF_OF_HEADER = "X-On-Behalf-Of"
INTERNAL_SECRET_HEADER = "X-Internal-Secret"
_ALGORITHM = "HS256"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    JWT_SECRET: str
    SYSTEM_TOKEN_SECRET: str
    JWT_TTL_MINUTES: int = 60
    INTERNAL_SECRET: str = ""
    ALLOW_RESET: bool = False


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str
    token: str = ""
    on_behalf_of: int | None = None  # set only for system tokens

    @property
    def is_staff(self) -> bool:
        return self.role == "staff"

    @property
    def is_system(self) -> bool:
        return self.role == SYSTEM_ROLE


def create_access_token(user_id: int, username: str, role: str, ttl_minutes: int | None = None) -> str:
    if role == SYSTEM_ROLE:
        raise ValueError("system tokens must be created with create_system_token")
    s = get_auth_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes or s.JWT_TTL_MINUTES)
    claims = {"sub": str(user_id), "username": username, "role": role, "exp": exp}
    return jwt.encode(claims, s.JWT_SECRET, algorithm=_ALGORITHM)


def create_system_token(ttl_minutes: int = 5) -> str:
    s = get_auth_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    claims = {"sub": "0", "username": "system", "role": SYSTEM_ROLE, "exp": exp}
    return jwt.encode(claims, s.SYSTEM_TOKEN_SECRET, algorithm=_ALGORITHM)


def _decode(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"require": ["exp", "sub"]})


def decode_token(token: str) -> dict:
    s = get_auth_settings()
    try:
        claims = _decode(token, s.JWT_SECRET)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Token đã hết hạn")
    except jwt.InvalidSignatureError:
        claims = None
    except jwt.InvalidTokenError:
        raise AppError(401, "invalid_token", "Token không hợp lệ")

    if claims is not None:
        if claims.get("role") == SYSTEM_ROLE:
            raise AppError(401, "invalid_token", "Token không hợp lệ")
        return claims

    try:
        claims = _decode(token, s.SYSTEM_TOKEN_SECRET)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Token đã hết hạn")
    except jwt.InvalidTokenError:
        raise AppError(401, "invalid_token", "Token không hợp lệ")
    if claims.get("role") != SYSTEM_ROLE:
        raise AppError(401, "invalid_token", "Token không hợp lệ")
    return claims


_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    """Returns None when no token is sent; raises 401 when a token is sent but invalid."""
    if creds is None:
        return None
    claims = decode_token(creds.credentials)
    on_behalf_of = None
    if claims["role"] == SYSTEM_ROLE:
        raw = request.headers.get(ON_BEHALF_OF_HEADER)
        if raw is not None:
            try:
                on_behalf_of = int(raw)
            except ValueError:
                raise AppError(400, "bad_request", f"{ON_BEHALF_OF_HEADER} phải là user_id dạng số")
    return CurrentUser(
        id=int(claims["sub"]),
        username=claims.get("username", ""),
        role=claims["role"],
        token=creds.credentials,
        on_behalf_of=on_behalf_of,
    )


def get_current_user(user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    if user is None:
        raise AppError(401, "unauthorized", "Thiếu token xác thực")
    return user


def require_roles(*roles: str):
    """Dependency factory: `user = Depends(require_roles("customer", "staff"))`."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise AppError(403, "forbidden", f"Role '{user.role}' không có quyền thực hiện thao tác này")
        return user

    return _dep


def is_internal_request(request: Request) -> bool:
    secret = get_auth_settings().INTERNAL_SECRET
    sent = request.headers.get(INTERNAL_SECRET_HEADER)
    return bool(secret) and bool(sent) and hmac.compare_digest(sent, secret)


def require_internal(request: Request) -> None:
    """Dependency for service-to-service endpoints (/internal/*)."""
    if not is_internal_request(request):
        raise AppError(403, "forbidden", "Chỉ dành cho service nội bộ")
