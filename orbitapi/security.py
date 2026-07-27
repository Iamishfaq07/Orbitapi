"""Core-side request context.

The core service runs behind the gateway, which authenticates the caller and
forwards the resolved identity in `X-Orbit-*` headers. Handlers read that
identity here and make their authorization decisions from it.
"""
import time
from collections import defaultdict
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from . import config, db
from .identity import create_token, decode_token  # re-exported for handlers that still mint tokens


def _header(request: Request, name: str) -> Optional[str]:
    return request.headers.get(name)


def current_user(request: Request) -> Dict[str, Any]:
    """Identity for the current request, taken from the gateway-supplied headers."""
    uid = _header(request, config.H_USER)
    if uid is None:
        raise HTTPException(status_code=401, detail="Missing identity context")
    role = _header(request, config.H_ROLE) or "member"
    return {
        "sub": _header(request, config.H_USERNAME) or "",
        "user_id": int(uid) if str(uid).lstrip("-").isdigit() else uid,
        "org_id": int(_header(request, config.H_ORG) or 0),
        "role": role,
        "clearance": _header(request, config.H_CLEARANCE) or "standard",
        "is_admin": (_header(request, config.H_ADMIN) or "").lower() == "true" or role in ("admin", "owner"),
        "is_support": (_header(request, config.H_SUPPORT) or "").lower() == "true",
    }


def optional_user(request: Request) -> Optional[Dict[str, Any]]:
    try:
        return current_user(request)
    except HTTPException:
        return None


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def is_internal(request: Request) -> bool:
    return client_ip(request).startswith(config.TRUSTED_INTERNAL_PREFIXES)


def is_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") in ("admin", "owner") or bool(user.get("is_admin"))


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        window = [t for t in self.hits[key] if now - t < 60]
        if len(window) >= self.per_minute:
            self.hits[key] = window
            raise HTTPException(status_code=429, detail="Too many attempts, slow down",
                                headers={"Retry-After": "60"})
        window.append(now)
        self.hits[key] = window


login_limiter = RateLimiter(config.LOGIN_RATE_LIMIT_PER_MINUTE)


def audit(actor: str, ip: str, action: str, detail: str) -> None:
    db.execute("INSERT INTO audit_logs (actor, ip, action, detail) VALUES (?,?,?,?)",
               (actor, ip, action, detail))
