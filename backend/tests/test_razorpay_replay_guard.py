
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.integrations.razorpay_replay_guard import WebhookReplayGuard


def test_first_event_is_accepted():
    guard = WebhookReplayGuard()

    assert guard.record_if_new("evt_001") is True


def test_duplicate_event_is_rejected():
    guard = WebhookReplayGuard()

    assert guard.record_if_new("evt_001") is True
    assert guard.record_if_new("evt_001") is False


def test_different_events_are_accepted():
    guard = WebhookReplayGuard()

    assert guard.record_if_new("evt_001") is True
    assert guard.record_if_new("evt_002") is True


@pytest.mark.parametrize("event_id", ["", " ", " evt_001", "evt_001 "])
def test_invalid_event_ids_are_rejected(event_id):
    guard = WebhookReplayGuard()

    assert guard.record_if_new(event_id) is False


@pytest.mark.parametrize("event_id", [None, 123, True, [], {}])
def test_non_string_event_ids_are_rejected(event_id):
    guard = WebhookReplayGuard()

    assert guard.record_if_new(event_id) is False


def test_event_capacity_is_bounded():
    guard = WebhookReplayGuard(max_events=2)

    assert guard.record_if_new("evt_001")
    assert guard.record_if_new("evt_002")
    assert guard.record_if_new("evt_003")

    assert guard.contains("evt_001") is False
    assert guard.contains("evt_002") is True
    assert guard.contains("evt_003") is True


def test_expired_from_capacity_event_can_be_recorded_again():
    guard = WebhookReplayGuard(max_events=1)

    assert guard.record_if_new("evt_001")
    assert guard.record_if_new("evt_002")

    # The oldest event was evicted due to capacity.
    assert guard.record_if_new("evt_001")


def test_invalid_capacity_is_rejected():
    for value in (0, -1, True, 1.5, "10"):
        with pytest.raises(ValueError):
            WebhookReplayGuard(max_events=value)


def test_concurrent_duplicate_events_are_accepted_only_once():
    guard = WebhookReplayGuard()

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(
            executor.map(
                guard.record_if_new,
                ["evt_concurrent"] * 50,
            )
        )

    assert results.count(True) == 1
    assert results.count(False) == 49
