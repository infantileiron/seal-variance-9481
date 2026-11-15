from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base

class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    role:Mapped[str]=mapped_column(String(20))
    password_hash:Mapped[str]=mapped_column(String(200))

class Process(Base):
    __tablename__='processes'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    name:Mapped[str]=mapped_column(String(100))
    temperature:Mapped[float]=mapped_column(Float)
    dwell:Mapped[float]=mapped_column(Float)
    pressure:Mapped[float]=mapped_column(Float)
    note:Mapped[str]=mapped_column(Text,default='')

class Sample(Base):
    __tablename__='samples'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    process_id:Mapped[int]=mapped_column(ForeignKey('processes.id'))
    lot:Mapped[str]=mapped_column(String(60))
    force:Mapped[float]=mapped_column(Float)
    flagged:Mapped[bool]=mapped_column(Boolean,default=False)
    note:Mapped[str]=mapped_column(Text,default='')

class CalibrationRule(Base):
    """Immutable calibration revision for an inclusive test-strip code range.

    A new revision for the same range supersedes older rows by setting
    ``active`` to false; the old rows stay queryable as conversion evidence.
    """
    __tablename__='calibration_rules'
    id:Mapped[int]=mapped_column(primary_key=True)
    code_start:Mapped[str]=mapped_column(String(50))
    code_end:Mapped[str]=mapped_column(String(50))
    revision:Mapped[int]=mapped_column(Integer,default=1)
    points:Mapped[list]=mapped_column(JSON)
    note:Mapped[str]=mapped_column(Text,default='')
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    impact_scope:Mapped[list|None]=mapped_column(JSON,nullable=True)
    created_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40),default='')
    __table_args__=(UniqueConstraint('code_start','code_end','revision',name='uq_calibration_range_revision'),)

class Assessment(Base):
    __tablename__='assessments'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(120),unique=True)
    lot:Mapped[str]=mapped_column(String(60),default='全部')
    status:Mapped[str]=mapped_column(String(20),default='queued')
    snapshot:Mapped[dict]=mapped_column(JSON)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    recommendation:Mapped[str]=mapped_column(Text,default='')
    selected_process_id:Mapped[int|None]=mapped_column(ForeignKey('processes.id'),nullable=True)
    approved:Mapped[bool]=mapped_column(Boolean,default=False)
    approved_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40))
    # Version pointers are plain integers to avoid a circular FK with
    # assessment_versions.assessment_id; the versions table remains the
    # authoritative history.
    current_version_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    approved_version_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    recommendation_version_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    candidate_version_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    stale:Mapped[bool]=mapped_column(Boolean,default=False)

class AssessmentVersion(Base):
    """One immutable computation attempt for an assessment.

    A retry reuses the row with the same calibration fingerprint, so repeated
    clicks or duplicate queue messages cannot create duplicate result versions.
    """
    __tablename__='assessment_versions'
    id:Mapped[int]=mapped_column(primary_key=True)
    assessment_id:Mapped[int]=mapped_column(ForeignKey('assessments.id'))
    version:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(20),default='queued')
    calibration_fingerprint:Mapped[str]=mapped_column(String(64),default='')
    calibration_snapshot:Mapped[list|None]=mapped_column(JSON,nullable=True)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    quarantine:Mapped[list|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    trigger:Mapped[str]=mapped_column(String(40),default='created')
    requested_by:Mapped[str]=mapped_column(String(120),default='')
    published:Mapped[bool]=mapped_column(Boolean,default=False)
    stale:Mapped[bool]=mapped_column(Boolean,default=False)
    superseded:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[str]=mapped_column(String(40),default='')
    started_at:Mapped[str]=mapped_column(String(40),default='')
    completed_at:Mapped[str]=mapped_column(String(40),default='')
    __table_args__=(UniqueConstraint('assessment_id','version',name='uq_assessment_version'),UniqueConstraint('assessment_id','calibration_fingerprint',name='uq_assessment_calibration'),)

class Audit(Base):
    __tablename__='audit_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(String(200))
    status:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[str]=mapped_column(String(40))
