"""Stripe billing wrapper — Checkout, Customer Portal, Webhook.

Reads its config from env so a release can be cut without touching
code; if STRIPE_SECRET_KEY is unset the module loads but every
endpoint short-circuits with a clear 503, so unconfigured environments
(dev, demo) keep working.

Env vars:
    STRIPE_SECRET_KEY        sk_test_xxx or sk_live_xxx
    STRIPE_WEBHOOK_SECRET    whsec_xxx (from Stripe dashboard)
    STRIPE_PRICE_STARTER     price_xxx (recurring monthly EUR)
    STRIPE_PRICE_PRO         price_xxx
    STRIPE_PRICE_EARLY       price_xxx (optional legacy)
    PUBLIC_APP_URL           used for success/cancel return URLs
                             (defaults to the Railway preview URL)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("autotax.billing")

try:
    import stripe  # type: ignore
except ImportError:
    stripe = None  # billing endpoints will return 503

SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

PRICE_IDS: dict[str, str] = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", "").strip(),
    "pro":     os.getenv("STRIPE_PRICE_PRO", "").strip(),
    "premium": os.getenv("STRIPE_PRICE_PREMIUM", "").strip(),
    "early":   os.getenv("STRIPE_PRICE_EARLY", "").strip(),
}

_PRICE_TO_PLAN: Optional[dict[str, str]] = None


def _public_base() -> str:
    base = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if base:
        return base
    return "https://autotax-public-production-3f2a.up.railway.app"


def is_configured() -> bool:
    return bool(stripe and SECRET_KEY)


def _ensure_configured() -> None:
    if not stripe:
        raise RuntimeError("stripe SDK not installed")
    if not SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    stripe.api_key = SECRET_KEY


def price_to_plan(price_id: str) -> Optional[str]:
    global _PRICE_TO_PLAN
    if _PRICE_TO_PLAN is None:
        _PRICE_TO_PLAN = {pid: plan for plan, pid in PRICE_IDS.items() if pid}
    return _PRICE_TO_PLAN.get(price_id)


def plan_to_price(plan: str) -> Optional[str]:
    return PRICE_IDS.get(plan) or None


def get_or_create_customer(*, user_id: int, email: str, existing_id: Optional[str]) -> str:
    """Returns a Stripe Customer ID for this user. Caches via existing_id."""
    _ensure_configured()
    if existing_id:
        try:
            cust = stripe.Customer.retrieve(existing_id)
            if not getattr(cust, "deleted", False):
                return existing_id
        except Exception:
            logger.warning("Stripe customer %s missing — creating fresh", existing_id)
    cust = stripe.Customer.create(
        email=email,
        metadata={"autotax_user_id": str(user_id)},
    )
    return cust.id


def create_checkout_session(*, customer_id: str, plan: str, user_id: int) -> str:
    """Returns the Checkout URL the client should redirect to."""
    _ensure_configured()
    price = plan_to_price(plan)
    if not price:
        raise ValueError(f"Unknown plan '{plan}' — STRIPE_PRICE_{plan.upper()} env not set")
    base = _public_base()
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        success_url=f"{base}/app?subscription=success&plan={plan}",
        cancel_url=f"{base}/app?subscription=cancelled",
        allow_promotion_codes=True,
        client_reference_id=str(user_id),
        subscription_data={"metadata": {"autotax_user_id": str(user_id), "plan": plan}},
        locale="auto",
        billing_address_collection="auto",
        tax_id_collection={"enabled": True},
        customer_update={"name": "auto", "address": "auto"},
    )
    return session.url


def create_portal_session(*, customer_id: str) -> str:
    """Customer Portal: kart guncelle, abonelik iptal, fatura indir."""
    _ensure_configured()
    base = _public_base()
    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base}/app",
    )
    return portal.url


def verify_webhook(payload: bytes, signature: str):
    """Returns the Stripe event after signature verification."""
    _ensure_configured()
    if not WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not set")
    return stripe.Webhook.construct_event(payload, signature, WEBHOOK_SECRET)
