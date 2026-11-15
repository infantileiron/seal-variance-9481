from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Sample,Process
def listing(db):return db.scalars(select(Sample).order_by(Sample.id)).all()
def save(db,data,id=None):
    if not db.get(Process,data.process_id):raise HTTPException(404,'工艺方案不存在')
    item=db.get(Sample,id) if id else Sample()
    if not item:raise HTTPException(404,'拉力样本不存在')
    for k,v in data.model_dump().items():setattr(item,k,v)
    db.add(item);db.commit();db.refresh(item);return item
