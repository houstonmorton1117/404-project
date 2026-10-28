
from datetime import datetime, timedelta, timezone

MAX_ATTEMPTS = 3
LOCKOUT_SECONDS = 60


def check_login_lockout(conn, username):
    """Return the remaining lockout time for an account."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT locked_until FROM users WHERE username = %s",
            (username,)
        )
        row = cur.fetchone()

        if not row or row[0] is None:
            return 0

        locked_until = row[0]
        now = datetime.now(timezone.utc)

        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)

        remaining = (locked_until - now).total_seconds()
        return max(0, int(remaining + 0.999))
    finally:
        cur.close()


def record_failed_login(conn, username):
    """Increment failed attempts and lock after the third failure."""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE users
            SET failed_login_attempts =
                CASE
                    WHEN locked_until IS NOT NULL
                         AND locked_until <= NOW()
                    THEN 1
                    ELSE failed_login_attempts + 1
                END,
                locked_until =
                CASE
                    WHEN (
                        CASE
                            WHEN locked_until IS NOT NULL
                                 AND locked_until <= NOW()
                            THEN 1
                            ELSE failed_login_attempts + 1
                        END
                    ) >= %s
                    THEN NOW() + INTERVAL '60 seconds'
                    ELSE NULL
                END
            WHERE username = %s
            RETURNING failed_login_attempts
        """, (MAX_ATTEMPTS, username))

        row = cur.fetchone()
        conn.commit()

        if not row:
            return MAX_ATTEMPTS

        return max(0, MAX_ATTEMPTS - row[0])
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def reset_failed_logins(conn, username):
    """Clear failed attempts after successful authentication."""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE users
            SET failed_login_attempts = 0,
                locked_until = NULL
            WHERE username = %s
        """, (username,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
