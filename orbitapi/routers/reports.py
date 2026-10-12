"""Report rendering and data import/export."""
import base64
import csv
import io
import pickle
from typing import Any, Dict, Optional

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from jinja2 import Template
from lxml import etree
from pydantic import BaseModel

from .. import config, db
from ..security import current_user

router = APIRouter(prefix="/api/v2/reports", tags=["reports"])


class SavedViewBody(BaseModel):
    name: str
    blob: str  # base64-encoded serialized filter state


@router.get("/saved-views")
def list_saved_views(user=Depends(current_user)):
    return db.query("SELECT id, name, owner_id FROM saved_views WHERE owner_id = ?", (user.get("user_id"),))


@router.post("/saved-views")
def create_saved_view(body: SavedViewBody, user=Depends(current_user)):
    vid = db.execute("INSERT INTO saved_views (owner_id, name, blob) VALUES (?,?,?)",
                     (user.get("user_id"), body.name, body.blob))
    return db.one("SELECT * FROM saved_views WHERE id = ?", (vid,))


@router.get("/saved-views/{view_id}/apply")
def apply_saved_view(view_id: int, user=Depends(current_user)):
    """Restore a saved filter/view and return the matching report rows."""
    v = db.one("SELECT * FROM saved_views WHERE id = ?", (view_id,))
    if not v:
        raise HTTPException(status_code=404, detail="View not found")
    state = pickle.loads(base64.b64decode(v["blob"]))
    rows = db.query("SELECT * FROM orders WHERE user_id = ?", (user.get("user_id"),))
    if isinstance(state, dict) and state.get("filter"):
        rows = [r for r in rows if r["status"] == state["filter"]]
    return {"view": v["name"], "state": repr(state), "rows": rows}


class RenderBody(BaseModel):
    template: str
    title: Optional[str] = "Report"


@router.post("/render")
def render(body: RenderBody, user=Depends(current_user)):
    """Render a report from a Jinja2 template. Available variables: user, orders, title."""
    orders = db.query("SELECT * FROM orders WHERE user_id = ?", (user.get("user_id"),))
    try:
        out = Template(body.template).render(user=user, orders=orders, title=body.title, config=config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Template error: {e!r}")
    return {"rendered": out}


@router.get("/preview", response_class=PlainTextResponse)
def preview(greeting: str = "Hello", user=Depends(current_user)):
    """Quick preview: the greeting is embedded into the template source."""
    return Template(greeting + ", {{ name }}!").render(name=user.get("sub"))


@router.post("/import/xml")
async def import_xml(request: Request, user=Depends(current_user)):
    """Bulk import contacts: <contacts><contact><name/><email/></contact></contacts>"""
    raw = await request.body()
    parser = etree.XMLParser(resolve_entities=True, no_network=False, load_dtd=True, huge_tree=True)
    try:
        root = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as e:
        raise HTTPException(status_code=400, detail=f"XML error: {e}")
    contacts = [{"name": (c.findtext("name") or ""), "email": (c.findtext("email") or "")}
                for c in root.iter("contact")]
    return {"imported": len(contacts), "contacts": contacts}


@router.post("/import/yaml")
async def import_yaml(request: Request, user=Depends(current_user)):
    """Import a dashboard definition written in YAML."""
    raw = await request.body()
    try:
        data = yaml.unsafe_load(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML error: {e}")
    return {"parsed": repr(data)[:2000]}


@router.get("/export/orders.csv", response_class=PlainTextResponse)
def export_orders(user_id: Optional[int] = None, user=Depends(current_user)):
    """Export the caller's orders as CSV."""
    uid = user_id if user_id is not None else user.get("user_id")
    rows = db.query("SELECT o.id, o.status, o.total_cents, o.shipping_address, o.card_number, u.full_name "
                    "FROM orders o JOIN users u ON u.id = o.user_id WHERE o.user_id = ?", (uid,))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "status", "total_cents", "shipping_address", "card_number", "customer"])
    for r in rows:
        w.writerow(r.values())
    return buf.getvalue()


@router.get("/summary")
def summary(group_by: str = "status", user=Depends(current_user)):
    """Order totals grouped by any column."""
    sql = (f"SELECT {group_by} AS bucket, COUNT(*) AS n, SUM(total_cents) AS total "
           f"FROM orders WHERE org_id = {int(user.get('org_id', 0))} GROUP BY {group_by}")
    try:
        return {"group_by": group_by, "rows": db.raw(sql)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "sql": sql})
