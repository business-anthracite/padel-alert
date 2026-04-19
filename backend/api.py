"""
Padel Alert — API HTTP interne
Reçoit les webhooks WooCommerce pour créer/mettre à jour les users et abonnements en DB.
"""
import os
import logging
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, EmailStr

from database import (
    upsert_user_subscription,
    get_user_with_subscription,
    get_user_alerts,
    create_alert,
    delete_alert,
    toggle_alert,
)
from criteria import PLAN_ALERT_LIMITS

log = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)

API_SECRET = os.environ.get("API_SECRET", "")


def _check_secret(x_api_secret: str | None):
    if not API_SECRET or x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class AlertCreate(BaseModel):
    name: str | None = None
    location_type: str = "ville"
    location_value: str
    location_label: str
    lat: float | None = None
    lng: float | None = None
    radius_km: int = 80
    match_types: list[str] = ["DM"]
    age_categories: list[str] = ["200"]
    competition_types: list[str] = ["P"]
    tournament_categories: list[str] = ["P50", "P100"]


class AlertToggle(BaseModel):
    is_active: bool


class SubscriptionWebhook(BaseModel):
    email: str
    first_name: str
    last_name: str
    plan: str            # "standard" | "premium"
    billing_period: str  # "monthly" | "annual"
    stripe_subscription_id: str | None = None
    wc_subscription_id: int | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Alertes ────────────────────────────────────────────────────────────────────

@app.get("/users/{email}/alerts")
def list_alerts(email: str, x_api_secret: str | None = Header(default=None)):
    _check_secret(x_api_secret)
    user = get_user_with_subscription(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    alerts = get_user_alerts(str(user["id"]))
    plan = user.get("plan_type") or "standard"
    limit = PLAN_ALERT_LIMITS.get(plan)
    # Convert UUIDs and dates to strings for JSON
    for a in alerts:
        a["id"] = str(a["id"])
    return {
        "user": {
            "id": str(user["id"]),
            "first_name": user["first_name"],
            "plan": plan,
            "status": user.get("status"),
        },
        "alerts": alerts,
        "limit": limit,
        "can_add": limit is None or len(alerts) < limit,
    }


@app.post("/users/{email}/alerts", status_code=201)
def add_alert(email: str, payload: AlertCreate, x_api_secret: str | None = Header(default=None)):
    _check_secret(x_api_secret)
    user = get_user_with_subscription(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("status"):
        raise HTTPException(status_code=403, detail="No active subscription")

    plan = user.get("plan_type") or "standard"
    limit = PLAN_ALERT_LIMITS.get(plan)
    existing = get_user_alerts(str(user["id"]))
    if limit is not None and len(existing) >= limit:
        raise HTTPException(status_code=403, detail=f"Alert limit reached ({limit})")

    alert = create_alert(str(user["id"]), payload.model_dump())
    alert["id"] = str(alert["id"])
    return alert


@app.delete("/alerts/{alert_id}")
def remove_alert(alert_id: str, email: str, x_api_secret: str | None = Header(default=None)):
    _check_secret(x_api_secret)
    user = get_user_with_subscription(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ok = delete_alert(alert_id, str(user["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "deleted"}


@app.patch("/alerts/{alert_id}/toggle")
def toggle(alert_id: str, payload: AlertToggle, email: str, x_api_secret: str | None = Header(default=None)):
    _check_secret(x_api_secret)
    user = get_user_with_subscription(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ok = toggle_alert(alert_id, str(user["id"]), payload.is_active)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "ok", "is_active": payload.is_active}


# ── Webhook WooCommerce ─────────────────────────────────────────────────────────

@app.post("/webhook/subscription")
def webhook_subscription(
    payload: SubscriptionWebhook,
    x_api_secret: str | None = Header(default=None),
):
    _check_secret(x_api_secret)
    try:
        result = upsert_user_subscription(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            plan=payload.plan,
            billing_period=payload.billing_period,
            stripe_subscription_id=payload.stripe_subscription_id,
            wc_subscription_id=payload.wc_subscription_id,
        )
        log.info(f"Webhook subscription OK — user_id={result['user_id']} sub_id={result['subscription_id']}")
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"Webhook subscription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
