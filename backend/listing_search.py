# backend/listing_search.py
# GET /api/listings?q=hoodie&sort=price_asc&page=1&limit=20
from flask import Blueprint, jsonify, request
from psycopg2.extras import RealDictCursor


from backend.db import get_db_connection  

listing_search = Blueprint("listing_search", __name__)

# Whitelist: user input only selects a key, it never goes into SQL directly.
# id is the tie-breaker so paging stays stable when prices/dates match.
SORTS = {
    "newest": "created_at DESC, id DESC",
    "price_asc": "price ASC NULLS LAST, id ASC",
    "price_desc": "price DESC NULLS LAST, id DESC",
}


def _int_arg(name, default, low, high):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


@listing_search.get("/api/listings")
def search_listings():
    q = (request.args.get("q") or "").strip()[:100]
    sort_key = request.args.get("sort", "newest")
    if sort_key not in SORTS:
        sort_key = "newest"

    limit = _int_arg("limit", 20, 1, 50)
    page = _int_arg("page", 1, 1, 100000)
    offset = (page - 1) * limit

    params = []
    where = ""
    if q:
        
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = "WHERE name ILIKE %s"
        params.append(f"%{escaped}%")

    params += [limit, offset]

    # Safe to use an f-string here: `where` and the ORDER BY come from
    # fixed strings above, and all user values are passed as parameters.
    sql = f"""
        SELECT id, name, price, created_at, COUNT(*) OVER() AS total
        FROM listings
        {where}
        ORDER BY {SORTS[sort_key]}
        LIMIT %s OFFSET %s
    """

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    total = rows[0]["total"] if rows else 0
    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "price": float(r["price"]) if r["price"] is not None else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return jsonify(items=items, total=total, page=page, limit=limit, sort=sort_key, q=q)


# In app.py:
#   from backend.listing_search import listing_search
#   app.register_blueprint(listing_search)
