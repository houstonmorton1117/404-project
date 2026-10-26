# backend/utils/payments.py
# Simulated in-platform payment processing. This does NOT talk to a real
# payment processor (Stripe, etc.) -- it only validates that the submitted
# card fields look well-formed, then returns a fake "approved" result. No
# real money moves. Added so checkout can happen through the platform
# instead of relying on an in-person cash exchange.
#
# Security note: only the card's last 4 digits are ever returned/stored.
# The full card number and CVV exist only for the duration of this
# function call and are never logged, returned, or persisted anywhere.

import re
import uuid
from datetime import datetime


class PaymentError(Exception):
    """Raised when the submitted payment details fail validation."""


def _luhn_checksum(card_number):
    digits = [int(d) for d in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(divmod(d * 2, 10))
    return checksum % 10 == 0


def process_simulated_payment(card_number, card_expiry, cvv, cardholder_name, amount):
    """
    Validates simulated card details and returns a fake payment result.

    Args:
        card_number: digits, spaces/dashes allowed (e.g. "4242 4242 4242 4242")
        card_expiry: "MM/YY"
        cvv: 3-4 digit string
        cardholder_name: non-empty string
        amount: the order total, just for sanity-checking it's positive

    Returns:
        {"status": "PAID", "card_last4": "4242", "transaction_ref": "SIM-..."}

    Raises:
        PaymentError with a user-facing message if anything is invalid.
    """
    if not cardholder_name or not cardholder_name.strip():
        raise PaymentError("Cardholder name is required.")

    digits_only = re.sub(r"[\s-]", "", card_number or "")
    if not digits_only.isdigit() or not (13 <= len(digits_only) <= 19):
        raise PaymentError("Card number must be 13-19 digits.")
    if not _luhn_checksum(digits_only):
        raise PaymentError("Card number is invalid.")

    expiry_match = re.match(r"^(\d{2})/(\d{2})$", (card_expiry or "").strip())
    if not expiry_match:
        raise PaymentError("Expiration date must be in MM/YY format.")
    month, year = int(expiry_match.group(1)), int(expiry_match.group(2))
    if not (1 <= month <= 12):
        raise PaymentError("Expiration month is invalid.")
    expiry_date = datetime(2000 + year, month, 1)
    now = datetime.now()
    if (expiry_date.year, expiry_date.month) < (now.year, now.month):
        raise PaymentError("Card has expired.")

    if not re.match(r"^\d{3,4}$", (cvv or "").strip()):
        raise PaymentError("CVV must be 3-4 digits.")

    if amount is None or amount <= 0:
        raise PaymentError("Payment amount must be greater than zero.")

    return {
        "status": "PAID",
        "card_last4": digits_only[-4:],
        "transaction_ref": f"SIM-{uuid.uuid4().hex[:12].upper()}",
    }
