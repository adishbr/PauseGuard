"""Add authoritative monotonic append_seq ordering to audit_events.

Revision ID: 0004_audit_append_sequence
Revises: 0003_razorpay_merchant_sandbox

Adds:
- audit_events.append_seq BIGINT NOT NULL (> 0)
- ix_audit_events_append_seq UNIQUE index
- audit_events_append_seq PostgreSQL sequence
- Verified chain-order backfill for any pre-existing audit_events rows (fail-closed on forks/cycles/orphans)
"""

from alembic import context, op
import sqlalchemy as sa

revision = "0004_audit_append_sequence"
down_revision = "0003_razorpay_merchant_sandbox"
branch_labels = None
depends_on = None

GENESIS_HASH = "0" * 64


def reconstruct_verified_chain_order(rows: list[tuple[object, str | None, str]]) -> list[object]:
    """Reconstruct exact linear append order from genesis using prev_hash -> event_hash links.

    Raises RuntimeError on forks (duplicate successors), cycles, missing genesis,
    multiple roots, duplicate hashes, or unreachable/orphaned rows rather than guessing.
    """
    if not rows:
        return []

    seen_hashes: set[str] = set()
    children_by_prev: dict[str, list[tuple[object, str]]] = {}
    for row_id, prev_hash, event_hash in rows:
        if event_hash in seen_hashes:
            raise RuntimeError(
                f"Cannot backfill audit_events.append_seq: duplicate event_hash {event_hash!r}"
            )
        seen_hashes.add(event_hash)
        if not prev_hash:
            raise RuntimeError(
                f"Cannot backfill audit_events.append_seq: row {row_id!r} missing prev_hash"
            )
        children_by_prev.setdefault(prev_hash, []).append((row_id, event_hash))

    roots = children_by_prev.get(GENESIS_HASH, [])
    if len(roots) != 1:
        raise RuntimeError(
            f"Cannot backfill audit_events.append_seq: expected exactly 1 genesis event, found {len(roots)}"
        )

    ordered_ids: list[object] = []
    visited_hashes: set[str] = set()
    current_id, current_hash = roots[0]

    while True:
        if current_hash in visited_hashes:
            raise RuntimeError(
                f"Cannot backfill audit_events.append_seq: cycle detected at hash {current_hash!r}"
            )
        visited_hashes.add(current_hash)
        ordered_ids.append(current_id)

        next_nodes = children_by_prev.get(current_hash, [])
        if len(next_nodes) > 1:
            raise RuntimeError(
                f"Cannot backfill audit_events.append_seq: chain fork detected at parent hash {current_hash!r}"
            )
        if not next_nodes:
            break
        current_id, current_hash = next_nodes[0]

    if len(ordered_ids) != len(rows):
        raise RuntimeError(
            f"Cannot backfill audit_events.append_seq: {len(rows) - len(ordered_ids)} orphaned/unreachable row(s)"
        )

    return ordered_ids


def _backfill_existing_audit_events() -> int:
    if context.is_offline_mode():
        return 0
    bind = op.get_bind()
    result = bind.execute(sa.text("SELECT id, prev_hash, event_hash FROM audit_events"))
    rows = [(row[0], row[1], row[2]) for row in result.fetchall()]
    if not rows:
        return 0

    ordered_ids = reconstruct_verified_chain_order(rows)
    for seq, row_id in enumerate(ordered_ids, start=1):
        bind.execute(
            sa.text("UPDATE audit_events SET append_seq = :seq WHERE id = :row_id"),
            {"seq": seq, "row_id": row_id},
        )
    return len(ordered_ids)


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("append_seq", sa.BigInteger(), nullable=True))
    max_seq = _backfill_existing_audit_events()
    op.create_check_constraint(
        "ck_audit_events_positive_append_seq",
        "audit_events",
        "append_seq > 0",
    )
    op.alter_column(
        "audit_events",
        "append_seq",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_index("ix_audit_events_append_seq", "audit_events", ["append_seq"], unique=True)
    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS audit_events_append_seq START WITH 1 INCREMENT BY 1"))
    if max_seq > 0 and not context.is_offline_mode():
        op.execute(sa.text(f"SELECT setval('audit_events_append_seq', {int(max_seq)}, true)"))


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE IF EXISTS audit_events_append_seq"))
    op.drop_index("ix_audit_events_append_seq", table_name="audit_events")
    op.drop_constraint("ck_audit_events_positive_append_seq", "audit_events", type_="check")
    op.drop_column("audit_events", "append_seq")
