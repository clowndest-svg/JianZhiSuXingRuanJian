"""Move FK-orphaned legacy rows to a recoverable operator-only archive."""
import sqlite3,json,os,argparse
from pathlib import Path
from datetime import datetime

parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
db=Path('/opt/qingsu/data/qingsu.db');c=sqlite3.connect(db);c.row_factory=sqlite3.Row
rows=c.execute('PRAGMA foreign_key_check').fetchall()
print(json.dumps({'violations':len(rows),'apply':args.apply}))
if not args.apply:c.close();raise SystemExit(0)
allowed={'profiles','food_logs','weight_logs','workout_logs','water_logs','body_cycles','takeout_events','checklist_state','ai_memory','cheers'}
if any(r[0] not in allowed or r[2]!='users' for r in rows):raise SystemExit('Unexpected relationship; no rows changed')
stamp=datetime.now().strftime('%Y%m%d-%H%M%S');target=Path('/opt/qingsu/backups')/('orphan-archive-'+stamp+'.db')
archive=sqlite3.connect(target);archive.execute('CREATE TABLE recovered(source_table TEXT,row_id INTEGER,row_json TEXT,PRIMARY KEY(source_table,row_id))')
c.execute('BEGIN IMMEDIATE')
try:
    for table,rowid,parent,fk in rows:
        data=c.execute(f'SELECT * FROM {table} WHERE rowid=?',(rowid,)).fetchone()
        if data:archive.execute('INSERT INTO recovered VALUES (?,?,?)',(table,rowid,json.dumps(dict(data),ensure_ascii=False)))
    archive.commit();target.chmod(0o600)
    for table,rowid,parent,fk in rows:c.execute(f'DELETE FROM {table} WHERE rowid=?',(rowid,))
    if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Remaining FK violations')
    c.commit();print(json.dumps({'quarantined':len(rows),'archive':str(target),'remaining_violations':0}))
except Exception:c.rollback();raise
finally:c.close();archive.close()
