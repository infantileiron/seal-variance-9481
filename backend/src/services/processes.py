from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Process
def listing(db):return db.scalars(select(Process).order_by(Process.id)).all()
def save(db,data,id=None):
    item=db.get(Process,id) if id else Process()
    if not item:raise HTTPException(404,'工艺方案不存在')
    for k,v in data.model_dump().items():setattr(item,k,v)
    db.add(item);db.commit();db.refresh(item);return item
