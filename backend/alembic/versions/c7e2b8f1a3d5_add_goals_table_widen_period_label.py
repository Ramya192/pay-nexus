"""add goals table, widen bank_statements.period_label

Revision ID: c7e2b8f1a3d5
Revises: b3f1a9c2d4e7
Create Date: 2026-08-15 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2b8f1a3d5'
down_revision: Union[str, Sequence[str], None] = 'b3f1a9c2d4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'bank_statements',
        'period_label',
        existing_type=sa.String(length=20),
        type_=sa.String(length=60),
        existing_nullable=False,
    )

    op.create_table('goals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('iv', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_goals_user_id'), 'goals', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_goals_user_id'), table_name='goals')
    op.drop_table('goals')

    op.alter_column(
        'bank_statements',
        'period_label',
        existing_type=sa.String(length=60),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
