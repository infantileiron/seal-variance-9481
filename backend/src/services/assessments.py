import json
import os
from datetime import datetime, timezone

import redis
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.entities import Assessment, AssessmentVersion, Process, Sample
from src.services import calibration

queue = redis.Redis.from_url(os.environ['REDIS_URL'])
QUEUE_KEY = 'seal:assessments'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def listing(db):
    return db.scalars(select(Assessment).order_by(Assessment.id.desc())).all()


def get(db, id):
    item = db.get(Assessment, id)
    if not item:
        raise HTTPException(404, '评议任务不存在')
    return item


def snapshot_for(db, ids, lot):
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '不能重复选择同一工艺')
    groups = []
    for id in ids:
        process = db.get(Process, id)
        if not process:
            raise HTTPException(404, '工艺方案不存在')
        q = select(Sample).where(Sample.process_id == id).order_by(Sample.code)
        if lot != '全部':
            q = q.where(Sample.lot == lot)
        samples = db.scalars(q).all()
        groups.append({
            'id': id, 'code': process.code, 'name': process.name,
            'temperature': process.temperature, 'dwell': process.dwell,
            'pressure': process.pressure,
            'samples': [{'code': s.code, 'force': s.force, 'flagged': s.flagged, 'lot': s.lot} for s in samples],
        })
    return {'lot': lot, 'groups': groups}


def versions_for(db, assessment_id):
    return db.scalars(select(AssessmentVersion).where(
        AssessmentVersion.assessment_id == assessment_id
    ).order_by(AssessmentVersion.version)).all()


def version_summary(version):
    if not version:
        return None
    return {
        'id': version.id,
        'version': version.version,
        'status': version.status,
        'trigger': version.trigger,
        'published': version.published,
        'stale': version.stale,
        'superseded': version.superseded,
        'error': version.error,
        'calibration_fingerprint': version.calibration_fingerprint,
        'calibration_rules': version.calibration_snapshot or [],
        'quarantine_count': len(version.quarantine or []),
        'created_at': version.created_at,
        'started_at': version.started_at,
        'completed_at': version.completed_at,
        'requested_by': version.requested_by,
    }


def serialize_version(version, include_result=False):
    payload = version_summary(version)
    if version and include_result:
        payload['result'] = version.result
        payload['quarantine'] = version.quarantine or []
    return payload


def serialize_detail(db, item):
    versions = versions_for(db, item.id)
    by_id = {v.id: v for v in versions}
    base = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    base['current_version'] = version_summary(by_id.get(item.current_version_id))
    base['approved_version'] = version_summary(by_id.get(item.approved_version_id))
    base['candidate_version'] = version_summary(by_id.get(item.candidate_version_id))
    base['versions'] = [serialize_version(v, include_result=True) for v in versions]
    current = by_id.get(item.current_version_id)
    if current and current.result:
        base['quarantine'] = current.result.get('quarantine', [])
        base['calibration_used'] = current.result.get('calibration', {})
        base['samples'] = current.result.get('samples', [])
    else:
        base['quarantine'] = []
        base['calibration_used'] = {}
        base['samples'] = []
    return base


def _check_pending_limit(db):
    pending = db.scalars(select(AssessmentVersion).where(
        AssessmentVersion.status.in_(['queued', 'running']),
        AssessmentVersion.superseded.is_(False),
    )).all()
    if len(pending) >= 10:
        raise HTTPException(429, '最多10个待执行任务，请稍后重试')


def _enqueue(version):
    queue.lpush(QUEUE_KEY, json.dumps({'assessment_id': version.assessment_id, 'version_id': version.id}))


def _new_version(db, assessment, rules, trigger, actor):
    number = max([v.version for v in versions_for(db, assessment.id)], default=0) + 1
    expected = calibration.fingerprint(rules)
    version = AssessmentVersion(
        assessment_id=assessment.id,
        version=number,
        status='queued',
        calibration_fingerprint=expected,
        calibration_snapshot=rules,
        trigger=trigger,
        requested_by=actor or '',
        created_at=now_iso(),
        published=False,
        stale=False,
        superseded=False,
    )
    try:
        # Savepoint so a concurrent duplicate only rolls back this insert, not
        # the calibration rule written in the same transaction.
        with db.begin_nested():
            db.add(version)
    except IntegrityError:
        # A concurrent request already created the version for this
        # calibration fingerprint; reuse it instead of duplicating results.
        existing = db.scalar(select(AssessmentVersion).where(
            AssessmentVersion.assessment_id == assessment.id,
            AssessmentVersion.calibration_fingerprint == expected,
        ))
        if not existing:
            raise
        return existing
    return version


def create(db, data, actor=''):
    _check_pending_limit(db)
    snapshot = snapshot_for(db, data.process_ids, data.lot)
    rules, _ = calibration.basis_for_snapshot(db, snapshot)
    item = Assessment(
        title=data.title, lot=data.lot, snapshot=snapshot, status='queued',
        created_at=now_iso(), stale=False,
    )
    db.add(item)
    db.flush()
    version = _new_version(db, item, rules, 'created', actor)
    item.candidate_version_id = version.id
    db.commit()
    db.refresh(item)
    db.refresh(version)
    try:
        _enqueue(version)
    except redis.RedisError:
        fail(db, item, version, '队列不可用，请恢复后在评议页重试或新建评议', [])
        db.commit()
        raise HTTPException(503, item.error)
    return item


def ensure_version(db, assessment, trigger, actor=''):
    """Return a queued version for the latest active calibration.

    Retrying the same calibration revision reuses the existing row, so a
    repeated queue message or an operator retry never creates duplicate
    result versions.  A newer revision creates exactly one new version.
    """
    codes = [s.get('code') for g in assessment.snapshot.get('groups', []) for s in g.get('samples', [])]
    rules = calibration.rules_for_codes(db, codes)
    expected = calibration.fingerprint(rules)
    versions = versions_for(db, assessment.id)
    existing = next((v for v in versions if v.calibration_fingerprint == expected), None)
    if existing:
        if existing.status == 'completed' and existing.published:
            return existing
        if existing.status in ('queued', 'running'):
            return existing
        # failed or superseded row for the same revision: reuse it as a retry
        existing.status = 'queued'
        existing.error = ''
        existing.quarantine = None
        existing.result = None
        existing.stale = False
        existing.superseded = False
        existing.published = False
        existing.trigger = trigger
        existing.requested_by = actor or existing.requested_by
        existing.created_at = now_iso()
        existing.started_at = ''
        existing.completed_at = ''
        assessment.candidate_version_id = existing.id
        db.flush()
        return existing
    version = _new_version(db, assessment, rules, trigger, actor)
    for old in versions:
        if old.id != version.id and old.status == 'queued':
            old.status = 'superseded'
            old.superseded = True
            old.stale = True
            old.error = '已有更新的校准修订排队，本版本不再执行'
    assessment.candidate_version_id = version.id
    db.flush()
    return version


def _validate_result(result):
    if not isinstance(result, dict):
        return False, '统计结果缺失'
    required = ['n', 'groups', 'ss_between', 'ss_within', 'ss_total', 'df_between', 'df_within',
                'f', 'p', 'eta_squared', 'quarantine', 'quarantine_count', 'samples', 'calibration']
    missing = [key for key in required if key not in result]
    if missing:
        return False, '统计结果缺少字段：' + '、'.join(missing)
    if not isinstance(result['quarantine'], list):
        return False, '隔离清单格式不完整'
    if len(result['samples']) != result['n']:
        return False, '参与统计的样本数与结果不一致'
    if len(result['quarantine']) != result['quarantine_count']:
        return False, '隔离清单条数与计数不一致'
    converted_total = len(result['samples']) + len(result['quarantine'])
    if converted_total != result['calibration'].get('original_count'):
        return False, '原始样本、换算样本与隔离样本数量不能守恒'
    if any(s.get('converted') is None for s in result['samples']):
        return False, '存在未完成换算的样本'
    return True, ''


def publish(db, assessment, version, result):
    """Atomically replace the current result only with a complete version.

    Previous published versions are retained as superseded evidence.  A signed
    assessment is never replaced here.
    """
    if assessment.approved:
        raise ValueError('评议已签核，不能替换结果')
    ok, reason = _validate_result(result)
    if not ok:
        raise ValueError(reason)
    version.result = result
    version.quarantine = result['quarantine']
    version.status = 'completed'
    version.completed_at = now_iso()
    version.published = True
    version.stale = False
    version.superseded = False
    previous = db.get(AssessmentVersion, assessment.current_version_id) if assessment.current_version_id else None
    if previous and previous.id != version.id:
        previous.superseded = True
        previous.published = False
    assessment.result = result
    assessment.current_version_id = version.id
    assessment.candidate_version_id = None
    assessment.status = 'completed'
    assessment.error = ''
    assessment.stale = False
    db.flush()
    return version


def fail(db, assessment, version, message, quarantine=None):
    """Keep the old published result but mark it invalid when recompute fails."""
    if assessment.approved and assessment.current_version_id != version.id:
        # Signed reviews are never altered by a recalculation failure.
        version.status = 'failed'
        version.error = message
        version.quarantine = quarantine or []
        version.completed_at = now_iso()
        version.published = False
        if assessment.candidate_version_id == version.id:
            assessment.candidate_version_id = None
        db.flush()
        return version
    version.status = 'failed'
    version.error = message
    version.quarantine = quarantine or []
    version.completed_at = now_iso()
    version.published = False
    if assessment.current_version_id and assessment.current_version_id != version.id:
        current = db.get(AssessmentVersion, assessment.current_version_id)
        assessment.stale = True
        assessment.status = 'completed'
        assessment.error = f'校准重算失败：{message}；当前结果基于旧校准，已标明失效，请重试'
        if current:
            current.stale = True
    else:
        assessment.status = 'failed'
        assessment.stale = False
        assessment.error = message
    if assessment.candidate_version_id == version.id:
        assessment.candidate_version_id = None
    db.flush()
    return version


def retry(db, id, actor=''):
    item = get(db, id)
    if item.approved:
        raise HTTPException(409, '已签核评议冻结保留，请新建评议后再计算')
    candidate = db.get(AssessmentVersion, item.candidate_version_id) if item.candidate_version_id else None
    if candidate and candidate.status in ('queued', 'running'):
        return item, candidate
    version = ensure_version(db, item, 'retry', actor)
    if version.status == 'completed' and version.published and not item.stale:
        raise HTTPException(409, '当前结果已是该校准下的最新发布版本，无需重试；如需重新计算请登记新的校准修订或新建评议')
    if item.current_version_id is None and version.status == 'queued':
        item.status = 'queued'
    db.commit()
    db.refresh(version)
    if version.status != 'queued':
        return item, version
    try:
        _enqueue(version)
    except redis.RedisError:
        db.refresh(version)
        db.refresh(item)
        fail(db, item, version, '队列不可用，请恢复后重试')
        db.commit()
        raise HTTPException(503, '队列不可用，请恢复后重试')
    return item, version


def _impact_scope(db, rule):
    scope = []
    for item in db.scalars(select(Assessment).order_by(Assessment.id)).all():
        codes = [s.get('code', '') for g in (item.snapshot or {}).get('groups', []) for s in g.get('samples', [])]
        matched = [code for code in codes if calibration.in_range(code, rule.code_start, rule.code_end)]
        if not matched:
            continue
        scope.append({
            'assessment_id': item.id,
            'title': item.title,
            'matched_samples': len(matched),
            'approved': bool(item.approved),
            'status': item.status,
            'action': 'skip_signed' if item.approved else 'recompute',
            'reason': '已签核版本冻结保留，不自动重算；如需更新请新建评议' if item.approved
            else '提交快照包含该编号范围试条，按新校准重算',
        })
    return scope


def register_calibration(db, data, actor=''):
    """Register a calibration revision and recompute only affected assessments."""
    total_assessments = len(db.scalars(select(Assessment)).all())
    rule = calibration.create_rule(db, data, actor)
    scope = _impact_scope(db, rule)
    rule.impact_scope = scope
    impacted = []
    for entry in scope:
        if entry['action'] != 'recompute':
            continue
        item = db.get(Assessment, entry['assessment_id'])
        if not item:
            continue
        version = ensure_version(db, item, 'calibration_update', actor)
        if item.current_version_id is None and item.status in ('completed', 'failed'):
            item.status = 'queued'
            item.error = ''
        impacted.append({'assessment_id': item.id, 'version_id': version.id,
                         'version': version.version, 'status': version.status})
    db.commit()
    db.refresh(rule)
    for entry in impacted:
        version = db.get(AssessmentVersion, entry['version_id'])
        if version and version.status == 'queued':
            try:
                _enqueue(version)
            except redis.RedisError:
                item = db.get(Assessment, version.assessment_id)
                if item:
                    fail(db, item, version, '队列不可用，校准已登记，请在评议页重试重算')
                    db.commit()
    summary = {
        'total_assessments': total_assessments,
        'affected': len(scope),
        'recomputed': len(impacted),
        'skipped_signed': sum(1 for entry in scope if entry['action'] == 'skip_signed'),
        'unaffected': total_assessments - len(scope),
    }
    return rule, scope, impacted, summary


def recommend(db, id, data):
    item = get(db, id)
    if item.status != 'completed':
        raise HTTPException(409, '计算完成后才能起草工艺评议')
    if item.approved:
        raise HTTPException(409, '已签核评议冻结，请新建评议留痕')
    if item.stale:
        raise HTTPException(409, '当前结果已因校准修订或重算失败标明失效，请重算并确认后再起草')
    candidate = db.get(AssessmentVersion, item.candidate_version_id) if item.candidate_version_id else None
    if candidate and candidate.status in ('queued', 'running'):
        raise HTTPException(409, '校准重算进行中，请等待新版本发布后再起草')
    if data.selected_process_id not in [g['id'] for g in item.snapshot['groups']]:
        raise HTTPException(422, '只能推荐本次比较内的工艺')
    item.selected_process_id = data.selected_process_id
    item.recommendation = data.recommendation
    item.recommendation_version_id = item.current_version_id
    db.commit()
    return item


def approve(db, id, user):
    item = get(db, id)
    if item.approved:
        raise HTTPException(409, '评议已签核')
    if item.status != 'completed' or not item.recommendation or not item.selected_process_id:
        raise HTTPException(409, '请先完成计算并填写推荐方案与业务理由')
    if item.recommendation_version_id != item.current_version_id:
        raise HTTPException(409, '推荐理由基于旧版本结果，当前结果已重算；请核对新结论并重新保存推荐后再签核')
    if item.stale:
        raise HTTPException(409, '当前结果已标明失效，不能签核；请先完成校准重算')
    candidate = db.get(AssessmentVersion, item.candidate_version_id) if item.candidate_version_id else None
    if candidate and candidate.status in ('queued', 'running'):
        raise HTTPException(409, '校准重算尚未完成，不能签核')
    current = db.get(AssessmentVersion, item.current_version_id) if item.current_version_id else None
    if not current or current.status != 'completed' or not current.published:
        raise HTTPException(409, '当前版本尚未形成完整结果，不能签核')
    if current.stale or current.superseded:
        raise HTTPException(409, '当前版本已失效，不能签核')
    item.approved = True
    item.approved_by = user.email
    item.approved_version_id = current.id
    db.commit()
    return item
