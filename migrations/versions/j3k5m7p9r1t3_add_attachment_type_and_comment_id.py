"""add_attachment_type_and_comment_id

Revision ID: j3k5m7p9r1t3
Revises: h7k9m2p4q6s8
Create Date: 2026-02-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j3k5m7p9r1t3'
down_revision = 'h7k9m2p4q6s8'
branch_labels = None
depends_on = None


def upgrade():
    # Tipo de adjunto: 'ticket' (foto inicial), 'resolution', 'comment'
    op.add_column('helpdesk_attachment', sa.Column(
        'attachment_type', sa.String(length=20), nullable=False, server_default='ticket'
    ))
    # FK opcional a comentario (solo cuando attachment_type='comment')
    op.add_column('helpdesk_attachment', sa.Column(
        'comment_id', sa.Integer(), sa.ForeignKey('helpdesk_comment.id'), nullable=True
    ))

    op.create_index('ix_helpdesk_attachment_type', 'helpdesk_attachment', ['attachment_type'])
    op.create_index('ix_helpdesk_attachment_comment_id', 'helpdesk_attachment', ['comment_id'])


def downgrade():
    op.drop_index('ix_helpdesk_attachment_comment_id', table_name='helpdesk_attachment')
    op.drop_index('ix_helpdesk_attachment_type', table_name='helpdesk_attachment')
    op.drop_column('helpdesk_attachment', 'comment_id')
    op.drop_column('helpdesk_attachment', 'attachment_type')
