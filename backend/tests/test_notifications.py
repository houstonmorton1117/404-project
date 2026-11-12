# backend/tests/test_notifications.py
# Test for the in-app notification system (Iteration 4, Houston Morton):
# a buyer gets notified when an admin changes their return's status.
#
# Creates its own user and return record and deletes them afterward.

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

PASSWORD_HASH = "not-a-real-hash"  # this user never logs in, so the password doesn't matter


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
def buyer():
    username = f"notif_buyer_{uuid.uuid4().hex[:8]}"
    user_id = _query(
        "INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id",
        (username, PASSWORD_HASH, f"{username}@hamptonu.edu"), commit=True,
    )[0][0]
    yield user_id
    _query("DELETE FROM users WHERE username = %s", (username,), commit=True)


def test_buyer_is_notified_when_their_return_status_changes(client, buyer):
    from services.notification_service import get_notifications_service

    return_id = _query(
        """INSERT INTO returns (user_id, order_number, reason, has_damage, status)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (buyer, "SHOWTIME-TEST-1", "Wrong size", False, "pending"), commit=True,
    )[0][0]

    with client.session_transaction() as sess:
        sess["user"] = "admin"
        sess["role"] = "admin"

    response = client.patch(f"/admin/returns/{return_id}", json={"status": "resolved"})
    assert response.status_code == 200

    notifications = get_notifications_service(buyer)
    assert any("resolved" in n["message"] for n in notifications)

    _query("DELETE FROM returns WHERE id = %s", (return_id,), commit=True)
