"""持久化长任务表：HTTP 请求只负责起任务，浏览器关掉也不会丢结果。

放在业务库同一个文件里，是为了让每日备份把任务历史一起带走；
每个方法各开各的连接（WAL + busy_timeout），worker 与后台进程抢同一行才安全。
"""
import json,os,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

TERMINAL=('done','failed','cancelled')
RUNNABLE=('pending','interrupted')
# 部分索引的 WHERE 里不能带绑定参数，只能把这几个固定状态名写成字面量
TERMINAL_SQL="('"+"','".join(TERMINAL)+"')"
RUNNABLE_SQL="('"+"','".join(RUNNABLE)+"')"

def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def _cutoff(seconds):
    return datetime.fromtimestamp(time.time()-seconds,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

class LongTaskBusy(RuntimeError):
    """并发上限已满，这一轮不启动新任务。"""

class LongTasks:
    def __init__(self,path=None):
        if path is None:
            path=os.environ.get('QINGSU_LONG_TASKS_DB') or str(Path(os.environ.get('QINGSU_DB','/opt/qingsu/data/qingsu.db')).parent/'long_tasks.db')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._connect().close()

    def _connect(self):
        conn=sqlite3.connect(self.path,timeout=5,check_same_thread=False)
        conn.row_factory=sqlite3.Row
        try:
            # busy_timeout 必须先于 journal_mode：两个进程同时冷启动时，后到的 PRAGMA
            # 会在拿不到锁时直接报 database is locked，而不是等锁（和业务库同一个坑）。
            conn.execute('PRAGMA busy_timeout=5000')
            for attempt in range(20):
                try:
                    conn.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as error:
                    if 'locked' not in str(error) or attempt==19:raise
                    time.sleep(0.05)
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute("""CREATE TABLE IF NOT EXISTS ops_long_tasks(
                id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,owner TEXT,
                args_json TEXT,result_json TEXT,attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,updated_at TEXT,heartbeat_at TEXT,dedup_key TEXT)""")
            # 同一 dedup_key 在未终态期间全局唯一：重复点击只有一份任务，靠数据库而不是靠内存标记
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ops_long_tasks_active_dedup '
                         "ON ops_long_tasks(kind,dedup_key) WHERE status NOT IN %s AND dedup_key IS NOT NULL"%TERMINAL_SQL)
            conn.commit()
        except Exception:
            conn.close();raise
        return conn

    def _row(self,conn,task_id):
        row=conn.execute('SELECT * FROM ops_long_tasks WHERE id=?',(task_id,)).fetchone()
        return dict(row) if row else None

    def _run(self,body):
        """在一个 BEGIN IMMEDIATE 事务里跑 body，异常一律回滚后原样抛出。"""
        conn=self._connect();conn.execute('BEGIN IMMEDIATE')
        try:
            outcome=body(conn)
            conn.execute('COMMIT')
            return outcome
        except Exception:
            try:conn.execute('ROLLBACK')
            except sqlite3.OperationalError:pass
            raise
        finally:
            conn.close()

    def enqueue(self,kind,args=None,owner=None,dedup_key=None,max_active=None):
        """起一个任务；同 dedup_key 还没进终态就把已有那份还回去。

        max_active 满时抛 LongTaskBusy：调用方（后台接口）决定排队还是回"正在忙"，
        而不是在这里再悄悄起一份把服务器压垮。

        dedup 必须先于 max_active 判：否则"同一个人连点两下"会先撞上并发上限拿到 409，
        而复用那一份本来就不会增加并发——上限该管的是"多开了几份不同的活"，不是"同一个人手抖"。
        """
        created=_now();task_id=uuid4().hex
        def body(conn):
            if dedup_key:
                existing=conn.execute("SELECT id FROM ops_long_tasks WHERE kind=? AND dedup_key=? AND status NOT IN %s"%TERMINAL_SQL,
                                      (kind,dedup_key)).fetchone()
                if existing:return existing['id']
            if max_active is not None:
                active=conn.execute("SELECT COUNT(*) FROM ops_long_tasks WHERE kind=? AND status NOT IN %s"%TERMINAL_SQL,
                                    (kind,)).fetchone()[0]
                if active>=max_active:raise LongTaskBusy('%s 已有 %s 个未终态任务，达到上限'%(kind,active))
            conn.execute('INSERT INTO ops_long_tasks(id,kind,status,owner,args_json,created_at,updated_at,dedup_key) '
                         "VALUES(?,?,'pending',?,?,?,?,?)",(task_id,kind,owner,
                         json.dumps(args if args is not None else {}),created,created,dedup_key))
            return task_id
        return self.status(self._run(body))

    def claim(self,task_id,owner):
        """原子领取：只有把这一行从可领取改成 running 的那个进程拿到 True。"""
        moment=_now()
        return self._run(lambda conn: conn.execute(
            'UPDATE ops_long_tasks SET status=\'running\',owner=?,heartbeat_at=?,updated_at=?,attempts=attempts+1 '
            'WHERE id=? AND status IN %s'%RUNNABLE_SQL,(owner,moment,moment,task_id)).rowcount)==1

    def heartbeat(self,task_id,owner=None):
        moment=_now();sql="UPDATE ops_long_tasks SET heartbeat_at=? WHERE id=? AND status='running'";params=[moment,task_id]
        if owner is not None:sql+=' AND owner=?';params.append(owner)
        return self._run(lambda conn: conn.execute(sql,params).rowcount)==1

    def finish(self,task_id,result=None,owner=None):
        return self._close(task_id,'done',{'result':result},owner)

    def fail(self,task_id,error=None,owner=None,retryable=False):
        # retryable 失败退回 interrupted：下一轮同 dedup_key 的 enqueue 会拿到这一份重跑，attempts 继续累加
        return self._close(task_id,'interrupted' if retryable else 'failed',
                           {'error':str(error) if error is not None else None},owner)

    def cancel(self,task_id,owner=None):
        return self._close(task_id,'cancelled',{'result':'调用方取消'},owner)

    def _close(self,task_id,status,payload,owner):
        moment=_now();sql='UPDATE ops_long_tasks SET status=?,result_json=?,updated_at=? WHERE id=?'
        params=[status,json.dumps(payload,ensure_ascii=False),moment,task_id]
        if owner is not None:sql+=' AND owner=?';params.append(owner)
        return self.status(task_id) if self._run(lambda conn: conn.execute(sql,params).rowcount==1) else None

    def status(self,task_id):
        conn=self._connect()
        try:task=self._row(conn,task_id)
        finally:conn.close()
        if task is None:return None
        for column in ('args_json','result_json'):
            task[column]=json.loads(task[column]) if task[column] else None
        return task

    def reap_stale(self,older_than_seconds,kind=None):
        """心跳超时的 running 标成 interrupted，可重试；不猜它是死了还是在忙。"""
        cutoff=_cutoff(older_than_seconds)
        sql="SELECT id FROM ops_long_tasks WHERE status='running' AND COALESCE(heartbeat_at,updated_at,created_at)<?"
        params=[cutoff]
        if kind is not None:sql+=' AND kind=?';params.append(kind)
        def body(conn):
            found=[row['id'] for row in conn.execute(sql,params)]
            for task_id in found:
                conn.execute("UPDATE ops_long_tasks SET status='interrupted',updated_at=?,result_json=? WHERE id=? AND status='running'",
                             (_now(),json.dumps({'error':'心跳超时，判为中断'},ensure_ascii=False),task_id))
            return found
        return self._run(body)
