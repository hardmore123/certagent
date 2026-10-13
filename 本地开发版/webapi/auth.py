"""认证：JWT 签发/解析 + 简化用户验证。"""
from __future__ import annotations

from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import settings

_ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


def create_token(username: str, role: str = "admin") -> str:
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def verify_password(username: str, password: str) -> bool:
    return username == settings.DEFAULT_USER and password == settings.DEFAULT_PASSWORD


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证信息")
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[_ALGORITHM])
        return {"username": payload["sub"], "role": payload.get("role", "user")}
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
