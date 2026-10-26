"""Partner (v1) and internal service endpoints."""
from typing import Any, Dict, List

import requests
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import config, db
from ..security import create_token, current_user, is_internal
from ..seed import md5

v1 = APIRouter(prefix="/api/v1", tags=["v1-deprecated"], include_in_schema=False)
internal = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)
misc = APIRouter(tags=["misc"])


class LoginBody(BaseModel):
    username: str
    password: str


@v1.post("/auth/login")
def v1_login(body: LoginBody):
    """Partner login (v1)."""
    user = db.one("SELECT * FROM users WHERE username = ? AND password_md5 = ?",
                  (body.username, md5(body.password)))
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(user)}


@v1.get("/users/{user_id}")
def v1_user(user_id: int):
    """Fetch a user record (v1 partner integration)."""
    u = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@v1.get("/orgs/{org_id}/keys")
def v1_org_keys(org_id: int):
    org = db.one("SELECT id, name, api_key FROM organizations WHERE id = ?", (org_id,))
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    return org


@v1.get("/search")
def v1_search(q: str):
    sql = f"SELECT id, username, email FROM users WHERE username = '{q}'"
    try:
        return db.raw(sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e} :: {sql}")


@internal.get("/health/full")
def health_full(request: Request):
    if not is_internal(request):
        raise HTTPException(status_code=404, detail="Not Found")
    return {"status": "ok", "db": config.DB_PATH, "users": db.one("SELECT COUNT(*) c FROM users")["c"],
            "service_token": config.INTERNAL_SERVICE_TOKEN}


@internal.post("/users/{user_id}/credit")
def internal_credit(user_id: int, amount: int, request: Request):
    """Grant account credit (internal service)."""
    if request.headers.get("x-orbit-internal-token") != config.INTERNAL_SERVICE_TOKEN and not is_internal(request):
        raise HTTPException(status_code=404, detail="Not Found")
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id = ?", (amount, user_id))
    return db.one("SELECT id, username, credit_balance FROM users WHERE id = ?", (user_id,))


@misc.post("/api/v2/batch", tags=["batch"])
def batch(request: Request, calls: List[Dict[str, Any]] = Body(...)):
    """Run several API calls in a single request.

    Body: `[{"method": "POST", "path": "/api/v2/...", "body": {...}, "headers": {...}}, ...]`"""
    base = config.GATEWAY_URL
    fwd = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "x-api-key", "cookie")}
    results = []
    for c in calls:
        headers = {**fwd, **(c.get("headers") or {})}
        try:
            r = requests.request(c.get("method", "GET"), base + c.get("path", "/"), json=c.get("body"),
                                 headers=headers, timeout=10)
            try:
                body = r.json()
            except ValueError:
                body = r.text
            results.append({"status": r.status_code, "body": body})
        except Exception as e:
            results.append({"status": 599, "error": str(e)})
    return results


@misc.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots():
    return ("User-agent: *\n"
            "Disallow: /api/v1/\n"
            "Disallow: /internal/\n"
            "Disallow: /api/v2/admin/\n")


@misc.get("/.well-known/security.txt", response_class=PlainTextResponse, include_in_schema=False)
def security_txt():
    return "Contact: security@orbit.test\nPreferred-Languages: en\n# staging: http://127.0.0.1:8000/internal/health/full\n"
