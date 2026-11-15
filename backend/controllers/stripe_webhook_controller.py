# backend/controllers/stripe_webhook_controller.py
# The Vault Campus Marketplace
# Added 11/14/26 for the payment token system.
#
# POST /webhooks/stripe - Stripe calls this whenever a payment changes (charged, failed,
# refunded, ...) so the app hears about it even when the change didn't start on our site,
# for example a refund issued from the Stripe Dashboard.
#
# Every request must carry a valid Stripe-Signature header made with STRIPE_WEBHOOK_SECRET;
# anything else is rejected. This route is exempt from CSRF (Stripe can't send our CSRF token)
# and needs no login; the signature is what proves the request came from Stripe.
#
# Setup:
#   - Local testing: install the Stripe CLI and run
#       stripe listen --forward-to localhost:5000/webhooks/stripe
#     then put the whsec_... secret it prints into .env as STRIPE_WEBHOOK_SECRET.
#   - Deployed site: Stripe Dashboard -> Developers -> Webhooks -> add endpoint
#     https://<your-site>/webhooks/stripe, choose the payment_intent.* and charge.refunded
#     events, and set the endpoint's signing secret as STRIPE_WEBHOOK_SECRET on the server.

from flask import Blueprint, jsonify, request

from services.payment_webhook_service import handle_stripe_event
from utils.payments import PaymentError, parse_webhook_event

stripe_webhook_bp = Blueprint("stripe_webhook", __name__)


@stripe_webhook_bp.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    # The signature is computed over the exact bytes Stripe sent, so read the raw body.
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature")

    try:
        event = parse_webhook_event(payload, signature)
    except PaymentError as e:
        return jsonify({"error": str(e)}), 400

    try:
        result = handle_stripe_event(event)
    except Exception as e:
        # A non-2xx answer makes Stripe retry the event later.
        # Stripe events aren't dicts (no .get), so read the id as an attribute.
        print(f"[webhook] failed to process Stripe event {getattr(event, 'id', '?')}: {e}")
        return jsonify({"error": "Could not process event."}), 500

    return jsonify({"received": True, **result}), 200
