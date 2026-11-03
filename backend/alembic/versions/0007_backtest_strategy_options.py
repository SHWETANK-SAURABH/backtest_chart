"""Store each backtest's strategy options: entry patterns and MTZ choice.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Backtests made before options existed keep an empty object: they used every pattern and
    # both MTZs, under strategy implementation 1.0.0.
    op.add_column(
        "backtest_jobs",
        sa.Column(
            "strategy_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("backtest_jobs", "strategy_options")
