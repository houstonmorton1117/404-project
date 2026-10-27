# By Elali McNair 4/19/26
# Updated 10/26 - rewritten to log in via the real session instead of
# setting an X-User-Id header directly. Setting that header alone used to
# be enough to authenticate as any user id -- a broken access control bug
# fixed this iteration -- so these tests now create their own user and
# storefront and log in for real, matching how the app is actually used.
import io
import os
import sys
import unittest
import uuid

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from app import create_app
from backend.config.db import get_connection

PASSWORD = "pw12345"


class TestCreateListingFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        if get_connection() is None:
            raise unittest.SkipTest("Database not available.")

    def setUp(self):
        tag = uuid.uuid4().hex[:8]
        self.username = f"cl_owner_{tag}"
        self.client = self.app.test_client()
        self.created_listing_ids = []

        self.client.post("/auth/signup", data={
            "username": self.username, "password": PASSWORD, "email": f"{self.username}@hamptonu.edu",
        })
        self.user_id = self._query("SELECT id FROM users WHERE username = %s", (self.username,))[0][0]
        self.storefront_id = self._query(
            "INSERT INTO storefronts (owner_id, brand_name) VALUES (%s, %s) RETURNING id",
            (self.user_id, f"CL Store {tag}"), commit=True,
        )[0][0]

        self.client.post("/auth/login", data={"username": self.username, "password": PASSWORD})

    def tearDown(self):
        self._query("DELETE FROM users WHERE username = %s", (self.username,), commit=True)

    def _query(self, sql, params=(), commit=False):
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            if commit:
                conn.commit()
            return rows
        finally:
            cur.close()
            conn.close()

    def test_create_listing_from_form_success(self):
        unique_title = f"TEST_CREATE_LISTING_{uuid.uuid4().hex[:8]}"

        response = self.client.post(
            "/api/listings/create",
            data={
                "title": unique_title,
                "quantity_on_hand": "5",
                "price": "39.99",
                "fulfillment_type": "IN_STOCK",
                "status": "ACTIVE",
                "sizes_available": '["M", "L"]',
                "listing_image": (io.BytesIO(b"fake image bytes"), "test_listing.png"),
            },
            content_type="multipart/form-data",
        )

        if response.status_code == 500 and "S3" in response.get_data(as_text=True):
            self.skipTest("AWS S3 isn't configured in this environment (no AWS_S3_BUCKET in .env).")

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        payload = response.get_json()

        self.assertIsNotNone(payload)
        self.assertEqual(payload["title"], unique_title)
        self.assertEqual(payload["storefront_id"], self.storefront_id)
        self.assertEqual(payload["status"], "ACTIVE")
        self.assertEqual(payload["fulfillment_type"], "IN_STOCK")

        listing_id = payload["id"]
        self.created_listing_ids.append(listing_id)

        verify_response = self.client.get(f"/api/storefronts/{self.storefront_id}/listings")
        self.assertEqual(verify_response.status_code, 200)

        listings = verify_response.get_json()
        matched = next((item for item in listings if item["id"] == listing_id), None)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["title"], unique_title)

    def test_create_listing_requires_image_file(self):
        response = self.client.post(
            "/api/listings/create",
            data={
                "title": f"TEST_CREATE_LISTING_{uuid.uuid4().hex[:8]}",
                "quantity_on_hand": "3",
                "price": "25.00",
                "fulfillment_type": "IN_STOCK",
                "status": "ACTIVE",
                "sizes_available": '["S"]',
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("listing image is required", response.get_data(as_text=True).lower())

    def test_create_listing_requires_authentication(self):
        self.client.get("/auth/logout")
        response = self.client.post(
            f"/api/storefronts/{self.storefront_id}/listings",
            json={
                "title": "Unauthorized Listing",
                "price": 20,
                "fulfillment_type": "IN_STOCK",
                "quantity_on_hand": 2,
            },
        )

        self.assertEqual(response.status_code, 401, response.get_data(as_text=True))
        self.assertIn("Unauthorized", response.get_data(as_text=True))

    def test_forged_header_cannot_impersonate_another_owner(self):
        """A logged-out request can't authenticate just by setting X-User-Id."""
        self.client.get("/auth/logout")
        response = self.client.post(
            "/api/listings/create",
            data={
                "title": "Impersonated Listing",
                "quantity_on_hand": "1",
                "price": "10.00",
                "fulfillment_type": "IN_STOCK",
                "status": "ACTIVE",
                "sizes_available": '["S"]',
                "listing_image": (io.BytesIO(b"fake image bytes"), "test.png"),
            },
            headers={"X-User-Id": str(self.user_id), "X-User-Role": "user"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 401, response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
