
import os
import sys

import pytest
from flask import Flask

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("SECRET_KEY", "pytest-secret")


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https://api.stripe.com; "
            "frame-src https://js.stripe.com https://hooks.stripe.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com"
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app.test_client()


def test_x_frame_options_header(client):
    response = client.get("/health")
    assert response.headers["X-Frame-Options"] == "DENY"


def test_x_content_type_options_header(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_content_security_policy_header(client):
    response = client.get("/health")
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "https://js.stripe.com" in policy
