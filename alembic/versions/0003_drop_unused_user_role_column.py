"""drop unused user role column

Revision ID: b6a383ffd939
Revises: 298d22e146c0
Create Date: 2026-08-17 00:50:37.406447

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6a383ffd939'
down_revision: Union[str, Sequence[str], None] = '298d22e146c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('users', 'role')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'users',
        sa.Column('role', sa.String(length=20), nullable=False, server_default='owner'),
    )
