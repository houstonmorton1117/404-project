# backend/tests/test_payments.py
# Tests for Stripe tokenized payments. Rewritten 10/27/26 (replaces the simulated-card tests).
#
# None of these need a database or network: Stripe is replaced by the fake in conftest.py, and the
# checkout tests below swap the database functions for stand-ins.

import os
import sys
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

import utils.payments as payments
import services.checkout_service as checkout_service
from utils.payments import PaymentError
from services.checkout_service import CheckoutError

KEY = "checkout-1-pm_card_visa-50.00"


# ---------------------------------------------------------------- payments module

def test_authorize_places_a_hold_for_the_amount_in_cents(fake_stripe):
    result = payments.authorize_payment("pm_card_visa", 50.10, "Test Buyer", KEY)

    assert result["intent_id"].startswith("pi_")
    assert result["card_last4"] == "4242"
    assert result["status"] == "requires_capture"

    sent = fake_stripe.calls[0][1]
    assert sent["amount"] == 5010
    assert sent["currency"] == "usd"
    assert sent["payment_method"] == "pm_card_visa"
    assert sent["capture_method"] == "manual"   # a hold, not a charge
    # Stripe rejects payment_method_types now; methods come from the Dashboard instead.
    assert "payment_method_types" not in sent
    assert "error_on_requires_action" not in sent   # also rejected with Dashboard-managed methods
    assert sent["automatic_payment_methods"] == {"enabled": True, "allow_redirects": "never"}
    assert sent["confirm"] is True
    assert sent["idempotency_key"] == KEY


def test_declined_card_gives_the_buyer_stripes_message(fake_stripe):
    with pytest.raises(PaymentError, match="declined"):
        payments.authorize_payment("pm_card_chargeDeclined", 50, "Test Buyer", KEY)


def test_card_needing_bank_verification_is_released_not_charged(fake_stripe):
    with pytest.raises(PaymentError, match="extra verification"):
        payments.authorize_payment("pm_card_threeDSecure2Required", 50, "Test Buyer", KEY)
    assert fake_stripe.actions() == ["create", "cancel"]


@pytest.mark.parametrize("bad_token", [None, "", "4242424242424242", "pm_", "pm_abc; DROP TABLE"])
def test_anything_but_a_stripe_token_is_rejected(fake_stripe, bad_token):
    with pytest.raises(PaymentError):
        payments.authorize_payment(bad_token, 50, "Test Buyer", KEY)
    assert fake_stripe.calls == []


def test_cardholder_name_is_required(fake_stripe):
    with pytest.raises(PaymentError):
        payments.authorize_payment("pm_card_visa", 50, "  ", KEY)


def test_zero_amount_is_rejected(fake_stripe):
    with pytest.raises(PaymentError):
        payments.authorize_payment("pm_card_visa", 0, "Test Buyer", KEY)


def test_payments_are_off_without_a_secret_key(fake_stripe, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    with pytest.raises(PaymentError, match="not set up"):
        payments.authorize_payment("pm_card_visa", 50, "Test Buyer", KEY)
    assert fake_stripe.calls == []


def test_live_key_is_refused_unless_explicitly_allowed(fake_stripe, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_not_a_real_key")
    with pytest.raises(PaymentError):
        payments.authorize_payment("pm_card_visa", 50, "Test Buyer", KEY)
    assert fake_stripe.calls == []


def test_capture_turns_the_hold_into_a_charge(fake_stripe):
    hold = payments.authorize_payment("pm_card_visa", 50, "Test Buyer", KEY)
    assert payments.capture_payment(hold["intent_id"])["status"] == "PAID"
    assert fake_stripe.intents[hold["intent_id"]].status == "succeeded"


# ---------------------------------------------------------------- checkout service (no database)

CART = [{"id": 7, "name": "Hoodie", "price": 999.00, "quantity": 2, "size": None}]
BUYER = {
    "first_name": "Test",
    "last_name": "Buyer",
    "email": "buyer@hamptonu.edu",
    "contact": "555-0100",
    "meeting_location": "Library",
    "cardholder_name": "Test Buyer",
    "payment_method_id": "pm_card_visa",
}


@pytest.fixture
def fake_db(monkeypatch, fake_stripe):
    """Stand-ins for every database call checkout makes. The connection logs commit/rollback
    into the same list as the Stripe calls, so tests can check the exact order of events."""
    conn = MagicMock()
    conn.commit.side_effect = lambda: fake_stripe.calls.append(("commit", None))
    conn.rollback.side_effect = lambda: fake_stripe.calls.append(("rollback", None))
    db = MagicMock()
    db.conn = conn
    db.create_order.side_effect = lambda **kw: {"id": 1, **kw}
    db.create_order_item.side_effect = lambda **kw: dict(kw)

    monkeypatch.setattr(checkout_service, "get_connection", lambda: conn)
    # The listing really costs $25.00, whatever the cart says.
    monkeypatch.setattr(checkout_service, "check_listing_availability",
                        lambda item_id, qty, size, conn=None: ("Hoodie", 25.00, False))
    monkeypatch.setattr(checkout_service, "create_order", db.create_order)
    monkeypatch.setattr(checkout_service, "create_order_item", db.create_order_item)
    monkeypatch.setattr(checkout_service, "update_listing_quantity_inventory", db.update_qty)
    monkeypatch.setattr(checkout_service, "update_listing_size_inventory", db.update_size)
    monkeypatch.setattr(checkout_service, "clear_cart_for_user", db.clear_cart)
    monkeypatch.setattr(checkout_service, "remove_purchased_from_wishlist", db.wishlist)
    return db


def test_checkout_charges_the_server_price_then_commits(fake_stripe, fake_db):
    result = checkout_service.complete_transaction_from_session(1, CART, BUYER)

    assert fake_stripe.actions() == ["create", "capture", "commit"]
    assert fake_stripe.calls[0][1]["amount"] == 5000          # 2 x $25.00 from the database, not $999
    order_kwargs = fake_db.create_order.call_args.kwargs
    assert order_kwargs["transaction_ref"] == result["payment"]["transaction_ref"]
    assert order_kwargs["card_last4"] == "4242"
    assert result["payment"]["status"] == "PAID"


def test_database_failure_releases_the_hold_and_never_charges(fake_stripe, fake_db):
    fake_db.create_order_item.side_effect = Exception("simulated DB error")
    with pytest.raises(Exception, match="simulated DB error"):
        checkout_service.complete_transaction_from_session(1, CART, BUYER)
    assert fake_stripe.actions() == ["create", "cancel", "rollback"]


def test_failed_commit_after_the_charge_is_refunded(fake_stripe, fake_db):
    def failing_commit():
        fake_stripe.calls.append(("commit", None))
        raise Exception("simulated commit failure")
    fake_db.conn.commit.side_effect = failing_commit

    with pytest.raises(Exception, match="simulated commit failure"):
        checkout_service.complete_transaction_from_session(1, CART, BUYER)
    assert fake_stripe.actions() == ["create", "capture", "commit", "refund", "rollback"]


def test_failed_capture_releases_the_hold(fake_stripe, fake_db):
    fake_stripe.fail_capture = True
    with pytest.raises(CheckoutError, match="not been charged"):
        checkout_service.complete_transaction_from_session(1, CART, BUYER)
    assert fake_stripe.actions() == ["create", "capture", "cancel", "rollback"]


def test_declined_card_saves_no_order(fake_stripe, fake_db):
    declined = {**BUYER, "payment_method_id": "pm_card_chargeDeclined"}
    with pytest.raises(CheckoutError, match="declined"):
        checkout_service.complete_transaction_from_session(1, CART, declined)
    fake_db.create_order.assert_not_called()
    assert "capture" not in fake_stripe.actions()


def test_raw_card_number_is_refused_before_anything_happens(fake_stripe, fake_db, monkeypatch):
    monkeypatch.setattr(checkout_service, "get_connection",
                        lambda: pytest.fail("database should not be touched"))
    old_style = {**BUYER, "card_number": "4242424242424242", "card_expiry": "12/30", "cvv": "123"}
    with pytest.raises(CheckoutError, match="card details can't be sent"):
        checkout_service.complete_transaction_from_session(1, CART, old_style)
    assert fake_stripe.calls == []


# ---------------------------------------------------------------- checkout page and API

@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        with test_client.session_transaction() as sess:
            sess["user"] = "buyer"
            sess["user_id"] = 1
            sess["cart"] = CART
        yield test_client


def test_checkout_page_uses_stripe_card_field_not_raw_inputs(client):
    html = client.get("/checkout").get_data(as_text=True)
    assert 'content="pk_test_fake_key_for_tests"' in html
    assert "https://js.stripe.com/v3/" in html
    assert 'id="cardElement"' in html
    for old_field in ('id="cardNumber"', 'id="cardExpiry"', 'id="cardCvv"'):
        assert old_field not in html
    assert "sk_test_" not in html   # the secret key must never reach the browser


def test_checkout_api_rejects_raw_card_data(client):
    response = client.post("/api/checkout/complete", json={**BUYER, "card_number": "4242424242424242"})
    assert response.status_code == 400
    assert "card details can't be sent" in response.get_json()["error"]
