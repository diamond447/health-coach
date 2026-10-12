"""key strength data by openGym ids

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent


def upgrade() -> None:
    # 1. Drop views that depend on strength_sets and exercises
    op.execute("DROP VIEW IF EXISTS v_exercise_e1rm")
    op.execute("DROP VIEW IF EXISTS v_strength_volume_weekly")

    # 2. Update strength_sets: drop FK, drop wger_log_id, change exercise_id to text,
    # add external_id, alter source default
    op.drop_constraint(
        "fk_strength_sets_exercise_id_exercises", "strength_sets", type_="foreignkey"
    )
    op.drop_constraint("uq_strength_sets_wger_log_id", "strength_sets", type_="unique")
    op.drop_column("strength_sets", "wger_log_id")
    op.add_column("strength_sets", sa.Column("external_id", sa.Text(), nullable=False))
    op.create_unique_constraint(
        op.f("uq_strength_sets_external_id"), "strength_sets", ["external_id"]
    )
    op.alter_column(
        "strength_sets",
        "exercise_id",
        type_=sa.Text(),
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "strength_sets",
        "source",
        server_default="opengym",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 3. Update exercises: drop PK, drop wger_id, add id Text PK, alter source default
    op.drop_constraint("pk_exercises", "exercises", type_="primary")
    op.drop_column("exercises", "wger_id")
    op.add_column("exercises", sa.Column("id", sa.Text(), nullable=False))
    op.create_primary_key(op.f("pk_exercises"), "exercises", ["id"])
    op.alter_column(
        "exercises",
        "source",
        server_default="opengym",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 4. Recreate foreign key from strength_sets.exercise_id to exercises.id
    op.create_foreign_key(
        op.f("fk_strength_sets_exercise_id_exercises"),
        "strength_sets",
        "exercises",
        ["exercise_id"],
        ["id"],
    )

    # 5. Update strength_sessions: drop wger_session_id, wger_routine_id, impression;
    # add external_id, routine_id; alter source default
    op.drop_constraint("uq_strength_sessions_wger_session_id", "strength_sessions", type_="unique")
    op.drop_column("strength_sessions", "wger_session_id")
    op.add_column("strength_sessions", sa.Column("external_id", sa.Text(), nullable=False))
    op.create_unique_constraint(
        op.f("uq_strength_sessions_external_id"), "strength_sessions", ["external_id"]
    )
    op.drop_column("strength_sessions", "wger_routine_id")
    op.add_column("strength_sessions", sa.Column("routine_id", sa.Text(), nullable=True))
    op.drop_column("strength_sessions", "impression")
    op.alter_column(
        "strength_sessions",
        "source",
        server_default="opengym",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 6. Recreate views and grants
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0003_views.sql").read_text())


def downgrade() -> None:
    # 1. Drop views
    op.execute("DROP VIEW IF EXISTS v_exercise_e1rm")
    op.execute("DROP VIEW IF EXISTS v_strength_volume_weekly")

    # 2. Drop FK from strength_sets
    op.drop_constraint(
        "fk_strength_sets_exercise_id_exercises", "strength_sets", type_="foreignkey"
    )

    # 3. Revert strength_sessions
    op.drop_constraint("uq_strength_sessions_external_id", "strength_sessions", type_="unique")
    op.drop_column("strength_sessions", "external_id")
    op.drop_column("strength_sessions", "routine_id")
    op.add_column(
        "strength_sessions", sa.Column("wger_session_id", postgresql.UUID(), nullable=False)
    )
    op.create_unique_constraint(
        op.f("uq_strength_sessions_wger_session_id"), "strength_sessions", ["wger_session_id"]
    )
    op.add_column("strength_sessions", sa.Column("wger_routine_id", sa.Integer(), nullable=True))
    op.add_column(
        "strength_sessions",
        sa.Column(
            "impression",
            sa.SmallInteger(),
            nullable=True,
            comment="wger impression: 1 bad, 2 neutral, 3 good",
        ),
    )
    op.alter_column(
        "strength_sessions",
        "source",
        server_default="wger",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 4. Revert exercises
    op.drop_constraint("pk_exercises", "exercises", type_="primary")
    op.drop_column("exercises", "id")
    op.add_column(
        "exercises",
        sa.Column("wger_id", sa.Integer(), nullable=False),
    )
    op.create_primary_key(op.f("pk_exercises"), "exercises", ["wger_id"])
    op.alter_column(
        "exercises",
        "source",
        server_default="wger",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 5. Revert strength_sets
    op.drop_constraint("uq_strength_sets_external_id", "strength_sets", type_="unique")
    op.drop_column("strength_sets", "external_id")
    op.add_column("strength_sets", sa.Column("wger_log_id", postgresql.UUID(), nullable=False))
    op.create_unique_constraint(
        op.f("uq_strength_sets_wger_log_id"), "strength_sets", ["wger_log_id"]
    )
    op.alter_column(
        "strength_sets",
        "exercise_id",
        type_=sa.Integer(),
        existing_type=sa.Text(),
        nullable=False,
        postgresql_using="exercise_id::integer",
    )
    op.create_foreign_key(
        op.f("fk_strength_sets_exercise_id_exercises"),
        "strength_sets",
        "exercises",
        ["exercise_id"],
        ["wger_id"],
    )
    op.alter_column(
        "strength_sets",
        "source",
        server_default="wger",
        existing_type=sa.Text(),
        existing_nullable=False,
    )

    # 6. Recreate views from 0001
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0001_views.sql").read_text())
    op.execute(
        "GRANT SELECT ON v_strength_volume_weekly, v_exercise_e1rm "
        "TO coach_ro, coach_rw, ingest, grafana_ro"
    )
