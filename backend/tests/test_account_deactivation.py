# backend/tests/test_account_deactivation.py
# Admin deactivate / restore (replaces permanent delete).
# Added by Jasmine Mark 11/12/26. database is faked, so no DB connection is needed.

import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import init_db
import controllers.auth_controller as auth_controller
import services.admin_service as admin_service
from services.auth_services import AuthService, ACCOUNT_DEACTIVATED
from utils.auth_utils import hash_password


@pytest.fixture
def app(monkeypatch):
    # Skip the real DB migrations that create_app() runs on startup
    monkeypatch.setattr(init_db, "create_vault_tables", lambda: None)
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app

@pytest.fixture
def client(app):
    return app.test_client()


def set_session(client, user_id, role="user", username="student"):
    with client.session_transaction() as s:
        s["user"] = username
        s["role"] = role
        s["user_id"] = user_id


@pytest.fixture
def users_active(monkeypatch):
    """Fake users table: {user_id: is_active}. Used by the model functions."""
    users = {1: True, 2: True, 3: False}

    def fake_set_user_active(user_id, is_active):
        if user_id not in users:
            return 0
        users[user_id] = bool(is_active)
        return 1

    monkeypatch.setattr(admin_service, "set_user_active", fake_set_user_active)
    monkeypatch.setattr("models.admin_model._is_user_active", lambda uid: users.get(uid))
    return users

# ---- service ----

def test_admin_cannot_deactivate_self(users_active):
    with pytest.raises(ValueError):
        admin_service.deactivate_user(1, acting_user_id=1)
    assert users_active[1] is True


def test_deactivate_unknown_user_raises_lookup_error(users_active):
    with pytest.raises(LookupError):
        admin_service.deactivate_user(99, acting_user_id=1)


def test_admin_can_deactivate_and_restore_another_user(users_active):
    admin_service.deactivate_user(2, acting_user_id=1)
    assert users_active[2] is False
    admin_service.restore_user(2)
    assert users_active[2] is True


# ---- admin routes ----

def test_deactivate_route_requires_admin(client, users_active):
    set_session(client, 2, role="user")
    res = client.patch("/admin/users/1/deactivate")
    assert res.status_code == 403
    assert users_active[1] is True


def test_deactivate_route_blocks_own_account(client, users_active):
    set_session(client, 1, role="admin", username="admin")
    res = client.patch("/admin/users/1/deactivate")
    assert res.status_code == 400
    assert "own account" in res.get_json()["error"]


def test_deactivate_route_unknown_user_is_404(client, users_active):
    set_session(client, 1, role="admin", username="admin")
    res = client.patch("/admin/users/99/deactivate")
    assert res.status_code == 404


def test_deactivate_and_restore_routes(client, users_active):
    set_session(client, 1, role="admin", username="admin")
    assert client.patch("/admin/users/2/deactivate").status_code == 200
    assert users_active[2] is False
    assert client.patch("/admin/users/3/restore").status_code == 200
    assert users_active[3] is True


# ---- validate_login ----

class FakeLoginConn:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        conn = self

        class Cur:
            def execute(self, sql, params):
                pass

            def fetchone(self):
                return conn.row

            def close(self):
                pass

        return Cur()


def test_validate_login_refuses_deactivated_account_with_right_password():
    conn = FakeLoginConn((hash_password("rightpassword"), "user", False))
    assert AuthService().validate_login("bob", "rightpassword", conn) == (False, ACCOUNT_DEACTIVATED)


def test_validate_login_wrong_password_on_deactivated_account_is_plain_failure():
    conn = FakeLoginConn((hash_password("rightpassword"), "user", False))
    assert AuthService().validate_login("bob", "wrongpassword", conn) == (False, None)


def test_validate_login_active_account_still_works():
    conn = FakeLoginConn((hash_password("rightpassword"), "admin", True))
    assert AuthService().validate_login("bob", "rightpassword", conn) == (True, "admin")


# ---- login routes ----

class DummyConn:
    def close(self):
        pass


@pytest.fixture
def deactivated_login(monkeypatch):
    failed = []
    monkeypatch.setattr(auth_controller, "get_connection", lambda: DummyConn())
    monkeypatch.setattr(auth_controller, "check_login_lockout", lambda conn, user: 0)
    monkeypatch.setattr(auth_controller, "record_failed_login",
                        lambda conn, user: failed.append(user) or 4)
    monkeypatch.setattr(auth_controller.service, "validate_login",
                        lambda user, pw, conn: (False, ACCOUNT_DEACTIVATED))
    return failed


@pytest.mark.parametrize("path", ["/auth/login", "/auth/admin-login"])
def test_login_shows_deactivated_message_and_does_not_count_attempt(client, deactivated_login, path):
    res = client.post(path, data={"username": "bob", "password": "rightpassword"})
    assert res.status_code == 403
    assert b"This account has been deactivated. Contact an administrator." in res.data
    assert deactivated_login == []
    with client.session_transaction() as s:
        assert "user" not in s

# ---- before_request: signed out on next click ----

def test_deactivated_user_is_signed_out_on_next_request(client, users_active):
    set_session(client, 3)
    res = client.get("/auth/account")
    assert res.status_code == 302
    assert "/auth/login" in res.headers["Location"]
    with client.session_transaction() as s:
        assert "user" not in s and "user_id" not in s


def test_deactivated_user_api_call_gets_json_401(client, users_active):
    set_session(client, 3)
    res = client.post("/auth/account/email", data={"email": "x@hamptonu.edu"})
    assert res.status_code == 401
    assert "deactivated" in res.get_json()["error"]

def test_active_user_is_not_signed_out(client, users_active):
    set_session(client, 2)
    res = client.get("/auth/account")
    assert res.status_code == 200
