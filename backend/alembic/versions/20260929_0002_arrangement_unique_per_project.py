"""arrangements unique per project

Two projects can share one analysis (deduplicated uploads); each project keeps
its own arrangements, titled after that project.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_arrangements_analysis_params", "arrangements", type_="unique")
    op.create_unique_constraint(
        "uq_arrangements_project_params",
        "arrangements",
        ["project_id", "analysis_id", "difficulty", "params_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_arrangements_project_params", "arrangements", type_="unique")
    op.create_unique_constraint(
        "uq_arrangements_analysis_params",
        "arrangements",
        ["analysis_id", "difficulty", "params_hash"],
    )
