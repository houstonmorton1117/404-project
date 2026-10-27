# The Vault Campus Marketplace
# CSC 405 Sp 26'
# Updated by Jasmine Mark 10/25/26 - New OutOfStockError class and updated checkout flow to handle stock checks and inventory updates.

from contextlib import contextmanager

from db import get_connection


@contextmanager
def _connection(conn=None):
    """Yields the caller's connection if one was passed in; the caller then commits or rolls back,
    so several functions can share one all-or-nothing transaction (checkout does this).
    Otherwise opens a new connection, commits if the work succeeds, and always closes it."""
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


def create_order(user_id, confirmation_number, buyer_first_name, buyer_last_name,
                 buyer_email, buyer_contact, buyer_meeting_location, total_amount,
                 card_last4=None, transaction_ref=None, payment_status='PAID', payment_method='CARD',
                 conn=None):
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders (user_id, confirmation_number, buyer_first_name, buyer_last_name,
                                buyer_email, buyer_contact, buyer_meeting_location, total_amount, order_status,
                                payment_method, card_last4, payment_status, transaction_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'SUBMITTED', %s, %s, %s, %s)
            RETURNING id, user_id, confirmation_number, buyer_first_name, buyer_last_name,
                      buyer_email, buyer_contact, buyer_meeting_location, total_amount, order_status, created_at,
                      payment_method, card_last4, payment_status, transaction_ref;
        """, (user_id, confirmation_number, buyer_first_name, buyer_last_name,
              buyer_email, buyer_contact, buyer_meeting_location, total_amount,
              payment_method, card_last4, payment_status, transaction_ref))
        row = cur.fetchone()
    return {
        "id": row[0],
        "user_id": row[1],
        "confirmation_number": row[2],
        "buyer_first_name": row[3],
        "buyer_last_name": row[4],
        "buyer_email": row[5],
        "buyer_contact": row[6],
        "buyer_meeting_location": row[7],
        "total_amount": float(row[8]),
        "order_status": row[9],
        "created_at": str(row[10]),
        "payment_method": row[11],
        "card_last4": row[12],
        "payment_status": row[13],
        "transaction_ref": row[14],
    }


def create_order_item(order_id, listing_id, item_name, quantity, price_at_purchase, selected_size=None,
                      conn=None):
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO order_items (order_id, listing_id, item_name, quantity, price_at_purchase, selected_size)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, order_id, listing_id, item_name, quantity, price_at_purchase, selected_size;
        """, (order_id, listing_id, item_name, quantity, price_at_purchase, selected_size))
        row = cur.fetchone()
    return {
        "id": row[0],
        "order_id": row[1],
        "listing_id": row[2],
        "item_name": row[3],
        "quantity": row[4],
        "price_at_purchase": float(row[5]),
        "selected_size": row[6],
    }


def get_order_by_confirmation(confirmation_number):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, confirmation_number, buyer_first_name, buyer_last_name,
               buyer_email, buyer_contact, buyer_meeting_location, total_amount, order_status, created_at,
               payment_method, card_last4, payment_status, transaction_ref
        FROM orders
        WHERE confirmation_number = %s;
    """, (confirmation_number,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "confirmation_number": row[2],
        "buyer_first_name": row[3],
        "buyer_last_name": row[4],
        "buyer_email": row[5],
        "buyer_contact": row[6],
        "buyer_meeting_location": row[7],
        "total_amount": float(row[8]),
        "order_status": row[9],
        "created_at": str(row[10]),
        "payment_method": row[11],
        "card_last4": row[12],
        "payment_status": row[13],
        "transaction_ref": row[14],
    }


def get_order_items_by_order_id(order_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, order_id, listing_id, item_name, quantity, price_at_purchase, selected_size
        FROM order_items
        WHERE order_id = %s
        ORDER BY id ASC;
    """, (order_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "order_id": r[1],
            "listing_id": r[2],
            "item_name": r[3],
            "quantity": r[4],
            "price_at_purchase": float(r[5]),
            "selected_size": r[6],
        }
        for r in rows
    ]


def get_orders_by_user_id(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, confirmation_number, buyer_first_name, buyer_last_name,
               buyer_email, total_amount, order_status, created_at
        FROM orders
        WHERE user_id = %s
        ORDER BY created_at DESC;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "confirmation_number": r[2],
            "buyer_first_name": r[3],
            "buyer_last_name": r[4],
            "buyer_email": r[5],
            "total_amount": float(r[6]),
            "order_status": r[7],
            "created_at": str(r[8]),
        }
        for r in rows
    ]


def remove_purchased_from_wishlist(user_id, listing_ids):
    """
    Removes wishlist entries for listings the user just purchased.
    Uses listing_id matching only — the wishlist has a UNIQUE(user_id, listing_id)
    constraint so there is at most one entry per listing per user.
    """
    if not listing_ids:
        return {"deleted_count": 0}
    # Filter out None values
    valid_ids = [int(lid) for lid in listing_ids if lid is not None]
    if not valid_ids:
        return {"deleted_count": 0}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM wishlist WHERE user_id = %s AND listing_id = ANY(%s);",
        (user_id, valid_ids)
    )
    deleted_count = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"deleted_count": deleted_count}


def clear_cart_for_user(user_id, conn=None):
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM cart_items WHERE user_id = %s;", (user_id,))
        deleted_count = cur.rowcount
    return {"deleted_count": deleted_count}


class OutOfStockError(Exception):
    """Raised when a listing can't be added to a cart or purchased in the requested quantity."""


def check_listing_availability(listing_id, quantity_requested, size=None, conn=None):
    """Raises OutOfStockError if the listing (or the chosen size) is sold out or has insufficient
    stock (skipped for made-to-order items). Returns (title, price, is_made_to_order) from the database.

    When checkout passes in its transaction's conn, the listing row is locked (FOR UPDATE) until that
    transaction ends, so a second buyer checking out the same listing waits and then sees the updated stock."""
    lock = " FOR UPDATE" if conn is not None else ""
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT title, price, status, quantity_on_hand, is_made_to_order FROM listings WHERE id = %s" + lock,
            (listing_id,)
        )
        row = cur.fetchone()
        if not row:
            raise OutOfStockError(f"Item (ID {listing_id}) is no longer available.")
        title, price, status, qty_on_hand, is_made_to_order = row
        if status not in ("ACTIVE", "SOLD_OUT"):
            raise OutOfStockError(f'"{title}" is no longer available.')
        if not is_made_to_order:
            if status == "SOLD_OUT" or (qty_on_hand is not None and int(qty_on_hand) <= 0):
                raise OutOfStockError(f'"{title}" is sold out.')
            if qty_on_hand is not None and int(qty_on_hand) < quantity_requested:
                raise OutOfStockError(
                    f'"{title}" only has {qty_on_hand} in stock (you requested {quantity_requested}).'
                )

            # Stock is tracked per size, so a listing with stock left can still have a sold-out size.
            cur.execute("SELECT size, quantity FROM listing_sizes WHERE listing_id = %s", (listing_id,))
            size_stock = {s: int(q or 0) for s, q in cur.fetchall()}
            if size_stock:
                if not size:
                    raise OutOfStockError(f'Please choose a size for "{title}".')
                available = size_stock.get(size, 0)
                if available <= 0:
                    raise OutOfStockError(f'"{title}" in size {size} is sold out.')
                if available < quantity_requested:
                    raise OutOfStockError(
                        f'"{title}" in size {size} only has {available} in stock '
                        f'(you requested {quantity_requested}).'
                    )
    return title, float(price), bool(is_made_to_order)


def update_listing_size_inventory(listing_id, size, purchased_qty, conn=None):
    """Decrements per-size inventory and syncs listing quantity_on_hand after purchase.

    The decrement is done as a single atomic UPDATE guarded by
    `quantity >= purchased_qty` in the WHERE clause, instead of a separate
    SELECT-then-UPDATE. Two checkouts for the last item racing each other
    could otherwise both pass a SELECT-based check before either commits,
    letting both orders succeed against stock that only covers one of them.
    The UPDATE's rowcount tells us whether this specific request actually
    had enough stock at the moment it ran.
    """
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE listing_sizes
            SET quantity = quantity - %s
            WHERE listing_id = %s AND size = %s AND quantity >= %s;
        """, (purchased_qty, listing_id, size, purchased_qty))
        if cur.rowcount == 0:
            cur.execute(
                "SELECT quantity FROM listing_sizes WHERE listing_id = %s AND size = %s",
                (listing_id, size)
            )
            size_row = cur.fetchone()
            available = int(size_row[0]) if size_row else 0
            raise OutOfStockError(
                f"Insufficient stock for listing {listing_id} size '{size}': "
                f"requested {purchased_qty}, available {available}."
            )
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0) FROM listing_sizes WHERE listing_id = %s;
        """, (listing_id,))
        total_qty = int(cur.fetchone()[0])
        new_status = "SOLD_OUT" if total_qty == 0 else None
        cur.execute("""
            UPDATE listings
            SET quantity_on_hand = %s,
                status = COALESCE(%s, CASE WHEN status = 'SOLD_OUT' AND %s > 0 THEN 'ACTIVE' ELSE status END),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND (is_made_to_order = FALSE OR is_made_to_order IS NULL);
        """, (total_qty, new_status, total_qty, listing_id))


def update_listing_quantity_inventory(listing_id, purchased_qty, conn=None):
    """Decrements quantity_on_hand for a listing that has no per-size inventory.

    Same guarded, single-statement UPDATE pattern as update_listing_size_inventory,
    for the WHERE clause to guard against a race: the UPDATE only applies if enough
    stock is still available at the moment it runs, so two checkouts racing for the
    last units can't both succeed.
    """
    with _connection(conn) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE listings
            SET quantity_on_hand = quantity_on_hand - %s,
                status = CASE WHEN quantity_on_hand - %s <= 0 THEN 'SOLD_OUT' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND quantity_on_hand >= %s;
        """, (purchased_qty, purchased_qty, listing_id, purchased_qty))
        if cur.rowcount == 0:
            cur.execute("SELECT quantity_on_hand FROM listings WHERE id = %s", (listing_id,))
            row = cur.fetchone()
            available = int(row[0]) if row and row[0] is not None else 0
            raise OutOfStockError(
                f"Insufficient stock for listing {listing_id}: "
                f"requested {purchased_qty}, available {available}."
            )
