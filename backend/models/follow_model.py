# Showtime
# follow_model.py - Added by Houston Morton - Iteration 4
# Lets a user follow a storefront and get notified about its new listings.

from db import get_connection


def follow_storefront(user_id, storefront_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO storefront_follows (user_id, storefront_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, storefront_id) DO NOTHING
                RETURNING id, user_id, storefront_id, created_at;
            """, (user_id, storefront_id))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return row is not None


def unfollow_storefront(user_id, storefront_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM storefront_follows WHERE user_id = %s AND storefront_id = %s;
            """, (user_id, storefront_id))
            deleted = cur.rowcount > 0
        conn.commit()
    finally:
        conn.close()
    return deleted


def is_following(user_id, storefront_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM storefront_follows WHERE user_id = %s AND storefront_id = %s;
            """, (user_id, storefront_id))
            found = cur.fetchone() is not None
    finally:
        conn.close()
    return found


def get_followed_storefronts(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id, s.brand_name, s.logo_url, s.bio, f.created_at
                FROM storefront_follows f
                JOIN storefronts s ON s.id = f.storefront_id
                WHERE f.user_id = %s
                ORDER BY f.created_at DESC;
            """, (user_id,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row[0],
            "brand_name": row[1],
            "logo_url": row[2],
            "bio": row[3],
            "followed_at": row[4].isoformat() if row[4] else None,
        }
        for row in rows
    ]


def get_follower_user_ids(storefront_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id FROM storefront_follows WHERE storefront_id = %s;
            """, (storefront_id,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]
