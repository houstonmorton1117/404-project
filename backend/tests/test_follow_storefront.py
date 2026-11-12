# backend/tests/test_follow_storefront.py
# Test for "Follow a storefront" (Iteration 4, Houston Morton): a user can follow
# a storefront, it shows up on their account's following list, and they get
# notified through the notification system when that store posts a new listing.
#
# Creates its own users, storefront, and listing and deletes them afterward.

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


@pytest.fixture
def owner_and_storefront():
    tag = uuid.uuid4().hex[:8]
    username = f"follow_owner_{tag}"
    owner_id = _query(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (username, PASSWORD_HASH, f"{username}@hamptonu.edu"), commit=True,
    )[0][0]
    storefront_id = _query(
        "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
        (owner_id, f"Follow Test Store {tag}"), commit=True,
    )[0][0]
    yield owner_id, storefront_id
    _query("DELETE FROM users WHERE username = %s", (username,), commit=True)


@pytest.fixture
def follower():
    username = f"follow_follower_{uuid.uuid4().hex[:8]}"
    user_id = _query(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (username, PASSWORD_HASH, f"{username}@hamptonu.edu"), commit=True,
    )[0][0]
    yield user_id
    _query("DELETE FROM users WHERE username = %s", (username,), commit=True)


def test_follower_sees_store_in_following_list_and_is_notified_of_new_listing(
    client, owner_and_storefront, follower
):
    owner_id, storefront_id = owner_and_storefront

    with client.session_transaction() as sess:
        sess["user_id"] = follower

    follow_res = client.post(f"/api/storefronts/{storefront_id}/follow")
    assert follow_res.status_code == 200
    assert follow_res.get_json()["following"] is True

    following_res = client.get("/api/account/following")
    following = following_res.get_json()["following"]
    assert any(store["id"] == storefront_id for store in following)

    from services.listing_service import create_listing_service
    from services.notification_service import get_notifications_service

    current_user = {"id": owner_id, "role": "user"}
    listing = create_listing_service(current_user, storefront_id, {
        "title": "New Drop Hoodie",
        "price": 40.00,
        "fulfillment_type": "IN_STOCK",
        "quantity_on_hand": 5,
    })

    notifications = get_notifications_service(follower)
    assert any("New Drop Hoodie" in n["message"] for n in notifications)

    _query("DELETE FROM listings WHERE id = %s", (listing["id"],), commit=True)
