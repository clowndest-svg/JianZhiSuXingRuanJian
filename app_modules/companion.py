"""Private period summaries and opt-in small-group activity goals."""
import hashlib
import secrets
from datetime import date, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS shared_goals (
        id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
        title TEXT NOT NULL, kind TEXT NOT NULL, target INTEGER NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, invite_hash TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS shared_goal_members (
        goal_id INTEGER NOT NULL REFERENCES shared_goals(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(goal_id,user_id));
    CREATE INDEX IF NOT EXISTS idx_goal_member_user ON shared_goal_members(user_id,goal_id);
    ''')
    c.commit()


def period_summary(c, uid, days, end):
    start = end - timedelta(days=days - 1)
    bounds = (uid, start.isoformat(), end.isoformat())
    weights = c.execute('SELECT log_date,weight_jin FROM weight_logs WHERE user_id=? AND log_date BETWEEN ? AND ? ORDER BY log_date,id', bounds).fetchall()
    food = {r['log_date']: dict(r) for r in c.execute('SELECT log_date,COUNT(*) AS entries,SUM(cal) AS cal FROM food_logs WHERE user_id=? AND log_date BETWEEN ? AND ? GROUP BY log_date', bounds)}
    workout = {r['log_date']: dict(r) for r in c.execute('SELECT log_date,SUM(duration_minutes) AS minutes FROM workout_logs WHERE user_id=? AND log_date BETWEEN ? AND ? GROUP BY log_date', bounds)}
    complete = {r[0] for r in c.execute('SELECT log_date FROM daily_reviews WHERE user_id=? AND log_date BETWEEN ? AND ? AND complete=1', bounds)}
    rows = []
    for offset in range(days):
        ds = (start + timedelta(days=offset)).isoformat()
        rows.append({'date': ds, 'complete': ds in complete,
                     'meal_entries': food.get(ds, {}).get('entries', 0),
                     'recorded_kcal': food[ds]['cal'] if ds in food else None,
                     'workout_minutes': workout[ds]['minutes'] if ds in workout else None})
    vals = [r['cal'] for ds, r in food.items() if ds in complete]
    # Two entries on one day do not establish a period trend.
    distinct_days = len({r['log_date'] for r in weights})
    return {'start': start.isoformat(), 'end': end.isoformat(), 'days': days,
            'complete_days': len(complete), 'workout_days': len(workout),
            'weight_days': distinct_days,
            'weight_change_jin': round(weights[-1]['weight_jin'] - weights[0]['weight_jin'], 2) if distinct_days >= 2 else None,
            'average_recorded_kcal': round(sum(vals) / len(vals)) if vals else None,
            'calorie_sample_days': len(vals), 'rows': rows}


def install(app, env):
    get_db = env['get_db']
    current = env['get_current_user']
    c = get_db()
    try:
        migrate(c)
    finally:
        c.close()

    @app.get('/api/summary')
    def summary(days: int = 7, end: date | None = None, user: dict = Depends(current)):
        if days not in (7, 30):
            raise HTTPException(400, '请选择最近7天或30天')
        last = end or date.today()
        if last > date.today():
            raise HTTPException(400, '不能汇总未来日期')
        c = get_db()
        try:
            return {'code': 0, **period_summary(c, user['id'], days, last)}
        finally:
            c.close()

    class GoalReq(BaseModel):
        title: str = Field(min_length=1, max_length=30)
        kind: str = 'workout'
        target: int = Field(default=3, ge=1, le=30)
        days: int = 7

    class JoinReq(BaseModel):
        code: str = Field(min_length=16, max_length=80)

    @app.post('/api/goals')
    def create(req: GoalReq, user: dict = Depends(current)):
        if req.kind not in ('workout', 'complete') or req.days not in (7, 30) or req.target > req.days or not req.title.strip():
            raise HTTPException(400, '目标名称、类型或天数无效')
        invite = secrets.token_urlsafe(18)
        today = date.today()
        c = get_db()
        try:
            c.execute('BEGIN IMMEDIATE')
            n = c.execute('SELECT COUNT(*) FROM shared_goals g JOIN shared_goal_members m ON g.id=m.goal_id WHERE m.user_id=? AND g.end_date>=?', (user['id'], today.isoformat())).fetchone()[0]
            if n >= 5:
                raise HTTPException(400, '每人最多同时参加5个目标')
            cur = c.execute('INSERT INTO shared_goals(owner_id,title,kind,target,start_date,end_date,invite_hash) VALUES (?,?,?,?,?,?,?)',
                            (user['id'], req.title.strip(), req.kind, req.target, today.isoformat(), (today + timedelta(days=req.days - 1)).isoformat(), hashlib.sha256(invite.encode()).hexdigest()))
            c.execute('INSERT INTO shared_goal_members VALUES (?,?)', (cur.lastrowid, user['id']))
            c.commit()
            return {'code': 0, 'id': cur.lastrowid, 'invite': invite}
        finally:
            c.close()

    @app.post('/api/goals/join')
    def join(req: JoinReq, user: dict = Depends(current)):
        c = get_db()
        try:
            c.execute('BEGIN IMMEDIATE')
            g = c.execute('SELECT * FROM shared_goals WHERE invite_hash=? AND end_date>=?', (hashlib.sha256(req.code.strip().encode()).hexdigest(), date.today().isoformat())).fetchone()
            if not g:
                raise HTTPException(404, '邀请码不存在或已过期')
            if c.execute('SELECT 1 FROM shared_goal_members WHERE goal_id=? AND user_id=?', (g['id'], user['id'])).fetchone():
                return {'code': 0, 'id': g['id']}
            if c.execute('SELECT COUNT(*) FROM shared_goal_members WHERE goal_id=?', (g['id'],)).fetchone()[0] >= 8:
                raise HTTPException(400, '目标已达到8人上限')
            if c.execute('SELECT COUNT(*) FROM shared_goal_members m JOIN shared_goals g ON g.id=m.goal_id WHERE m.user_id=? AND g.end_date>=?', (user['id'], date.today().isoformat())).fetchone()[0] >= 5:
                raise HTTPException(400, '每人最多同时参加5个目标')
            c.execute('INSERT INTO shared_goal_members VALUES (?,?)', (g['id'], user['id']))
            c.commit()
            return {'code': 0, 'id': g['id']}
        finally:
            c.close()

    @app.get('/api/goals')
    def goals(user: dict = Depends(current)):
        c = get_db()
        try:
            rows = c.execute('SELECT g.* FROM shared_goals g JOIN shared_goal_members m ON g.id=m.goal_id WHERE m.user_id=? ORDER BY g.id DESC LIMIT 30', (user['id'],)).fetchall()
            out = []
            for g in rows:
                members = []
                for m in c.execute('SELECT u.id,u.nickname FROM users u JOIN shared_goal_members m ON u.id=m.user_id WHERE m.goal_id=? ORDER BY u.id', (g['id'],)).fetchall():
                    table, clause = ('workout_logs', '') if g['kind'] == 'workout' else ('daily_reviews', ' AND complete=1')
                    n = c.execute(f'SELECT COUNT(DISTINCT log_date) FROM {table} WHERE user_id=? AND log_date BETWEEN ? AND ?' + clause, (m['id'], g['start_date'], g['end_date'])).fetchone()[0]
                    members.append({'nickname': m['nickname'], 'me': m['id'] == user['id'], 'days': n})
                out.append({k: g[k] for k in ('id', 'title', 'kind', 'target', 'start_date', 'end_date') } | {'owner': g['owner_id'] == user['id'], 'members': members})
            return {'code': 0, 'items': out}
        finally:
            c.close()

    @app.post('/api/goals/{gid}/leave')
    def leave(gid: int, user: dict = Depends(current)):
        c = get_db()
        try:
            g = c.execute('SELECT owner_id FROM shared_goals g JOIN shared_goal_members m ON m.goal_id=g.id WHERE g.id=? AND m.user_id=?', (gid, user['id'])).fetchone()
            if not g:
                raise HTTPException(404, '目标不存在')
            if g['owner_id'] == user['id']:
                c.execute('DELETE FROM shared_goal_members WHERE goal_id=?', (gid,))
                c.execute('DELETE FROM shared_goals WHERE id=?', (gid,))
            else:
                c.execute('DELETE FROM shared_goal_members WHERE goal_id=? AND user_id=?', (gid, user['id']))
            c.commit()
            return {'code': 0}
        finally:
            c.close()
