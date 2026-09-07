"""Project and invoice endpoints (v0 compatibility surface).

The original clients call these unprefixed routes. They now read from the
database and go through the shared project policy in `authz`.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import authz, db
from .security import current_user

router = APIRouter(tags=["projects"])


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    budget: Optional[int] = None
    visibility: Optional[str] = None
    owner_id: Optional[int] = None


class InvoiceCreate(BaseModel):
    project_id: int
    amount: int


@router.get("/projects/{project_id}")
def get_project(project_id: int, user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not authz.can_read_project(proj, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return proj


@router.put("/projects/{project_id}")
def update_project(project_id: int, update: ProjectUpdate, user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not authz.can_write_project(proj, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    fields = {k: v for k, v in update.dict().items() if v is not None}
    if fields:
        db.execute(f"UPDATE projects SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?",
                   [*fields.values(), project_id])
    return authz.load_project(project_id)


@router.post("/invoices")
def create_invoice(body: InvoiceCreate, user=Depends(current_user)):
    proj = authz.load_project(body.project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not authz.can_read_project(proj, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    iid = db.execute("INSERT INTO invoices (project_id, org_id, amount, status, created_by) VALUES (?,?,?,?,?)",
                     (body.project_id, proj["org_id"], body.amount, "draft", user.get("user_id")))
    db.execute("UPDATE projects SET last_invoice_id = ? WHERE id = ?", (iid, body.project_id))
    return db.one("SELECT * FROM invoices WHERE id = ?", (iid,))


@router.get("/org/projects")
def list_org_projects(user=Depends(current_user)):
    return db.query("SELECT * FROM projects WHERE org_id = ?", (user.get("org_id"),))
