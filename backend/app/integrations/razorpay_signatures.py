
"""Standalone Razorpay Test Mode signature verification utilities.

This module verifies signatures only. It does not create orders,
process payments, change payment states, or make network requests.
"""

import hashlib
import hmac


def _is_valid_hex_signature(signature: object) -> bool:
    """Check that a signature is exactly 64 hexadecimal characters."""
    if not isinstance(signature, str) or len(signature) != 64:
        return False

    try:
        bytes.fromhex(signature)
    except ValueError:
        return False

    return True


def verify_payment_signature(
    order_id: str,
    payment_id: str,
    signature: str,
    key_secret: str,
) -> bool:
    """Verify a Razorpay payment signature.

    Expected message: order_id|payment_id
    Algorithm: HMAC-SHA256 using the Test Mode key secret.
    """
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in (order_id, payment_id, key_secret)
    ):
        return False

    if not _is_valid_hex_signature(signature):
        return False

    message = f"{order_id}|{payment_id}".encode("utf-8")

    expected = hmac.new(
        key_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature.lower())


def verify_webhook_signature(
    raw_body: bytes,
    signature: str,
    webhook_secret: str,
) -> bool:
    """Verify a Razorpay webhook signature against its original raw body."""
    if not isinstance(raw_body, bytes) or not raw_body:
        return False

    if not isinstance(webhook_secret, str) or not webhook_secret:
        return False

    if webhook_secret != webhook_secret.strip():
        return False

    if not _is_valid_hex_signature(signature):
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature.lower())
