"""The OrbitAPI gateway.

Public entry point. Authenticates the caller, resolves which organisation and
role the request runs as, and forwards it to the core service with the resolved
identity in `X-Orbit-*` headers.
"""
import traceback
from typing import Dict, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import config, db, seed
from .gateway_auth import router as auth_router
from .identity import claims_from_request, role_in_org

app = FastAPI(title="OrbitAPI", version=config.VERSION,
              description="OrbitAPI — multi-tenant project, billing and commerce platform.",
              contact={"name": "Orbit Platform Team", "email": "support@orbit.test"})

# Identity headers must never be accepted from the client; the gateway sets them.
_STRIP = {config.H_USER, config.H_USERNAME, config.H_ORG, config.H_ROLE, config.H_SUPPORT,
          config.H_ADMIN, config.H_CLEARANCE, config.H_INTERNAL, "host", "content-length",
          "connection", "transfer-encoding"}

# The gateway enforces a coarse admin gate on these path prefixes.
_ADMIN_PREFIXES = ("/api/v2/admin/impersonate",)


@app.on_event("startup")
def _startup() -> None:
    # Make sure the dataset exists even if the core service has not seeded yet.
    import os
    if not os.path.exists(config.DB_PATH):
        seed.seed()


@app.middleware("http")
async def response_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as exc:
        response = JSONResponse(status_code=500, content={
            "error": type(exc).__name__, "message": str(exc),
            "trace": traceback.format_exc().splitlines(), "path": request.url.path,
        })
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "access-control-request-headers", "*")
    response.headers["X-Powered-By"] = f"OrbitAPI/{config.VERSION} FastAPI Python"
    response.headers["Server"] = "uvicorn (orbit-gateway-1.prod.internal)"
    return response


@app.options("/{rest:path}", include_in_schema=False)
def preflight(rest: str):
    return JSONResponse({"ok": True})


@app.get("/", include_in_schema=False)
def root():
    return {"name": "OrbitAPI", "version": config.VERSION, "docs": "/docs",
            "api": ["/api/v2"], "status": "ok"}


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "gateway", "version": config.VERSION}


app.include_router(auth_router)


def _identity_headers(request: Request) -> Dict[str, str]:
    """Authenticate (if possible) and build the identity headers for the core call."""
    try:
        claims = claims_from_request(request, request.headers.get("authorization"),
                                     request.headers.get("x-api-key"))
    except HTTPException:
        # Anonymous: forward with no identity. Public routes still work; the rest 401 downstream.
        return {config.H_INTERNAL: config.INTERNAL_SERVICE_TOKEN}

    user_id = claims.get("user_id")
    # Active organisation: an explicit X-Org-Id (or ?org=) overrides the token's tenant.
    requested = request.headers.get("x-org-id") or request.query_params.get("org")
    active_org = int(requested) if requested and str(requested).isdigit() else claims.get("org_id")

    role = None
    if user_id:
        role = role_in_org(user_id, active_org)
    # Fall back to the role carried in the token when we have no membership row.
    role = role or claims.get("role", "member")

    is_support = False
    if user_id:
        row = db.one("SELECT is_support FROM users WHERE id = ?", (user_id,))
        is_support = bool(row and row["is_support"])

    headers = {
        config.H_USER: str(user_id),
        config.H_USERNAME: str(claims.get("sub", "")),
        config.H_ORG: str(active_org),
        config.H_ROLE: str(role),
        config.H_CLEARANCE: str(claims.get("clearance", "standard")),
        config.H_SUPPORT: "true" if is_support else "false",
        config.H_ADMIN: "true" if role in ("admin", "owner") else "false",
        config.H_INTERNAL: config.INTERNAL_SERVICE_TOKEN,
    }

    for prefix in _ADMIN_PREFIXES:
        if request.url.path.startswith(prefix) and role not in ("admin", "owner") and not is_support:
            raise HTTPException(status_code=403, detail="Admin role required")
    return headers


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def proxy(path: str, request: Request):
    inject = _identity_headers(request)
    fwd = {k: v for k, v in request.headers.items() if k.lower() not in _STRIP}
    fwd.update(inject)
    body = await request.body()
    url = f"{config.CORE_SERVICE_URL}/{path}"
    try:
        r = requests.request(request.method, url, params=dict(request.query_params),
                             data=body, headers=fwd, timeout=30, allow_redirects=False)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Core service unavailable: {e}")
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in excluded}
    return Response(content=r.content, status_code=r.status_code, headers=out_headers,
                    media_type=r.headers.get("content-type"))
