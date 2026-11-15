from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from flask import Flask

from backend.listing_search import listing_search


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(listing_search)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db():
    """Mocks get_db_connection and yields (mock_conn, mock_cursor)."""
    with patch("backend.listing_search.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Support `with conn.cursor(...) as cur:`
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        yield mock_conn, mock_cursor


def test_default_search_returns_formatted_items(client, mock_db):
    mock_conn, mock_cursor = mock_db
    sample_time = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "name": "Vintage Hoodie",
            "price": Decimal("49.99"),
            "created_at": sample_time,
            "total": 2,
        },
        {
            "id": 2,
            "name": "Free Sticker",
            "price": None,  # Tests nullable price handling
            "created_at": sample_time,
            "total": 2,
        },
    ]

    res = client.get("/api/listings")
    assert res.status_code == 200

    data = res.get_json()
    assert data == {
        "items": [
            {
                "id": 1,
                "name": "Vintage Hoodie",
                "price": 49.99,
                "created_at": "2026-05-01T12:00:00+00:00",
            },
            {
                "id": 2,
                "name": "Free Sticker",
                "price": None,
                "created_at": "2026-05-01T12:00:00+00:00",
            },
        ],
        "total": 2,
        "page": 1,
        "limit": 20,
        "sort": "newest",
        "q": "",
    }

    # Verify default SQL parameters (limit=20, offset=0) and connection cleanup
    sql, params = mock_cursor.execute.call_args[0]
    assert "ORDER BY created_at DESC, id DESC" in sql
    assert "WHERE" not in sql
    assert params == [20, 0]
    mock_conn.close.assert_called_once()


def test_empty_results(client, mock_db):
    _, mock_cursor = mock_db
    mock_cursor.fetchall.return_value = []

    res = client.get("/api/listings?q=nonexistent")
    assert res.status_code == 200

    data = res.get_json()
    assert data["items"] == []
    assert data["total"] == 0


def test_search_query_escapes_wildcards_and_truncates(client, mock_db):
    _, mock_cursor = mock_db
    mock_cursor.fetchall.return_value = []

    # Test LIKE wildcard escaping (%, _, \) and trimming
    res = client.get("/api/listings?q=%20100%25_wool\\coat%20")
    assert res.status_code == 200

    sql, params = mock_cursor.execute.call_args[0]
    assert "WHERE name ILIKE %s" in sql
    assert params[0] == "%100\\%\\_wool\\\\coat%"

    # Test 100-character truncation
    long_q = "a" * 150
    res = client.get(f"/api/listings?q={long_q}")
    assert len(res.get_json()["q"]) == 100


@pytest.mark.parametrize(
    "sort_param,expected_order",
    [
        ("newest", "created_at DESC, id DESC"),
        ("price_asc", "price ASC NULLS LAST, id ASC"),
        ("price_desc", "price DESC NULLS LAST, id DESC"),
        ("DROP TABLE listings;--", "created_at DESC, id DESC"),  # Fallback on invalid sort
    ],
)
def test_sort_whitelist(client, mock_db, sort_param, expected_order):
    _, mock_cursor = mock_db
    mock_cursor.fetchall.return_value = []

    res = client.get(f"/api/listings?sort={sort_param}")
    assert res.status_code == 200

    sql, _ = mock_cursor.execute.call_args[0]
    assert f"ORDER BY {expected_order}" in sql


def test_pagination_clamping_and_invalid_ints(client, mock_db):
    _, mock_cursor = mock_db
    mock_cursor.fetchall.return_value = []

    # Out-of-bounds values get clamped (limit max 50, page min 1)
    res = client.get("/api/listings?page=-5&limit=999")
    data = res.get_json()
    assert data["page"] == 1
    assert data["limit"] == 50
    _, params = mock_cursor.execute.call_args[0]
    assert params == [50, 0]

    # Non-integer values fall back to defaults (page=1, limit=20)
    res = client.get("/api/listings?page=abc&limit=xyz")
    data = res.get_json()
    assert data["page"] == 1
    assert data["limit"] == 20

    # Offset calculation: page 3 with limit 10 -> offset 20
    client.get("/api/listings?page=3&limit=10")
    _, params = mock_cursor.execute.call_args[0]
    assert params == [10, 20]


def test_connection_closes_on_db_error(client, mock_db):
    mock_conn, mock_cursor = mock_db
    mock_cursor.execute.side_effect = RuntimeError("DB failure")

    with pytest.raises(RuntimeError):
        client.get("/api/listings")

    mock_conn.close.assert_called_once()
