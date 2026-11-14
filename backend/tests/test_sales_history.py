# backend/tests/test_sales_history.py
# Tests for Seller Sales History (added 11/14/26): a seller's Sales History tab
# lists each item sold from their storefront with the buyer, date and amount.
#
# Creates its own users, storefronts, listings and order, and deletes them afterward.

import os
import sys
import uuid

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from app import create_app
from db import get_connection

PASSWORD_HASH = "not-a-real-hash"  # these users never log in, so the password doesn't matter


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _query(sql, params=(), commit=False):
    """Runs one SQL statement on a fresh connection and returns any rows."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall() if cur.description else None
    if commit:
        conn.commit()
    cur.close()
    conn.close()
    return rows


def _make_user(prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return _query(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (username, PASSWORD_HASH, f"{username}@hamptonu.edu"), commit=True,
    )[0][0]


def _make_seller_with_listing(prefix, title, price):
    """Creates a user with a storefront and one listing. Returns (user_id, listing_id)."""
    user_id = _make_user(prefix)
    storefront_id = _query(
        "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
        (user_id, f"{prefix} brand"), commit=True,
    )[0][0]
    listing_id = _query(
        """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand)
           VALUES (%s, %s, %s, 'IN_STOCK', 10) RETURNING id""",
        (storefront_id, title, price), commit=True,
    )[0][0]
    return user_id, listing_id


@pytest.fixture
def marketplace():
    """Two sellers, one buyer, and one order containing items from both sellers."""
    seller_id, hoodie_id = _make_seller_with_listing("sales_seller", "Gold Hoodie", 40)
    other_seller_id, cap_id = _make_seller_with_listing("sales_other", "Snapback Cap", 15)
    buyer_id = _make_user("sales_buyer")

    confirmation = f"SALES-TEST-{uuid.uuid4().hex[:8].upper()}"
    order_id = _query(
        """INSERT INTO orders (user_id, confirmation_number, buyer_first_name, buyer_last_name,
                               buyer_email, buyer_contact, buyer_meeting_location, total_amount)
           VALUES (%s, %s, 'Jordan', 'Buyer', 'jordan@hamptonu.edu', '555-0100', 'Student Center', 95)
           RETURNING id""",
        (buyer_id, confirmation), commit=True,
    )[0][0]
    _query(
        """INSERT INTO order_items (order_id, listing_id, item_name, quantity, price_at_purchase, selected_size)
           VALUES (%s, %s, 'Gold Hoodie', 2, 40, 'M'), (%s, %s, 'Snapback Cap', 1, 15, NULL)""",
        (order_id, hoodie_id, order_id, cap_id), commit=True,
    )

    yield {
        "seller_id": seller_id,
        "other_seller_id": other_seller_id,
        "buyer_id": buyer_id,
        "confirmation": confirmation,
    }

    # Deleting the users cascades to their storefronts, listings and orders (and order items).
    for user_id in (buyer_id, seller_id, other_seller_id):
        _query("DELETE FROM users WHERE id = %s", (user_id,), commit=True)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_seller_sees_only_their_own_sold_items(client, marketplace):
    _login(client, marketplace["seller_id"])

    response = client.get("/api/orders/sales")
    assert response.status_code == 200
    data = response.get_json()

    assert len(data["sales"]) == 1
    sale = data["sales"][0]
    assert sale["item_name"] == "Gold Hoodie"
    assert sale["buyer_name"] == "Jordan Buyer"
    assert sale["quantity"] == 2
    assert sale["selected_size"] == "M"
    assert sale["amount"] == 80.0
    assert sale["confirmation_number"] == marketplace["confirmation"]
    assert sale["sold_at"]

    # Totals cover only this seller's share of the order, not the $95 order total.
    assert data["total_items"] == 2
    assert data["total_amount"] == 80.0


def test_other_seller_in_same_order_sees_their_item(client, marketplace):
    _login(client, marketplace["other_seller_id"])

    data = client.get("/api/orders/sales").get_json()
    assert [s["item_name"] for s in data["sales"]] == ["Snapback Cap"]
    assert data["total_amount"] == 15.0


def test_user_without_sales_gets_empty_list(client, marketplace):
    _login(client, marketplace["buyer_id"])

    response = client.get("/api/orders/sales")
    assert response.status_code == 200
    assert response.get_json() == {"sales": [], "total_items": 0, "total_amount": 0}


def test_sales_history_requires_login(client):
    response = client.get("/api/orders/sales")
    assert response.status_code == 401
