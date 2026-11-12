from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.models.user import UserRole
from app.services.foundation_queries import (
    guardian_decision_for_update,
    idempotency_record_for_update,
    owned_account_for_update,
    payer_account_for_update,
    payment_for_update,
    role_bindings_for_update,
    safe_lock_for_payer_for_update,
    safe_lock_for_update,
)
from app.services.payment_guards import TrustedActorContext


def test_persisted_grants_and_owned_rows_are_bound_and_locked_offline():
    actor_id, account_id = UUID(int=11), UUID(int=12)
    actor = TrustedActorContext(actor_id, frozenset({UserRole.PAYER}))
    cases = [
        (role_bindings_for_update(actor), "role_bindings.user_id =", {actor_id}),
        (owned_account_for_update(actor, account_id), "accounts.owner_id =", {actor_id, account_id}),
        (safe_lock_for_update(actor), "safe_lock_states.payer_id =", {actor_id}),
        (safe_lock_for_payer_for_update(actor_id), "safe_lock_states.payer_id =", {actor_id}),
        (payer_account_for_update(actor_id), "accounts.owner_id =", {actor_id}),
        (payment_for_update("pg_test_001"), "payments.id =", {"pg_test_001"}),
        (guardian_decision_for_update("pg_test_001"), "guardian_decisions.payment_id =", {"pg_test_001"}),
        (idempotency_record_for_update("idem_key_001"), "idempotency_records.key =", {"idem_key_001"}),
    ]
    for statement, predicate, values in cases:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.endswith("FOR UPDATE")
        # A lock alone would retain stale identity-map attributes. Every builder
        # must explicitly refresh loaded instances, including expire_on_commit=False.
        assert statement.get_execution_options().get("populate_existing") is True
        assert predicate in sql
        assert set(compiled.params.values()) == values
        assert str(actor_id) not in sql
        assert str(account_id) not in sql
    assert "accounts.id =" in str(cases[1][0].compile(dialect=postgresql.dialect()))
