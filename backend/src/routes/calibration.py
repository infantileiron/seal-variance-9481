from fastapi import APIRouter,Depends
from sqlalchemy import select
from src.config.database import get_db
from src.utils.security import current_user,editor
from src.schemas.business import CalibrationInput
from src.services import calibration
from src.services import assessments as assessment_service
from src.controllers.business import serialize_many
from src.models.entities import CalibrationRule
router=APIRouter()
@router.get('/calibration')
def listing(db=Depends(get_db),user=Depends(current_user)):
    rules=db.scalars(select(CalibrationRule).order_by(CalibrationRule.code_start,CalibrationRule.revision.desc())).all()
    return serialize_many(rules)
@router.get('/calibration/preview')
def preview(db=Depends(get_db),user=Depends(current_user)):return calibration.preview(db)
@router.post('/calibration',status_code=201)
def create(data:CalibrationInput,db=Depends(get_db),user=Depends(editor)):
    rule,scope,impacted,summary=assessment_service.register_calibration(db,data,user.email)
    payload=calibration.rule_payload(rule)
    payload['impact_scope']=scope
    payload['impacted']=impacted
    payload['impact_summary']=summary
    return payload
