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


class TestI3BugFixes(unittest.TestCase):
    """Regression coverage for the I3 bugs found and fixed this iteration:
    cart deletion targeting the wrong row, the post-login redirect not
    returning to checkout, broken access control via forged X-User-Id
    headers, and the checkout inventory race condition."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        if get_connection() is None:
            raise unittest.SkipTest("Database not available.")

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.client = self.app.test_client()
        self.created_usernames = []

    def tearDown(self):
        if self.created_usernames:
            self._query(
                "DELETE FROM users WHERE username = ANY(%s)",
                (self.created_usernames,), commit=True,
            )

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

    def _signup_and_login(self, prefix):
        username = f"{prefix}_{self.tag}"
        self.created_usernames.append(username)
        self.client.post("/auth/signup", data={
            "username": username, "password": PASSWORD, "email": f"{username}@hamptonu.edu",
        })
        self.client.post("/auth/login", data={"username": username, "password": PASSWORD})
        return username

    def _make_listing(self, owner_username, price=25.00, qty=5):
        owner_id = self._query("SELECT id FROM users WHERE username = %s", (owner_username,))[0][0]
        storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (owner_id, f"Store {self.tag}"), commit=True,
        )[0][0]
        listing_id = self._query(
            """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand, status)
               VALUES (%s, 'Test Item', %s, 'IN_STOCK', %s, 'ACTIVE') RETURNING id""",
            (storefront_id, price, qty), commit=True,
        )[0][0]
        self._query(
            "INSERT INTO listing_sizes (listing_id, size, quantity) VALUES (%s, 'M', %s)",
            (listing_id, qty), commit=True,
        )
        return listing_id

    def _make_listing_no_size(self, owner_username, price=25.00, qty=5):
        """A plain IN_STOCK listing with no listing_sizes rows, the configuration
        that update_listing_quantity_inventory's regression test exercises."""
        owner_id = self._query("SELECT id FROM users WHERE username = %s", (owner_username,))[0][0]
        storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (owner_id, f"Store {self.tag}"), commit=True,
        )[0][0]
        listing_id = self._query(
            """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand, status)
               VALUES (%s, 'Test Item (No Size)', %s, 'IN_STOCK', %s, 'ACTIVE') RETURNING id""",
            (storefront_id, price, qty), commit=True,
        )[0][0]
        return listing_id

    def test_checkout_decrements_inventory_for_listing_with_no_sizes(self):
        """A listing with no listing_sizes rows (the common case for most listings)
        used to never have quantity_on_hand decremented after a purchase, since the
        inventory update only ran when the cart item had a size. Covers the fix in
        update_listing_quantity_inventory."""
        owner = self._signup_and_login("i3_nosize_owner")
        listing_id = self._make_listing_no_size(owner, qty=3)
        buyer = self._signup_and_login("i3_nosize_buyer")

        self.client.post("/auth/add_to_cart", data={"item_id": listing_id, "quantity": 2})
        response = self.client.post("/api/checkout/complete", json=BUYER_DETAILS)
        self.assertEqual(response.status_code, 200, response.get_json())

        qty_on_hand = self._query(
            "SELECT quantity_on_hand FROM listings WHERE id = %s", (listing_id,)
        )[0][0]
        self.assertEqual(qty_on_hand, 1)

    def test_remove_from_cart_deletes_correct_row_among_duplicates(self):
        owner = self._signup_and_login("i3_owner")
        listing_id = self._make_listing(owner)
        buyer = self._signup_and_login("i3_buyer")

        self.client.post("/auth/add_to_cart", data={"item_id": listing_id, "quantity": 1, "size": "M"})
        self.client.post("/auth/add_to_cart", data={"item_id": listing_id, "quantity": 2, "size": "M"})

        cart = self.client.get("/auth/cart/json").get_json()
        self.assertEqual(len(cart), 2)

        self.client.post("/auth/remove_from_cart/0")

        cart_after = self.client.get("/auth/cart/json").get_json()
        self.assertEqual(len(cart_after), 1)
        self.assertEqual(cart_after[0]["quantity"], 2)

    def test_checkout_login_redirect_returns_to_checkout(self):
        self._signup_and_login("i3_redir")
        self.client.get("/auth/logout")

        r1 = self.client.get("/checkout")
        self.assertEqual(r1.status_code, 302)
        self.assertEqual(r1.headers["Location"], "/auth/login?next=/checkout")

        username = self.created_usernames[-1]
        r2 = self.client.post("/auth/login", data={
            "username": username, "password": PASSWORD, "next": "/checkout",
        })
        self.assertEqual(r2.headers["Location"], "/checkout")

    def test_forged_user_id_header_cannot_bypass_ownership(self):
        owner = self._signup_and_login("i3_access_owner")
        listing_id = self._make_listing(owner)
        owner_id = self._query("SELECT id FROM users WHERE username = %s", (owner,))[0][0]

        self.client.get("/auth/logout")
        self._signup_and_login("i3_access_attacker")

        forged_headers = {"X-User-Id": str(owner_id), "X-User-Role": "user"}
        response = self.client.delete(f"/api/listings/{listing_id}", headers=forged_headers)
        self.assertIn(response.status_code, (401, 403))

        still_exists = self.client.get(f"/api/listings/{listing_id}")
        self.assertEqual(still_exists.status_code, 200)

    def test_checkout_inventory_decrement_is_atomic(self):
        from backend.models.checkout_model import update_listing_size_inventory

        owner = self._signup_and_login("i3_race_owner")
        listing_id = self._make_listing(owner, qty=1)
        self._query("UPDATE listing_sizes SET quantity = 1 WHERE listing_id = %s", (listing_id,), commit=True)

        update_listing_size_inventory(listing_id, "M", 1)

        with self.assertRaises(Exception):
            update_listing_size_inventory(listing_id, "M", 1)

        final_qty = self._query("SELECT quantity FROM listing_sizes WHERE listing_id = %s", (listing_id,))[0][0]
        self.assertEqual(final_qty, 0)


if __name__ == "__main__":
    unittest.main()
