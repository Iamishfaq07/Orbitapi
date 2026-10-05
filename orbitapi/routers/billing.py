"""Subscription and plan management."""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..security import current_user

router = APIRouter(prefix="/api/v2/billing", tags=["billing"])

PLANS = {"free": 0, "pro": 4900, "enterprise": 49000}


class PlanBody(BaseModel):
    plan: str
    seats: Optional[int] = None


@router.get("/subscription")
def get_subscription(org_id: Optional[int] = None, user=Depends(current_user)):
    org = org_id if org_id is not None else user.get("org_id")
    sub = db.one("SELECT * FROM subscriptions WHERE org_id = ?", (org,))
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription")
    return sub


@router.post("/subscription/change-plan")
def change_plan(body: PlanBody, org_id: Optional[int] = None, user=Depends(current_user)):
    if body.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Unknown plan, choose one of {list(PLANS)}")
    org = org_id if org_id is not None else user.get("org_id")
    seats = body.seats if body.seats is not None else db.one(
        "SELECT seats FROM subscriptions WHERE org_id = ?", (org,))["seats"]
    db.execute("UPDATE subscriptions SET plan = ?, seats = ?, mrr_cents = ? WHERE org_id = ?",
               (body.plan, seats, PLANS[body.plan] * seats, org))
    db.execute("UPDATE organizations SET plan = ?, seats = ? WHERE id = ?", (body.plan, seats, org))
    return db.one("SELECT * FROM subscriptions WHERE org_id = ?", (org,))


@router.post("/credits/apply")
def apply_credits(body: dict = Body(...), user=Depends(current_user)):
    """Apply promotional account credit. Body: {"amount_cents": 500, "user_id": 1}"""
    uid = body.get("user_id", user.get("user_id"))
    amount = int(body.get("amount_cents", 0))
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id = ?", (amount, uid))
    return db.one("SELECT id, username, credit_balance FROM users WHERE id = ?", (uid,))


@router.get("/invoices.json")
def billing_invoices(org_id: Optional[int] = None, user=Depends(current_user)):
    org = org_id if org_id is not None else user.get("org_id")
    return db.query("SELECT o.*, u.full_name, u.email FROM orders o JOIN users u ON u.id = o.user_id "
                    "WHERE o.org_id = ? ORDER BY o.id DESC", (org,))
