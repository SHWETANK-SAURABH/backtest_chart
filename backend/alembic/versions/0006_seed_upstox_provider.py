"""Register the Upstox provider and its documented capabilities.

Revision ID: 0006
Revises: 0005
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAPABILITIES = {
    "documentation": "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/",
    "verified_on": "2026-11-02",
    "nifty50_instrument_key": "NSE_INDEX|Nifty 50",
    "minute_intervals": "1 to 300",
    "intraday_max_range_per_request": "1 month for 1 to 15 minute candles",
    "intraday_history_from": "2022-01",
    "daily_history_from": "2000-01",
    "requests_per_second": 50,
    "requests_per_minute": 500,
    "requests_per_30_minutes": 2000,
    "timestamps": "ISO 8601 with +05:30 offset",
    "token_validity": "not stated in the documentation",
}


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO data_providers (id, code, name, is_enabled, capabilities)
            VALUES (gen_random_uuid(), 'upstox', 'Upstox', true, CAST(:capabilities AS jsonb))
            """
        ).bindparams(capabilities=json.dumps(CAPABILITIES))
    )


def downgrade() -> None:
    op.execute("DELETE FROM data_providers WHERE code = 'upstox'")
