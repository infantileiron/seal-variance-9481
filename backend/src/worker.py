import json
import os
import time
import traceback
from pathlib import Path

from sqlalchemy import select

from src.config.database import SessionLocal
from src.models.entities import Assessment, AssessmentVersion
from src.services import assessments as service
from src.services.calibration import CalculationError, fingerprint, rules_for_codes
from src.services.statistics import anova
from src.config.upgrade import upgrade

ARTIFACT_DIR = Path(os.getenv('ARTIFACT_DIR', '/app/artifacts'))


def _expected_rules(db, assessment):
    codes = [s.get('code') for g in (assessment.snapshot or {}).get('groups', []) for s in g.get('samples', [])]
    return rules_for_codes(db, codes)


def _expected_fingerprint(db, assessment):
    return fingerprint(_expected_rules(db, assessment))


def _queued_version(db):
    # Skip versions that have already been made obsolete (newer calibration
    # revision queued) so a stale message never computes the wrong rule set.
    return db.scalar(
        select(AssessmentVersion)
        .where(AssessmentVersion.status == 'queued', AssessmentVersion.superseded.is_(False))
        .order_by(AssessmentVersion.id)
        .with_for_update(skip_locked=True)
    )


def run_one():
    with SessionLocal() as db:
        version = _queued_version(db)
        if not version:
            return False
        task = db.get(Assessment, version.assessment_id)
        if not task:
            version.status = 'failed'
            version.error = '评议任务不存在'
            db.commit()
            return True
        version.status = 'running'
        version.started_at = service.now_iso()
        db.commit()

        result = None
        error = None
        quarantine = []
        rules = version.calibration_snapshot or []
        try:
            result = anova(task.snapshot, rules)
            quarantine = result.get('quarantine', [])
        except CalculationError as exc:
            error = str(exc)
            quarantine = exc.quarantine
        except Exception as exc:  # unexpected: still record a complete failure
            error = f'计算异常：{exc}'
            traceback.print_exc()
        db.refresh(version)
        db.refresh(task)

        latest = _expected_fingerprint(db, task)
        if version.calibration_fingerprint != latest:
            # Calibration changed while this version was running: never let an
            # outdated computation replace the latest conclusion.
            version.result = result
            version.quarantine = quarantine
            version.status = 'superseded' if result else 'failed'
            current_ids = {r['id'] for r in _expected_rules(db, task)}
            used_ids = {r['id'] for r in version.calibration_snapshot or []}
            if current_ids != used_ids:
                why = '校准规则在计算期间增补或撤销；本版结果未发布，仅作对照，不得作为最新结论'
            else:
                why = '同一编号范围校准点在计算期间修订；本版结果未发布，仅作对照，不得作为最新结论'
            version.error = why if result else (error or why)
            version.stale = True
            version.superseded = True
            version.published = False
            version.completed_at = service.now_iso()
            if task.candidate_version_id == version.id:
                replacement = db.scalar(select(AssessmentVersion).where(
                    AssessmentVersion.assessment_id == task.id,
                    AssessmentVersion.status.in_(['queued', 'running']),
                ).order_by(AssessmentVersion.id))
                task.candidate_version_id = replacement.id if replacement else None
            db.commit()
            print(f"assessment={task.id} version={version.version} superseded calibration changed", flush=True)
            return True

        if result is not None:
            try:
                service.publish(db, task, version, result)
                db.commit()
                try:
                    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
                    payload = {
                        'assessment_id': task.id,
                        'version': version.version,
                        'calibration': version.calibration_snapshot,
                        'result': result,
                    }
                    (ARTIFACT_DIR / f'{task.id}-v{version.version}.json').write_text(
                        json.dumps(payload, ensure_ascii=False)
                    )
                except OSError:
                    # Artifact volume is auxiliary; the database version is the
                    # authoritative result and has already been published.
                    traceback.print_exc()
            except ValueError as exc:
                service.fail(db, task, version, f'结果校验失败：{exc}', quarantine)
                db.commit()
        else:
            service.fail(db, task, version, error or '计算失败', quarantine)
            db.commit()
        print(f'assessment={task.id} version={version.version} status={version.status}', flush=True)
        return True


def main():
    upgrade()
    with SessionLocal() as db:
        for task in db.scalars(select(AssessmentVersion).where(AssessmentVersion.status == 'running')).all():
            task.status = 'queued'
            task.started_at = ''
        db.commit()
    print('seal variance worker started', flush=True)
    while True:
        Path('/tmp/worker-heartbeat').touch()
        try:
            # Drain any queued version directly; the Redis list only wakes the
            # worker and duplicate messages are harmless because status gates work.
            while run_one():
                pass
            service.queue.brpop(service.QUEUE_KEY, timeout=2)
        except Exception:
            traceback.print_exc()
            time.sleep(2)


if __name__ == '__main__':
    main()
