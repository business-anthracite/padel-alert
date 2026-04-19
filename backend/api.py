"""
Padel Alert — API HTTP interne
Reçoit les webhooks WooCommerce pour créer/mettre à jour les users et abonnements en DB.
"""
import os
import logging
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, EmailStr

from database import upsert_user_subscription

log = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)

API_SECRET = os.environ.get("API_SECRET", "")


def _check_secret(x_api_secret: str | None):
    if not API_SECRET or x_api_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


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
