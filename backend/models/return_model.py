"""
return_model.py

Handles database operations for marketplace return requests.
"""

from db import get_connection


def create_return_record(user_id, order_number, reason, has_damage, damage_image_url=None, status="pending"):
    conn = get_connection()
    cur = conn.cursor()

    query = """
        INSERT INTO returns (
            user_id, order_number, reason, has_damage, damage_image_url, status
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, user_id, order_number, reason, has_damage, damage_image_url,
                  status, created_at, updated_at, is_deleted;
    """

    cur.execute(query, (user_id, order_number, reason, has_damage, damage_image_url, status))
    row = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    return {
        "id": row[0],
        "user_id": row[1],
        "order_number": row[2],
        "reason": row[3],
        "has_damage": row[4],
        "damage_image_url": row[5],
        "status": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "is_deleted": row[9],
    }


def get_all_returns(include_deleted=False):
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT r.id, r.user_id, u.username, u.email, r.order_number, r.reason,
               r.has_damage, r.damage_image_url, r.status, r.created_at, r.updated_at, r.is_deleted
        FROM returns r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE (%s = TRUE OR r.is_deleted = FALSE)
        ORDER BY r.created_at DESC;
    """

    cur.execute(query, (include_deleted,))
    rows = cur.fetchall()

    cur.close()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "email": row[3],
            "order_number": row[4],
            "reason": row[5],
            "has_damage": row[6],
            "damage_image_url": row[7],
            "status": row[8],
            "created_at": row[9],
            "updated_at": row[10],
            "is_deleted": row[11],
        })

    return results


_RETURN_COLUMNS = """id, user_id, order_number, reason, has_damage, damage_image_url,
                  status, created_at, updated_at, is_deleted"""


def _return_row(row):
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "order_number": row[2],
        "reason": row[3],
        "has_damage": row[4],
        "damage_image_url": row[5],
        "status": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "is_deleted": row[9],
    }


def get_return_by_id(return_id, conn, for_update=False):
    """Reads one return on the caller's connection. With for_update=True the row stays locked
    until the caller commits, so two admins can't approve (and refund) the same return at once.
    Added 11/14/26."""
    lock = " FOR UPDATE" if for_update else ""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT {_RETURN_COLUMNS} FROM returns WHERE id = %s AND is_deleted = FALSE{lock};",
                    (return_id,))
        return _return_row(cur.fetchone())
    finally:
        cur.close()


def update_return_status(return_id, status, conn=None):
    """Sets a return's status. Pass `conn` to make it part of the caller's transaction (the caller
    then commits); without it, the change is committed right away. `conn` added 11/14/26."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.cursor()

    query = f"""
        UPDATE returns
        SET status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING {_RETURN_COLUMNS};
    """

    try:
        cur.execute(query, (status, return_id))
        row = cur.fetchone()
        if own_conn:
            conn.commit()
    finally:
        cur.close()
        if own_conn:
            conn.close()

    return _return_row(row)
