# The Vault Campus Marketplace
# Modified by Jasmine Mark 10/25/26 - Checkout now uses one databse connection and failed stock update cancels the entire transaction. Added OutOfStockError class to handle stock issues.
# Edited By Saffie C. Oct 27
# Updated 10/27/26 - payments now go through Stripe tokens; card is held, then charged only once the order is saved

import random
import string
from datetime import datetime

from db import get_connection
from models.checkout_model import (
    create_order,
    create_order_item,
    get_order_by_confirmation,
    get_order_items_by_order_id,
    get_orders_by_user_id,
    clear_cart_for_user,
    update_listing_size_inventory,
    update_listing_quantity_inventory,
    remove_purchased_from_wishlist,
    check_listing_availability,
)
from utils.payments import (
    PaymentError,
    authorize_payment,
    cancel_payment,
    capture_payment,
    refund_payment,
)

# Raw card fields the old checkout form used to send. Only Stripe's token is accepted now,
# so a request carrying any of these is refused before anything else happens.
RAW_CARD_FIELDS = ("card_number", "card_expiry", "cvv", "cvc", "card_cvc")


class CheckoutError(Exception):
    """A checkout problem the buyer should see (empty cart, missing details, declined card)."""


def _generate_confirmation_number():
    date_str = datetime.now().strftime("%y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"VAULT-{date_str}-{suffix}"


def complete_transaction_from_session(user_id, session_cart, buyer_details):
    """
    Completes checkout using session cart and submitted buyer details.

    buyer_details keys: first_name, last_name, email, contact, meeting_location
    session_cart items: { id, name, price, quantity, size }
    """
    if not session_cart:
        raise CheckoutError("Cart is empty.")

    if any(buyer_details.get(field) for field in RAW_CARD_FIELDS):
        raise CheckoutError(
            "For your security, card details can't be sent to our server. "
            "Please refresh the checkout page and try again."
        )

    # Each add-to-cart appends a line, so total the quantity per listing/size before checking stock.
    requested = {}
    for item in session_cart:
        item_id = item.get("id")
        quantity = int(item.get("quantity", 1))
        if not item_id:
            raise CheckoutError("Your cart contains an invalid item. Please remove it and try again.")
        if quantity < 1:
            raise CheckoutError("Item quantities must be at least 1.")
        key = (int(item_id), item.get("size"))
        requested[key] = requested.get(key, 0) + quantity

    # Everything from the stock check to clearing the cart runs in one transaction on one connection:
    # either the order, its items, the stock decrease, and the cleared cart are all saved, or none are.
    # The card is charged (captured) only after every database step has succeeded, right before the
    # commit. If anything fails first, the hold is released; if the commit itself fails after the
    # charge, the charge is refunded. Either way the buyer is never charged without an order.
    conn = get_connection()
    payment = {}  # _complete_transaction fills this in once Stripe has placed a hold
    captured = False
    try:
        result = _complete_transaction(conn, user_id, session_cart, buyer_details, requested, payment)
        try:
            capture_payment(payment["intent_id"])
        except PaymentError as e:
            raise CheckoutError(str(e))
        captured = True
        conn.commit()
    except Exception:
        if payment.get("intent_id"):
            if captured:
                refund_payment(payment["intent_id"])
            else:
                cancel_payment(payment["intent_id"])
        conn.rollback()
        raise
    finally:
        conn.close()

    # Wishlist cleanup is a nice-to-have, so it runs after the commit and can't undo a completed purchase.
    purchased_listing_ids = [item["listing_id"] for item in result["order_items"]]
    try:
        remove_purchased_from_wishlist(user_id, purchased_listing_ids)
    except Exception as e:
        print(f"[checkout] wishlist cleanup failed: {e}")

    return result


def _complete_transaction(conn, user_id, session_cart, buyer_details, requested, payment):
    """Runs the checkout steps on the caller's connection without committing.
    Places a payment hold and records its details in `payment` so the caller can capture or release it."""
    # Validate availability and re-price every item from the database; cart prices are display-only.
    # Each listing row stays locked until the transaction ends, so a second buyer for the same listing
    # waits here and then sees the reduced stock. Locking in listing-id order prevents deadlocks.
    listing_info = {}
    for (item_id, size), quantity in sorted(requested.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        listing_info[item_id] = check_listing_availability(item_id, quantity, size, conn=conn)

    priced_items = []
    for item in session_cart:
        title, price, is_made_to_order = listing_info[int(item["id"])]
        priced_items.append({
            "id": int(item["id"]),
            "name": title,
            "price": price,
            "quantity": int(item.get("quantity", 1)),
            "size": item.get("size"),
            "is_made_to_order": is_made_to_order,
        })

    first_name = (buyer_details.get("first_name") or "").strip()
    last_name = (buyer_details.get("last_name") or "").strip()
    email = (buyer_details.get("email") or "").strip()
    contact = (buyer_details.get("contact") or "").strip()
    meeting_location = (buyer_details.get("meeting_location") or "").strip()

    if not all([first_name, last_name, email, contact, meeting_location]):
        raise CheckoutError("All buyer details are required.")

    total_amount = round(sum(item["price"] * item["quantity"] for item in priced_items), 2)

    confirmation_number = _generate_confirmation_number()

    # Stripe places a hold for the server-computed total using the token the browser got from
    # Stripe.js. A declined card stops checkout here, before any order record is written.
    payment_method_id = buyer_details.get("payment_method_id")
    try:
        authorization = authorize_payment(
            payment_method_id=payment_method_id,
            amount=total_amount,
            cardholder_name=buyer_details.get("cardholder_name"),
            # A repeated submit of the same token for the same order reuses Stripe's first result
            # instead of placing a second hold.
            idempotency_key=f"checkout-{user_id}-{payment_method_id}-{total_amount:.2f}",
            metadata={"user_id": str(user_id), "confirmation_number": confirmation_number},
        )
    except PaymentError as e:
        raise CheckoutError(str(e))
    payment.update(authorization)

    order = create_order(
        user_id=user_id,
        confirmation_number=confirmation_number,
        buyer_first_name=first_name,
        buyer_last_name=last_name,
        buyer_email=email,
        buyer_contact=contact,
        buyer_meeting_location=meeting_location,
        total_amount=total_amount,
        card_last4=authorization["card_last4"],
        transaction_ref=authorization["intent_id"],
        payment_status="PAID",
        conn=conn,
    )

    order_items = []
    for item in priced_items:
        item_id = item["id"]
        item_name = item["name"]
        quantity = item["quantity"]
        price = item["price"]
        size = item["size"]

        order_item = create_order_item(
            order_id=order["id"],
            listing_id=item_id,
            item_name=item_name,
            quantity=quantity,
            price_at_purchase=price,
            selected_size=size,
            conn=conn,
        )
        order_items.append(order_item)

        # Made-to-order listings don't track inventory. If the stock decrease fails, the error
        # propagates and the whole checkout is rolled back, so the buyer never gets a confirmation.
        if not item["is_made_to_order"]:
            if size:
                update_listing_size_inventory(item_id, size, quantity, conn=conn)
            else:
                update_listing_quantity_inventory(item_id, quantity, conn=conn)

    clear_cart_for_user(user_id, conn=conn)

    return {
        "confirmation_number": confirmation_number,
        "order": order,
        "order_items": order_items,
        "total_amount": total_amount,
        "payment": {
            "status": "PAID",
            "card_last4": authorization["card_last4"],
            "transaction_ref": authorization["intent_id"],
        },
    }


def get_order_summary_service(confirmation_number, user_id):
    """Returns order + items for the confirmation page. Validates user ownership."""
    order = get_order_by_confirmation(confirmation_number)
    if not order:
        raise Exception("Order not found.")
    if order["user_id"] != user_id:
        raise Exception("Access denied.")
    items = get_order_items_by_order_id(order["id"])
    return {"order": order, "order_items": items}


def get_user_orders_service(user_id):
    """Returns all orders for the given user, newest first."""
    return get_orders_by_user_id(user_id)
