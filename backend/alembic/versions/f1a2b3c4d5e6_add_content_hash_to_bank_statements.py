"""add content_hash to bank_statements

Revision ID: f1a2b3c4d5e6
Revises: e8f3c7a1b9d2
Create Date: 2026-08-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e8f3c7a1b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('bank_statements', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_bank_statements_content_hash'), 'bank_statements', ['content_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_bank_statements_content_hash'), table_name='bank_statements')
    op.drop_column('bank_statements', 'content_hash')
