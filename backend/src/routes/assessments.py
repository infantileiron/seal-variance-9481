import json
from sqlalchemy import select
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from src.config.database import get_db
from src.utils.security import current_user,editor,admin
from src.schemas.business import AssessmentInput,RecommendationInput
from src.services import assessments
from src.controllers.business import serialize,serialize_many
from src.models.entities import Audit
router=APIRouter()
@router.get('/assessments')
def listing(db=Depends(get_db),user=Depends(current_user)):return serialize_many(assessments.listing(db))
@router.post('/assessments',status_code=202)
def create(data:AssessmentInput,db=Depends(get_db),user=Depends(editor)):return serialize(assessments.create(db,data))
@router.get('/assessments/{id}')
def detail(id:int,db=Depends(get_db),user=Depends(current_user)):return serialize(assessments.get(db,id))
@router.patch('/assessments/{id}/recommendation')
def recommendation(id:int,data:RecommendationInput,db=Depends(get_db),user=Depends(editor)):return serialize(assessments.recommend(db,id,data))
@router.post('/assessments/{id}/approve')
def approve(id:int,db=Depends(get_db),user=Depends(admin)):return serialize(assessments.approve(db,id,user))
@router.get('/assessments/{id}/export')
def export(id:int,db=Depends(get_db),user=Depends(current_user)):
    item=assessments.get(db,id)
    if item.status!='completed':raise HTTPException(409,'计算未成功完成，不能导出')
    return Response(json.dumps(serialize(item),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="seal-variance-{id}.json"'})
@router.get('/audit')
def audit(db=Depends(get_db),user=Depends(admin)):return serialize_many(db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100)).all())
