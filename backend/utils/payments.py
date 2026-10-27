# backend/utils/payments.py
# Online card payments through Stripe, using tokenization.
#
# Rewritten 10/27/26 for the "token for funds to pay online" fix.
# The previous version took the buyer's full card number, expiry and CVV
# as plain form fields on our own server and only pretended to charge them.
# Now the card details are typed into a Stripe-hosted field in the browser
# and go straight to Stripe. Stripe hands the browser back a token (a
# PaymentMethod id like "pm_1Q2x...") and that token is the only payment
# detail our server ever receives. The full card number and CVV never
# touch Flask, our logs, or our database.
#
# Checkout charges in two steps so money only moves if the order is saved:
#   1. authorize_payment()  - Stripe places a hold for the order total
#   2. capture_payment()    - turns the hold into a charge, right before the
#                             checkout database transaction is committed
# If anything fails in between, cancel_payment() releases the hold. If the
# commit itself fails after capture, refund_payment() gives the money back.
#
# Configuration (environment variables, see .env.example):
#   STRIPE_SECRET_KEY       sk_test_... (server side only, never sent to the browser)
#   STRIPE_PUBLISHABLE_KEY  pk_test_... (safe to put in the page, used by Stripe.js)
#   STRIPE_ALLOW_LIVE_KEYS  set to "true" only if the site should take real money

import os
import re

import stripe


CURRENCY = "usd"
_PAYMENT_METHOD_ID = re.compile(r"^pm_[A-Za-z0-9_]{1,250}$")


class PaymentError(Exception):
    """A payment problem the buyer should see (declined card, payments not set up, etc.)."""


def get_publishable_key():
    """The browser-safe key Stripe.js needs. Empty string if payments aren't configured."""
    return os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()


def _configure_stripe():
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        print("[payments] STRIPE_SECRET_KEY is not set; online payments are disabled.")
        raise PaymentError("Online payments are not set up on this server yet.")

    is_test_key = secret_key.startswith(("sk_test_", "rk_test_"))
    allow_live = os.getenv("STRIPE_ALLOW_LIVE_KEYS", "").strip().lower() == "true"
    if not is_test_key and not allow_live:
        # Guard against someone pasting a live key into a class/demo deployment.
        print("[payments] Refusing to use a non-test Stripe key without STRIPE_ALLOW_LIVE_KEYS=true.")
        raise PaymentError("Online payments are not set up on this server yet.")

    stripe.api_key = secret_key


def _to_cents(amount):
    cents = int(round(float(amount) * 100))
    if cents <= 0:
        raise PaymentError("Payment amount must be greater than zero.")
    return cents


def authorize_payment(payment_method_id, amount, cardholder_name, idempotency_key, metadata=None):
    """
    Places a hold on the buyer's card for `amount` dollars using the token from Stripe.js.

    Args:
        payment_method_id: the "pm_..." token the browser got from Stripe
        amount: order total in dollars, computed by the server (never trusted from the browser)
        cardholder_name: name entered on the checkout page
        idempotency_key: same key -> Stripe returns the same result instead of charging twice
        metadata: small dict of strings saved on the Stripe payment (e.g. user id)

    Returns:
        {"intent_id": "pi_...", "card_last4": "4242", "status": "requires_capture"}

    Raises:
        PaymentError with a buyer-facing message.
    """
    if not cardholder_name or not str(cardholder_name).strip():
        raise PaymentError("Cardholder name is required.")
    if not payment_method_id or not _PAYMENT_METHOD_ID.match(str(payment_method_id)):
        raise PaymentError("Payment details are missing. Please re-enter your card.")

    amount_cents = _to_cents(amount)
    _configure_stripe()

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=CURRENCY,
            payment_method=payment_method_id,
            # Stripe no longer accepts payment_method_types; enabled payment methods are managed in the
            # Stripe Dashboard. allow_redirects="never" keeps it to methods (like cards) that finish
            # without sending the buyer to another site, since checkout confirms on the server.
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            capture_method="manual",        # hold now, charge only once the order is saved
            confirm=True,
            description="Showtime marketplace order",
            metadata=metadata or {},
            expand=["payment_method"],
            idempotency_key=idempotency_key,
        )
    except stripe.CardError as e:
        # Stripe's card-error messages are written for buyers ("Your card was declined.")
        raise PaymentError(e.user_message or "Your card was declined.")
    except stripe.StripeError as e:
        print(f"[payments] Stripe error while authorizing: {e}")
        raise PaymentError("We couldn't process your payment right now. Please try again.")

    if intent.status == "requires_action":
        # The bank wants an extra verification step (3-D Secure pop-up). Checkout confirms on the
        # server and doesn't show that pop-up, so release the hold and ask for another card.
        cancel_payment(intent.id)
        raise PaymentError("This card needs extra verification from your bank, which checkout "
                           "doesn't support yet. Please try a different card.")
    if intent.status != "requires_capture":
        # Anything else means no usable hold was placed.
        print(f"[payments] Unexpected PaymentIntent status {intent.status} for {intent.id}")
        cancel_payment(intent.id)
        raise PaymentError("Your card could not be authorized. Please try a different card.")

    card = getattr(intent.payment_method, "card", None)
    return {
        "intent_id": intent.id,
        "card_last4": getattr(card, "last4", None),
        "status": intent.status,
    }


def capture_payment(intent_id):
    """Turns the hold into a real charge. Raises PaymentError if Stripe refuses."""
    _configure_stripe()
    try:
        intent = stripe.PaymentIntent.capture(intent_id)
    except stripe.StripeError as e:
        print(f"[payments] Stripe error while capturing {intent_id}: {e}")
        raise PaymentError("We couldn't complete your payment. You have not been charged.")
    if intent.status != "succeeded":
        print(f"[payments] Capture of {intent_id} ended in status {intent.status}")
        raise PaymentError("We couldn't complete your payment. You have not been charged.")
    return {"intent_id": intent.id, "status": "PAID"}


def cancel_payment(intent_id):
    """Releases a hold that was never captured. Never raises; failures are logged."""
    try:
        _configure_stripe()
        stripe.PaymentIntent.cancel(intent_id)
    except Exception as e:
        print(f"[payments] Could not cancel PaymentIntent {intent_id}: {e}")


def refund_payment(intent_id):
    """Refunds a captured charge. Never raises; failures are logged for manual follow-up."""
    try:
        _configure_stripe()
        stripe.Refund.create(payment_intent=intent_id)
    except Exception as e:
        print(f"[payments] REFUND FAILED for PaymentIntent {intent_id}, refund it in the Stripe dashboard: {e}")
