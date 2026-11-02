"""Answer cache, test questions and their runs (new tables only).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02 09:54:52.214749

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('answer_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_hit_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('site_id', 'key')
    )
    op.create_index(op.f('ix_answer_cache_site_id'), 'answer_cache', ['site_id'], unique=False)
    op.create_table('eval_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_eval_questions_embed_id'), 'eval_questions', ['embed_id'], unique=False)
    op.create_table('eval_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('passed', sa.Integer(), nullable=False),
    sa.Column('results', sa.JSON(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_eval_runs_embed_id'), 'eval_runs', ['embed_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_eval_runs_embed_id'), table_name='eval_runs')
    op.drop_table('eval_runs')
    op.drop_index(op.f('ix_eval_questions_embed_id'), table_name='eval_questions')
    op.drop_table('eval_questions')
    op.drop_index(op.f('ix_answer_cache_site_id'), table_name='answer_cache')
    op.drop_table('answer_cache')
