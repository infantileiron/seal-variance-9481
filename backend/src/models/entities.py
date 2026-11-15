from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,Text
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
class Audit(Base):
    __tablename__='audit_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(String(200))
    status:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[str]=mapped_column(String(40))
