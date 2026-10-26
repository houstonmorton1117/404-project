import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if path not in sys.path:
        sys.path.append(path)

from backend.utils.payments import process_simulated_payment, PaymentError

VALID = dict(
    card_number="4242424242424242",
    card_expiry="12/30",
    cvv="123",
    cardholder_name="Test Buyer",
    amount=50.00,
)


class TestSimulatedPayments(unittest.TestCase):
    def test_valid_card_is_approved(self):
        result = process_simulated_payment(**VALID)
        self.assertEqual(result["status"], "PAID")
        self.assertEqual(result["card_last4"], "4242")
        self.assertTrue(result["transaction_ref"].startswith("SIM-"))

    def test_full_card_number_and_cvv_are_never_returned(self):
        result = process_simulated_payment(**VALID)
        serialized = str(result)
        self.assertNotIn(VALID["card_number"], serialized)
        self.assertNotIn(VALID["cvv"], serialized)

    def test_rejects_invalid_card_number(self):
        bad = {**VALID, "card_number": "1234567890123456"}  # fails Luhn check
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_wrong_length_card_number(self):
        bad = {**VALID, "card_number": "4242"}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_expired_card(self):
        bad = {**VALID, "card_expiry": "01/20"}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_malformed_expiry(self):
        bad = {**VALID, "card_expiry": "2030-12"}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_short_cvv(self):
        bad = {**VALID, "cvv": "12"}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_missing_cardholder_name(self):
        bad = {**VALID, "cardholder_name": ""}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_rejects_zero_amount(self):
        bad = {**VALID, "amount": 0}
        with self.assertRaises(PaymentError):
            process_simulated_payment(**bad)

    def test_accepts_card_number_with_spaces(self):
        formatted = {**VALID, "card_number": "4242 4242 4242 4242"}
        result = process_simulated_payment(**formatted)
        self.assertEqual(result["card_last4"], "4242")


if __name__ == "__main__":
    unittest.main()
