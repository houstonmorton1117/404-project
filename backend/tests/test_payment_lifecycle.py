# backend/tests/test_payment_lifecycle.py
# Added 11/14/26 for the payment token system.
#
# What happens to an order's payment after checkout:
#   - the Stripe webhook (/webhooks/stripe) moving payment_status when Stripe reports a change
#   - approving a return refunding the order through Stripe
#
# These use the real database (each test creates its own user and order and deletes them after)
# and the fake Stripe from conftest.py. Webhook requests are signed exactly the way Stripe signs
# them, so the real signature check runs.

import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from app import create_app
from db import get_connection

WEBHOOK_SECRET = "whsec_test_secret_for_tests"


# ---------------------------------------------------------------- helpers

def _query(sql, params=()):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        conn.commit()
        return rows
    finally:
        cur.close()
        conn.close()


def _sign(payload, secret=WEBHOOK_SECRET, timestamp=None):
    """Builds a Stripe-Signature header the same way Stripe does."""
    timestamp = timestamp or int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def _event(event_type, obj):
    return json.dumps({
        "id": f"evt_test_{uuid.uuid4().hex[:10]}",
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
    })


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    app = create_app()
    app.config.update(TESTING=True)       # CSRF stays ON: the webhook must work without a token
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_available():
    try:
        conn = get_connection()
    except Exception:
        conn = None
    if conn is None:
        pytest.skip("Database not available.")
    conn.close()


@pytest.fixture
def buyer(db_available):
    """A user who will be deleted after the test (with their orders and returns)."""
    tag = uuid.uuid4().hex[:8]
    username = f"pay_buyer_{tag}"
    user_id = _query(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (username, "not-a-real-hash", f"{username}@hamptonu.edu"),
    )[0][0]
    yield {"id": user_id, "username": username}
    _query("DELETE FROM returns WHERE user_id = %s", (user_id,))
    _query("DELETE FROM users WHERE id = %s", (user_id,))


def _paid_order(fake_stripe, user_id, total=40.00, status="PAID"):
    """Creates a real (fake-Stripe) captured payment and an order row that uses it."""
    hold = fake_stripe.create(amount=int(total * 100), payment_method="pm_card_visa",
                              metadata={"user_id": str(user_id)})
    fake_stripe.capture(hold.id)
    confirmation = f"SHOWTIME-TEST-{uuid.uuid4().hex[:6].upper()}"
    order_id = _query(
        """INSERT INTO orders (user_id, confirmation_number, buyer_first_name, buyer_last_name, buyer_email,
                               buyer_contact, buyer_meeting_location, total_amount, payment_status, transaction_ref)
           VALUES (%s, %s, 'Test', 'Buyer', 'b@hamptonu.edu', '555-0100', 'Library', %s, %s, %s) RETURNING id""",
        (user_id, confirmation, total, status, hold.id),
    )[0][0]
    fake_stripe.calls.clear()
    return {"id": order_id, "confirmation_number": confirmation, "intent_id": hold.id}


def _payment_status(order_id):
    return _query("SELECT payment_status FROM orders WHERE id = %s", (order_id,))[0][0]


def _post_event(client, event_type, obj, secret=WEBHOOK_SECRET):
    payload = _event(event_type, obj)
    return client.post("/webhooks/stripe", data=payload, content_type="application/json",
                       headers={"Stripe-Signature": _sign(payload, secret)})


# ---------------------------------------------------------------- webhook: signature checks

def test_webhook_rejects_requests_without_a_signature(client):
    response = client.post("/webhooks/stripe", data=_event("payment_intent.succeeded", {"id": "pi_x"}),
                           content_type="application/json")
    assert response.status_code == 400


def test_webhook_rejects_a_signature_made_with_the_wrong_secret(client):
    response = _post_event(client, "payment_intent.succeeded", {"id": "pi_x"}, secret="whsec_attacker")
    assert response.status_code == 400
    assert "signature" in response.get_json()["error"].lower()


def test_webhook_rejects_an_old_replayed_message(client):
    payload = _event("payment_intent.succeeded", {"id": "pi_x"})
    old = int(time.time()) - 3600     # Stripe's default tolerance is 5 minutes
    response = client.post("/webhooks/stripe", data=payload, content_type="application/json",
                           headers={"Stripe-Signature": _sign(payload, timestamp=old)})
    assert response.status_code == 400


def test_webhook_is_off_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    response = _post_event(client, "payment_intent.succeeded", {"id": "pi_x"})
    assert response.status_code == 400


def test_webhook_accepts_event_types_it_does_not_track(client):
    response = _post_event(client, "customer.created", {"id": "cus_x"})
    assert response.status_code == 200
    assert response.get_json()["handled"] is False


def test_webhook_answers_500_so_stripe_retries_when_processing_fails(client, monkeypatch):
    import controllers.stripe_webhook_controller as webhook_controller

    def broken(event):
        raise RuntimeError("database is down")
    monkeypatch.setattr(webhook_controller, "handle_stripe_event", broken)

    response = _post_event(client, "payment_intent.succeeded", {"id": "pi_x"})
    assert response.status_code == 500


# ---------------------------------------------------------------- webhook: status changes

def test_webhook_marks_an_order_refunded_from_the_stripe_dashboard(client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    response = _post_event(client, "charge.refunded",
                           {"id": "ch_1", "object": "charge", "payment_intent": order["intent_id"],
                            "refunded": True})
    assert response.status_code == 200
    assert response.get_json()["to"] == "REFUNDED"
    assert _payment_status(order["id"]) == "REFUNDED"


def test_partial_refund_leaves_the_order_paid(client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    _post_event(client, "charge.refunded",
                {"id": "ch_1", "object": "charge", "payment_intent": order["intent_id"], "refunded": False})
    assert _payment_status(order["id"]) == "PAID"


def test_webhook_moves_authorized_to_paid_and_failed(client, fake_stripe, buyer):
    paid = _paid_order(fake_stripe, buyer["id"], status="AUTHORIZED")
    failed = _paid_order(fake_stripe, buyer["id"], status="AUTHORIZED")

    _post_event(client, "payment_intent.succeeded", {"id": paid["intent_id"], "object": "payment_intent"})
    _post_event(client, "payment_intent.payment_failed", {"id": failed["intent_id"], "object": "payment_intent"})

    assert _payment_status(paid["id"]) == "PAID"
    assert _payment_status(failed["id"]) == "FAILED"


def test_late_events_never_move_a_status_backwards(client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"], status="REFUNDED")
    for event_type in ("payment_intent.succeeded", "payment_intent.amount_capturable_updated",
                       "payment_intent.payment_failed"):
        response = _post_event(client, event_type, {"id": order["intent_id"], "object": "payment_intent"})
        assert response.status_code == 200
    assert _payment_status(order["id"]) == "REFUNDED"


def test_repeated_event_is_harmless(client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    for _ in range(2):
        response = _post_event(client, "payment_intent.succeeded",
                               {"id": order["intent_id"], "object": "payment_intent"})
        assert response.status_code == 200
    assert _payment_status(order["id"]) == "PAID"


def test_event_for_a_payment_with_no_order_is_ignored(client, db_available):
    response = _post_event(client, "payment_intent.canceled", {"id": "pi_never_used_for_an_order"})
    assert response.status_code == 200
    assert response.get_json() == {"received": True, "handled": False, "reason": "no matching order"}


# ---------------------------------------------------------------- approving a return refunds it

@pytest.fixture
def admin_client(app):
    client = app.test_client()
    app.config["WTF_CSRF_ENABLED"] = False
    with client.session_transaction() as sess:
        sess["user"] = "admin"
        sess["role"] = "admin"
    return client


def _return_for(user_id, order_number, status="pending"):
    return _query(
        "INSERT INTO returns (user_id, order_number, reason, has_damage, status) "
        "VALUES (%s, %s, 'Wrong size', FALSE, %s) RETURNING id",
        (user_id, order_number, status),
    )[0][0]


def _return_status(return_id):
    return _query("SELECT status FROM returns WHERE id = %s", (return_id,))[0][0]


def _approve(admin_client, return_id, status="approved"):
    return admin_client.patch(f"/admin/returns/{return_id}", json={"status": status})


def test_approving_a_return_refunds_the_order(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"], total=40.00)
    # Buyers type the number by hand, so case and spaces shouldn't matter.
    return_id = _return_for(buyer["id"], f"  {order['confirmation_number'].lower()} ")

    response = _approve(admin_client, return_id)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "approved"
    assert body["refund"]["status"] == "refunded"
    assert body["refund"]["amount"] == 40.00
    assert fake_stripe.actions() == ["refund"]
    assert fake_stripe.refunds[0]["payment_intent"] == order["intent_id"]
    assert fake_stripe.refunds[0]["idempotency_key"] == f"refund-{order['intent_id']}"
    assert _payment_status(order["id"]) == "REFUNDED"
    assert _return_status(return_id) == "approved"
    message = _query("SELECT message FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                     (buyer["id"],))[0][0]
    assert "$40.00 was refunded" in message


def test_approving_twice_refunds_only_once(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    return_id = _return_for(buyer["id"], order["confirmation_number"])

    assert _approve(admin_client, return_id).status_code == 200
    second = _approve(admin_client, return_id)

    assert second.status_code == 200
    assert second.get_json()["refund"]["status"] == "already_approved"
    assert fake_stripe.actions() == ["refund"]


def test_order_already_refunded_elsewhere_is_approved_without_a_second_refund(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"], status="REFUNDED")
    return_id = _return_for(buyer["id"], order["confirmation_number"])

    response = _approve(admin_client, return_id)

    assert response.status_code == 200
    assert response.get_json()["refund"]["status"] == "already_refunded"
    assert fake_stripe.actions() == []


def test_failed_refund_leaves_the_return_and_order_unchanged(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    return_id = _return_for(buyer["id"], order["confirmation_number"])
    fake_stripe.fail_refund = True

    response = _approve(admin_client, return_id)

    assert response.status_code == 400
    assert "couldn't refund" in response.get_json()["error"]
    assert _return_status(return_id) == "pending"
    assert _payment_status(order["id"]) == "PAID"


def test_unknown_order_number_is_not_approved(admin_client, fake_stripe, buyer):
    return_id = _return_for(buyer["id"], "SHOWTIME-NOT-A-REAL-ORDER")

    response = _approve(admin_client, return_id)

    assert response.status_code == 400
    assert "wasn't found" in response.get_json()["error"]
    assert _return_status(return_id) == "pending"
    assert fake_stripe.actions() == []


def test_return_for_someone_elses_order_is_not_refunded(admin_client, fake_stripe, buyer, db_available):
    other_name = f"pay_other_{uuid.uuid4().hex[:8]}"
    other_id = _query("INSERT INTO users (username, password, email) VALUES (%s, 'x', %s) RETURNING id",
                      (other_name, f"{other_name}@hamptonu.edu"))[0][0]
    try:
        order = _paid_order(fake_stripe, other_id)
        return_id = _return_for(buyer["id"], order["confirmation_number"])

        response = _approve(admin_client, return_id)

        assert response.status_code == 400
        assert "different account" in response.get_json()["error"]
        assert fake_stripe.actions() == []
        assert _payment_status(order["id"]) == "PAID"
    finally:
        _query("DELETE FROM users WHERE id = %s", (other_id,))


def test_other_statuses_never_refund(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    return_id = _return_for(buyer["id"], order["confirmation_number"])

    for status in ("reviewed", "rejected", "resolved", "pending"):
        assert _approve(admin_client, return_id, status=status).status_code == 200
        assert _return_status(return_id) == status

    assert fake_stripe.actions() == []
    assert _payment_status(order["id"]) == "PAID"


def test_approved_return_can_only_move_on_to_resolved(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    return_id = _return_for(buyer["id"], order["confirmation_number"])
    assert _approve(admin_client, return_id).status_code == 200

    assert _approve(admin_client, return_id, status="pending").status_code == 400
    assert _return_status(return_id) == "approved"
    assert _approve(admin_client, return_id, status="resolved").status_code == 200


def test_unknown_return_status_is_rejected(admin_client, fake_stripe, buyer):
    order = _paid_order(fake_stripe, buyer["id"])
    return_id = _return_for(buyer["id"], order["confirmation_number"])

    response = _approve(admin_client, return_id, status="refund-it-twice")

    assert response.status_code == 400
    assert _return_status(return_id) == "pending"
