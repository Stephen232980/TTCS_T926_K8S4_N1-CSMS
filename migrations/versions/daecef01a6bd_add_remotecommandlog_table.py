"""Add RemoteCommandLog table

Revision ID: daecef01a6bd
Revises: ff188b81808f
Create Date: 2026-10-04 14:09:48.071920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'daecef01a6bd'
down_revision: Union[str, Sequence[str], None] = 'ff188b81808f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ocpp_remote_command_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('charge_point_id', sa.Uuid(), nullable=True),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('command', sa.String(length=50), nullable=False),
        sa.Column('result', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['charge_point_id'], ['charge_points.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['session_id'], ['charging_sessions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ocpp_remote_command_logs_charge_point_id', 'ocpp_remote_command_logs', ['charge_point_id'], unique=False)
    op.create_index('ix_ocpp_remote_command_logs_created_at', 'ocpp_remote_command_logs', ['created_at'], unique=False)
    op.create_index('ix_ocpp_remote_command_logs_user_id', 'ocpp_remote_command_logs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ocpp_remote_command_logs_user_id', table_name='ocpp_remote_command_logs')
    op.drop_index('ix_ocpp_remote_command_logs_created_at', table_name='ocpp_remote_command_logs')
    op.drop_index('ix_ocpp_remote_command_logs_charge_point_id', table_name='ocpp_remote_command_logs')
    op.drop_table('ocpp_remote_command_logs')
