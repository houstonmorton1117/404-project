# Showtime
# In-app notifications: sellers are notified when someone buys from them or a
# followed storefront posts a new listing, and buyers are notified when their
# return status changes. Added by Houston Morton - Iteration 4.

from contextlib import contextmanager

from db import get_connection


@contextmanager
def _connection(conn=None):
    """Yields the caller's connection if one was passed in, so a notification can be
    written as part of a larger transaction. Otherwise opens, commits, and closes its own."""
    if conn is not None:
        yield conn
        return
    own_conn = get_connection()
    try:
        yield own_conn
        own_conn.commit()
    except Exception:
        own_conn.rollback()
        raise
    finally:
        own_conn.close()


def create_notification(user_id, type, message, link=None, conn=None):
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO notifications (user_id, type, message, link)
            VALUES (%s, %s, %s, %s)
            RETURNING id, user_id, type, message, link, is_read, created_at;
        """, (user_id, type, message, link))
        row = cur.fetchone()
    return _row_to_dict(row)


def get_notifications_for_user(user_id, limit=50):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, type, message, link, is_read, created_at
                FROM notifications
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s;
            """, (user_id, limit))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def get_unread_count(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = FALSE;
            """, (user_id,))
            (count,) = cur.fetchone()
    finally:
        conn.close()
    return count


def mark_notification_read(notification_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, type, message, link, is_read, created_at;
            """, (notification_id, user_id))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def mark_all_read(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE;
            """, (user_id,))
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "type": row[2],
        "message": row[3],
        "link": row[4],
        "is_read": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
    }
