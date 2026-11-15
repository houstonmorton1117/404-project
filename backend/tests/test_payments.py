# backend/tests/test_payments.py
# Tests for Stripe tokenized payments. Rewritten 10/27/26 (replaces the simulated-card tests).
# Updated 11/14/26 - 3-D Secure verification and AUTHORIZED -> PAID payment statuses.
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
from utils.payments import PaymentActionRequired, PaymentError
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


def test_card_needing_bank_verification_asks_the_browser_to_verify(fake_stripe):
    # Before 11/14/26 these cards were refused. Now the payment is kept (not cancelled) and the
    # browser gets the client secret it needs to show the bank's 3-D Secure pop-up.
    with pytest.raises(PaymentActionRequired) as raised:
        payments.authorize_payment("pm_card_threeDSecure2Required", 50, "Test Buyer", KEY)
    intent = fake_stripe.intents[raised.value.intent_id]
    assert raised.value.client_secret == intent.client_secret
    assert fake_stripe.actions() == ["create"]          # no cancel: the hold is still wanted
    assert fake_stripe.calls[0][1]["use_stripe_sdk"] is True   # lets Stripe.js run the pop-up


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
    monkeypatch.setattr(checkout_service, "update_order_payment_status", db.update_payment_status)
    db.get_order_payment_by_ref.return_value = None      # the payment hasn't paid for any order yet
    monkeypatch.setattr(checkout_service, "get_order_payment_by_ref", db.get_order_payment_by_ref)
    return db


def test_checkout_charges_the_server_price_then_commits(fake_stripe, fake_db):
    result = checkout_service.complete_transaction_from_session(1, CART, BUYER)

    assert fake_stripe.actions() == ["create", "capture", "commit"]
    assert fake_stripe.calls[0][1]["amount"] == 5000          # 2 x $25.00 from the database, not $999
    order_kwargs = fake_db.create_order.call_args.kwargs
    assert order_kwargs["transaction_ref"] == result["payment"]["transaction_ref"]
    assert order_kwargs["card_last4"] == "4242"
    # Saved as AUTHORIZED (card on hold), then marked PAID once captured, before the commit.
    assert order_kwargs["payment_status"] == "AUTHORIZED"
    fake_db.update_payment_status.assert_called_once_with(1, "PAID", conn=fake_db.conn)
    assert result["payment"]["status"] == "PAID"
    assert result["order"]["payment_status"] == "PAID"


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


# ---------------------------------------------------------------- 3-D Secure checkout (no database)

THREE_DS_BUYER = {**BUYER, "payment_method_id": "pm_card_threeDSecure2Required"}


def _start_3ds_checkout(fake_stripe, user_id=1):
    """First checkout attempt with a card whose bank wants verification. Returns the intent id."""
    with pytest.raises(PaymentActionRequired) as raised:
        checkout_service.complete_transaction_from_session(user_id, CART, THREE_DS_BUYER)
    return raised.value.intent_id


def _finish_details(intent_id):
    details = {k: v for k, v in BUYER.items() if k != "payment_method_id"}
    return {**details, "payment_intent_id": intent_id}


def test_3ds_checkout_saves_nothing_until_the_bank_verifies(fake_stripe, fake_db):
    _start_3ds_checkout(fake_stripe)
    # Rolled back so no listing rows stay locked while the buyer verifies; the hold isn't cancelled.
    assert fake_stripe.actions() == ["create", "rollback"]
    fake_db.create_order.assert_not_called()
    fake_db.clear_cart.assert_not_called()


def test_3ds_checkout_completes_after_the_bank_verifies(fake_stripe, fake_db):
    intent_id = _start_3ds_checkout(fake_stripe)
    fake_stripe.verify_3ds(intent_id)

    result = checkout_service.complete_transaction_from_session(1, CART, _finish_details(intent_id))

    assert fake_stripe.actions() == ["create", "rollback", "retrieve", "capture", "commit"]
    order_kwargs = fake_db.create_order.call_args.kwargs
    assert order_kwargs["transaction_ref"] == intent_id
    assert order_kwargs["payment_status"] == "AUTHORIZED"
    fake_db.update_payment_status.assert_called_once_with(1, "PAID", conn=fake_db.conn)
    assert result["payment"]["status"] == "PAID"


def test_3ds_payment_the_server_must_confirm_again_is_confirmed(fake_stripe, fake_db):
    intent_id = _start_3ds_checkout(fake_stripe)
    fake_stripe.verify_3ds(intent_id, server_confirms=True)

    checkout_service.complete_transaction_from_session(1, CART, _finish_details(intent_id))

    assert fake_stripe.actions() == ["create", "rollback", "retrieve", "confirm", "capture", "commit"]


def test_failed_bank_verification_gives_a_clear_message_and_saves_nothing(fake_stripe, fake_db):
    intent_id = _start_3ds_checkout(fake_stripe)
    fake_stripe.verify_3ds(intent_id, passed=False)

    with pytest.raises(CheckoutError, match="couldn't verify"):
        checkout_service.complete_transaction_from_session(1, CART, _finish_details(intent_id))
    fake_db.create_order.assert_not_called()
    assert "capture" not in fake_stripe.actions()


def test_someone_elses_verified_payment_is_refused_and_left_alone(fake_stripe, fake_db):
    intent_id = _start_3ds_checkout(fake_stripe, user_id=1)
    fake_stripe.verify_3ds(intent_id)

    with pytest.raises(CheckoutError):
        checkout_service.complete_transaction_from_session(2, CART, _finish_details(intent_id))
    fake_db.create_order.assert_not_called()
    assert "capture" not in fake_stripe.actions()
    assert "cancel" not in fake_stripe.actions()      # it's user 1's payment; don't touch it


def test_cart_total_changing_during_verification_releases_the_hold(fake_stripe, fake_db, monkeypatch):
    intent_id = _start_3ds_checkout(fake_stripe)
    fake_stripe.verify_3ds(intent_id)
    # The seller changed the price while the buyer was in the bank's pop-up.
    monkeypatch.setattr(checkout_service, "check_listing_availability",
                        lambda item_id, qty, size, conn=None: ("Hoodie", 30.00, False))

    with pytest.raises(CheckoutError, match="cart changed"):
        checkout_service.complete_transaction_from_session(1, CART, _finish_details(intent_id))
    assert "cancel" in fake_stripe.actions()
    assert "capture" not in fake_stripe.actions()
    fake_db.create_order.assert_not_called()


def test_payment_that_already_paid_for_an_order_cant_be_reused(fake_stripe, fake_db):
    intent_id = _start_3ds_checkout(fake_stripe)
    fake_stripe.verify_3ds(intent_id)
    fake_db.get_order_payment_by_ref.return_value = {"id": 99, "payment_status": "PAID"}

    with pytest.raises(CheckoutError, match="already been used"):
        checkout_service.complete_transaction_from_session(1, CART, _finish_details(intent_id))
    fake_db.create_order.assert_not_called()
    assert "cancel" not in fake_stripe.actions()      # that order's payment must not be released


@pytest.mark.parametrize("bad_id", ["pm_card_visa", "pi_", "pi_abc; DROP TABLE", "x" * 20])
def test_anything_but_a_payment_intent_id_is_rejected(fake_stripe, fake_db, bad_id):
    with pytest.raises(CheckoutError):
        checkout_service.complete_transaction_from_session(1, CART, _finish_details(bad_id))
    assert "retrieve" not in fake_stripe.actions()


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


def test_checkout_api_runs_the_3ds_step_then_completes(client, fake_stripe, fake_db):
    first = client.post("/api/checkout/complete", json=THREE_DS_BUYER)
    assert first.status_code == 200
    body = first.get_json()
    assert body["requires_action"] is True
    assert body["client_secret"].startswith(body["payment_intent_id"])
    assert "confirmation_number" not in body
    with client.session_transaction() as sess:
        assert sess["cart"] == CART                   # nothing bought yet, so the cart is kept

    fake_stripe.verify_3ds(body["payment_intent_id"])   # the buyer passes the bank's pop-up
    second = client.post("/api/checkout/complete", json=_finish_details(body["payment_intent_id"]))
    assert second.status_code == 200
    done = second.get_json()
    assert done["success"] is True
    assert done["payment"]["status"] == "PAID"
    assert done["payment"]["transaction_ref"] == body["payment_intent_id"]
    with client.session_transaction() as sess:
        assert sess["cart"] == []
