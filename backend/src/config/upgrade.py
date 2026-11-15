"""Lightweight in-place schema upgrade for deployments created before versions.

The project has no migration runner; ``Base.metadata.create_all`` only creates
missing tables.  This helper adds the version/calibration columns to an existing
install and backfills legacy results as an immutable published version so old
signed reviews remain readable instead of disappearing.
"""
import json

from sqlalchemy import inspect, text

from src.config.database import Base, engine, SessionLocal
from src.models.entities import Assessment, AssessmentVersion, CalibrationRule
from src.services.assessments import now_iso


NEW_COLUMNS = {
    'assessments': {
        'current_version_id': 'INTEGER',
        'approved_version_id': 'INTEGER',
        'recommendation_version_id': 'INTEGER',
        'candidate_version_id': 'INTEGER',
        'stale': 'BOOLEAN DEFAULT FALSE NOT NULL',
    },
}


def upgrade():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in NEW_COLUMNS.items():
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
    inspector = inspect(engine)
    if 'calibration_rules' not in inspector.get_table_names():
        CalibrationRule.__table__.create(engine)
    with SessionLocal() as db:
        from sqlalchemy import select
        legacy = db.scalars(select(Assessment).where(
            Assessment.current_version_id.is_(None),
            Assessment.result.is_not(None),
        )).all()
        for item in legacy:
            result = item.result or {}
            version = AssessmentVersion(
                assessment_id=item.id,
                version=1,
                status='completed',
                calibration_fingerprint='',
                calibration_snapshot=[],
                result=result,
                quarantine=result.get('quarantine', []),
                trigger='legacy',
                requested_by='',
                published=True,
                stale=False,
                superseded=False,
                created_at=item.created_at or now_iso(),
                completed_at=item.created_at or now_iso(),
            )
            db.add(version)
            db.flush()
            item.current_version_id = version.id
            if item.approved:
                item.approved_version_id = version.id
            if item.approved:
                # Signed legacy reviews stay frozen and readable; the missing
                # calibration basis is recorded on the version, not the review.
                item.stale = False
            else:
                # Legacy results predate calibration, so their fingerprint does
                # not match any active rule set: mark stale until recomputed.
                item.stale = True
                if not item.error:
                    item.error = '历史结果生成于校准功能之前，未含换算依据；请重算后再引用'
        db.commit()


if __name__ == '__main__':
    upgrade()
