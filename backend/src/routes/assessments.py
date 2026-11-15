import json
from sqlalchemy import select
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from src.config.database import get_db
from src.utils.security import current_user,editor,admin
from src.schemas.business import AssessmentInput,RecommendationInput
from src.services import assessments
from src.controllers.business import serialize,serialize_many
from src.models.entities import Audit,AssessmentVersion
router=APIRouter()
@router.get('/assessments')
def listing(db=Depends(get_db),user=Depends(current_user)):return serialize_many(assessments.listing(db))
@router.post('/assessments',status_code=202)
def create(data:AssessmentInput,db=Depends(get_db),user=Depends(editor)):return serialize(assessments.create(db,data,user.email))
@router.get('/assessments/{id}')
def detail(id:int,db=Depends(get_db),user=Depends(current_user)):return assessments.serialize_detail(db,assessments.get(db,id))
@router.patch('/assessments/{id}/recommendation')
def recommendation(id:int,data:RecommendationInput,db=Depends(get_db),user=Depends(editor)):return assessments.serialize_detail(db,assessments.recommend(db,id,data))
@router.post('/assessments/{id}/approve')
def approve(id:int,db=Depends(get_db),user=Depends(admin)):return assessments.serialize_detail(db,assessments.approve(db,id,user))
@router.post('/assessments/{id}/retry',status_code=202)
def retry(id:int,db=Depends(get_db),user=Depends(editor)):
    item,version=assessments.retry(db,id,user.email);return assessments.serialize_detail(db,item)
@router.get('/assessments/{id}/export')
def export(id:int,db=Depends(get_db),user=Depends(current_user)):
    item=assessments.get(db,id)
    if item.approved:
        version=db.get(AssessmentVersion,item.approved_version_id) if item.approved_version_id else None
    else:
        version=db.get(AssessmentVersion,item.current_version_id) if item.current_version_id else None
    if not version or version.status!='completed':raise HTTPException(409,'没有可导出的完整计算结果')
    if version.stale and not item.approved:raise HTTPException(409,'当前结果已标明失效，请先完成重算')
    payload={'assessment':assessments.serialize_detail(db,item),'exported_version':version.version,
             'exported_version_id':version.id,'export_mode':'approved' if item.approved else 'current'}
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="seal-variance-{id}.json"'})
@router.get('/audit')
def audit(db=Depends(get_db),user=Depends(admin)):return serialize_many(db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100)).all())
