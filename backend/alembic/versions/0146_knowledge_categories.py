"""Share the Knowledge PX workflow with definitions and regulations."""
from alembic import op
import sqlalchemy as sa

revision = "0146_knowledge_categories"
down_revision = "0145_reporting_points_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_prompts", sa.Column("knowledge_type", sa.String(32), nullable=False, server_default="PROMPT"))
    op.create_index("ix_knowledge_prompts_knowledge_type", "knowledge_prompts", ["knowledge_type"])
    op.create_check_constraint(op.f("ck_knowledge_prompts_knowledge_type"), "knowledge_prompts", "knowledge_type IN ('PROMPT', 'DEFINITION', 'REGULATION')")


def downgrade():
    op.drop_constraint(op.f("ck_knowledge_prompts_knowledge_type"), "knowledge_prompts", type_="check")
    op.drop_index("ix_knowledge_prompts_knowledge_type", table_name="knowledge_prompts")
    op.drop_column("knowledge_prompts", "knowledge_type")
