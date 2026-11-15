# backend/tests/test_owner_deactivation.py
# hide storefronts and listings whose owner is deactivated.
# Added by Jasmine Mark 11/14/26. Runs against the database in .env (creates and removes its own test data).

import os
import sys
import uuid

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from db import get_connection
from models.admin_model import set_user_active
from models.checkout_model import check_listing_availability, OutOfStockError


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def run(sql, params=(), fetch=False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        result = cur.fetchone() if fetch else None
        conn.commit()
        cur.close()
        return result
    finally:
        conn.close()


@pytest.fixture
def seller():
    """A user with an active storefront and one in-stock listing. Removed after the test."""
    unique = uuid.uuid4().hex[:8]
    title = f"Owner Test Hoodie {unique}"
    user_id = run(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (f"owner_test_{unique}", "x", f"owner_test_{unique}@hamptonu.edu"), fetch=True)[0]
    store_id = run(
        "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
        (user_id, f"Owner Test Brand {unique}"), fetch=True)[0]
    listing_id = run(
        """INSERT INTO listings (storefront_id, title, price, fulfillment_type, quantity_on_hand)
           VALUES (%s, %s, 25.00, 'IN_STOCK', 5) RETURNING id""",
        (store_id, title), fetch=True)[0]
    yield {"user_id": user_id, "store_id": store_id, "listing_id": listing_id, "title": title}
    # Deleting the user also removes the storefront and listing (ON DELETE CASCADE)
    run("DELETE FROM users WHERE id = %s", (user_id,))


@pytest.fixture
def admin_id():
    """A real admin user, since get_current_user() needs a user_id in the session."""
    unique = uuid.uuid4().hex[:8]
    user_id = run(
        "INSERT INTO users (username, password, email, role) VALUES (%s, %s, %s, 'admin') RETURNING id",
        (f"admin_test_{unique}", "x", f"admin_test_{unique}@hamptonu.edu"), fetch=True)[0]
    yield user_id
    run("DELETE FROM users WHERE id = %s", (user_id,))


def as_admin(client, admin_id):
    with client.session_transaction() as s:
        s["user"] = "admin"
        s["role"] = "admin"
        s["user_id"] = admin_id


def store_ids(client):
    return {s["id"] for s in client.get("/api/storefronts").get_json()}


def search_ids(client, q):
    return {i["id"] for i in client.get("/api/listings", query_string={"q": q, "limit": 50}).get_json()["items"]}


# -- storefront list ----

def test_store_hidden_while_owner_deactivated_and_back_after_restore(client, seller):
    assert seller["store_id"] in store_ids(client)

    set_user_active(seller["user_id"], False)
    assert seller["store_id"] not in store_ids(client)

    set_user_active(seller["user_id"], True)
    assert seller["store_id"] in store_ids(client)


def test_store_owner_switched_off_stays_off_after_restore(client, seller):
    run("UPDATE storefronts SET is_active = FALSE WHERE id = %s", (seller["store_id"],))
    set_user_active(seller["user_id"], False)
    set_user_active(seller["user_id"], True)
    assert seller["store_id"] not in store_ids(client)

# ---- saved links: store page, store listings, single listing ----

@pytest.mark.parametrize("path", [
    "/api/storefronts/{store_id}",
    "/api/storefronts/{store_id}/listings",
    "/api/listings/{listing_id}",
])
def test_saved_links_hidden_from_public_but_not_admins(client, seller, admin_id, path):
    url = path.format(**seller)
    assert client.get(url).status_code == 200

    set_user_active(seller["user_id"], False)
    assert client.get(url).status_code == 404

    as_admin(client, admin_id)
    assert client.get(url).status_code == 200


# ---- search ---

def test_search_works_and_hides_deactivated_owner(client, seller):
    assert seller["listing_id"] in search_ids(client, seller["title"])

    set_user_active(seller["user_id"], False)
    assert seller["listing_id"] not in search_ids(client, seller["title"])

    set_user_active(seller["user_id"], True)
    assert seller["listing_id"] in search_ids(client, seller["title"])


def test_search_skips_deleted_listings(client, seller):
    run("UPDATE listings SET status = 'DELETED' WHERE id = %s", (seller["listing_id"],))
    assert seller["listing_id"] not in search_ids(client, seller["title"])


def test_search_returns_title_as_name(client, seller):
    items = client.get("/api/listings", query_string={"q": seller["title"]}).get_json()["items"]
    assert items[0]["name"] == seller["title"]


# --- checkout and add to bag ----

def test_checkout_refuses_item_from_deactivated_owner(seller):
    check_listing_availability(seller["listing_id"], 1)

    set_user_active(seller["user_id"], False)
    with pytest.raises(OutOfStockError, match="no longer available"):
        check_listing_availability(seller["listing_id"], 1)

    set_user_active(seller["user_id"], True)
    check_listing_availability(seller["listing_id"], 1)


def test_add_to_bag_refuses_item_from_deactivated_owner(client, seller):
    buyer_id = run(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (f"buyer_test_{uuid.uuid4().hex[:8]}", "x", f"buyer_{uuid.uuid4().hex[:8]}@hamptonu.edu"),
        fetch=True)[0]
    try:
        with client.session_transaction() as s:
            s["user"] = "buyer"
            s["user_id"] = buyer_id

        set_user_active(seller["user_id"], False)
        res = client.post("/auth/add_to_cart", data={"item_id": seller["listing_id"], "quantity": 1})
        assert res.status_code == 409
        assert "no longer available" in res.get_json()["error"]
    finally:
        run("DELETE FROM users WHERE id = %s", (buyer_id,))
