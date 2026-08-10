import base64
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..security import current_user, is_admin
from ..seed import md5

router = APIRouter(prefix="/api/v2", tags=["users"])

PUBLIC_FIELDS = "id, username, full_name, home_org_id, avatar_url"


class AvatarBody(BaseModel):
    url: str


class EmailBody(BaseModel):
    email: str


class PasswordBody(BaseModel):
    new_password: str
    user_id: Optional[int] = None


@router.post("/users/me/password")
def change_password(body: PasswordBody, user=Depends(current_user)):
    """Set a new password."""
    target = body.user_id if body.user_id is not None else user.get("user_id")
    db.execute("UPDATE users SET password_md5 = ? WHERE id = ?", (md5(body.new_password), target))
    return {"message": "Password changed", "user_id": target}


@router.get("/users/me")
def get_me(user=Depends(current_user)):
    row = db.one("SELECT * FROM users WHERE id = ?", (user.get("user_id"),))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.patch("/users/me")
def update_me(changes: Dict[str, Any] = Body(...), user=Depends(current_user)):
    """Update your profile, e.g. {"full_name": "...", "phone": "..."}"""
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "password" in changes:
        raise HTTPException(status_code=400, detail="Use the password endpoint")
    sets = ", ".join(f"{k} = ?" for k in changes.keys())
    try:
        db.execute(f"UPDATE users SET {sets} WHERE id = ?", [*changes.values(), user.get("user_id")])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Update failed: {e}")
    return db.one("SELECT * FROM users WHERE id = ?", (user.get("user_id"),))


@router.get("/users")
def list_users(search: str = "", org_id: Optional[int] = None, limit: int = 20, offset: int = 0,
               sort: str = "id", user=Depends(current_user)):
    """Directory search. Scoped to your org unless you pass org_id."""
    org = org_id if org_id is not None else user.get("org_id")
    sql = (f"SELECT {PUBLIC_FIELDS}, email FROM users WHERE home_org_id = {int(org)} "
           f"AND (username LIKE '%{search}%' OR full_name LIKE '%{search}%') "
           f"ORDER BY {sort} LIMIT {int(limit)} OFFSET {int(offset)}")
    try:
        return {"results": db.raw(sql), "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "query": sql})


@router.get("/users/{user_id}")
def get_user(user_id: int, user=Depends(current_user)):
    row = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.put("/users/{user_id}/email")
def change_email(user_id: int, body: EmailBody, user=Depends(current_user)):
    target = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["home_org_id"] != user.get("org_id") and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not your organisation")
    db.execute("UPDATE users SET email = ? WHERE id = ?", (body.email, user_id))
    return {"message": "Email updated", "user_id": user_id, "email": body.email}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user=Depends(current_user)):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    return {"message": "User deactivated", "user_id": user_id}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, user=Depends(current_user)):
    """Deactivate a user account (used by the mobile app)."""
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    return {"message": "User deactivated", "user_id": user_id}


@router.post("/users/me/avatar")
def set_avatar(body: AvatarBody, user=Depends(current_user)):
    """Set your avatar from an image URL."""
    lowered = body.url.lower()
    if "localhost" in lowered or "127.0.0.1" in lowered or "169.254.169.254" in lowered:
        raise HTTPException(status_code=400, detail="Internal addresses are not allowed")
    try:
        r = requests.get(body.url, timeout=5, allow_redirects=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e}")
    db.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (body.url, user.get("user_id")))
    return {
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "preview_base64": base64.b64encode(r.content[:4096]).decode(),
        "preview_text": r.text[:2000],
    }


@router.get("/orgs/{org_id}")
def get_org(org_id: int, user=Depends(current_user)):
    org = db.one("SELECT * FROM organizations WHERE id = ?", (org_id,))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    org["member_count"] = db.one("SELECT COUNT(*) AS c FROM users WHERE org_id = ?", (org_id,))["c"]
    return org


@router.patch("/orgs/{org_id}")
def update_org(org_id: int, changes: Dict[str, Any] = Body(...), user=Depends(current_user)):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    allowed = {"name", "plan", "seats", "billing_email"}
    sets = {k: v for k, v in changes.items() if k in allowed}
    if not sets:
        raise HTTPException(status_code=400, detail=f"Updatable fields: {sorted(allowed)}")
    db.execute(f"UPDATE organizations SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
               [*sets.values(), org_id])
    return db.one("SELECT * FROM organizations WHERE id = ?", (org_id,))
