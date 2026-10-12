"""Webhooks, payment-provider callbacks and currency conversion."""
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from .. import config, db
from ..security import current_user

router = APIRouter(prefix="/api/v2", tags=["integrations"])

BLOCKED_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal")


class WebhookBody(BaseModel):
    url: str
    event: str = "order.paid"


@router.get("/webhooks")
def list_webhooks(user=Depends(current_user)):
    return db.query("SELECT * FROM webhooks WHERE org_id = ?", (user.get("org_id"),))


@router.post("/webhooks")
def create_webhook(body: WebhookBody, user=Depends(current_user)):
    if any(h in body.url for h in BLOCKED_HOSTS):
        raise HTTPException(status_code=400, detail="That host is not allowed")
    wid = db.execute("INSERT INTO webhooks (user_id, org_id, url, event, signing_secret) VALUES (?,?,?,?,?)",
                     (user.get("user_id"), user.get("org_id"), body.url, body.event,
                      "whsec_" + secrets.token_hex(6)))
    return db.one("SELECT * FROM webhooks WHERE id = ?", (wid,))


@router.get("/webhooks/{webhook_id}")
def get_webhook(webhook_id: int, user=Depends(current_user)):
    w = db.one("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
    if not w:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return w


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: int, method: str = "POST", user=Depends(current_user)):
    """Sends a sample event to the webhook URL and returns what came back."""
    w = db.one("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
    if not w:
        raise HTTPException(status_code=404, detail="Webhook not found")
    payload = {"event": w["event"], "test": True, "org_id": w["org_id"]}
    try:
        r = requests.request(method, w["url"], json=payload, timeout=5,
                             headers={"X-Orbit-Internal-Token": config.INTERNAL_SERVICE_TOKEN})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Delivery failed: {e}")
    return {"delivered_to": w["url"], "status": r.status_code,
            "response_headers": dict(r.headers), "response_body": r.text[:5000]}


@router.post("/integrations/payments/callback")
async def payment_callback(request: Request, x_orbit_signature: Optional[str] = Header(default=None)):
    """Called by the payment provider when an order is paid/refunded.
    Body: {"order_id": 4, "status": "paid", "amount_cents": 2500}"""
    raw = await request.body()
    if x_orbit_signature is not None:
        expected = hmac.new(config.PAYMENT_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if x_orbit_signature != expected:
            raise HTTPException(status_code=401, detail=f"Bad signature, expected {expected[:8]}...")
    data = json.loads(raw or b"{}")
    order = db.one("SELECT * FROM orders WHERE id = ?", (data.get("order_id"),))
    if not order:
        raise HTTPException(status_code=404, detail="Unknown order")
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (data.get("status", "paid"), order["id"]))
    if data.get("status") == "refunded":
        db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id = ?",
                   (int(data.get("amount_cents", order["total_cents"])), order["user_id"]))
    return {"ok": True, "order_id": order["id"], "status": data.get("status", "paid")}


@router.get("/fx/mock-provider")
def fx_mock_provider(base: str = "USD", to: str = "EUR"):
    """Stand-in for the third-party FX API."""
    rates = {"EUR": 0.92, "GBP": 0.79, "INR": 83.1, "JPY": 151.0}
    return {"base": base, "to": to, "rate": rates.get(to.upper(), 1.0), "provider": "mockfx"}


@router.get("/fx/convert")
def fx_convert(amount: float, to: str = "EUR", request: Request = None,
               provider_url: Optional[str] = None, user=Depends(current_user)):
    """Convert an amount between currencies using the configured rate provider."""
    url = provider_url or str(request.base_url).rstrip("/") + "/api/v2/fx/mock-provider"
    r = None
    try:
        r = requests.get(url, params={"base": "USD", "to": to}, timeout=5)
        data = r.json()
    except Exception as e:
        body = r.text[:1000] if r is not None else ""
        raise HTTPException(status_code=502, detail=f"Provider error from {url}: {e}; body={body}")
    rate = data.get("rate")
    result: Dict[str, Any] = {"amount": amount, "to": to, "rate": rate, "provider": data.get("provider")}
    # Optional pricing formula for exotic currency pairs.
    if "formula" in data:
        result["converted"] = eval(str(data["formula"]), {"amount": amount, "rate": rate})
    else:
        result["converted"] = round(amount * float(rate), 2)
    return result
