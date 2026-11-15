# backend/tests/test_account_settings.py
# account Settings (Settings tab): change email and change password.
# added by Jasmine Mark 11/12/26. uses a fake DB connection, so no database is needed.

import os
import sys

import pytest
from flask import Flask

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.auth_services import AuthService, is_valid_password
from utils.auth_utils import hash_password, verify_password
import controllers.auth_controller as auth_controller


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self._result = None

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.db.queries.append((sql, params))
        if sql.startswith("SELECT 1 FROM users WHERE LOWER(email)"):
            email, user_id = params
            self._result = next(
                ((1,) for uid, u in self.db.users.items()
                 if u["email"].lower() == email.lower() and uid != user_id), None)
        elif sql.startswith("SELECT password FROM users"):
            u = self.db.users.get(params[0])
            self._result = (u["password"],) if u else None
        elif sql.startswith("UPDATE users SET email"):
            email, user_id = params
            self.rowcount = int(user_id in self.db.users)
            if self.rowcount:
                self.db.users[user_id]["email"] = email
        elif sql.startswith("UPDATE users SET password"):
            pw, user_id = params
            self.rowcount = int(user_id in self.db.users)
            if self.rowcount:
                self.db.users[user_id]["password"] = pw
        else:
            raise AssertionError(f"unexpected query: {sql}")

    def fetchone(self):
        return self._result

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.users = {
            1: {"email": "alice@hamptonu.edu", "password": hash_password("oldpassword")},
            2: {"email": "bob@my.hamptonu.edu", "password": hash_password("bobpassword")},
        }
        self.queries = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def db():
    return FakeConn()


@pytest.fixture
def svc():
    return AuthService()


# ---- is_valid_password (stand-in until Joshua's rules are merged) ----

def test_password_rule_requires_8_characters():
    assert not is_valid_password("short")
    assert not is_valid_password(None)
    assert is_valid_password("eightchr")


# ---- update_email ----

@pytest.mark.parametrize("email", ["alice@gmail.com", "", None, "alice@hamptonu.edu.evil.com"])
def test_update_email_rejects_non_hampton_addresses(svc, db, email):
    ok, _ = svc.update_email(1, email, db)
    assert not ok
    assert db.users[1]["email"] == "alice@hamptonu.edu"


def test_update_email_rejects_email_used_by_another_user(svc, db):
    ok, msg = svc.update_email(1, "BOB@my.hamptonu.edu", db)
    assert not ok and "already in use" in msg
    assert db.users[1]["email"] == "alice@hamptonu.edu"


def test_update_email_allows_keeping_own_email(svc, db):
    ok, _ = svc.update_email(1, "alice@hamptonu.edu", db)
    assert ok


def test_update_email_saves_new_address(svc, db):
    ok, _ = svc.update_email(1, "  alice.new@my.hamptonu.edu ", db)
    assert ok
    assert db.users[1]["email"] == "alice.new@my.hamptonu.edu"
    assert db.commits == 1


# ---- change_password ----

def test_change_password_requires_correct_current_password(svc, db):
    ok, msg = svc.change_password(1, "wrongpassword", "newpassword1", "newpassword1", db)
    assert not ok and "incorrect" in msg
    assert verify_password(db.users[1]["password"], "oldpassword")


def test_change_password_rejects_mismatched_confirmation(svc, db):
    ok, msg = svc.change_password(1, "oldpassword", "newpassword1", "newpassword2", db)
    assert not ok and "match" in msg


def test_change_password_rejects_weak_new_password(svc, db):
    ok, _ = svc.change_password(1, "oldpassword", "short", "short", db)
    assert not ok
    assert verify_password(db.users[1]["password"], "oldpassword")


def test_change_password_saves_hashed_password(svc, db):
    ok, _ = svc.change_password(1, "oldpassword", "newpassword1", "newpassword1", db)
    assert ok
    stored = db.users[1]["password"]
    assert stored != "newpassword1"
    assert verify_password(stored, "newpassword1")


# ---- routes ----

@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(auth_controller, "get_connection", lambda: db)
    app = Flask(__name__)
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(auth_controller.auth_bp, url_prefix="/auth")
    return app.test_client()


def login_as(client, user_id):
    with client.session_transaction() as s:
        s["user"] = f"user{user_id}"
        s["user_id"] = user_id


@pytest.mark.parametrize("path", ["/auth/account/email", "/auth/account/password"])
def test_settings_routes_require_login(client, path):
    res = client.post(path, data={})
    assert res.status_code == 401


def test_email_route_uses_session_user_not_form(client, db):
    login_as(client, 1)
    res = client.post("/auth/account/email",
                      data={"email": "new@hamptonu.edu", "user_id": "2"})
    assert res.status_code == 200
    assert db.users[1]["email"] == "new@hamptonu.edu"
    assert db.users[2]["email"] == "bob@my.hamptonu.edu"
    assert db.closed


def test_email_route_returns_error_message(client):
    login_as(client, 1)
    res = client.post("/auth/account/email", data={"email": "x@gmail.com"})
    assert res.status_code == 400
    assert "Hampton" in res.get_json()["error"]


def test_password_route_changes_password(client, db):
    login_as(client, 1)
    res = client.post("/auth/account/password", data={
        "current_password": "oldpassword",
        "new_password": "newpassword1",
        "confirm_password": "newpassword1",
    })
    assert res.status_code == 200
    assert verify_password(db.users[1]["password"], "newpassword1")


def test_password_route_rejects_wrong_current_password(client):
    login_as(client, 1)
    res = client.post("/auth/account/password", data={
        "current_password": "nope",
        "new_password": "newpassword1",
        "confirm_password": "newpassword1",
    })
    assert res.status_code == 400


# ---deactivate my account (added 11/13/26) ----

@pytest.fixture
def deactivated(monkeypatch):
    """Records calls to set_user_active instead of touching the database."""
    calls = []

    def fake_set_user_active(user_id, is_active):
        calls.append((user_id, is_active))
        return 1

    monkeypatch.setattr("services.auth_services.set_user_active", fake_set_user_active)
    return calls

def test_deactivate_service_requires_password(svc, db, deactivated):
    ok, _ = svc.deactivate_own_account(1, "", db)
    assert not ok
    assert deactivated == []


def test_deactivate_service_rejects_wrong_password(svc, db, deactivated):
    ok, msg = svc.deactivate_own_account(1, "wrongpassword", db)
    assert not ok and "incorrect" in msg
    assert deactivated == []


def test_deactivate_route_requires_login(client, deactivated):
    res = client.post("/auth/account/deactivate", data={"password": "oldpassword"})
    assert res.status_code == 401
    assert deactivated == []


def test_deactivate_route_rejects_wrong_password(client, deactivated):
    login_as(client, 1)
    res = client.post("/auth/account/deactivate", data={"password": "wrongpassword"})
    assert res.status_code == 400
    assert deactivated == []
    with client.session_transaction() as s:
        assert s.get("user_id") == 1


def test_deactivate_route_deactivates_and_logs_out(client, deactivated):
    login_as(client, 1)
    res = client.post("/auth/account/deactivate",
                      data={"password": "oldpassword", "user_id": "2"})
    assert res.status_code == 200
    assert res.get_json()["redirect"].endswith("/auth/login")
    # Uses the session user (1), never the user_id sent in the form (2)
    assert deactivated == [(1, False)]
    with client.session_transaction() as s:
        assert "user" not in s and "user_id" not in s
        assert ("info", "Your account has been deactivated.") in s.get("_flashes", [])

def test_admin_cannot_deactivate_own_account(client, deactivated):
    with client.session_transaction() as s:
        s["user"] = "admin"
        s["user_id"] = 1
        s["role"] = "Admin"
    res = client.post("/auth/account/deactivate", data={"password": "oldpassword"})
    assert res.status_code == 400
    assert "Administrators" in res.get_json()["error"]
    assert deactivated == []
