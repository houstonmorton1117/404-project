# backend/tests/test_login_connection.py
# Tests that the login route always closes its database connection.
# Added by Jasmine Mark
#
# These tests don't need a real database. They replace get_connection() with a
# fake connection (a MagicMock) and then check that conn.close() was called.

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# add project root and backend folder to the Python path (same as the other tests)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
import controllers.auth_controller as auth_controller


@pytest.fixture
def client():
    # Each test gets a Flask test client in test mode.
    # CSRF is off because the test client can't send CSRF tokens.
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def test_connection_closes_on_failed_login(client):
    """Wrong password: the old code leaked the connection here."""
    fake_conn = MagicMock()
    #swap in the fake connection and make validate_login report a wrong password
    with patch.object(auth_controller, "get_connection", return_value=fake_conn), \
         patch.object(auth_controller.service, "validate_login", return_value=(False, None)):
        response = client.post("/auth/login", data={"username": "someone", "password": "wrong"})

    #the login page shows the error, and the connection was closed exactly once
    assert b"Invalid Credentials" in response.data
    fake_conn.close.assert_called_once()


def test_connection_closes_on_successful_login(client):
    """Correct password: the connection should still be closed exactly once."""
    fake_conn = MagicMock()
    # When the route looks up the user's id, the fake database returns 1
    fake_conn.cursor.return_value.fetchone.return_value = (1,)
    # Make validate_login succeed and return an empty saved cart
    with patch.object(auth_controller, "get_connection", return_value=fake_conn), \
         patch.object(auth_controller.service, "validate_login", return_value=(True, "user")), \
         patch.object(auth_controller.service, "get_user_cart", return_value=[]):
        response = client.post("/auth/login", data={"username": "someone", "password": "right"})

    assert response.status_code == 302  # redirected to the storefront page
    fake_conn.close.assert_called_once()


def test_connection_closes_when_an_error_happens(client):
    """Even if something crashes during login, the finally block still closes the connection."""
    fake_conn = MagicMock()
    # Make validate_login crash to simulate a database failure
    with patch.object(auth_controller, "get_connection", return_value=fake_conn), \
         patch.object(auth_controller.service, "validate_login", side_effect=Exception("database error")):
        # In TESTING mode Flask re-raises the error instead of returning a 500 page
        with pytest.raises(Exception):
            client.post("/auth/login", data={"username": "someone", "password": "pw"})

    fake_conn.close.assert_called_once()
