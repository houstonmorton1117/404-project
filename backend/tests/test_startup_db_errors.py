# backend/tests/test_startup_db_errors.py
# startup reports database errors instead of hiding them.
# added by Jasmine Mark 11/14/26. Uses a fake database, so no DB connection is needed.

import os
import sys

import psycopg2
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import init_db


class FakeCursor:
    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.count = 0

    def execute(self, sql, params=None):
        self.count += 1
        if self.count == self.fail_on:
            raise psycopg2.ProgrammingError("simulated schema failure")

    def close(self):
        pass


class FakeConn:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self.fail_on)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


# ---- init_db.create_vault_tables ---

def test_success_commits_and_closes(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(init_db.psycopg2, "connect", lambda **kw: conn)
    init_db.create_vault_tables()
    assert conn.committed and conn.closed and not conn.rolled_back


def test_failed_statement_rolls_back_closes_and_raises(monkeypatch):
    conn = FakeConn(fail_on=3)
    monkeypatch.setattr(init_db.psycopg2, "connect", lambda **kw: conn)
    with pytest.raises(psycopg2.ProgrammingError, match="simulated schema failure"):
        init_db.create_vault_tables()
    assert conn.rolled_back and conn.closed and not conn.committed


def test_connection_failure_is_raised(monkeypatch):
    def refuse(**kw):
        raise psycopg2.OperationalError("could not connect to server")
    monkeypatch.setattr(init_db.psycopg2, "connect", refuse)
    with pytest.raises(psycopg2.OperationalError, match="could not connect"):
        init_db.create_vault_tables()

# ---- app startup ----

def load_create_app(monkeypatch):
    # app.py runs create_app() when it's imported, so import it with a no-op database setup first
    monkeypatch.setattr(init_db, "create_vault_tables", lambda: None)
    from app import create_app
    return create_app


def test_app_startup_stops_with_clear_message(monkeypatch):
    create_app = load_create_app(monkeypatch)

    def broken():
        raise psycopg2.OperationalError("password authentication failed")
    monkeypatch.setattr(init_db, "create_vault_tables", broken)

    with pytest.raises(RuntimeError) as exc:
        create_app()
    message = str(exc.value)
    assert "Could not set up the database" in message
    assert "password authentication failed" in message
    for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        assert name in message


def test_app_starts_when_database_is_fine(monkeypatch):
    create_app = load_create_app(monkeypatch)
    assert create_app() is not None