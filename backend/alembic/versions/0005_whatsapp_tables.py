"""whatsapp tables: connections, authorized_senders, conversations, message_log, jobs

Revision ID: 134e2bbc2775
Revises: b9ad1e49af71
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '134e2bbc2775'
down_revision: Union[str, Sequence[str], None] = 'b9ad1e49af71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'whatsapp_connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=False),
        sa.Column('phone_number_id', sa.String(length=64), nullable=False),
        sa.Column('waba_id', sa.String(length=64), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_whatsapp_connections_business_id'),
        'whatsapp_connections', ['business_id'], unique=True,
    )
    op.create_index(
        op.f('ix_whatsapp_connections_phone_number_id'),
        'whatsapp_connections', ['phone_number_id'], unique=False,
    )
    op.create_index(
        'ux_whatsapp_connections_phone_number_id_active',
        'whatsapp_connections', ['phone_number_id'], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        'whatsapp_authorized_senders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=False),
        sa.Column('phone_e164', sa.String(length=20), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(), nullable=False),
        sa.Column('enrolled_by', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_whatsapp_authorized_senders_business_id'),
        'whatsapp_authorized_senders', ['business_id'], unique=False,
    )
    op.create_index(
        'ux_wa_senders_business_phone',
        'whatsapp_authorized_senders', ['business_id', 'phone_e164'], unique=True,
    )

    op.create_table(
        'whatsapp_conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=False),
        sa.Column('sender_phone_e164', sa.String(length=20), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('draft_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=True),
        sa.Column('last_result_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_whatsapp_conversations_business_id'),
        'whatsapp_conversations', ['business_id'], unique=False,
    )
    op.create_index(
        'ux_wa_conv_business_sender',
        'whatsapp_conversations', ['business_id', 'sender_phone_e164'], unique=True,
    )

    op.create_table(
        'whatsapp_message_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('wa_message_id', sa.String(length=128), nullable=False),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['whatsapp_conversations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_whatsapp_message_log_wa_message_id'),
        'whatsapp_message_log', ['wa_message_id'], unique=True,
    )

    op.create_table(
        'whatsapp_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('business_id', sa.UUID(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_wa_jobs_status_created', 'whatsapp_jobs', ['status', 'created_at'], unique=False)
    op.create_index(
        op.f('ix_whatsapp_jobs_business_id'), 'whatsapp_jobs', ['business_id'], unique=False
    )
    op.create_index(
        op.f('ix_whatsapp_jobs_created_at'), 'whatsapp_jobs', ['created_at'], unique=False
    )
    op.create_index(op.f('ix_whatsapp_jobs_status'), 'whatsapp_jobs', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_whatsapp_jobs_status'), table_name='whatsapp_jobs')
    op.drop_index(op.f('ix_whatsapp_jobs_created_at'), table_name='whatsapp_jobs')
    op.drop_index(op.f('ix_whatsapp_jobs_business_id'), table_name='whatsapp_jobs')
    op.drop_index('ix_wa_jobs_status_created', table_name='whatsapp_jobs')
    op.drop_table('whatsapp_jobs')

    op.drop_index(op.f('ix_whatsapp_message_log_wa_message_id'), table_name='whatsapp_message_log')
    op.drop_table('whatsapp_message_log')

    op.drop_index('ux_wa_conv_business_sender', table_name='whatsapp_conversations')
    op.drop_index(op.f('ix_whatsapp_conversations_business_id'), table_name='whatsapp_conversations')
    op.drop_table('whatsapp_conversations')

    op.drop_index('ux_wa_senders_business_phone', table_name='whatsapp_authorized_senders')
    op.drop_index(
        op.f('ix_whatsapp_authorized_senders_business_id'),
        table_name='whatsapp_authorized_senders',
    )
    op.drop_table('whatsapp_authorized_senders')

    op.drop_index('ux_whatsapp_connections_phone_number_id_active', table_name='whatsapp_connections')
    op.drop_index(op.f('ix_whatsapp_connections_phone_number_id'), table_name='whatsapp_connections')
    op.drop_index(op.f('ix_whatsapp_connections_business_id'), table_name='whatsapp_connections')
    op.drop_table('whatsapp_connections')
