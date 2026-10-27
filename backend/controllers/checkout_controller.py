# The Vault Campus Marketplace
# CSC 405 Sp 26'
# Updated by Saffie Cherif - 10/1/26 - API-only blueprint
# Updated by Jasmine Mark 10/25/26 - corrected error handling

from flask import Blueprint, request, jsonify, session

from models.checkout_model import OutOfStockError
from services.checkout_service import (
    CheckoutError,
    complete_transaction_from_session,
    get_order_summary_service,
    get_user_orders_service,
)

checkout_bp = Blueprint("checkout", __name__)


@checkout_bp.route("/checkout/complete", methods=["POST"])
def complete_checkout():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    session_cart = session.get("cart", [])
    if not session_cart:
        return jsonify({"error": "Cart is empty"}), 400

    data = request.get_json() or {}

    try:
        result = complete_transaction_from_session(user_id, session_cart, data)
        session["cart"] = []
        session.modified = True
        return jsonify({
            "success": True,
            "confirmation_number": result["confirmation_number"],
            "order_id": result["order"]["id"],
            "total_amount": result["total_amount"],
            "payment": result["payment"],
        }), 200
    except (CheckoutError, OutOfStockError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Unexpected errors (e.g. database failures) are logged here but never shown to the buyer.
        print(f"[checkout] unexpected error for user {user_id}: {e}")
        return jsonify({"error": "Checkout failed. Please try again."}), 500


@checkout_bp.route("/orders/by-confirmation/<confirmation_number>", methods=["GET"])
def get_order_confirmation(confirmation_number):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    try:
        result = get_order_summary_service(confirmation_number, user_id)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@checkout_bp.route("/orders/my", methods=["GET"])
def get_my_orders():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    try:
        orders = get_user_orders_service(user_id)
        return jsonify({"orders": orders}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
