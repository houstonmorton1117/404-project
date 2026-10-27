# backend/tests/test_checkout_integrity.py
# Tests that checkout is all-or-nothing: it either saves the order, its items, the stock
# change, and the cleared cart together, or saves none of them.
# Added by Jasmine Mark
#
# Each test creates its own users, storefront, and listing, and deletes them afterward.

import os
import sys
import threading
import unittest
import uuid
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# add project root and backend folder to the Python path so the imports below work
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from app import create_app
from backend.config.db import get_connection
import services.checkout_service as checkout_service

PASSWORD_HASH = "not-a-real-hash"  # these users never log in, so the password doesn't matter

#fake checkout form data sent with every checkout 
BUYER_DETAILS = {
    "first_name": "Test",
    "last_name": "Buyer",
    "email": "buyer@hamptonu.edu",
    "contact": "555-0100",
    "meeting_location": "Library",
    "cardholder_name": "Test Buyer",
    "card_number": "4242424242424242",
    "card_expiry": "12/30",
    "cvv": "123",
}

# race conditions don't happen every time, so the race test repeats this many times
RACE_ROUNDS = 5


class TestCheckoutIntegrity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Runs once before all tests: build the Flask app in test mode
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False  # test client can't send CSRF tokens
        # Skip every test in this file if we can't reach the database
        conn = get_connection()
        if conn is None:
            raise unittest.SkipTest("Database not available.")
        conn.close()

    def setUp(self):
        # Runs before each test: make a seller with a storefront.
        # The random tag keeps usernames unique so tests never clash with each other.
        self.tag = uuid.uuid4().hex[:8]
        self.created_usernames = []
        self.seller_id = self._create_user(f"ci_seller_{self.tag}")
        self.storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (self.seller_id, f"CI Store {self.tag}"), commit=True,
        )[0][0]


    def tearDown(self):
        # Runs after each test: clean up everything the test created.
        # Deleting the users cascades to their storefront, listings, cart items, and orders.
        self._query("DELETE FROM users WHERE username = ANY(%s)", (self.created_usernames,), commit=True)

    # ---------- helpers ----------

    def _query(self, sql, params=(), commit=False):
        """Runs one SQL statement on a fresh connection and returns any rows."""
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []  # only SELECT/RETURNING have rows
            if commit:
                conn.commit()
            return rows
        finally:
            cur.close()
            conn.close()

    def _create_user(self, username):
        """Inserts a user and remembers the name so tearDown can delete it."""
        self.created_usernames.append(username)
        return self._query(
            "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
            (username, PASSWORD_HASH, f"{username}@hamptonu.edu"), commit=True,
        )[0][0]

    def _create_listing(self, quantity_on_hand=1):
        """A $20 in-stock listing with no sizes."""
        return self._query(
            """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand, status)
               VALUES (%s, 'CI Hoodie', 20.00, 'IN_STOCK', %s, 'ACTIVE') RETURNING id""",
            (self.storefront_id, quantity_on_hand), commit=True,
        )[0][0]

    def _create_buyer_with_cart(self, listing_id, name="buyer"):
        """Creates a buyer with one unit of the listing in their saved cart. Returns (user_id, session_cart)."""
        buyer_id = self._create_user(f"ci_{name}_{self.tag}")
        #saved cart in the database
        self._query(
            """INSERT INTO cart_items (user_id, item_id, item_name, price, quantity, size)
               VALUES (%s, %s, 'CI Hoodie', 20.00, 1, NULL)""",
            (buyer_id, listing_id), commit=True,
        )
        # Same cart in the format the Flask session stores it
        session_cart = [{"id": listing_id, "name": "CI Hoodie", "price": 20.00, "quantity": 1, "size": None}]
        return buyer_id, session_cart

    # Small lookups used by the assertions
    def _order_count(self, user_id):
        return self._query("SELECT COUNT(*) FROM orders WHERE user_id = %s", (user_id,))[0][0]

    def _cart_count(self, user_id):
        return self._query("SELECT COUNT(*) FROM cart_items WHERE user_id = %s", (user_id,))[0][0]

    def _stock(self, listing_id):
        return self._query("SELECT quantity_on_hand FROM listings WHERE id = %s", (listing_id,))[0][0]

    def _assert_nothing_saved(self, buyer_id, listing_id):
        """After a failed checkout, the database should look exactly like it did before."""
        self.assertEqual(self._order_count(buyer_id), 0, "an order was saved even though checkout failed")
        self.assertEqual(self._cart_count(buyer_id), 1, "the cart was cleared even though checkout failed")
        self.assertEqual(self._stock(listing_id), 1, "stock changed even though checkout failed")

    # ---------- tests ----------

    def test_two_buyers_racing_for_last_item_only_one_succeeds(self):
        """Two buyers check out the last unit at the same moment. Only one can get a confirmation."""
        for round_number in range(1, RACE_ROUNDS + 1):
            # One item in stock, two buyers who both have it in their cart
            listing_id = self._create_listing(quantity_on_hand=1)
            buyers = [
                self._create_buyer_with_cart(listing_id, name=f"racer{round_number}a"),
                self._create_buyer_with_cart(listing_id, name=f"racer{round_number}b"),
            ]
            # the barrier makes both threads wait until both are ready, then start together
            start_together = threading.Barrier(len(buyers))
            results = {}

            def checkout(buyer_id, session_cart):
                start_together.wait()
                try:
                    checkout_service.complete_transaction_from_session(buyer_id, session_cart, BUYER_DETAILS)
                    results[buyer_id] = "confirmed"
                except Exception as e:
                    results[buyer_id] = f"rejected: {e}"

            # run both checkouts at the same time in separate threads and wait for them to finish
            threads = [threading.Thread(target=checkout, args=buyer) for buyer in buyers]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            #xactly one buyer should win: one confirmation, one order, and stock down to 0
            confirmed = [b for b, outcome in results.items() if outcome == "confirmed"]
            total_orders = sum(self._order_count(buyer_id) for buyer_id, _ in buyers)
            with self.subTest(round=round_number):
                self.assertEqual(len(confirmed), 1, f"expected exactly one confirmation, got {results}")
                self.assertEqual(total_orders, 1, "expected exactly one order saved for one unit of stock")
                self.assertEqual(self._stock(listing_id), 0)

    def test_failure_while_saving_order_items_saves_nothing(self):
        """If saving the order items fails, the order must not be left behind with zero items."""
        listing_id = self._create_listing(quantity_on_hand=1)
        buyer_id, session_cart = self._create_buyer_with_cart(listing_id)

        # Make create_order_item crash partway through checkout (after the order row is inserted)
        with patch.object(checkout_service, "create_order_item", side_effect=Exception("simulated DB error")):
            with self.assertRaises(Exception):
                checkout_service.complete_transaction_from_session(buyer_id, session_cart, BUYER_DETAILS)

        #The order insert should have been rolled back along with everything else
        self._assert_nothing_saved(buyer_id, listing_id)

    def test_failed_stock_update_cancels_checkout(self):
        """If lowering stock fails, the buyer must not get a confirmation."""
        listing_id = self._create_listing(quantity_on_hand=1)
        buyer_id, session_cart = self._create_buyer_with_cart(listing_id)

        # Make the stock update crash; checkout should raise instead of returning a confirmation
        with patch.object(checkout_service, "update_listing_quantity_inventory",
                          side_effect=Exception("simulated DB error")):
            with self.assertRaises(Exception, msg="checkout returned a confirmation even though stock wasn't lowered"):
                checkout_service.complete_transaction_from_session(buyer_id, session_cart, BUYER_DETAILS)

        self._assert_nothing_saved(buyer_id, listing_id)

    def test_database_error_is_not_shown_to_buyer(self):
        """The buyer should see a generic message, not the raw database error."""
        listing_id = self._create_listing(quantity_on_hand=1)
        buyer_id, session_cart = self._create_buyer_with_cart(listing_id)
        # Log the buyer in by putting their id and cart straight into the test session
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = buyer_id
            sess["cart"] = session_cart

        # Simulate a database error containing internal details, then call the real checkout route
        raw_error = 'relation "order_items" violates constraint SECRET_DB_DETAIL'
        with patch.object(checkout_service, "create_order_item", side_effect=Exception(raw_error)):
            response = client.post("/api/checkout/complete", json=BUYER_DETAILS)

        # The request should fail, but the internal details must not appear in the error message
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotIn("SECRET_DB_DETAIL", response.get_json()["error"])

    def test_sold_out_message_is_still_shown_to_buyer(self):
        """Errors meant for the buyer (like 'sold out') should still come through clearly."""
        # Listing with zero stock, so checkout should be rejected as sold out
        listing_id = self._create_listing(quantity_on_hand=0)
        buyer_id, session_cart = self._create_buyer_with_cart(listing_id)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = buyer_id
            sess["cart"] = session_cart

        response = client.post("/api/checkout/complete", json=BUYER_DETAILS)

        # The buyer gets a clear "sold out" message and no order is saved
        self.assertIn(response.status_code, (400, 409))
        self.assertIn("sold out", response.get_json()["error"])
        self.assertEqual(self._order_count(buyer_id), 0)


if __name__ == "__main__":
    unittest.main()
