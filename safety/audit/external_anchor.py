"""External audit-anchor preparation and verification.

This module prepares and verifies anchor receipts locally.
It does not contact or authenticate with an external provider.

A matching receipt proves only that its contents match the expected
chain checkpoint. Provider authenticity requires a separately trusted
signature or authenticated provider response.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import re


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuditAnchor:
    """Checkpoint that can be submitted to an external anchor provider."""

    sequence: int
    head_hash: str
    created_at: str


@dataclass(frozen=True)
class AnchorVerification:
    """Result of checking an anchor against a local audit checkpoint."""

    valid: bool
    reason: str


def create_anchor(chain) -> AuditAnchor:
    """Prepare an anchor from a verified, non-empty audit chain."""
    if chain is None or not callable(getattr(chain, "verify", None)):
        raise ValueError("A valid audit chain is required")

    if not chain.verify():
        raise ValueError("Cannot anchor an invalid audit chain")

    records = getattr(chain, "records", None)
    if not isinstance(records, list) or not records:
        raise ValueError("Cannot anchor an empty audit chain")

    head = records[-1]
    sequence = getattr(head, "sequence", None)
    head_hash = getattr(head, "record_hash", None)

    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("Invalid audit sequence")

    if not isinstance(head_hash, str) or not _SHA256_PATTERN.fullmatch(head_hash):
        raise ValueError("Invalid audit head hash")

    return AuditAnchor(
        sequence=sequence,
        head_hash=head_hash,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def verify_anchor(anchor: AuditAnchor, chain) -> AnchorVerification:
    """Compare a checkpoint with the current local chain.

    This checks consistency only. It does not authenticate who issued
    or stored the anchor.
    """
    if not isinstance(anchor, AuditAnchor):
        return AnchorVerification(False, "invalid_anchor_type")

    if chain is None or not callable(getattr(chain, "verify", None)):
        return AnchorVerification(False, "invalid_chain")

    if not chain.verify():
        return AnchorVerification(False, "invalid_local_chain")

    records = getattr(chain, "records", None)
    if not isinstance(records, list) or not records:
        return AnchorVerification(False, "empty_local_chain")

    if isinstance(anchor.sequence, bool) or not isinstance(anchor.sequence, int):
        return AnchorVerification(False, "invalid_anchor_sequence")

    if anchor.sequence <= 0 or anchor.sequence > len(records):
        return AnchorVerification(False, "anchor_sequence_not_found")

    if (
        not isinstance(anchor.head_hash, str)
        or not _SHA256_PATTERN.fullmatch(anchor.head_hash)
    ):
        return AnchorVerification(False, "invalid_anchor_hash")

    try:
        timestamp = datetime.fromisoformat(anchor.created_at)
    except (TypeError, ValueError):
        return AnchorVerification(False, "invalid_anchor_timestamp")

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return AnchorVerification(False, "naive_anchor_timestamp")

    anchored_record = records[anchor.sequence - 1]

    if anchored_record.record_hash != anchor.head_hash:
        return AnchorVerification(False, "anchor_hash_mismatch")

    return AnchorVerification(True, "checkpoint_matches")