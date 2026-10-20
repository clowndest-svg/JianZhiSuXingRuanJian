"""Run one aggregate Web Push batch; never log endpoints or message contents."""
import json
import sqlite3
import sys
from pathlib import Path

root = Path('/opt/qingsu')
sys.path.insert(0, str(root))
from app_modules.webpush import dispatch

key = root / 'keys/webpush-vapid.pem'
if not key.is_file():
    raise SystemExit('Push key has not been provisioned')
c = sqlite3.connect(root / 'data/qingsu.db', timeout=5)
c.row_factory = sqlite3.Row
c.execute('PRAGMA foreign_keys=ON')
try:
    print(json.dumps(dispatch(c, key)))
finally:
    c.close()
