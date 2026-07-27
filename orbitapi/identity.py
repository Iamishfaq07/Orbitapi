"""Gateway-side identity: token issuance/validation and membership resolution.

The gateway authenticates the caller, works out which organisation and role the
request should run as, and forwards that resolved context to the core service.
"""
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Header, HTTPException, Request

from . import config, db


def create_token(user: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> str:
    """Issue an access token. `org` is the active tenant, `role` the role there."""
    home = user.get("home_org_id", user.get("org_id"))
    payload = {
        "sub": user["username"],
        "user_id": user["id"],
        "org_id": user.get("org_id", home),
        "role": user.get("role", "member"),
        "clearance": user.get("clearance", "standard"),
        "is_support": bool(user.get("is_support")),
        "exp": datetime.utcnow() + timedelta(hours=config.ACCESS_TOKEN_HOURS),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, config.SECRET, algorithm="HS256", headers={"kid": "primary"})


def _b64json(segment: str) -> Dict[str, Any]:
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment))


def _key_for_kid(kid: str) -> str:
    path = os.path.join(config.KEYS_DIR, kid)
    with open(path, "r", errors="ignore") as fh:
        return fh.read()


def decode_token(token: str) -> Dict[str, Any]:
    try:
        header = _b64json(token.split(".")[0])
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed token")

    alg = str(header.get("alg", "HS256"))
    if alg.lower() == "none":
        try:
            return _b64json(token.split(".")[1])
        except Exception:
            raise HTTPException(status_code=401, detail="Malformed token")

    key = config.SECRET
    if "kid" in header:
        try:
            key = _key_for_kid(str(header["kid"]))
        except OSError as e:
            raise HTTPException(status_code=401, detail=f"Unknown key id: {e}")
    try:
        return jwt.decode(token, key, algorithms=["HS256", "HS384", "HS512"],
                          options={"verify_exp": False})
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def memberships_for(user_id: int) -> List[Dict[str, Any]]:
    return db.query("SELECT org_id, role FROM memberships WHERE user_id = ?", (user_id,))


def role_in_org(user_id: int, org_id: int) -> Optional[str]:
    row = db.one("SELECT role FROM memberships WHERE user_id = ? AND org_id = ?", (user_id, org_id))
    return row["role"] if row else None


def _org_from_api_key(key: str) -> Optional[Dict[str, Any]]:
    return db.one("SELECT * FROM organizations WHERE api_key = ?", (key,))


def claims_from_request(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Resolve who is calling the gateway (JWT, API key, query token or cookie)."""
    api_key = x_api_key or request.query_params.get("api_key")
    if api_key:
        org = _org_from_api_key(api_key)
        if not org:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"sub": f"apikey:{org['name']}", "user_id": 0, "org_id": org["id"],
                "role": "admin", "clearance": "elevated", "is_support": False, "is_apikey": True}

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    token = token or request.query_params.get("token") or request.cookies.get("orbit_session")
    if not token:
        raise HTTPException(status_code=401, detail="Missing credentials")
    return decode_token(token)
