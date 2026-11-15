from pydantic import BaseModel,Field,field_validator

class LoginInput(BaseModel):
    email:str=Field(max_length=120)
    password:str=Field(max_length=200)
class ProcessInput(BaseModel):
    code:str=Field(min_length=1,max_length=50)
    name:str=Field(min_length=2,max_length=100)
    temperature:float=Field(ge=80,le=250,allow_inf_nan=False)
    dwell:float=Field(gt=0,le=10,allow_inf_nan=False)
    pressure:float=Field(gt=0,le=2,allow_inf_nan=False)
    note:str=Field(default='',max_length=2000)
class SampleInput(BaseModel):
    code:str=Field(min_length=1,max_length=50)
    process_id:int=Field(gt=0)
    lot:str=Field(min_length=1,max_length=60)
    force:float=Field(gt=0,le=200,allow_inf_nan=False)
    flagged:bool=False
    note:str=Field(default='',max_length=1000)
class AssessmentInput(BaseModel):
    title:str=Field(min_length=2,max_length=120)
    process_ids:list[int]=Field(min_length=2,max_length=8)
    lot:str=Field(default='全部',min_length=1,max_length=60)
class RecommendationInput(BaseModel):
    selected_process_id:int=Field(gt=0)
    recommendation:str=Field(min_length=20,max_length=3000)
class CalibrationPointInput(BaseModel):
    measured:float=Field(allow_inf_nan=False)
    standard:float=Field(allow_inf_nan=False)
class CalibrationInput(BaseModel):
    code_start:str=Field(min_length=1,max_length=50)
    code_end:str=Field(min_length=1,max_length=50)
    points:list[CalibrationPointInput]=Field(min_length=2,max_length=20)
    note:str=Field(default='',max_length=1000)
    @field_validator('points')
    @classmethod
    def _monotonic(cls,points):
        measured=[p.measured for p in points]
        standard=[p.standard for p in points]
        if any(b<=a for a,b in zip(measured,measured[1:])):raise ValueError('实测点必须严格递增')
        if any(b<=a for a,b in zip(standard,standard[1:])):raise ValueError('标准点必须严格递增')
        return points
