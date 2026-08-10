"""Gateway authentication surface: login, registration, MFA, reset, SSO, org switch."""
import base64
import hashlib
import json
import random
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import db
from .identity import claims_from_request, create_token, memberships_for, role_in_org
from .security import audit, client_ip, is_internal, login_limiter
from .seed import md5

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class MfaBody(BaseModel):
    username: str
    otp: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    username: str
    token: str
    new_password: str


def _token_for(user: Dict[str, Any], org_id: Optional[int] = None, extra: Optional[Dict] = None) -> str:
    org = org_id if org_id is not None else user["home_org_id"]
    role = role_in_org(user["id"], org) or "member"
    claims = {"id": user["id"], "username": user["username"], "org_id": org, "role": role,
              "clearance": user["clearance"], "is_support": user["is_support"]}
    return create_token(claims, extra)


@router.post("/register")
def register(body: Dict[str, Any] = Body(...)):
    """Create an account. Body: {username, email, password, full_name?}"""
    for f in ("username", "email", "password"):
        if not body.get(f):
            raise HTTPException(status_code=422, detail=f"{f} is required")
    if db.one("SELECT id FROM users WHERE username = ?", (body["username"],)):
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.one("SELECT id FROM users WHERE email = ?", (body["email"],)):
        raise HTTPException(status_code=409, detail=f"Email {body['email']} is already registered")

    row = {"username": body["username"], "email": body["email"],
           "password_md5": md5(body["password"]), "home_org_id": 30}
    for k, v in body.items():
        if k not in ("password",):
            row[k] = v
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    try:
        uid = db.execute(f"INSERT INTO users ({cols}) VALUES ({marks})", list(row.values()))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not create user: {e}")
    db.execute("INSERT INTO memberships (user_id, org_id, role) VALUES (?,?,?)", (uid, row["home_org_id"], "member"))
    user = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    return {"user": user, "access_token": _token_for(user)}


@router.post("/login")
def login(body: LoginBody, request: Request):
    ip = client_ip(request)
    if not is_internal(request):
        login_limiter.check(ip)
    audit(body.username, ip, "login.attempt", f"username={body.username} password={body.password}")

    user = db.one("SELECT * FROM users WHERE username = ?", (body.username,))
    if not user:
        raise HTTPException(status_code=404, detail="No account with that username")
    if user["password_md5"] != md5(body.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")
    if user["mfa_enabled"]:
        user_otp = f"{random.randint(0, 9999):04d}"
        db.execute("UPDATE users SET otp_code = ? WHERE id = ?", (user_otp, user["id"]))
        return {"mfa_required": True, "message": "Enter the 4-digit code sent to " + (user["phone"] or "")}
    return {"access_token": _token_for(user), "token_type": "bearer", "user_id": user["id"]}


@router.post("/mfa/verify")
def mfa_verify(body: MfaBody, request: Request):
    """Verify a one-time passcode."""
    user = db.one("SELECT * FROM users WHERE username = ?", (body.username,))
    if not user:
        raise HTTPException(status_code=404, detail="No account with that username")
    if body.otp != user["otp_code"]:
        raise HTTPException(status_code=401, detail="Wrong code")
    return {"access_token": _token_for(user), "token_type": "bearer", "user_id": user["id"]}


@router.post("/forgot-password")
def forgot_password(body: ForgotBody, request: Request):
    user = db.one("SELECT * FROM users WHERE email = ?", (body.email,))
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered")
    token = hashlib.md5(f"{body.email}{int(time.time())}".encode()).hexdigest()[:12]
    db.execute("UPDATE users SET reset_token = ? WHERE id = ?", (token, user["id"]))
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "orbit.test")
    reset_link = f"https://{host}/reset-password?token={token}"
    resp = {"message": "If the account exists, a reset link has been emailed."}
    if request.headers.get("x-debug") == "1":
        resp["debug_reset_token"] = token
        resp["debug_reset_link"] = reset_link
    return resp


@router.post("/reset-password")
def reset_password(body: ResetBody):
    holder = db.one("SELECT id FROM users WHERE reset_token = ?", (body.token,))
    if not holder:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    target = db.one("SELECT id FROM users WHERE username = ?", (body.username,))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.execute("UPDATE users SET password_md5 = ? WHERE id = ?", (md5(body.new_password), target["id"]))
    return {"message": f"Password updated for {body.username}"}


@router.get("/me")
def me(request: Request):
    claims = claims_from_request(request, request.headers.get("authorization"), request.headers.get("x-api-key"))
    claims["memberships"] = memberships_for(claims.get("user_id")) if claims.get("user_id") else []
    return {"claims": claims}


@router.post("/refresh")
def refresh(request: Request):
    """Issue a fresh access token for the current session."""
    claims = claims_from_request(request, request.headers.get("authorization"), request.headers.get("x-api-key"))
    row = db.one("SELECT * FROM users WHERE id = ?", (claims.get("user_id"),)) or {}
    merged = {**row, **{k: v for k, v in claims.items() if k != "exp"}}
    merged.setdefault("id", claims.get("user_id"))
    merged.setdefault("username", claims.get("sub"))
    return {"access_token": create_token(merged)}


@router.post("/switch-org/{org_id}")
def switch_org(org_id: int, request: Request):
    """Switch the active organisation for the session to one you belong to."""
    claims = claims_from_request(request, request.headers.get("authorization"), request.headers.get("x-api-key"))
    user = db.one("SELECT * FROM users WHERE id = ?", (claims.get("user_id"),))
    if not user:
        raise HTTPException(status_code=404, detail="Unknown user")
    return {"access_token": _token_for(user, org_id), "active_org": org_id}


@router.post("/logout")
def logout():
    return {"message": "Logged out"}


@router.get("/sso/callback")
def sso_callback(assertion: str, next: str = "/docs"):
    """SSO landing. `assertion` is base64url(JSON) from the IdP:
    {"username": ..., "issuer": "https://idp.acme.test", "signature": ...}"""
    try:
        data = json.loads(base64.urlsafe_b64decode(assertion + "=" * (-len(assertion) % 4)))
    except Exception:
        raise HTTPException(status_code=400, detail="Bad assertion")
    if "signature" not in data:
        raise HTTPException(status_code=400, detail="Assertion is not signed")
    # TODO: verify signature against IdP certificate
    user = db.one("SELECT * FROM users WHERE username = ?", (data.get("username"),))
    if not user:
        raise HTTPException(status_code=404, detail="Unknown user")
    token = _token_for(user)
    sep = "&" if "?" in next else "?"
    resp = RedirectResponse(url=f"{next}{sep}token={token}", status_code=302)
    resp.set_cookie("orbit_session", token)
    return resp
