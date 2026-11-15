import io
import os
import sys

from PIL import Image
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
BACKEND = os.path.join(ROOT, "backend")

sys.path.insert(0, ROOT)
sys.path.insert(0, BACKEND)

os.environ.setdefault("SECRET_KEY", "pytest-secret")

import init_db
init_db.create_vault_tables = lambda: None

from app import create_app
import utils.s3 as s3


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.static_folder = str(tmp_path)

    monkeypatch.setattr(s3, "BUCKET_NAME", None)

    return app.test_client()


def login(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["role"] = "user"


def make_image():
    image = Image.new("RGB", (10, 10), color="red")
    file = io.BytesIO()
    image.save(file, format="PNG")
    file.seek(0)
    return file


def test_upload_requires_login(client):
    response = client.post(
        "/api/storefronts/upload-image",
        data={"file": (make_image(), "test.png"), "folder": "storefronts"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_valid_image_upload_saves_locally(client, tmp_path):
    login(client)
    response = client.post(
        "/api/storefronts/upload-image",
        data={"file": (make_image(), "test.png"), "folder": "storefronts"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["url"].startswith("/static/uploads/storefronts/")
    assert list((tmp_path / "uploads" / "storefronts").iterdir())


def test_invalid_image_contents_are_rejected(client):
    login(client)
    response = client.post(
        "/api/storefronts/upload-image",
        data={"file": (io.BytesIO(b"this is not an image"), "fake.png"),
              "folder": "storefronts"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_unapproved_upload_folder_is_rejected(client):
    login(client)
    response = client.post(
        "/api/storefronts/upload-image",
        data={"file": (make_image(), "test.png"), "folder": "random-folder"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400