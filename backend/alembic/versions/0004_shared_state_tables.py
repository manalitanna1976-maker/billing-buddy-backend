"""shared state tables: revoked_tokens, rate_limit_events

Revision ID: b9ad1e49af71
Revises: b6a383ffd939
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9ad1e49af71'
down_revision: Union[str, Sequence[str], None] = 'b6a383ffd939'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'revoked_tokens',
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('jti'),
    )
    op.create_table(
        'rate_limit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('bucket_key', sa.String(length=255), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_rate_limit_events_bucket_key'), 'rate_limit_events', ['bucket_key'], unique=False
    )
    op.create_index(
        'ix_rate_limit_events_bucket_key_occurred_at',
        'rate_limit_events',
        ['bucket_key', 'occurred_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rate_limit_events_bucket_key_occurred_at', table_name='rate_limit_events')
    op.drop_index(op.f('ix_rate_limit_events_bucket_key'), table_name='rate_limit_events')
    op.drop_table('rate_limit_events')
    op.drop_table('revoked_tokens')
