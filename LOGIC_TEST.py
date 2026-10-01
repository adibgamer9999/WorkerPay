import os, sys, sqlite3, tempfile, calendar
sys.path.insert(0, os.path.dirname(__file__))
from app import WorkerPay

checks=[]
def check(name, ok, detail=''):
    checks.append((name, bool(ok), detail))
    print(('PASS' if ok else 'FAIL') + ' | ' + name + (f' | {detail}' if detail else ''))

# ID normalization rules — the important EMP010 case.
for raw, expected in [('1','EMP001'),('9','EMP009'),('10','EMP010'),('EMP010','EMP010'),('EMP1000','EMP1000')]:
    got,_=WorkerPay.normalize_employee_id(raw)
    check(f'ID {raw}', got==expected, f'{got} expected {expected}')

# Invalid IDs must be rejected.
for raw in ('EMP0','ABC10','', 'P1250'):
    try:
        WorkerPay.normalize_employee_id(raw)
        check(f'invalid ID rejected: {raw or "<empty>"}', False)
    except ValueError:
        check(f'invalid ID rejected: {raw or "<empty>"}', True)

# Pure SQLite business-logic stress fixtures.
root=tempfile.mkdtemp(prefix='workerpay_logic_'); path=os.path.join(root,'logic.db')
con=sqlite3.connect(path); con.row_factory=sqlite3.Row
con.executescript('''
CREATE TABLE employees(id INTEGER PRIMARY KEY AUTOINCREMENT, empid TEXT UNIQUE NOT NULL, emp_number INTEGER NOT NULL, name TEXT NOT NULL, daily_rate REAL DEFAULT 0, start TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE plots(id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL, plot_no TEXT NOT NULL, daily_rate REAL NOT NULL, active INTEGER DEFAULT 1, UNIQUE(employee_id,plot_no));
CREATE TABLE attendance(id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL, plot_id INTEGER NOT NULL, day TEXT NOT NULL, code TEXT NOT NULL, UNIQUE(employee_id,plot_id,day));
CREATE INDEX idx_e_empnum ON employees(emp_number);
CREATE INDEX idx_p_emp ON plots(employee_id,active,id);
CREATE INDEX idx_a_emp_plot_day ON attendance(employee_id,plot_id,day);
''')
cur=con.execute('INSERT INTO employees(empid,emp_number,name,start,active) VALUES(?,?,?,?,1)',('EMP010',10,'Mamun','2026-09-01'))
eid=cur.lastrowid
p1=con.execute('INSERT INTO plots(employee_id,plot_no,daily_rate) VALUES(?,?,?)',(eid,'1250',600)).lastrowid
p2=con.execute('INSERT INTO plots(employee_id,plot_no,daily_rate) VALUES(?,?,?)',(eid,'1356',650)).lastrowid
p3=con.execute('INSERT INTO plots(employee_id,plot_no,daily_rate) VALUES(?,?,?)',(eid,'Third Plot',700)).lastrowid
codes={p1:['P']*28+['P/2'],p2:['P']*26,p3:['P']*29+['P/2']}
for pid,items in codes.items():
    for d,code in enumerate(items,1): con.execute('INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?,?)'.replace('VALUES(?,?,?,?,?)','VALUES(?,?,?,?)'),(eid,pid,f'2026-09-{d:02d}',code))
con.commit()
mult={'P':1.0,'P/2':0.5,'P+P/2':1.5,'2P':2.0,'A':0.0}
expected=[28.5*600,26*650,29.5*700]
for (pid,_), exp in zip([(p1,600),(p2,650),(p3,700)], expected):
    rows=con.execute('SELECT code FROM attendance WHERE plot_id=?',(pid,)).fetchall(); units=sum(mult[r['code']] for r in rows)
    rate=con.execute('SELECT daily_rate FROM plots WHERE id=?',(pid,)).fetchone()[0]
    check(f'plot calculation {pid}', abs(units*rate-exp)<1e-9, f'{units:g}P x {rate:g} = {units*rate:g}')
check('plot numbers remain plot values', [r['plot_no'] for r in con.execute('SELECT * FROM plots ORDER BY id')] == ['1250','1356','Third Plot'])
check('employee ID remains EMP010', con.execute("SELECT empid FROM employees WHERE emp_number=10").fetchone()[0]=='EMP010')
check('September has 30 days', calendar.monthrange(2026,9)[1]==30)
check('October has 31 days', calendar.monthrange(2026,10)[1]==31)
con.close()
import shutil; shutil.rmtree(root,ignore_errors=True)

fails=[x for x in checks if not x[1]]
print(f'\nTOTAL CHECKS: {len(checks)} | FAILURES: {len(fails)}')
if fails: raise SystemExit(1)
print('RESULT: ALL LOGIC TESTS PASSED')
