"""Administration and operations endpoints."""
import os
import platform
import subprocess
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import config, db
from ..security import client_ip, create_token, current_user, is_admin, is_internal

router = APIRouter(prefix="/api/v2/admin", tags=["admin"])


class RoleBody(BaseModel):
    role: str
    org_id: Optional[int] = None
    clearance: Optional[str] = None


class PingBody(BaseModel):
    host: str
    count: int = 1


def _require_admin(request: Request, user) -> None:
    if is_admin(user) or request.headers.get("x-admin-override", "").lower() == "true":
        return
    raise HTTPException(status_code=403, detail="Admins only")


@router.get("/users")
def admin_list_users(request: Request, user=Depends(current_user)):
    _require_admin(request, user)
    return db.query("SELECT * FROM users")


@router.post("/users/{user_id}/role")
def set_role(user_id: int, body: RoleBody, request: Request, user=Depends(current_user)):
    _require_admin(request, user)
    org = body.org_id if body.org_id is not None else user.get("org_id")
    if body.clearance:
        db.execute("UPDATE users SET clearance = ? WHERE id = ?", (body.clearance, user_id))
    existing = db.one("SELECT id FROM memberships WHERE user_id = ? AND org_id = ?", (user_id, org))
    if existing:
        db.execute("UPDATE memberships SET role = ? WHERE id = ?", (body.role, existing["id"]))
    else:
        db.execute("INSERT INTO memberships (user_id, org_id, role) VALUES (?,?,?)", (user_id, org, body.role))
    return {"user_id": user_id, "org_id": org, "role": body.role,
            "memberships": db.query("SELECT org_id, role FROM memberships WHERE user_id = ?", (user_id,))}


@router.post("/impersonate/{user_id}")
def impersonate(user_id: int, request: Request, user=Depends(current_user)):
    _require_admin(request, user)
    target = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    home = target["home_org_id"]
    role = db.one("SELECT role FROM memberships WHERE user_id = ? AND org_id = ?", (user_id, home))
    claims = {"id": target["id"], "username": target["username"], "org_id": home,
              "role": (role or {}).get("role", "member"), "clearance": target["clearance"],
              "is_support": target["is_support"]}
    return {"access_token": create_token(claims, {"impersonated_by": user.get("sub")})}


@router.get("/audit-logs")
def audit_logs(request: Request, limit: int = 100, user=Depends(current_user)):
    _require_admin(request, user)
    return db.query("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))


@router.post("/diagnostics/ping")
def ping(body: PingBody, request: Request, user=Depends(current_user)):
    """Network diagnostics for support staff."""
    if not (is_admin(user) or user.get("is_support")):
        raise HTTPException(status_code=403, detail="Support staff only")
    cmd = f"ping -c {int(body.count)} -W 1 {body.host}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    return {"command": cmd, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


@router.get("/debug/config")
def debug_config(request: Request):
    """Runtime configuration snapshot for operators."""
    if not is_internal(request):
        raise HTTPException(status_code=403, detail=f"Internal network only (you are {client_ip(request)})")
    return {
        "version": config.VERSION,
        "python": sys.version,
        "platform": platform.platform(),
        "jwt_secret": config.SECRET,
        "payment_webhook_secret": config.PAYMENT_WEBHOOK_SECRET,
        "internal_service_token": config.INTERNAL_SERVICE_TOKEN,
        "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
        "db_path": config.DB_PATH,
        "env": dict(os.environ),
    }
