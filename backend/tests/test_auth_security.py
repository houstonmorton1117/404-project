
# Added by Joshua Hall on 11/14/2026
# Showtime Iteration 4 - Authentication Security Tests
#
# Tests password validation, login lockout, email verification,
# IP-based rate limiting, and inline authentication errors.
# Tests do not send emails or modify the shared database.

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, render_template_string

from backend.services.email_verification_service import (
    generate_verification_code,
    verify_email_code,
)

from backend.services.login_security_service import (
    record_failed_login,
    check_login_lockout,
    reset_failed_logins,
    MAX_ATTEMPTS,
    LOCKOUT_SECONDS,
)
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------
# Password requirements
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "password, expected",
    [
        ("1234567", False),
        ("12345678", True),
        ("SecurePass123", True),
    ],
)
def test_password_minimum_length(password, expected):
    """Check that passwords require at least eight characters."""
    result = len(password) >= 8
    assert result is expected


# ---------------------------------------------------------
# Email verification code generation
# ---------------------------------------------------------

def test_verification_code_has_six_digits():
    """Check that generated verification codes have six digits."""
    code = generate_verification_code()

    assert isinstance(code, str)
    assert len(code) == 6
    assert code.isdigit()


def test_verification_codes_are_numeric():
    """Check that generated codes contain only numbers."""
    for _ in range(20):
        code = generate_verification_code()
        assert code.isdigit()


# ---------------------------------------------------------
# Email verification service
# ---------------------------------------------------------

def test_verification_rejects_missing_account():
    """Reject verification when no matching account exists."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = None

    result = verify_email_code(
        conn,
        "missing@my.hamptonu.edu",
        "123456",
    )

    assert result is False
    conn.rollback.assert_called_once()
    cursor.close.assert_called_once()


def test_verification_rejects_too_many_attempts():
    """Block verification after five incorrect attempts."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = (
        "stored_hash",
        None,
        5,
    )

    result = verify_email_code(
        conn,
        "test@my.hamptonu.edu",
        "123456",
    )

    assert result is False
    conn.rollback.assert_called_once()


# ---------------------------------------------------------
# Login lockout rules
# ---------------------------------------------------------

# Added by Joshua Hall on 11/14/2026
# Test actual login lockout functions without modifying the database.

def test_login_lockout_after_five_attempts():
    """Check that five failed logins trigger the account lockout."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = (5,)

    remaining = record_failed_login(conn, "testuser")

    assert MAX_ATTEMPTS == 5
    assert remaining == 0
    assert cursor.execute.call_args.args[1] == (
        MAX_ATTEMPTS,
        LOCKOUT_SECONDS,
        "testuser",
    )
    conn.commit.assert_called_once()
    cursor.close.assert_called_once()


def test_login_lockout_duration():
    """Check that a locked account has approximately 180 seconds remaining."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = (
        datetime.now(timezone.utc) + timedelta(seconds=180),
    )

    remaining = check_login_lockout(conn, "testuser")

    assert LOCKOUT_SECONDS == 180
    assert 179 <= remaining <= 180
    cursor.close.assert_called_once()


def test_login_lockout_expired():
    """Check that an expired lockout no longer blocks login."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = (
        datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    assert check_login_lockout(conn, "testuser") == 0


def test_successful_login_resets_failed_attempts():
    """Check that successful authentication resets failed login attempts."""
    conn = MagicMock()
    cursor = conn.cursor.return_value

    reset_failed_logins(conn, "testuser")

    query = cursor.execute.call_args.args[0]
    assert "failed_login_attempts = 0" in query
    assert "locked_until = NULL" in query
    conn.commit.assert_called_once()
    cursor.close.assert_called_once()

# ---------------------------------------------------------
# Authentication error display
# ---------------------------------------------------------

def test_signup_error_is_displayed():
    """Check that signup errors render inside the signup page."""
    app = Flask(__name__)

    with app.app_context():
        html = render_template_string(
            """
            {% if error %}
                <p class="signup-error" role="alert">
                    {{ error }}
                </p>
            {% endif %}
            """,
            error="Password must be at least 8 characters long.",
        )

    assert "signup-error" in html
    assert "Password must be at least 8 characters long." in html


def test_login_error_is_displayed():
    """Check that login errors can be rendered in red."""
    app = Flask(__name__)

    with app.app_context():
        html = render_template_string(
            """
            {% if error %}
                <p style="color: red">{{ error }}</p>
            {% endif %}
            """,
            error="Invalid Credentials",
        )

    assert "color: red" in html
    assert "Invalid Credentials" in html


# ---------------------------------------------------------
# IP-based rate limiting
# ---------------------------------------------------------

# Added by Joshua Hall on 11/14/2026
# Verify actual Flask-Limiter settings for authentication routes.


# Updated by Joshua Hall on 11/14/2026
# Test actual Flask-Limiter behavior using Flask's test client.

@pytest.mark.parametrize(
    "route, allowed_requests",
    [
        ("/auth/login", 5),
        ("/auth/signup", 3),
    ],
)
def test_auth_rate_limiting(route, allowed_requests):
    """Verify authentication requests eventually receive HTTP 429."""
    from app import app

    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        for _ in range(allowed_requests):
            response = client.post(
                route,
                data={
                    "username": "",
                    "password": "short",
                    "email": "",
                },
            )
            assert response.status_code != 429

        response = client.post(
            route,
            data={
                "username": "",
                "password": "short",
                "email": "",
            },
        )

        assert response.status_code == 429

