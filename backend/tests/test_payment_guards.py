from datetime import datetime, timedelta, timezone
from itertools import product
from uuid import UUID

import pytest

from app.models.user import UserRole
from app.services.payment_guards import (
    PaymentGuardError, PaymentStatus as S, TRANSITION_TOPOLOGY, TrustedActorContext,
    guardian_approval_target, guardian_timeout_target, is_topologically_allowed,
    require_payer_confirmation_preconditions,
)


PAYER = UUID(int=1)
GUARDIAN = UUID(int=2)
DEADLINE = datetime(2026, 11, 10, tzinfo=timezone.utc)


def actor(user_id=GUARDIAN, roles=frozenset({UserRole.GUARDIAN})):
    return TrustedActorContext(user_id, roles)


# Independent representation of every edge in the frozen V2 table.
EXPECTED = {
    "CREATED": "AWAITING_WARNING AWAITING_STEP_UP AWAITING_GUARDIAN AWAITING_FALLBACK_REVIEW READY_TO_EXECUTE REJECTED",
    "AWAITING_WARNING": "READY_TO_EXECUTE CANCELLED",
    "AWAITING_STEP_UP": "READY_TO_EXECUTE CANCELLED EXPIRED REJECTED",
    "AWAITING_GUARDIAN": "READY_TO_EXECUTE REJECTED CANCELLED AWAITING_FALLBACK_REVIEW",
    "AWAITING_FALLBACK_REVIEW": "READY_TO_EXECUTE REJECTED CANCELLED EXPIRED",
    "READY_TO_EXECUTE": "EXECUTED CANCELLED REJECTED EXPIRED FAILED",
}


@pytest.mark.parametrize("source,target", list(product(S, S)))
def test_every_canonical_edge_and_nonedge(source, target):
    assert is_topologically_allowed(source, target) == (target.value in EXPECTED.get(source.value, "").split())


def test_topology_is_immutable_and_never_accepts_unparsed_client_strings():
    with pytest.raises(TypeError):
        TRANSITION_TOPOLOGY[S.CREATED] = frozenset()
    assert not is_topologically_allowed("CREATED", S.READY_TO_EXECUTE)
    assert not is_topologically_allowed(S.CREATED, "READY_TO_EXECUTE")


def guardian(**overrides):
    values = dict(status=S.AWAITING_GUARDIAN, actor=actor(), assigned_guardian_id=GUARDIAN,
                  guardian_deadline=DEADLINE, server_now=DEADLINE - timedelta(microseconds=1),
                  hard_policy_allows=True)
    return guardian_approval_target(**(values | overrides))


def confirm(**overrides):
    values = dict(status=S.READY_TO_EXECUTE, actor=actor(PAYER, frozenset({UserRole.PAYER})),
                  payer_id=PAYER, safe_lock_is_locked=False, hard_policy_allows=True)
    return require_payer_confirmation_preconditions(**(values | overrides))


def test_guardian_approval_only_returns_ready_and_needs_separate_payer():
    assert guardian() is S.READY_TO_EXECUTE
    with pytest.raises(PaymentGuardError):
        confirm(actor=actor())
    assert confirm() is None


@pytest.mark.parametrize("offset", [0, 1, 30_000_000])
def test_guardian_exact_deadline_and_late_approval_fail_without_timeout_job(offset):
    with pytest.raises(PaymentGuardError):
        guardian(server_now=DEADLINE + timedelta(microseconds=offset))
    assert guardian_timeout_target(status=S.AWAITING_GUARDIAN, guardian_deadline=DEADLINE,
                                   server_now=DEADLINE + timedelta(microseconds=offset)) is S.AWAITING_FALLBACK_REVIEW


def test_timeout_before_deadline_cannot_activate_fallback():
    with pytest.raises(PaymentGuardError):
        guardian_timeout_target(status=S.AWAITING_GUARDIAN, guardian_deadline=DEADLINE,
                                server_now=DEADLINE - timedelta(microseconds=1))


@pytest.mark.parametrize("status", [state for state in S if state is not S.AWAITING_GUARDIAN] + ["AWAITING_GUARDIAN"])
def test_timeout_only_applies_to_current_guardian_review(status):
    with pytest.raises(PaymentGuardError):
        guardian_timeout_target(status=status, guardian_deadline=DEADLINE, server_now=DEADLINE)


@pytest.mark.parametrize("field", ["guardian_deadline", "server_now"])
@pytest.mark.parametrize("value", [None, DEADLINE.replace(tzinfo=None)])
def test_timeout_missing_or_naive_timestamps_fail_closed(field, value):
    values = dict(status=S.AWAITING_GUARDIAN, guardian_deadline=DEADLINE, server_now=DEADLINE)
    with pytest.raises(PaymentGuardError):
        guardian_timeout_target(**(values | {field: value}))


def test_equivalent_timezone_instants_use_absolute_time():
    assert guardian(server_now=(DEADLINE - timedelta(microseconds=1)).astimezone(
        timezone(timedelta(hours=5, minutes=30)))) is S.READY_TO_EXECUTE


@pytest.mark.parametrize("status", [state for state in S if state is not S.AWAITING_GUARDIAN] + ["AWAITING_GUARDIAN"])
def test_guardian_requires_current_review_state(status):
    with pytest.raises(PaymentGuardError):
        guardian(status=status)


@pytest.mark.parametrize("status", [state for state in S if state is not S.READY_TO_EXECUTE] + ["READY_TO_EXECUTE"])
def test_confirmation_requires_current_ready_state(status):
    with pytest.raises(PaymentGuardError):
        confirm(status=status)


@pytest.mark.parametrize("field", ["guardian_deadline", "server_now"])
@pytest.mark.parametrize("value", [None, "2026-11-10", DEADLINE.replace(tzinfo=None)])
def test_missing_or_naive_server_timestamps_fail_closed(field, value):
    with pytest.raises(PaymentGuardError):
        guardian(**{field: value})


@pytest.mark.parametrize("binding", [None, PAYER, str(GUARDIAN)])
def test_guardian_assignment_is_required(binding):
    with pytest.raises(PaymentGuardError):
        guardian(assigned_guardian_id=binding)


@pytest.mark.parametrize("role", list(UserRole))
def test_roles_are_independent_and_admin_has_no_implicit_override(role):
    if role is not UserRole.GUARDIAN:
        with pytest.raises(PaymentGuardError):
            guardian(actor=actor(roles=frozenset({role})))
    if role is not UserRole.PAYER:
        with pytest.raises(PaymentGuardError):
            confirm(actor=actor(PAYER, frozenset({role})))


@pytest.mark.parametrize("overrides", [
    {"actor": None}, {"actor": {"user_id": str(PAYER), "roles": ["payer"]}},
    {"actor": actor(GUARDIAN, frozenset({UserRole.PAYER}))}, {"payer_id": str(PAYER)},
])
def test_untrusted_or_wrong_payer_fails(overrides):
    with pytest.raises(PaymentGuardError):
        confirm(**overrides)


@pytest.mark.parametrize("lock,hard_policy", list(product([False, True, None, 0, 1, "false"], [True, False, None, 1, "true"])))
def test_only_binary_unlocked_and_explicit_hard_policy_allow_can_pass(lock, hard_policy):
    if lock is False and hard_policy is True:
        assert confirm(safe_lock_is_locked=lock, hard_policy_allows=hard_policy) is None
    else:
        with pytest.raises(PaymentGuardError):
            confirm(safe_lock_is_locked=lock, hard_policy_allows=hard_policy)


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_guardian_cannot_override_hard_policy(value):
    with pytest.raises(PaymentGuardError):
        guardian(hard_policy_allows=value)


@pytest.mark.parametrize("user_id,roles", [(str(PAYER), frozenset({UserRole.PAYER})),
                                         (PAYER, {UserRole.PAYER}), (PAYER, frozenset({"payer"}))])
def test_trusted_context_validates_shape_without_claiming_authentication(user_id, roles):
    with pytest.raises(PaymentGuardError):
        TrustedActorContext(user_id, roles)
