
import os
import pytest
from flask import Flask, session


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = "pytest-secret"

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv(
            "SESSION_COOKIE_SECURE", "false"
        ).lower() == "true"
    )

    @app.get("/test-session")
    def test_session():
        session["user_id"] = 1
        return {"status": "ok"}

    return app.test_client()


def test_session_cookie_is_httponly(client):
    response = client.get("/test-session")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie


def test_session_cookie_uses_samesite_lax(client):
    response = client.get("/test-session")
    cookie = response.headers["Set-Cookie"]
    assert "SameSite=Lax" in cookie


def test_session_cookie_secure_setting_is_false_locally(client):
    response = client.get("/test-session")
    cookie = response.headers["Set-Cookie"]
    assert "Secure" not in cookie
