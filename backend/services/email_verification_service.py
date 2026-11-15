# Added by Joshua Hall on 11/13/2026
# Generates secure email verification codes for Showtime

import secrets
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

def generate_verification_code():
    """Generate a random 6-digit email verification code."""
    return f"{secrets.randbelow(900000) + 100000:06d}"

# Added by Joshua Hall on 11/13/2026 - Send verification emails
def send_verification_email(recipient_email, code):
    """Send a six-digit verification code through Gmail SMTP."""

    message = EmailMessage()
    message["Subject"] = "Showtime - Verify Your Email"
    message["From"] = os.getenv("MAIL_USERNAME")
    message["To"] = recipient_email

    message.set_content(
        f"Welcome to Showtime!\n\n"
        f"Your email verification code is: {code}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not create a Showtime account, ignore this email."
    )

    with smtplib.SMTP(
        os.getenv("MAIL_SERVER"),
        int(os.getenv("MAIL_PORT", "587")),
        timeout=15
    ) as server:
        server.starttls()
        server.login(
            os.getenv("MAIL_USERNAME"),
            os.getenv("MAIL_APP_PASSWORD")
        )
        server.send_message(message)

    return True

# Updated by Joshua Hall on 11/14/2026 - Support resend cooldown 
def store_verification_code(db_conn, email, code, is_resend=False):
    """Store a hashed verification code that expires after 10 minutes."""
    from werkzeug.security import generate_password_hash

    code_hash = generate_password_hash(code)

    cur = db_conn.cursor()

    try:
        # Added by Joshua Hall on 11/14/2026 - Reset verification attempts
        cur.execute("""
            UPDATE users
            SET verification_code_hash = %s,
                verification_expires_at = CURRENT_TIMESTAMP + INTERVAL '10 minutes',
                verification_attempts = 0,
                verification_sent_at = CURRENT_TIMESTAMP
            WHERE email = %s
              AND email_verified = FALSE
              AND (
                NOT %s
                OR verification_sent_at IS NULL
                OR verification_sent_at <= CURRENT_TIMESTAMP - INTERVAL '60 seconds')
        """, (code_hash, email, is_resend))

        if cur.rowcount != 1:
            db_conn.rollback()
            return False

        db_conn.commit()
        return True

    except Exception:
        db_conn.rollback()
        raise

    finally:
        cur.close()

# Added by Joshua Hall on 11/14/2026 - Verify email confirmation codes
def verify_email_code(db_conn, email, code):
    """Verify an email code and activate the user's account."""
    from werkzeug.security import check_password_hash

    cur = db_conn.cursor()

    try:
        # Updated by Joshua Hall on 11/14/2026 - Track verification attempts
        cur.execute("""
            SELECT verification_code_hash,
                verification_expires_at,
                verification_attempts
            FROM users
            WHERE email = %s
            AND email_verified = FALSE
            FOR UPDATE
        """, (email,))

        row = cur.fetchone()

        if row is None:
            db_conn.rollback()
            return False

        code_hash, expires_at, attempts = row

        # Added by Joshua Hall on 11/14/2026 - Block excessive verification attempts
        if attempts >= 5:
            db_conn.rollback()
            return False      

        cur.execute("SELECT CURRENT_TIMESTAMP")
        current_time = cur.fetchone()[0]

        # Updated by Joshua Hall on 11/14/2026 - Record failed verification attempts
        if (not code_hash or not expires_at
                or current_time > expires_at
                or not check_password_hash(code_hash, code)):

            attempts += 1

            cur.execute("""
                UPDATE users
                SET verification_attempts = %s,
                    verification_code_hash = CASE
                        WHEN %s >= 5 THEN NULL
                        ELSE verification_code_hash
                    END
                WHERE email = %s
            """, (attempts, attempts, email))

            db_conn.commit()
            return False

        cur.execute("""
            UPDATE users
            SET email_verified = TRUE,
                verification_code_hash = NULL,
                verification_expires_at = NULL,
                verification_attempts = 0
            WHERE email = %s
        """, (email,))

        db_conn.commit()
        return True

    except Exception:
        db_conn.rollback()
        raise

    finally:
        cur.close()

# Added by Joshua Hall on 11/14/2026 - Check verification email resend cooldown
def can_resend_verification_code(db_conn, email):
    """Allow a new verification code after a 60-second cooldown."""
    cur = db_conn.cursor()

    try:
        cur.execute("""
            SELECT verification_sent_at
            FROM users
            WHERE email = %s
              AND email_verified = FALSE
        """, (email,))

        row = cur.fetchone()

        if row is None:
            return False

        sent_at = row[0]

        if sent_at is None:
            return True

        cur.execute("SELECT CURRENT_TIMESTAMP")
        current_time = cur.fetchone()[0]

        return (current_time - sent_at).total_seconds() >= 60

    finally:
        cur.close()


