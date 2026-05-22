"""add_constraints_timestamps_and_validations

Revision ID: 088edfdc10c4
Revises: f6a7b8c9d0e1
Create Date: 2026-05-21 13:51:18.859644

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '088edfdc10c4'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # T4.1: CheckConstraints for status/role/source fields
    op.execute("ALTER TABLE pois ADD CONSTRAINT ck_pois_verification_status CHECK (verification_status IN ('pending', 'flagged', 'verified'))")
    op.execute("ALTER TABLE pois ADD CONSTRAINT ck_pois_access_type CHECK (access_type IN ('public', 'restricted', 'private'))")
    op.execute("ALTER TABLE itineraries ADD CONSTRAINT ck_itineraries_status CHECK (status IN ('planned', 'active', 'completed', 'cancelled'))")
    op.execute("ALTER TABLE entrepreneur_profiles ADD CONSTRAINT ck_entrepreneur_profiles_verification_status CHECK (verification_status IN ('unverified', 'verified', 'rejected'))")
    op.execute("ALTER TABLE ara_sessions ADD CONSTRAINT ck_ara_sessions_status CHECK (status IN ('clarifying', 'searching', 'generating', 'completed', 'failed'))")
    op.execute("ALTER TABLE ara_messages ADD CONSTRAINT ck_ara_messages_role CHECK (role IN ('user', 'assistant', 'system'))")
    op.execute("ALTER TABLE poi_visits ADD CONSTRAINT ck_poi_visits_source CHECK (source IN ('frontend', 'itinerary', 'external'))")

    # T4.2: Integrity constraints
    op.execute("ALTER TABLE pois ADD CONSTRAINT ck_pois_confidence_score CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0)")
    op.execute("ALTER TABLE itinerary_steps ADD CONSTRAINT ck_itinerary_steps_step_order CHECK (step_order > 0)")
    op.execute("ALTER TABLE itinerary_steps ADD CONSTRAINT ck_itinerary_steps_time_order CHECK (departure_time IS NULL OR arrival_time IS NULL OR departure_time > arrival_time)")
    op.execute("ALTER TABLE itineraries ADD CONSTRAINT ck_itineraries_date_range CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)")
    op.execute("ALTER TABLE ara_sessions ADD CONSTRAINT ck_ara_sessions_radius CHECK (radius IS NULL OR radius > 0)")

    # T4.2.6: VARCHAR(255) for tourist_profiles.full_name
    op.alter_column('tourist_profiles', 'full_name',
                    existing_type=sa.String(),
                    type_=sa.String(255),
                    existing_nullable=False)

    # T4.4: Add missing timestamps
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('categories', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('itineraries', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('itineraries', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('entrepreneur_profiles', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('entrepreneur_profiles', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('tourist_profiles', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('tourist_profiles', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('pois', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('pois', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))


def downgrade() -> None:
    # T4.4: Remove timestamps
    op.drop_column('pois', 'updated_at')
    op.drop_column('pois', 'created_at')
    op.drop_column('tourist_profiles', 'updated_at')
    op.drop_column('tourist_profiles', 'created_at')
    op.drop_column('entrepreneur_profiles', 'updated_at')
    op.drop_column('entrepreneur_profiles', 'created_at')
    op.drop_column('itineraries', 'updated_at')
    op.drop_column('itineraries', 'created_at')
    op.drop_column('categories', 'created_at')
    op.drop_column('users', 'updated_at')

    # T4.2.6: Revert full_name to unbounded String
    op.alter_column('tourist_profiles', 'full_name',
                    existing_type=sa.String(255),
                    type_=sa.String(),
                    existing_nullable=False)

    # T4.2: Remove integrity constraints
    op.execute("ALTER TABLE ara_sessions DROP CONSTRAINT ck_ara_sessions_radius")
    op.execute("ALTER TABLE itineraries DROP CONSTRAINT ck_itineraries_date_range")
    op.execute("ALTER TABLE itinerary_steps DROP CONSTRAINT ck_itinerary_steps_time_order")
    op.execute("ALTER TABLE itinerary_steps DROP CONSTRAINT ck_itinerary_steps_step_order")
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_confidence_score")

    # T4.1: Remove status/role/source CheckConstraints
    op.execute("ALTER TABLE poi_visits DROP CONSTRAINT ck_poi_visits_source")
    op.execute("ALTER TABLE ara_messages DROP CONSTRAINT ck_ara_messages_role")
    op.execute("ALTER TABLE ara_sessions DROP CONSTRAINT ck_ara_sessions_status")
    op.execute("ALTER TABLE entrepreneur_profiles DROP CONSTRAINT ck_entrepreneur_profiles_verification_status")
    op.execute("ALTER TABLE itineraries DROP CONSTRAINT ck_itineraries_status")
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_access_type")
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_verification_status")