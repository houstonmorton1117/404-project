"""
return_service.py

Business rules and validation for return requests.

Updated 11/14/26 - returns can now be 'approved' or 'rejected'. Approving a return refunds the
order in full through Stripe (refund_payment) and marks the order REFUNDED. The return is only
approved if the refund succeeds, and an order is never refunded twice.
"""

from db import get_connection
from models.checkout_model import get_order_payment_by_confirmation, update_order_payment_status
from models.return_model import (
    create_return_record,
    get_all_returns,
    get_return_by_id,
    update_return_status,
)
from utils.payments import PAID, REFUNDED, refund_payment

VALID_RETURN_STATUSES = ("pending", "reviewed", "approved", "rejected", "resolved")


class ReturnError(ValueError):
    """A return problem the admin should see. Subclasses ValueError so the admin routes answer 400."""


def _normalize_has_damage(value):
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    raise Exception("has_damage is required.")


def create_return_service(current_user, data, damage_image_url=None):
    if not current_user or not current_user.get("id"):
        raise Exception("Unauthorized.")

    order_number = str(data.get("order_number") or "").strip()
    reason = str(data.get("reason") or "").strip()
    raw_has_damage = data.get("has_damage")

    if not order_number:
        raise Exception("order_number is required.")
    if not reason:
        raise Exception("reason is required.")
    if raw_has_damage in (None, ""):
        raise Exception("has_damage is required.")

    has_damage = _normalize_has_damage(raw_has_damage)

    return create_return_record(
        user_id=current_user["id"],
        order_number=order_number,
        reason=reason,
        has_damage=has_damage,
        damage_image_url=damage_image_url,
        status="pending",
    )


def fetch_returns_service():
    return get_all_returns(include_deleted=False)


def update_return_status_service(return_id, status):
    return change_return_status(return_id, status)["return"]


def change_return_status(return_id, status):
    """
    Moves a return to a new status. Approving refunds the order first (see approve_return_with_refund).

    Returns {"return": <updated return>, "refund": <refund details or None>}.
    Raises ReturnError with an admin-facing message if the change isn't allowed.
    """
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in VALID_RETURN_STATUSES:
        raise ReturnError("status must be one of: " + ", ".join(VALID_RETURN_STATUSES) + ".")

    if normalized_status == "approved":
        return approve_return_with_refund(return_id)

    conn = get_connection()
    try:
        current = get_return_by_id(return_id, conn, for_update=True)
        if current is None:
            raise ReturnError("Return not found")
        if current["status"] == "approved" and normalized_status != "resolved":
            # The buyer has already been refunded; moving it back would make the record misleading.
            raise ReturnError("This return was already approved and refunded, so it can only be marked Resolved.")
        updated = update_return_status(return_id, normalized_status, conn=conn)
        conn.commit()
        return {"return": updated, "refund": None}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def approve_return_with_refund(return_id):
    """
    Approves a return and refunds its order in full through Stripe.

    The return's order_number is the order's confirmation number, typed by the buyer on the
    returns form. The return and the order are locked while this runs, so a double click or two
    admins can't refund the same order twice. If the refund fails, nothing is changed.
    """
    conn = get_connection()
    try:
        ret = get_return_by_id(return_id, conn, for_update=True)
        if ret is None:
            raise ReturnError("Return not found")
        if ret["status"] == "approved":
            conn.rollback()
            return {"return": ret, "refund": {"status": "already_approved"}}

        order_number = ret["order_number"]
        order = get_order_payment_by_confirmation(order_number, conn=conn, for_update=True)
        if order is None:
            raise ReturnError(
                f"Order {order_number} wasn't found, so it can't be refunded automatically. Check the "
                "order number with the buyer, or refund it in the Stripe Dashboard and mark the return Resolved."
            )
        if order["user_id"] != ret["user_id"]:
            raise ReturnError(
                f"Order {order_number} belongs to a different account than the one that asked for this "
                "return, so it wasn't refunded."
            )

        payment_status = order["payment_status"]
        if payment_status == REFUNDED:
            # Already refunded (e.g. from the Stripe Dashboard): approve without refunding again.
            refund = {"status": "already_refunded", "amount": order["total_amount"]}
        elif payment_status == PAID:
            intent_id = order["transaction_ref"] or ""
            if not intent_id.startswith("pi_"):
                raise ReturnError(
                    f"Order {order_number} wasn't paid through Stripe, so it can't be refunded "
                    "automatically. Refund the buyer another way and mark the return Resolved."
                )
            if not refund_payment(intent_id):
                raise ReturnError(
                    f"Stripe couldn't refund order {order_number}, so the return was not approved. "
                    "Try again, or check the payment in the Stripe Dashboard."
                )
            update_order_payment_status(order["id"], REFUNDED, conn=conn)
            refund = {"status": "refunded", "amount": order["total_amount"]}
        else:
            raise ReturnError(
                f"Order {order_number}'s payment is {payment_status}, not PAID, so there is nothing to refund."
            )

        updated = update_return_status(return_id, "approved", conn=conn)
        conn.commit()
        refund["confirmation_number"] = order["confirmation_number"]
        return {"return": updated, "refund": refund}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
