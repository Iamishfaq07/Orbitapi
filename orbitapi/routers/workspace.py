"""Projects, invoices, notes and support tickets."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from .. import authz, db
from ..security import current_user, is_admin

router = APIRouter(prefix="/api/v2", tags=["workspace"])


class PayBody(BaseModel):
    amount: int
    method: str = "card"


class NoteBody(BaseModel):
    title: str
    content: str
    is_private: bool = True


class TicketBody(BaseModel):
    subject: str
    body: str
    priority: str = "normal"


# ---------------------------------------------------------------- projects

@router.get("/projects")
def list_projects(org_id: Optional[int] = None, status: Optional[str] = None, user=Depends(current_user)):
    org = org_id if org_id is not None else user.get("org_id")
    if status:
        return db.query("SELECT * FROM projects WHERE org_id = ? AND status = ?", (org, status))
    return db.query("SELECT * FROM projects WHERE org_id = ?", (org,))


@router.get("/projects/{project_id}")
def get_project(project_id: int, user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not authz.can_read_project(proj, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    shares = db.query("SELECT principal_type, principal_id, access FROM project_shares WHERE project_id = ?",
                      (project_id,))
    return {**proj, "shares": shares}


@router.post("/projects")
def create_project(body: Dict[str, Any] = Body(...), user=Depends(current_user)):
    row = {"org_id": user.get("org_id"), "owner_id": user.get("user_id"), "name": body.get("name", "Untitled"),
           "sensitivity": "internal", "budget": 0, "status": "active", "visibility": "org"}
    for k in ("org_id", "owner_id", "name", "sensitivity", "budget", "status", "visibility"):
        if k in body:
            row[k] = body[k]
    cols = ", ".join(row)
    pid = db.execute(f"INSERT INTO projects ({cols}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    return authz.load_project(pid)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, changes: Dict[str, Any] = Body(...), user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not authz.can_write_project(proj, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    allowed = {"name", "status", "budget", "sensitivity", "visibility"}
    sets = {k: v for k, v in changes.items() if k in allowed}
    if sets:
        db.execute(f"UPDATE projects SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                   [*sets.values(), project_id])
    return authz.load_project(project_id)


@router.post("/projects/{project_id}/shares")
def add_share(project_id: int, body: Dict[str, Any] = Body(...), user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if proj["owner_id"] != user.get("user_id") and not is_admin(user):
        raise HTTPException(status_code=403, detail="Only the owner can share")
    sid = db.execute("INSERT INTO project_shares (project_id, principal_type, principal_id, access) VALUES (?,?,?,?)",
                     (project_id, body.get("principal_type", "user"), int(body["principal_id"]),
                      body.get("access", "read")))
    return db.one("SELECT * FROM project_shares WHERE id = ?", (sid,))


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, user=Depends(current_user)):
    proj = authz.load_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if user.get("role") not in ("admin", "owner", "member") or proj["org_id"] != user.get("org_id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return {"message": f"Project {project_id} deleted"}


@router.get("/projects/{project_id}/invoices")
def project_invoices(project_id: int, user=Depends(current_user)):
    return db.query("SELECT * FROM invoices WHERE project_id = ?", (project_id,))


# ---------------------------------------------------------------- invoices

@router.get("/invoices")
def list_invoices(status: Optional[str] = None, user=Depends(current_user)):
    if status:
        return db.query("SELECT * FROM invoices WHERE org_id = ? AND status = ?", (user.get("org_id"), status))
    return db.query("SELECT * FROM invoices WHERE org_id = ?", (user.get("org_id"),))


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, user=Depends(current_user)):
    inv = db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    proj = db.one("SELECT name, budget FROM projects WHERE id = ?", (inv["project_id"],)) or {}
    return {**inv, "project_name": proj.get("name"), "project_budget": proj.get("budget")}


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, user=Depends(current_user)):
    inv = db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if user.get("role") in ("viewer", "member"):
        raise HTTPException(status_code=403, detail="Billing approval required")
    db.execute("UPDATE invoices SET status = 'approved', approved_by = ? WHERE id = ?",
               (user.get("user_id"), invoice_id))
    return db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: int, body: PayBody, user=Depends(current_user)):
    inv = db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["status"] not in ("approved", "issued", "draft"):
        raise HTTPException(status_code=409, detail=f"Invoice is {inv['status']}")
    db.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
    return {**db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,)), "paid_amount": body.amount}


# ---------------------------------------------------------------- notes

@router.get("/notes")
def list_notes(user=Depends(current_user)):
    return db.query("SELECT id, title, owner_id, is_private FROM notes WHERE org_id = ? "
                    "AND (is_private = 0 OR owner_id = ?)", (user.get("org_id"), user.get("user_id")))


@router.post("/notes")
def create_note(body: NoteBody, user=Depends(current_user)):
    nid = db.execute("INSERT INTO notes (owner_id, org_id, title, content, is_private) VALUES (?,?,?,?,?)",
                     (user.get("user_id"), user.get("org_id"), body.title, body.content, int(body.is_private)))
    return db.one("SELECT * FROM notes WHERE id = ?", (nid,))


@router.get("/notes/{note_id}")
def get_note(note_id: int, user=Depends(current_user)):
    note = db.one("SELECT * FROM notes WHERE id = ?", (note_id,))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note["org_id"] != user.get("org_id") and not is_admin(user):
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.put("/notes/{note_id}")
def update_note(note_id: int, body: NoteBody, user=Depends(current_user)):
    note = db.one("SELECT * FROM notes WHERE id = ?", (note_id,))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.execute("UPDATE notes SET title = ?, content = ?, is_private = ? WHERE id = ?",
               (body.title, body.content, int(body.is_private), note_id))
    return db.one("SELECT * FROM notes WHERE id = ?", (note_id,))


# ---------------------------------------------------------------- tickets

@router.get("/tickets")
def list_tickets(status: Optional[str] = None, user=Depends(current_user)):
    # Support staff service every tenant; everyone else sees only their own tickets.
    if user.get("is_support"):
        rows = db.query("SELECT * FROM tickets")
    else:
        rows = db.query("SELECT * FROM tickets WHERE user_id = ?", (user.get("user_id"),))
    for r in rows:
        r.pop("internal_notes", None)
    return [r for r in rows if not status or r["status"] == status]


@router.post("/tickets")
def create_ticket(body: TicketBody, user=Depends(current_user)):
    tid = db.execute("INSERT INTO tickets (user_id, org_id, subject, body, priority) VALUES (?,?,?,?,?)",
                     (user.get("user_id"), user.get("org_id"), body.subject, body.body, body.priority))
    return db.one("SELECT * FROM tickets WHERE id = ?", (tid,))


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, user=Depends(current_user)):
    t = db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, changes: Dict[str, Any] = Body(...), user=Depends(current_user)):
    t = db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if t["user_id"] != user.get("user_id") and not user.get("is_support"):
        raise HTTPException(status_code=403, detail="Not your ticket")
    allowed = {"subject", "body", "status", "priority", "assigned_to", "internal_notes"}
    sets = {k: v for k, v in changes.items() if k in allowed}
    if sets:
        db.execute(f"UPDATE tickets SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                   [*sets.values(), ticket_id])
    return db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
