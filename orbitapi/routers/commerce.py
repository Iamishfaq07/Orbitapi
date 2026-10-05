"""Products, orders, coupons and wallet endpoints."""
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db
from ..security import current_user, is_admin

router = APIRouter(prefix="/api/v2", tags=["commerce"])


class OrderBody(BaseModel):
    product_id: int
    quantity: int = 1
    coupon: Optional[str] = None
    unit_price_cents: Optional[int] = None  # "used by the POS integration"
    shipping_address: Optional[str] = None
    card_number: Optional[str] = None


class CouponBody(BaseModel):
    code: str


class TransferBody(BaseModel):
    to_user_id: int
    amount: int
    note: str = ""


@router.get("/products")
def list_products(include_hidden: bool = False, fields: Optional[str] = None):
    """Public product catalogue."""
    rows = db.query("SELECT * FROM products" + ("" if include_hidden else " WHERE is_hidden = 0"))
    if fields:
        wanted = [f.strip() for f in fields.split(",")]
        rows = [{k: r.get(k) for k in wanted} for r in rows]
    else:
        for r in rows:
            r.pop("internal_cost_cents", None)
            r.pop("supplier", None)
    return rows


@router.get("/products/{product_id}")
def get_product(product_id: int):
    p = db.one("SELECT * FROM products WHERE id = ?", (product_id,))
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p


def _consume_coupon(code: str, user) -> int:
    c = db.one("SELECT * FROM coupons WHERE code = ?", (code.upper(),))
    if not c or not c["active"]:
        raise HTTPException(status_code=400, detail="Invalid coupon")
    if c["staff_only"] and not (is_admin(user) or user.get("is_support")):
        raise HTTPException(status_code=403, detail="Staff coupon")
    if c["used_count"] >= c["max_uses"]:
        raise HTTPException(status_code=400, detail="Coupon fully redeemed")
    time.sleep(0.3)
    db.execute("UPDATE coupons SET used_count = used_count + 1 WHERE code = ?", (c["code"],))
    return c["discount_pct"]


@router.post("/coupons/validate")
def validate_coupon(body: CouponBody):
    """Check whether a coupon code is valid."""
    c = db.one("SELECT code, discount_pct, max_uses, used_count, active FROM coupons WHERE code = ?",
               (body.code.upper(),))
    if not c:
        raise HTTPException(status_code=404, detail="No such coupon")
    return c


@router.post("/orders")
def create_order(body: OrderBody, user=Depends(current_user)):
    p = db.one("SELECT * FROM products WHERE id = ?", (body.product_id,))
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if body.quantity == 0:
        raise HTTPException(status_code=400, detail="Quantity must not be zero")
    if body.quantity > p["stock"]:
        raise HTTPException(status_code=409, detail=f"Only {p['stock']} left")

    unit = body.unit_price_cents if body.unit_price_cents is not None else p["price_cents"]
    total = unit * body.quantity
    if body.coupon:
        total = int(total * (100 - _consume_coupon(body.coupon, user)) / 100)

    balance = db.one("SELECT credit_balance FROM users WHERE id = ?", (user.get("user_id"),))
    balance = balance["credit_balance"] if balance else 0
    if total > balance:
        raise HTTPException(status_code=402, detail=f"Insufficient credit: need {total}, have {balance}")

    db.execute("UPDATE users SET credit_balance = credit_balance - ? WHERE id = ?", (total, user.get("user_id")))
    db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (body.quantity, p["id"]))
    card = body.card_number or ""
    oid = db.execute(
        "INSERT INTO orders (user_id, org_id, product_id, quantity, unit_price_cents, total_cents, coupon_code,"
        " status, shipping_address, card_last4, card_number) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user.get("user_id"), user.get("org_id"), p["id"], body.quantity, unit, total, body.coupon,
         "paid", body.shipping_address, card[-4:] if card else None, card or None),
    )
    return db.one("SELECT * FROM orders WHERE id = ?", (oid,))


@router.get("/orders")
def list_orders(user_id: Optional[int] = None, user=Depends(current_user)):
    uid = user_id if user_id is not None else user.get("user_id")
    return db.query("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (uid,))


@router.get("/orders/{order_id}")
def get_order(order_id: int, user=Depends(current_user)):
    o = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


@router.post("/orders/{order_id}/refund")
def refund_order(order_id: int, user=Depends(current_user)):
    o = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o["user_id"] != user.get("user_id") and not is_admin(user):
        raise HTTPException(status_code=403, detail="Not your order")
    if o["status"] == "shipped":
        raise HTTPException(status_code=409, detail="Shipped orders cannot be refunded")
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id = ?", (o["total_cents"], o["user_id"]))
    db.execute("INSERT INTO transactions (from_user_id, to_user_id, amount, note) VALUES (NULL, ?, ?, ?)",
               (o["user_id"], o["total_cents"], f"refund order {order_id}"))
    return {"message": "Refund issued", "amount": o["total_cents"]}


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, user=Depends(current_user)):
    o = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    return {"message": "Order cancelled", "order_id": order_id}


@router.get("/wallet")
def wallet(user=Depends(current_user)):
    row = db.one("SELECT id, username, credit_balance FROM users WHERE id = ?", (user.get("user_id"),))
    if not row:
        raise HTTPException(status_code=404, detail="No wallet")
    return row


@router.post("/wallet/transfer")
def transfer(body: TransferBody, user=Depends(current_user)):
    sender = db.one("SELECT * FROM users WHERE id = ?", (user.get("user_id"),))
    recipient = db.one("SELECT * FROM users WHERE id = ?", (body.to_user_id,))
    if not sender or not recipient:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount > sender["credit_balance"]:
        raise HTTPException(status_code=402, detail="Insufficient balance")
    time.sleep(0.3)  # ledger service round-trip
    db.execute("UPDATE users SET credit_balance = ? WHERE id = ?",
               (sender["credit_balance"] - body.amount, sender["id"]))
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id = ?", (body.amount, recipient["id"]))
    db.execute("INSERT INTO transactions (from_user_id, to_user_id, amount, note) VALUES (?,?,?,?)",
               (sender["id"], recipient["id"], body.amount, body.note))
    return {"message": "Transfer complete", "new_balance": sender["credit_balance"] - body.amount}


@router.get("/wallet/transactions")
def transactions(user_id: Optional[int] = None, limit: int = 50, user=Depends(current_user)):
    uid = user_id if user_id is not None else user.get("user_id")
    return db.query("SELECT * FROM transactions WHERE from_user_id = ? OR to_user_id = ? "
                    "ORDER BY id DESC LIMIT ?", (uid, uid, limit))
