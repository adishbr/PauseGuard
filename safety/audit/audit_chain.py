
"""SHA-256 audit chain for PauseGuard.

Detects changes to records in a local audit chain.
A hash chain alone is not tamper-proof or a trusted external anchor.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json


GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    timestamp: str
    event_type: str
    data: dict
    previous_hash: str
    record_hash: str


class AuditChain:

    def __init__(self):
        self.records: list[AuditRecord] = []

    @staticmethod
    def _calculate_hash(
        sequence: int,
        timestamp: str,
        event_type: str,
        data: dict,
        previous_hash: str,
    ) -> str:
        payload = {
            "sequence": sequence,
            "timestamp": timestamp,
            "event_type": event_type,
            "data": data,
            "previous_hash": previous_hash,
        }

        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def append(self, event_type: str, data: dict) -> AuditRecord:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type is required")

        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")

        # Ensure data can be serialized consistently.
        try:
            json.dumps(data, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("data must contain valid JSON values") from exc

        sequence = len(self.records) + 1
        timestamp = datetime.now(timezone.utc).isoformat()

        previous_hash = (
            self.records[-1].record_hash
            if self.records
            else GENESIS_HASH
        )

        record_hash = self._calculate_hash(
            sequence,
            timestamp,
            event_type,
            data,
            previous_hash,
        )

        record = AuditRecord(
            sequence=sequence,
            timestamp=timestamp,
            event_type=event_type,
            data=data,
            previous_hash=previous_hash,
            record_hash=record_hash,
        )

        self.records.append(record)
        return record

    def verify(self) -> bool:
        previous_hash = GENESIS_HASH

        for expected_sequence, record in enumerate(self.records, start=1):
            if record.sequence != expected_sequence:
                return False

            if record.previous_hash != previous_hash:
                return False

            calculated_hash = self._calculate_hash(
                record.sequence,
                record.timestamp,
                record.event_type,
                record.data,
                record.previous_hash,
            )

            if record.record_hash != calculated_hash:
                return False

            previous_hash = record.record_hash

        return True
