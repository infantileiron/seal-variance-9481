import json
import hashlib
import math

from scipy.stats import f

from src.services.calibration import CalculationError, convert, fingerprint


def _checksum(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def anova(snapshot, calibration_rules=None):
    """One-way ANOVA over calibrated forces.

    ``snapshot`` is the frozen submission snapshot (original measurements).
    ``calibration_rules`` is the frozen active rule set captured with the
    assessment version; original values stay in the result for every sample.
    Samples whose original force falls outside a matching calibration segment
    are quarantined (never extrapolated, never silently dropped) and listed
    separately.  Statistics are only returned when the quarantine list and
    per-sample conversion evidence are both complete.
    """
    groups = snapshot['groups']
    if len(groups) < 2:
        raise CalculationError('至少选择两种工艺方案')
    rules = calibration_rules or []

    converted_groups = []
    quarantined = []
    missing = []
    for group in groups:
        converted_samples = []
        for sample in group['samples']:
            try:
                record = convert(sample['force'], sample['code'], rules)
            except CalculationError as error:
                missing.append({'code': sample['code'], 'reason': str(error)})
                raise CalculationError(str(error), quarantine=quarantined, evidence=missing) from error
            if record['converted'] is None:
                quarantined.append({
                    'sample_code': sample['code'],
                    'process_code': group['code'],
                    'process_name': group['name'],
                    'lot': sample.get('lot', snapshot.get('lot', '')),
                    'original': record['original'],
                    'rule_id': record['rule_id'],
                    'rule_revision': record['rule_revision'],
                    'rule_range': record['rule_range'],
                    'bounds': record.get('bounds'),
                    'reason': record['explanation'],
                    'flagged': bool(sample.get('flagged')),
                })
                continue
            converted_samples.append({
                'code': sample['code'],
                'lot': sample.get('lot', ''),
                'flagged': bool(sample.get('flagged')),
                'original': record['original'],
                'converted': record['converted'],
                'method': record['method'],
                'rule_id': record['rule_id'],
                'rule_revision': record['rule_revision'],
                'rule_range': record['rule_range'],
                'segment': record['segment'],
                'slope': record['slope'],
                'intercept': record['intercept'],
                'explanation': record['explanation'],
            })
        if len(converted_samples) < 2:
            reason = f"{group['code']} 校准换算后不足2条可用样本（现有 {len(converted_samples)} 条）"
            raise CalculationError(reason, quarantine=quarantined, evidence=converted_groups + [{
                'code': group['code'], 'name': group['name'], 'kept': [s['code'] for s in converted_samples],
            }])
        converted_groups.append({'id': group['id'], 'code': group['code'], 'name': group['name'],
                                 'temperature': group.get('temperature'), 'dwell': group.get('dwell'),
                                 'pressure': group.get('pressure'), 'samples': converted_samples})

    n = sum(len(g['samples']) for g in converted_groups)
    k = len(converted_groups)
    grand = sum(s['converted'] for g in converted_groups for s in g['samples']) / n
    summaries = []
    between = 0.0
    within = 0.0
    for g in converted_groups:
        values = [s['converted'] for s in g['samples']]
        mean = sum(values) / len(values)
        ss = sum((v - mean) ** 2 for v in values)
        between += len(values) * (mean - grand) ** 2
        within += ss
        summaries.append({
            'id': g['id'], 'code': g['code'], 'name': g['name'], 'n': len(values),
            'mean': mean, 'sd': math.sqrt(ss / (len(values) - 1)),
            'min': min(values), 'max': max(values),
            'flagged': sum(s['flagged'] for s in g['samples']),
            'quarantined': sum(1 for q in quarantined if q['process_code'] == g['code']),
        })
    if within <= 1e-12:
        raise CalculationError('组内方差为零，F检验不成立；补充有实际测量差异的独立样本',
                               quarantine=quarantined)
    df_between = k - 1
    df_within = n - k
    ms_between = between / df_between
    ms_within = within / df_within
    statistic = ms_between / ms_within
    p = float(f.sf(statistic, df_between, df_within))
    return {
        'n': n,
        'groups': summaries,
        'grand_mean': grand,
        'ss_between': between,
        'ss_within': within,
        'ss_total': between + within,
        'df_between': df_between,
        'df_within': df_within,
        'ms_between': ms_between,
        'ms_within': ms_within,
        'f': statistic,
        'p': p,
        'eta_squared': between / (between + within),
        'significant': p < .05,
        'flagged': sum(g['flagged'] for g in summaries),
        'quarantine': quarantined,
        'quarantine_count': len(quarantined),
        'samples': [
            {
                'process_id': g['id'], 'process_code': g['code'], 'process_name': g['name'],
                'code': s['code'], 'lot': s['lot'], 'flagged': s['flagged'],
                'original': s['original'], 'converted': s['converted'],
                'method': s['method'], 'rule_id': s['rule_id'], 'rule_revision': s['rule_revision'],
                'rule_range': s['rule_range'], 'segment': s['segment'],
                'slope': s['slope'], 'intercept': s['intercept'], 'explanation': s['explanation'],
            }
            for g in converted_groups for s in g['samples']
        ],
        'calibration': {
            'fingerprint': fingerprint(rules),
            'rules': [{
                'id': r['id'], 'code_start': r['code_start'], 'code_end': r['code_end'],
                'revision': r['revision'], 'points': r['points'],
            } for r in rules],
            'converted_count': n,
            'original_count': n + len(quarantined),
            'quarantined_count': len(quarantined),
        },
        'checksum': _checksum({'snapshot': snapshot, 'calibration': rules}),
        'method': ('单因素独立样本 ANOVA；α=0.05；试条按编号范围分段线性校准，原始实测值保留；'
                   '校准范围外样本隔离且不参与计算；未登记校准的试条按原值参与。'
                   '要求独立、组内近似正态与方差齐性。显著F不说明哪一组更优，也不替代工艺合格判定。'),
    }
