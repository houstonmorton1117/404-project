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
}


class TestCartPrice(unittest.TestCase):
    """Test cases CF-06 to CF-08: cart and checkout prices always come from the listings table."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        if get_connection() is None:
            raise unittest.SkipTest("Database not available.")

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.seller = f"cf_seller_{tag}"
        self.buyer = f"cf_buyer_{tag}"
        self.client = self.app.test_client()

        for username in (self.seller, self.buyer):
            self.client.post("/auth/signup", data={
                "username": username, "password": PASSWORD, "email": f"{username}@hamptonu.edu",
            })

        seller_id = self._query("SELECT id FROM users WHERE username = %s", (self.seller,))[0][0]
        storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (seller_id, f"CF Store {tag}"), commit=True,
        )[0][0]
        self.listing_id = self._query(
            """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand, status)
               VALUES (%s, 'CF Hoodie', 50.00, 'IN_STOCK', 5, 'ACTIVE') RETURNING id""",
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

    def _cart_rows(self):
        return self._query(
            """SELECT c.item_name, c.price, c.quantity FROM cart_items c
               JOIN users u ON u.id = c.user_id WHERE u.username = %s""",
            (self.buyer,),
        )

    def test_cf06_price_tampering_is_ignored(self):
        self.client.post("/auth/add_to_cart", data={
            "item_id": self.listing_id, "item_name": "FREE", "price": "0.01", "quantity": 2, "size": "M",
        })

        self.assertEqual(len(self._cart_rows()), 1)
        name, price, quantity = self._cart_rows()[0]
        self.assertEqual(name, "CF Hoodie")
        self.assertEqual(float(price), 50.00)
        self.assertEqual(quantity, 2)

        session_cart = self.client.get("/auth/cart/json").get_json()
        self.assertEqual(session_cart[0]["price"], 50.00)
        self.assertEqual(session_cart[0]["name"], "CF Hoodie")

    def test_cf07_invalid_quantity_is_rejected(self):
        for bad_quantity in ("-3", "0", "abc"):
            response = self.client.post("/auth/add_to_cart", data={
                "item_id": self.listing_id, "quantity": bad_quantity, "size": "M",
            })
            self.assertEqual(response.status_code, 400, f"quantity={bad_quantity!r}")

        self.assertEqual(self._cart_rows(), [])

    def test_cf08_checkout_uses_current_listing_price(self):
        self.client.post("/auth/add_to_cart", data={"item_id": self.listing_id, "quantity": 2, "size": "M"})
        self._query(
            """UPDATE cart_items SET price = 0.01
               WHERE user_id = (SELECT id FROM users WHERE username = %s)""",
            (self.buyer,), commit=True,
        )
        self._query("UPDATE listings SET price = 60.00 WHERE id = %s", (self.listing_id,), commit=True)

        # Log in again so the session cart is reloaded from the tampered cart_items row.
        self.client.get("/auth/logout")
        self.client.post("/auth/login", data={"username": self.buyer, "password": PASSWORD})
        self.assertEqual(self.client.get("/auth/cart/json").get_json()[0]["price"], 0.01)

        response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["total_amount"], 120.00)

        prices = self._query(
            """SELECT oi.price_at_purchase FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               JOIN users u ON u.id = o.user_id WHERE u.username = %s""",
            (self.buyer,),
        )
        self.assertEqual([float(p[0]) for p in prices], [60.00])


if __name__ == "__main__":
    unittest.main()
