import os
from datetime import datetime,timezone
from sqlalchemy import select
from fastapi import HTTPException
import redis
from src.models.entities import Assessment,Process,Sample
queue=redis.Redis.from_url(os.environ['REDIS_URL'])
def listing(db):return db.scalars(select(Assessment).order_by(Assessment.id.desc())).all()
def get(db,id):
    item=db.get(Assessment,id)
    if not item:raise HTTPException(404,'评议任务不存在')
    return item
def snapshot_for(db,ids,lot):
    if len(ids)!=len(set(ids)):raise HTTPException(422,'不能重复选择同一工艺')
    groups=[]
    for id in ids:
        process=db.get(Process,id)
        if not process:raise HTTPException(404,'工艺方案不存在')
        q=select(Sample).where(Sample.process_id==id).order_by(Sample.code)
        if lot!='全部':q=q.where(Sample.lot==lot)
        samples=db.scalars(q).all()
        groups.append({'id':id,'code':process.code,'name':process.name,'temperature':process.temperature,'dwell':process.dwell,'pressure':process.pressure,'samples':[{'code':s.code,'force':s.force,'flagged':s.flagged,'lot':s.lot} for s in samples]})
    return {'lot':lot,'groups':groups}
def create(db,data):
    if len(db.scalars(select(Assessment).where(Assessment.status.in_(['queued','running']))).all())>=10:raise HTTPException(429,'最多10个待执行任务，请稍后重试')
    snapshot=snapshot_for(db,data.process_ids,data.lot)
    item=Assessment(title=data.title,lot=data.lot,snapshot=snapshot,status='queued',created_at=datetime.now(timezone.utc).isoformat())
    db.add(item);db.commit();db.refresh(item)
    try:queue.lpush('seal:assessments',item.id)
    except redis.RedisError:
        item.status='failed';item.error='队列不可用，请恢复后新建评议';db.commit();raise HTTPException(503,item.error)
    return item
def recommend(db,id,data):
    item=get(db,id)
    if item.status!='completed':raise HTTPException(409,'计算完成后才能起草工艺评议')
    if item.approved:raise HTTPException(409,'已签核评议冻结，请新建评议留痕')
    if data.selected_process_id not in [g['id'] for g in item.snapshot['groups']]:raise HTTPException(422,'只能推荐本次比较内的工艺')
    item.selected_process_id=data.selected_process_id;item.recommendation=data.recommendation
    db.commit();return item
def approve(db,id,user):
    item=get(db,id)
    if item.status!='completed' or not item.recommendation or not item.selected_process_id:raise HTTPException(409,'请先完成计算并填写推荐方案与业务理由')
    if item.approved:raise HTTPException(409,'评议已签核')
    item.approved=True;item.approved_by=user.email;db.commit();return item
