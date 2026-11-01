"""Register the DhanHQ provider and its documented capabilities.

Revision ID: 0003
Revises: 0002
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAPABILITIES = {
    "documentation": "https://dhanhq.co/docs/v2/historical-data/",
    "verified_on": "2026-11-01",
    "intervals_minutes": [1, 5, 15, 25, 60],
    "intraday_max_days_per_request": 90,
    "intraday_history_years": 5,
    "data_requests_per_second": 5,
    "data_requests_per_day": 100000,
    "token_validity_hours": 24,
    "requires_paid_data_plan": True,
}


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO data_providers (id, code, name, is_enabled, capabilities)
            VALUES (gen_random_uuid(), 'dhan', 'DhanHQ', true, CAST(:capabilities AS jsonb))
            """
        ).bindparams(capabilities=json.dumps(CAPABILITIES))
    )


def downgrade() -> None:
    op.execute("DELETE FROM data_providers WHERE code = 'dhan'")
