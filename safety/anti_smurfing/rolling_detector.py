
"""Rolling anti-smurfing risk indicators for PauseGuard.

Advisory only: this module never blocks, approves, or executes payments.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    amount_paise: int
    timestamp: datetime


@dataclass(frozen=True)
class SmurfingAssessment:
    suspicious: bool
    attempt_count: int
    total_amount_paise: int
    reasons: tuple[str, ...]


class RollingSmurfingDetector:
    def __init__(
        self,
        window_seconds: int = 600,
        minimum_attempts: int = 3,
        amount_threshold_paise: int = 100_000,
    ):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if minimum_attempts < 2:
            raise ValueError("minimum_attempts must be at least 2")
        if amount_threshold_paise <= 0:
            raise ValueError("amount threshold must be positive")

        self.window = timedelta(seconds=window_seconds)
        self.minimum_attempts = minimum_attempts
        self.amount_threshold_paise = amount_threshold_paise

        self._attempts = defaultdict(deque)
        self._seen_ids = defaultdict(set)
        self._lock = RLock()

    def record_attempt(
        self,
        subject_id: str,
        attempt_id: str,
        amount_paise: int,
        timestamp: datetime | None = None,
    ) -> SmurfingAssessment:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("subject_id is required")
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ValueError("attempt_id is required")
        if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
            raise ValueError("amount_paise must be an integer")
        if amount_paise <= 0:
            raise ValueError("amount_paise must be positive")

        timestamp = timestamp or datetime.now(timezone.utc)

        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")

        with self._lock:
            if attempt_id in self._seen_ids[subject_id]:
                return self._assess(subject_id, timestamp)

            attempts = self._attempts[subject_id]
            cutoff = timestamp - self.window

            while attempts and attempts[0].timestamp < cutoff:
                expired = attempts.popleft()
                self._seen_ids[subject_id].discard(expired.attempt_id)

            attempts.append(
                Attempt(attempt_id, amount_paise, timestamp)
            )
            self._seen_ids[subject_id].add(attempt_id)

            return self._assess(subject_id, timestamp)

    def _assess(
        self,
        subject_id: str,
        timestamp: datetime,
    ) -> SmurfingAssessment:
        cutoff = timestamp - self.window

        recent = [
            attempt
            for attempt in self._attempts[subject_id]
            if cutoff <= attempt.timestamp <= timestamp
        ]

        count = len(recent)
        total = sum(item.amount_paise for item in recent)

        reasons = []

        if count >= self.minimum_attempts:
            reasons.append("repeated_attempts_in_rolling_window")

        if total >= self.amount_threshold_paise:
            reasons.append("cumulative_amount_threshold_reached")

        return SmurfingAssessment(
            suspicious=bool(reasons),
            attempt_count=count,
            total_amount_paise=total,
            reasons=tuple(reasons),
        )
