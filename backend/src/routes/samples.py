from fastapi import APIRouter,Depends
from src.config.database import get_db
from src.utils.security import current_user,editor
from src.schemas.business import SampleInput
from src.services import samples
from src.controllers.business import serialize,serialize_many
router=APIRouter()
@router.get('/samples')
def listing(db=Depends(get_db),user=Depends(current_user)):return serialize_many(samples.listing(db))
@router.post('/samples',status_code=201)
def create(data:SampleInput,db=Depends(get_db),user=Depends(editor)):return serialize(samples.save(db,data))
@router.put('/samples/{id}')
def update(id:int,data:SampleInput,db=Depends(get_db),user=Depends(editor)):return serialize(samples.save(db,data,id))
