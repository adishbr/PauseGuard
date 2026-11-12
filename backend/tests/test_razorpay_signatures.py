
import hashlib
import hmac

import pytest

from app.integrations.razorpay_signatures import (
    verify_payment_signature,
    verify_webhook_signature,
)


TEST_SECRET = "synthetic-test-secret"


def make_signature(message: bytes, secret: str = TEST_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


class TestPaymentSignature:
    def test_valid_payment_signature_is_accepted(self):
        order_id = "order_test_123"
        payment_id = "pay_test_456"
        message = f"{order_id}|{payment_id}".encode()

        signature = make_signature(message)

        assert verify_payment_signature(
            order_id, payment_id, signature, TEST_SECRET
        )

    def test_tampered_payment_id_is_rejected(self):
        signature = make_signature(b"order_test_123|pay_test_456")

        assert not verify_payment_signature(
            "order_test_123", "pay_tampered", signature, TEST_SECRET
        )

    def test_wrong_secret_is_rejected(self):
        signature = make_signature(b"order_test_123|pay_test_456")

        assert not verify_payment_signature(
            "order_test_123",
            "pay_test_456",
            signature,
            "wrong-secret",
        )

    def test_invalid_signature_format_is_rejected(self):
        assert not verify_payment_signature(
            "order_test_123",
            "pay_test_456",
            "not-a-signature",
            TEST_SECRET,
        )

    @pytest.mark.parametrize(
        "values",
        [
            ("", "pay_test_456", "signature", TEST_SECRET),
            ("order_test_123", "", "signature", TEST_SECRET),
            ("order_test_123", "pay_test_456", "signature", ""),
            (" order_test_123", "pay_test_456", "signature", TEST_SECRET),
        ],
    )
    def test_invalid_payment_inputs_are_rejected(self, values):
        assert not verify_payment_signature(*values)


class TestWebhookSignature:
    def test_valid_webhook_signature_is_accepted(self):
        raw_body = b'{"event":"payment.captured","id":"evt_test_123"}'
        signature = make_signature(raw_body)

        assert verify_webhook_signature(
            raw_body, signature, TEST_SECRET
        )

    def test_tampered_webhook_body_is_rejected(self):
        original_body = b'{"event":"payment.captured"}'
        signature = make_signature(original_body)

        assert not verify_webhook_signature(
            b'{"event":"payment.failed"}',
            signature,
            TEST_SECRET,
        )

    def test_wrong_webhook_secret_is_rejected(self):
        raw_body = b'{"event":"payment.captured"}'
        signature = make_signature(raw_body)

        assert not verify_webhook_signature(
            raw_body, signature, "wrong-secret"
        )

    def test_empty_webhook_body_is_rejected(self):
        assert not verify_webhook_signature(
            b"", "a" * 64, TEST_SECRET
        )

    def test_non_bytes_webhook_body_is_rejected(self):
        assert not verify_webhook_signature(
            '{"event":"payment.captured"}',
            "a" * 64,
            TEST_SECRET,
        )

    def test_malformed_webhook_signature_is_rejected(self):
        assert not verify_webhook_signature(
            b'{"event":"payment.captured"}',
            "invalid",
            TEST_SECRET,
        )

    def test_missing_webhook_secret_is_rejected(self):
        assert not verify_webhook_signature(
            b'{"event":"payment.captured"}',
            "a" * 64,
            "",
        )
