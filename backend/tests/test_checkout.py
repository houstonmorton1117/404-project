import os
import sys
import unittest
import uuid

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from app import create_app
from backend.config.db import get_connection

PASSWORD = "pw12345"
BUYER_DETAILS = {
    "first_name": "Test",
    "last_name": "Buyer",
    "email": "buyer@hamptonu.edu",
    "contact": "555-0100",
    "meeting_location": "Library",
    "cardholder_name": "Test Buyer",
    "payment_method_id": "pm_card_visa",  # Stripe test token (card ending 4242)
}


class TestCheckoutFeature(unittest.TestCase):
    """Covers /api/checkout/complete, /api/orders/by-confirmation/<n>, and /api/orders/my."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        if get_connection() is None:
            raise unittest.SkipTest("Database not available.")

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.seller = f"co_seller_{tag}"
        self.buyer = f"co_buyer_{tag}"
        self.client = self.app.test_client()

        for username in (self.seller, self.buyer):
            self.client.post("/auth/signup", data={
                "username": username, "password": PASSWORD, "email": f"{username}@hamptonu.edu",
            })

        seller_id = self._query("SELECT id FROM users WHERE username = %s", (self.seller,))[0][0]
        storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (seller_id, f"CO Store {tag}"), commit=True,
        )[0][0]
        self.listing_id = self._query(
            """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand, status)
               VALUES (%s, 'CO Hoodie', 20.00, 'IN_STOCK', 5, 'ACTIVE') RETURNING id""",
            (storefront_id,), commit=True,
        )[0][0]
        self._query(
            "INSERT INTO listing_sizes (listing_id, size, quantity) VALUES (%s, 'M', 5)",
            (self.listing_id,), commit=True,
        )

        self.client.post("/auth/login", data={"username": self.buyer, "password": PASSWORD})

    def tearDown(self):
        # Cascades remove the storefront, listing, sizes, cart items, and orders.
        self._query("DELETE FROM users WHERE username IN (%s, %s)", (self.seller, self.buyer), commit=True)

    def _query(self, sql, params=(), commit=False):
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            if commit:
                conn.commit()
            return rows
        finally:
            cur.close()
            conn.close()

    def _add_to_cart(self, quantity=2):
        return self.client.post("/auth/add_to_cart", data={
            "item_id": self.listing_id, "quantity": quantity, "size": "M",
        })

    def test_complete_transaction_requires_authentication(self):
        self.client.get("/auth/logout")
        response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.get_json())

    def test_complete_transaction_rejects_empty_cart(self):
        response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_complete_transaction_creates_order_successfully(self):
        self._add_to_cart(quantity=2)

        response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()

        self.assertTrue(payload["success"])
        self.assertIn("confirmation_number", payload)
        self.assertIn("order_id", payload)
        self.assertEqual(payload["total_amount"], 40.00)

        # Cart is cleared after a successful checkout.
        cart = self.client.get("/auth/cart/json").get_json()
        self.assertEqual(cart, [])

    def test_order_confirmation_lookup_after_checkout(self):
        self._add_to_cart(quantity=1)
        checkout_response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        confirmation_number = checkout_response.get_json()["confirmation_number"]

        response = self.client.get(f"/api/orders/by-confirmation/{confirmation_number}")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()

        self.assertEqual(payload["order"]["confirmation_number"], confirmation_number)
        self.assertEqual(len(payload["order_items"]), 1)
        self.assertEqual(payload["order_items"][0]["item_name"], "CO Hoodie")
        self.assertEqual(float(payload["order_items"][0]["price_at_purchase"]), 20.00)

    def test_my_orders_lists_completed_checkout(self):
        self._add_to_cart(quantity=1)
        checkout_response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        confirmation_number = checkout_response.get_json()["confirmation_number"]

        response = self.client.get("/api/orders/my")
        self.assertEqual(response.status_code, 200, response.get_json())
        confirmation_numbers = [o["confirmation_number"] for o in response.get_json()["orders"]]
        self.assertIn(confirmation_number, confirmation_numbers)


if __name__ == "__main__":
    unittest.main()
