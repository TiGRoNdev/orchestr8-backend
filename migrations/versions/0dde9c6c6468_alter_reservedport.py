"""Alter ReservedPort

Revision ID: 0dde9c6c6468
Revises: aec681689bb8
Create Date: 2025-03-06 09:03:19.259453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0dde9c6c6468'
down_revision: Union[str, None] = 'aec681689bb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('reserved_port', sa.Column('protocol', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('reserved_port', 'protocol')
    # ### end Alembic commands ###
