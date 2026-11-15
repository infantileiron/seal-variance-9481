import time,traceback,json
from pathlib import Path
from sqlalchemy import select
from src.config.database import SessionLocal
from src.models.entities import Assessment
from src.services.assessments import queue
from src.services.statistics import anova
with SessionLocal() as db:
    for task in db.scalars(select(Assessment).where(Assessment.status=='running')).all():task.status='queued'
    db.commit()
print('seal variance worker started',flush=True)
while True:
    Path('/tmp/worker-heartbeat').touch()
    try:
        queue.brpop('seal:assessments',timeout=2)
        with SessionLocal() as db:
            task=db.scalar(select(Assessment).where(Assessment.status=='queued').order_by(Assessment.id).with_for_update(skip_locked=True))
            if not task:continue
            task.status='running';db.commit()
            try:
                task.result=anova(task.snapshot);task.status='completed'
                Path('/app/artifacts/'+str(task.id)+'.json').write_text(json.dumps(task.result,ensure_ascii=False))
            except Exception as e:task.error=str(e);task.status='failed'
            db.commit();print(f'assessment={task.id} status={task.status}',flush=True)
    except Exception:traceback.print_exc();time.sleep(2)
