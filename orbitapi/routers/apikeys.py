"""Personal API token management."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..security import current_user

router = APIRouter(prefix="/api/v2/api-keys", tags=["api-keys"])


class KeyBody(BaseModel):
    name: str
    scopes: str = "read"


def _next_token() -> str:
    row = db.one("SELECT token FROM api_keys ORDER BY id DESC LIMIT 1")
    last = int(row["token"].rsplit("_", 1)[1]) if row and row["token"].startswith("sk_live_") else 1000
    return f"sk_live_{last + 1}"


@router.get("")
def list_keys(user_id: Optional[int] = None, user=Depends(current_user)):
    uid = user_id if user_id is not None else user.get("user_id")
    return db.query("SELECT * FROM api_keys WHERE user_id = ? ORDER BY id", (uid,))


@router.post("")
def create_key(body: KeyBody, user=Depends(current_user)):
    token = _next_token()
    kid = db.execute("INSERT INTO api_keys (user_id, org_id, name, token, scopes) VALUES (?,?,?,?,?)",
                     (user.get("user_id"), user.get("org_id"), body.name, token, body.scopes))
    return db.one("SELECT * FROM api_keys WHERE id = ?", (kid,))


@router.get("/{key_id}")
def get_key(key_id: int, user=Depends(current_user)):
    k = db.one("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    if not k:
        raise HTTPException(status_code=404, detail="Key not found")
    return k


@router.delete("/{key_id}")
def delete_key(key_id: int, user=Depends(current_user)):
    k = db.one("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    if not k:
        raise HTTPException(status_code=404, detail="Key not found")
    db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    return {"message": "Revoked"}
