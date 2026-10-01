import os, sqlite3, tempfile, sys
root = tempfile.mkdtemp(prefix='workerpay_legacy_')
os.environ['APPDATA'] = root
os.environ['WORKERPAY_TEST_MODE']='1'
# app.py computes DATA_DIR at import time, so APPDATA must be set first.
sys.path.insert(0, os.path.dirname(__file__))
from app import WorkerPay

path=os.path.join(root,'WorkerPay','workerpay.db')
os.makedirs(os.path.dirname(path), exist_ok=True)
c=sqlite3.connect(path)
c.executescript('''
CREATE TABLE employees(id INTEGER PRIMARY KEY AUTOINCREMENT, empid TEXT UNIQUE NOT NULL, name TEXT NOT NULL, salary REAL DEFAULT 0, start TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE plots(id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL, plot_no TEXT NOT NULL, daily_rate REAL DEFAULT 0, active INTEGER DEFAULT 1, UNIQUE(employee_id,plot_no), FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE);
CREATE TABLE attendance(id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL, plot_id INTEGER NOT NULL, day TEXT NOT NULL, code TEXT NOT NULL, UNIQUE(employee_id,plot_id,day), FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE, FOREIGN KEY(plot_id) REFERENCES plots(id) ON DELETE CASCADE);
CREATE TABLE rules(code TEXT PRIMARY KEY,label TEXT NOT NULL,mult REAL NOT NULL);
CREATE TABLE payments(id INTEGER PRIMARY KEY AUTOINCREMENT,employee_id INTEGER NOT NULL,month TEXT NOT NULL,amount REAL NOT NULL,paid_on TEXT NOT NULL,FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE);
CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, entity TEXT, entity_id TEXT, details TEXT, prev_hash TEXT, row_hash TEXT);
CREATE TABLE data_quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT, row_id INTEGER, reason TEXT, row_json TEXT, quarantined_at TEXT);
INSERT INTO audit_log(action,entity,entity_id,details,prev_hash,row_hash) VALUES('legacy','system','','{}','','');
INSERT INTO employees(empid,name,salary,start,active) VALUES('10','Legacy Worker',18000,'2026-01-01',1);
INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(1,'1250',600,1);
INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(1,1,'2026-09-01','P');
''')
c.commit(); c.close()
app=WorkerPay()
try:
    cols=[r[1] for r in app.db.execute('PRAGMA table_info(audit_log)').fetchall()]
    assert 'created_at' in cols, cols
    assert app.db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert not app.db.execute('PRAGMA foreign_key_check').fetchall()
    assert app.verify_audit_log() is True
    print('LEGACY_MIGRATION: PASS')
finally:
    app.destroy()
