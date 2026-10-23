"""B07：周报的三个维度与少量可执行反馈。只读，不改任何写入路径。

口径（方案点名，别再改回去）：
- 完整记录日 = 当天餐食、体重、训练都有记录；缺记既不算完成，也不折成 0 摄入/0 消耗。
- 体重趋势至少两个不同日期；单点只回"数据不足"，不画线、不下结论。
- 反馈固定 2~3 条，每条带一个能回到库里的依据数字；不写确定性减重承诺。
- 缺数据时只说"先看得到的是哪几天"，不拿窗口天数当分母算完成率。
"""
from datetime import date, timedelta

from fastapi import Depends, HTTPException

from app_modules.metrics import compute_metrics

BAND_KCAL = 200


def _current_metrics(c, uid):
    row = c.execute('SELECT * FROM profiles WHERE user_id=?', (uid,)).fetchone()
    if not row:
        return None
    profile = dict(row)
    if any(profile.get(key) is None for key in ('age', 'height', 'weight_jin', 'target_weight_jin')):
        return None
    return compute_metrics(profile)


def _mmdd(stamp):
    return stamp[5:]


def build_review(c, uid, days, end, base):
    """在 companion.period_summary 的结果上补三个维度和可执行反馈。

    base 里的 rows 已经按天给出 recorded_kcal/workout_minutes，
    这里只补 weight_jin、deficit_kcal 与三个布尔维度，避免前端再拼一套口径。
    """
    start = end - timedelta(days=days - 1)
    lo, hi = start.isoformat(), end.isoformat()
    bounds = (uid, lo, hi)
    metrics = _current_metrics(c, uid)

    food = {r['log_date']: {'entries': int(r['entries'] or 0), 'cal': int(r['cal'] or 0)}
            for r in c.execute('SELECT log_date,COUNT(*) AS entries,COALESCE(SUM(cal),0) AS cal '
                               'FROM food_logs WHERE user_id=? AND log_date BETWEEN ? AND ? '
                               'GROUP BY log_date', bounds)}
    workout = {r['log_date']: {'minutes': int(r['minutes'] or 0), 'burned': float(r['burned'] or 0)}
               for r in c.execute('SELECT log_date,COALESCE(SUM(duration_minutes),0) AS minutes,'
                                  'COALESCE(SUM(cal_burned),0) AS burned FROM workout_logs '
                                  'WHERE user_id=? AND log_date BETWEEN ? AND ? '
                                  'GROUP BY log_date', bounds)}
    weights = {}
    for r in c.execute('SELECT log_date,weight_jin FROM weight_logs WHERE user_id=? '
                       'AND log_date BETWEEN ? AND ? ORDER BY log_date,id', bounds):
        # 同一天称多次取当天最后一条；趋势仍按"不同日期"数
        weights[r['log_date']] = float(r['weight_jin'])

    meal_days = set(food)
    training_days = set(workout)
    weight_days = set(weights)
    full_days = meal_days & training_days & weight_days
    record_days = sorted(meal_days | training_days | weight_days)
    weight_only_days = {ds for ds in weight_days if ds not in meal_days and ds not in training_days}

    # 缺口只对"当天有餐食记录"的日子算；没记的那天返回 None，不造 0。
    deficits = {}
    if metrics:
        for ds, row in food.items():
            burned = (workout.get(ds) or {}).get('burned', 0.0)
            deficits[ds] = round(metrics['tdee'] + burned - row['cal'])
    in_band = [ds for ds, value in deficits.items()
               if abs(value - metrics['deficit']) <= BAND_KCAL]

    rows = []
    for source in base['rows']:
        row = dict(source)
        ds = row['date']
        row['full_record'] = ds in full_days
        row['training_day'] = ds in training_days
        row['weigh_in'] = ds in weight_days
        row['weight_jin'] = weights.get(ds)
        row['deficit_kcal'] = deficits.get(ds)
        rows.append(row)

    ordered = sorted(weights)
    if len(ordered) >= 2:
        change = round(weights[ordered[-1]] - weights[ordered[0]], 2)
        trend = {'status': 'ok', 'distinct_days': len(ordered), 'change_jin': change,
                 'first_date': ordered[0], 'last_date': ordered[-1],
                 'text': '首末两次称重相差 %s 斤（%s → %s）；这是两次记录的差，补记或换秤都会影响它。'
                         % (change, ordered[0], ordered[-1])}
    else:
        trend = {'status': 'insufficient', 'distinct_days': len(ordered), 'change_jin': None,
                 'first_date': ordered[0] if ordered else None,
                 'last_date': ordered[-1] if ordered else None,
                 'text': '体重只有 %d 个日期的记录，数据不足，先不下结论；补到两个不同日期再看。'
                         % len(ordered)}

    def item(kind, text, metric, label, value):
        return {'kind': kind, 'text': text,
                'basis': {'metric': metric, 'label': label, 'value': value, 'unit': '天'}}

    if full_days:
        coverage = ('这周有 %d 天把餐食、体重、训练都记了；训练记录共 %d 天，只记体重的有 %d 天。'
                    '建议从记全的这 %d 天里挑一天，照同样份量吃一顿并记下来。'
                    % (len(full_days), len(training_days), len(weight_only_days), len(full_days)))
    else:
        coverage = ('这周还没有一天把餐食、体重、训练都记全；建议从今天开始，'
                    '三餐、体重、训练各记一笔。')
    feedback = [item('coverage', coverage, 'full_record_days',
                     '完整记录日（餐食、体重、训练都记了）', len(full_days))]

    if not metrics:
        gap = ('当前档案缺少计算热量预算所需的年龄、身高或体重，先补全档案，'
               '再对比每天的缺口。')
    elif not deficits:
        gap = ('这周没有能算缺口的餐食记录；先补一天的三餐，再对比目标缺口 ±%d kcal。'
               % BAND_KCAL)
    elif in_band:
        gap = ('这周有 %d 天能算缺口，其中 %d 天落在目标缺口 ±%d kcal 内；'
               '建议照落在区间的那一天重复一次晚餐份量。'
               % (len(deficits), len(in_band), BAND_KCAL))
    else:
        gap = ('这周有 %d 天能算缺口，没有一天落在目标缺口 ±%d kcal 内；'
               '建议先把其中一天的晚餐记全，再对比这个区间。'
               % (len(deficits), BAND_KCAL))
    feedback.append(item('deficit', gap, 'deficit_sample_days',
                         '能算缺口的餐食记录天数', len(deficits)))

    if trend['status'] == 'ok':
        scale = ('这周 %d 个日期有称重，首末相差 %s 斤；'
                 '建议下周固定同一天早晨再称一次，只看两周的走向。'
                 % (trend['distinct_days'], trend['change_jin']))
    else:
        scale = ('这周只有 %d 个日期有称重，数据不足；'
                 '下周挑两个不同日期的早晨各称一次。' % trend['distinct_days'])
    feedback.append(item('weight', scale, 'weight_days', '有称重的日期数', len(weight_days)))

    if not record_days:
        coverage_note = '这周记录不足，还没有任何一天有记录；先从今天的一餐一笔开始。'
    elif len(record_days) < days:
        listed = '、'.join(_mmdd(ds) for ds in record_days[:10])
        if len(record_days) > 10:
            listed += ' 等 %d 天' % len(record_days)
        coverage_note = ('这周记录不足，先看得到的是这 %d 天：%s；'
                         '其中餐食、体重、训练都记了的是 %d 天。'
                         % (len(record_days), listed or '无', len(full_days)))
    elif len(full_days) < days:
        coverage_note = ('这周 %d 天都有记录，其中餐食、体重、训练都记了的是 %d 天。'
                         % (days, len(full_days)))
    else:
        coverage_note = ''

    return {
        'full_record_days': len(full_days),
        'training_days': len(training_days),
        'training_minutes': sum(row['minutes'] for row in workout.values()),
        'meal_days': len(meal_days),
        'weight_days': len(weight_days),
        'weight_trend': trend,
        'deficit_sample_days': len(deficits),
        'deficit_in_band_days': len(in_band),
        'average_deficit_kcal': (round(sum(deficits.values()) / len(deficits))
                                 if deficits else None),
        'target_deficit_kcal': metrics['deficit'] if metrics else None,
        'band_kcal': BAND_KCAL,
        'record_days': record_days,
        'coverage_note': coverage_note,
        'feedback': feedback,
        'rows': rows,
        # 覆盖 base 里按"确认完整章"算的两个字段，避免同一个响应出现两套口径
        'calorie_sample_days': len(meal_days),
        'average_recorded_kcal': (round(sum(row['cal'] for row in food.values()) / len(food))
                                  if food else None),
    }


def install(app, env):
    from app_modules.companion import period_summary

    get_db = env['get_db']
    current = env['get_current_user']

    @app.get('/api/weekly/review')
    def weekly_review(days: int = 7, end: date | None = None, user: dict = Depends(current)):
        if days not in (7, 30):
            raise HTTPException(400, '请选择最近7天或30天')
        last = end or date.today()
        if last > date.today():
            raise HTTPException(400, '不能汇总未来日期')
        c = get_db()
        try:
            base = period_summary(c, user['id'], days, last)
            return {'code': 0, **base, **build_review(c, user['id'], days, last, base)}
        finally:
            c.close()
