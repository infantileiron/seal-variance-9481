"""Tensile-tester calibration rules and piecewise-linear conversion.

Original measured forces are never rewritten.  A calibration rule covers an
inclusive range of test-strip codes and stores measured/standard force points.
At calculation time the active rule set is frozen into the assessment version,
so later rule revisions can be detected and old calculations cannot silently
become the latest conclusion.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from fastapi import HTTPException

from src.models.entities import CalibrationRule, Sample

_TOKEN = re.compile(r'\d+|\D+')


class CalculationError(Exception):
    """Raised when a frozen snapshot cannot produce complete statistics."""

    def __init__(self, message, quarantine=None, evidence=None):
        super().__init__(message)
        self.quarantine = quarantine or []
        self.evidence = evidence or []


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def code_key(code):
    """Natural ordering so HC-S1-010 sits between HC-S1-002 and HC-S1-035."""
    text = str(code or '').strip().upper()
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in _TOKEN.findall(text))


def in_range(code, code_start, code_end):
    key = code_key(code)
    return code_key(code_start) <= key <= code_key(code_end)


def ranges_overlap(a_start, a_end, b_start, b_end):
    return code_key(a_start) <= code_key(b_end) and code_key(b_start) <= code_key(a_end)


def normalize_points(points):
    """Validate and return calibration points as plain JSON-safe dicts.

    Both axes must be strictly increasing: this keeps the piecewise-linear
    mapping single-valued and prevents a non-monotonic calibration from being
    silently applied to a physical measurement.
    """
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        raise HTTPException(422, '校准点至少需要2个实测值与标准值对应点')
    normalized = []
    for point in points:
        if isinstance(point, dict):
            measured = point.get('measured')
            standard = point.get('standard')
        else:
            measured = getattr(point, 'measured', None)
            standard = getattr(point, 'standard', None)
        try:
            measured = float(measured)
            standard = float(standard)
        except (TypeError, ValueError):
            raise HTTPException(422, '校准点的实测拉力与标准拉力必须为数字')
        if not (0 < measured <= 500) or not (0 < standard <= 500):
            raise HTTPException(422, '校准点拉力须在 0–500 N 之间，且不能为 NaN/Infinity')
        normalized.append({'measured': measured, 'standard': standard})
    for previous, current in zip(normalized, normalized[1:]):
        if current['measured'] <= previous['measured']:
            raise HTTPException(422, '校准点的实测拉力必须严格递增，不能重复或倒序')
        if current['standard'] <= previous['standard']:
            raise HTTPException(422, '校准点的标准拉力必须严格递增，避免换算方向歧义')
    return normalized


def _rule_dict(rule):
    return {
        'id': rule.id,
        'code_start': rule.code_start,
        'code_end': rule.code_end,
        'revision': rule.revision,
        'points': rule.points,
        'note': rule.note or '',
        'created_by': rule.created_by or '',
        'created_at': rule.created_at or '',
    }


def active_rules(db):
    return db.scalars(select(CalibrationRule).where(CalibrationRule.active.is_(True)).order_by(CalibrationRule.id)).all()


def rules_for_codes(db, codes):
    """Return active rules that cover at least one code, sorted deterministically."""
    codes = [c for c in codes if c]
    matched = []
    for rule in active_rules(db):
        if any(in_range(code, rule.code_start, rule.code_end) for code in codes):
            matched.append(_rule_dict(rule))
    return matched


def fingerprint(rules):
    payload = [
        {
            'id': r['id'],
            'code_start': r['code_start'],
            'code_end': r['code_end'],
            'revision': r['revision'],
            'points': r['points'],
        }
        for r in rules
    ]
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def basis_for_snapshot(db, snapshot):
    codes = [s.get('code') for g in snapshot.get('groups', []) for s in g.get('samples', [])]
    rules = rules_for_codes(db, codes)
    return rules, fingerprint(rules)


def _matches(rules, code):
    hits = [r for r in rules or [] if in_range(code, r['code_start'], r['code_end'])]
    if len(hits) > 1:
        ids = '、'.join(str(r['id']) for r in hits)
        raise CalculationError(f'试条 {code} 同时匹配多条有效校准规则（规则 {ids}），拒绝换算；请先消除编号范围重叠')
    return hits[0] if hits else None


def convert(force, code, rules):
    """Convert one measured force using the frozen rule set.

    Returns a self-describing record so the UI and export can show the original
    value, the rule/revision, the exact segment and the resulting value.
    """
    original = float(force)
    rule = _matches(rules, code)
    if rule is None:
        return {
            'original': original,
            'converted': original,
            'method': 'original',
            'rule_id': None,
            'rule_revision': None,
            'rule_range': None,
            'segment': None,
            'slope': None,
            'intercept': None,
            'explanation': f'试条 {code} 未登记有效校准规则，按原始实测值 {original:g} N 计算',
        }
    points = sorted(rule['points'], key=lambda p: p['measured'])
    xs = [p['measured'] for p in points]
    range_text = f"{rule['code_start']}–{rule['code_end']}"
    if original < xs[0] or original > xs[-1]:
        side = '低于下限' if original < xs[0] else '高于上限'
        explanation = (
            f"实测 {original:g} N {side}；规则 R{rule['id']}（{range_text} 第{rule['revision']}版）"
            f"校准段为 [{xs[0]:g}, {xs[-1]:g}] N，禁止外推。样本已隔离，不纳入统计。"
        )
        return {
            'original': original,
            'converted': None,
            'method': 'quarantine',
            'rule_id': rule['id'],
            'rule_revision': rule['revision'],
            'rule_range': range_text,
            'segment': None,
            'slope': None,
            'intercept': None,
            'bounds': [xs[0], xs[-1]],
            'explanation': explanation,
        }
    segment_index = len(points) - 2
    for index, (left, right) in enumerate(zip(points, points[1:])):
        if left['measured'] <= original <= right['measured']:
            segment_index = index
            break
    left, right = points[segment_index], points[segment_index + 1]
    slope = (right['standard'] - left['standard']) / (right['measured'] - left['measured'])
    converted = left['standard'] + (original - left['measured']) * slope
    return {
        'original': original,
        'converted': converted,
        'method': 'linear',
        'rule_id': rule['id'],
        'rule_revision': rule['revision'],
        'rule_range': range_text,
        'segment': {
            'index': segment_index + 1,
            'x0': left['measured'],
            'y0': left['standard'],
            'x1': right['measured'],
            'y1': right['standard'],
        },
        'slope': slope,
        'intercept': left['standard'] - left['measured'] * slope,
        'explanation': (
            f"按规则 R{rule['id']}（{range_text} 第{rule['revision']}版）第{segment_index + 1}段 "
            f"[{left['measured']:g}, {right['measured']:g}] N 做线性换算："
            f"y = {left['standard']:g} + (x − {left['measured']:g}) × {slope:.6g}"
        ),
    }


def create_rule(db, data, actor):
    """Create a new immutable revision for an inclusive code range.

    Existing revisions of the same range are deactivated but retained as
    conversion evidence.  Overlapping active ranges are rejected because two
    rules for one strip would make the conversion ambiguous.
    """
    start = data.code_start.strip()
    end = data.code_end.strip()
    if not start or not end:
        raise HTTPException(422, '试条编号范围不能为空')
    if code_key(start) > code_key(end):
        raise HTTPException(422, '试条编号范围起点必须小于等于终点')
    points = normalize_points(data.points)
    existing = db.scalars(select(CalibrationRule).where(
        CalibrationRule.code_start == start,
        CalibrationRule.code_end == end,
    )).all()
    for rule in active_rules(db):
        if rule.code_start == start and rule.code_end == end:
            continue
        if ranges_overlap(start, end, rule.code_start, rule.code_end):
            raise HTTPException(
                409,
                f'编号范围 {start}–{end} 与有效规则 R{rule.id}（{rule.code_start}–{rule.code_end}）重叠；请先登记覆盖旧范围的新修订',
            )
    for sample in db.scalars(select(Sample)).all():
        if not in_range(sample.code, start, end):
            continue
        for rule in active_rules(db):
            if rule.code_start == start and rule.code_end == end:
                continue
            if in_range(sample.code, rule.code_start, rule.code_end):
                raise HTTPException(
                    409,
                    f'样本 {sample.code} 会同时落入新范围与有效规则 R{rule.id}（{rule.code_start}–{rule.code_end}）；换算将产生歧义，请先修订该规则',
                )
    revision = max([r.revision for r in existing], default=0) + 1
    for rule in existing:
        rule.active = False
    created = CalibrationRule(
        code_start=start,
        code_end=end,
        revision=revision,
        points=points,
        note=data.note or '',
        active=True,
        created_by=actor or '',
        created_at=now_iso(),
        impact_scope=[],
    )
    db.add(created)
    db.flush()
    return created


def preview_sample(sample, rules):
    record = convert(sample.force, sample.code, rules)
    return {
        'sample_id': sample.id,
        'code': sample.code,
        'process_id': sample.process_id,
        'lot': sample.lot,
        'flagged': sample.flagged,
        'original': sample.force,
        **{k: v for k, v in record.items() if k != 'original'},
    }


def preview(db):
    samples = db.scalars(select(Sample).order_by(Sample.code)).all()
    rules = rules_for_codes(db, [s.code for s in samples])
    rows = []
    for sample in samples:
        try:
            rows.append(preview_sample(sample, rules))
        except CalculationError as error:
            rows.append({
                'sample_id': sample.id,
                'code': sample.code,
                'process_id': sample.process_id,
                'lot': sample.lot,
                'flagged': sample.flagged,
                'original': sample.force,
                'converted': None,
                'method': 'error',
                'explanation': str(error),
            })
    return {'rules': rules, 'fingerprint': fingerprint(rules), 'rows': rows}


def rule_payload(rule):
    payload = _rule_dict(rule)
    payload['active'] = bool(rule.active)
    payload['impact_scope'] = list(rule.impact_scope or [])
    return payload
