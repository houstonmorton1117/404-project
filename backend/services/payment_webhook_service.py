# backend/services/payment_webhook_service.py
# The Vault Campus Marketplace
# Added 11/14/26 for the payment token system.
#
# Keeps each order's payment_status in step with Stripe. Stripe sends a webhook whenever a
# payment changes (charged, failed, refunded, ...); the controller checks the signature and
# hands the event here. Orders are matched by orders.transaction_ref, which holds the Stripe
# PaymentIntent id ("pi_...") used to pay for the order.
#
# Stripe can deliver events late, twice, or out of order, so a status only moves forward:
# for example, a late "payment succeeded" event never turns a REFUNDED order back into PAID.

from db import get_connection
from models.checkout_model import get_order_payment_by_ref, update_order_payment_status
from utils.payments import AUTHORIZED, FAILED, PAID, REFUNDED

# Which status each status is allowed to change into.
ALLOWED_CHANGES = {
    AUTHORIZED: {PAID, FAILED, REFUNDED},
    PAID: {REFUNDED},
    FAILED: {AUTHORIZED, PAID},   # a failed attempt can still be followed by a successful one
    REFUNDED: set(),              # final
}

# Stripe event type -> the payment status it means
EVENT_STATUS = {
    "payment_intent.amount_capturable_updated": AUTHORIZED,   # card hold placed
    "payment_intent.succeeded": PAID,                         # hold captured, buyer charged
    "payment_intent.payment_failed": FAILED,
    "payment_intent.canceled": FAILED,                        # hold released or expired
    "charge.refunded": REFUNDED,
}


def _field(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None


def _status_change_for(event):
    """Returns (payment_intent_id, new_status) for events we track, otherwise (None, None)."""
    event_type = _field(event, "type")
    new_status = EVENT_STATUS.get(event_type)
    if new_status is None:
        return None, None

    obj = _field(_field(event, "data"), "object")
    if event_type == "charge.refunded":
        # Only a full refund makes the order REFUNDED; a partial refund leaves it PAID.
        if not _field(obj, "refunded"):
            return None, None
        return _field(obj, "payment_intent"), new_status
    return _field(obj, "id"), new_status


def handle_stripe_event(event):
    """
    Applies a verified Stripe event to the matching order.

    Returns a small dict describing what happened, e.g.
        {"handled": True, "order_id": 12, "from": "PAID", "to": "REFUNDED"}
        {"handled": False, "reason": "no matching order"}
    """
    intent_id, new_status = _status_change_for(event)
    if not intent_id:
        return {"handled": False, "reason": "event type not tracked"}

    conn = get_connection()
    try:
        # Lock the order so two events for the same payment can't both change it at once.
        order = get_order_payment_by_ref(intent_id, conn=conn, for_update=True)
        if not order:
            # e.g. a payment from a checkout that was abandoned or rolled back; nothing to update.
            conn.rollback()
            return {"handled": False, "reason": "no matching order"}

        current = order["payment_status"]
        if current == new_status:
            conn.rollback()
            return {"handled": False, "order_id": order["id"], "reason": f"already {current}"}

        allowed = ALLOWED_CHANGES.get(current)
        if allowed is not None and new_status not in allowed:
            conn.rollback()
            print(f"[webhook] ignoring {current} -> {new_status} for order {order['id']} ({intent_id})")
            return {"handled": False, "order_id": order["id"],
                    "reason": f"{current} can't change to {new_status}"}

        update_order_payment_status(order["id"], new_status, conn=conn)
        conn.commit()
        return {"handled": True, "order_id": order["id"], "from": current, "to": new_status}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
