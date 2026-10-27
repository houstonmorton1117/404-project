# backend/tests/conftest.py
# Shared pytest setup. Added 10/27/26 with the Stripe payments change.
#
# Checkout charges cards through Stripe. So the test suite never needs network access or real
# Stripe keys, every test runs against a small fake Stripe that behaves like Stripe's test mode
# for the test tokens we use:
#   pm_card_visa            -> approved, card ending 4242
#   pm_card_chargeDeclined  -> declined
#   pm_card_threeDSecure2Required -> needs a bank verification pop-up (status requires_action)
# To run against the real Stripe test API instead, set STRIPE_LIVE_TESTS=1 and a real sk_test_ key.

import os
from types import SimpleNamespace

import pytest
import stripe

# app.py reads SECRET_KEY when it is imported; give tests a default so they don't need a .env file.
os.environ.setdefault("SECRET_KEY", "test-secret-key")


class FakeStripe:
    """Records every Stripe call in order, so tests can check what happened to the buyer's money."""

    def __init__(self):
        self.intents = {}
        self.calls = []          # e.g. [("create", {...}), ("capture", "pi_..."), ...]
        self._by_idempotency_key = {}
        self.fail_capture = False

    def actions(self):
        return [name for name, _ in self.calls]

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        key = kwargs.get("idempotency_key")
        if key in self._by_idempotency_key:
            return self._by_idempotency_key[key]
        if kwargs.get("payment_method") == "pm_card_chargeDeclined":
            raise stripe.CardError("Your card was declined.", param=None, code="card_declined")
        needs_action = kwargs.get("payment_method") == "pm_card_threeDSecure2Required"
        intent = SimpleNamespace(
            id=f"pi_fake{len(self.intents) + 1:04d}",
            status="requires_action" if needs_action else "requires_capture",
            amount=kwargs["amount"],
            payment_method=SimpleNamespace(id=kwargs.get("payment_method"),
                                           card=SimpleNamespace(last4="4242")),
        )
        self.intents[intent.id] = intent
        if key:
            self._by_idempotency_key[key] = intent
        return intent

    def capture(self, intent_id, **kwargs):
        self.calls.append(("capture", intent_id))
        if self.fail_capture:
            raise stripe.StripeError("simulated capture failure")
        self.intents[intent_id].status = "succeeded"
        return self.intents[intent_id]

    def cancel(self, intent_id, **kwargs):
        self.calls.append(("cancel", intent_id))
        self.intents[intent_id].status = "canceled"
        return self.intents[intent_id]

    def refund(self, payment_intent=None, **kwargs):
        self.calls.append(("refund", payment_intent))
        self.intents[payment_intent].status = "refunded"
        return SimpleNamespace(id="re_fake", status="succeeded")


@pytest.fixture(autouse=True)
def fake_stripe(monkeypatch):
    if os.getenv("STRIPE_LIVE_TESTS") == "1":
        yield None
        return
    fake = FakeStripe()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake_key_for_tests")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_fake_key_for_tests")
    monkeypatch.delenv("STRIPE_ALLOW_LIVE_KEYS", raising=False)
    monkeypatch.setattr(stripe.PaymentIntent, "create", fake.create)
    monkeypatch.setattr(stripe.PaymentIntent, "capture", fake.capture)
    monkeypatch.setattr(stripe.PaymentIntent, "cancel", fake.cancel)
    monkeypatch.setattr(stripe.Refund, "create", fake.refund)
    yield fake
