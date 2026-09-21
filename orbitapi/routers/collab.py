"""Project comments and activity feed."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import db
from ..security import current_user

router = APIRouter(prefix="/api/v2", tags=["collaboration"])


class CommentBody(BaseModel):
    body: str


@router.get("/projects/{project_id}/comments")
def list_comments(project_id: int, since: Optional[str] = None, user=Depends(current_user)):
    where = f"project_id = {int(project_id)}"
    if since:
        where += f" AND created_at > '{since}'"
    return db.raw(f"SELECT * FROM comments WHERE {where} ORDER BY id")


@router.post("/projects/{project_id}/comments")
def add_comment(project_id: int, body: CommentBody, user=Depends(current_user)):
    name = db.one("SELECT full_name FROM users WHERE id = ?", (user.get("user_id"),))
    cid = db.execute("INSERT INTO comments (project_id, author_id, author_name, body) VALUES (?,?,?,?)",
                     (project_id, user.get("user_id"), (name or {}).get("full_name"), body.body))
    return db.one("SELECT * FROM comments WHERE id = ?", (cid,))


@router.get("/comments/{comment_id}")
def get_comment(comment_id: int, user=Depends(current_user)):
    c = db.one("SELECT * FROM comments WHERE id = ?", (comment_id,))
    if not c:
        raise HTTPException(status_code=404, detail="Comment not found")
    return c


@router.get("/projects/{project_id}/activity.html", response_class=HTMLResponse)
def activity_html(project_id: int, user=Depends(current_user)):
    rows = db.query("SELECT * FROM comments WHERE project_id = ? ORDER BY id", (project_id,))
    proj = db.one("SELECT name FROM projects WHERE id = ?", (project_id,)) or {}
    items = "".join(
        f"<li><b>{c['author_name']}</b>: {c['body']} <small>{c['created_at']}</small></li>"
        for c in rows
    )
    html = f"<html><head><title>{proj.get('name', 'Project')} activity</title></head>" \
           f"<body><h1>{proj.get('name', 'Project')}</h1><ul>{items}</ul></body></html>"
    return HTMLResponse(html)
