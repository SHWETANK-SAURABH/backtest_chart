"""Seed the NIFTY 50 instrument and enforce strategy version immutability.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO instruments (id, symbol, name, exchange, instrument_type, timezone,
                                 is_tradable, is_active)
        VALUES (gen_random_uuid(), 'NIFTY50', 'NIFTY 50', 'NSE', 'index', 'Asia/Kolkata',
                false, true)
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_used_strategy_version_change() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM backtest_jobs
                WHERE strategy_version_id = OLD.id AND status = 'completed'
            ) THEN
                RAISE EXCEPTION 'strategy version % is immutable: used by a completed backtest',
                    OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER strategy_version_immutable
        BEFORE UPDATE ON strategy_versions
        FOR EACH ROW EXECUTE FUNCTION reject_used_strategy_version_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER strategy_version_immutable ON strategy_versions")
    op.execute("DROP FUNCTION reject_used_strategy_version_change()")
    op.execute("DELETE FROM instruments WHERE symbol = 'NIFTY50'")
