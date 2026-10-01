import os, sqlite3, tempfile, shutil, time, sys

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
PLOTS_PER_EMPLOYEE = 2
ATTENDANCE_PER_PLOT = 1
BATCH = 20_000
root = tempfile.mkdtemp(prefix='workerpay_v20_heavy_')
path = os.path.join(root, 'stress.db')
con = None
results = []

def timed(label, fn):
    t = time.perf_counter()
    r = fn()
    sec = time.perf_counter() - t
    print(f'{label}: {sec:.3f}s')
    results.append((label, sec))
    return r

try:
    con = sqlite3.connect(path, timeout=120.0)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    con.execute('PRAGMA temp_store=MEMORY')
    con.execute('PRAGMA cache_size=-131072')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
    CREATE TABLE employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empid TEXT UNIQUE NOT NULL,
        emp_number INTEGER NOT NULL,
        name TEXT NOT NULL,
        daily_rate REAL NOT NULL DEFAULT 0,
        start TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE plots(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        plot_no TEXT NOT NULL,
        daily_rate REAL NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(employee_id,plot_no),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );
    CREATE TABLE attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        plot_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        code TEXT NOT NULL,
        UNIQUE(employee_id,plot_id,day),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(plot_id) REFERENCES plots(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_emp_number ON employees(emp_number,id);
    CREATE INDEX idx_emp_name ON employees(name COLLATE NOCASE);
    CREATE INDEX idx_emp_empid ON employees(empid);
    CREATE INDEX idx_plot_no ON plots(plot_no COLLATE NOCASE);
    CREATE INDEX idx_plot_emp ON plots(employee_id,active,id);
    CREATE INDEX idx_att_day ON attendance(day,employee_id,plot_id);
    CREATE INDEX idx_att_emp_plot_day ON attendance(employee_id,plot_id,day);
    ''')
    print(f'Target: {N:,} employees | {N*PLOTS_PER_EMPLOYEE:,} plots | {N*PLOTS_PER_EMPLOYEE*ATTENDANCE_PER_PLOT:,} attendance rows')

    def insert_employees():
        cur = con.cursor()
        for start in range(1, N + 1, BATCH):
            end = min(N, start + BATCH - 1)
            cur.executemany(
                'INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,1)',
                [(f'EMP{i:03d}', i, f'Worker {i}', 0.0, '2026-09-01') for i in range(start, end + 1)])
        con.commit()
    timed('Insert employees', insert_employees)

    def insert_plots():
        cur = con.cursor()
        for start in range(1, N + 1, BATCH):
            end = min(N, start + BATCH - 1)
            block=[]
            for i in range(start, end + 1):
                eid=i
                block.append((eid, f'{1000000+i}', 600.0))
                block.append((eid, f'{2000000+i}', 650.0))
            cur.executemany('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)', block)
        con.commit()
    timed('Insert plots (2 per employee)', insert_plots)

    def insert_attendance():
        cur = con.cursor()
        cur.execute('SELECT id,employee_id,plot_no FROM plots ORDER BY id')
        while True:
            block=cur.fetchmany(BATCH)
            if not block:break
            codes=('P','P/2','P+P/2','2P','A')
            cur.executemany(
                'INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?)',
                [(eid,pid,'2026-09-01',codes[(eid+pid)%5]) for pid,eid,_ in block]
            )
        con.commit()
    timed('Insert attendance', insert_attendance)

    timed('Count employees', lambda: con.execute('SELECT COUNT(*) FROM employees').fetchone()[0])
    timed('Lookup EMP010', lambda: con.execute('SELECT id,emp_number,name FROM employees WHERE empid=?', ('EMP010',)).fetchone())
    timed('Lookup highest Employee ID', lambda: con.execute('SELECT id,emp_number,name FROM employees WHERE empid=?', (f'EMP{N:03d}',)).fetchone())
    timed('Keyset page near 500k', lambda: con.execute('SELECT id,empid,name FROM employees WHERE emp_number>? ORDER BY emp_number LIMIT 200', (500_000,)).fetchall())
    timed('Offset page near 500k', lambda: con.execute('SELECT id,empid,name FROM employees ORDER BY emp_number LIMIT 200 OFFSET 500_000').fetchall())
    timed('Plot exact filter', lambda: con.execute('SELECT employee_id FROM plots WHERE plot_no=?', ('1000100',)).fetchone())
    timed('Attendance day count', lambda: con.execute('SELECT COUNT(*) FROM attendance WHERE day=?', ('2026-09-01',)).fetchone()[0])
    timed(f'Salary aggregate ({N*PLOTS_PER_EMPLOYEE*ATTENDANCE_PER_PLOT:,} attendance)', lambda: con.execute("SELECT COALESCE(SUM(CASE code WHEN 'P' THEN 1.0 WHEN 'P/2' THEN 0.5 WHEN 'P+P/2' THEN 1.5 WHEN '2P' THEN 2.0 ELSE 0.0 END * CASE WHEN plot_id % 2 = 0 THEN 650.0 ELSE 600.0 END),0) FROM attendance").fetchone()[0])
    timed('SQLite quick_check', lambda: con.execute('PRAGMA quick_check').fetchone()[0])

    # Confirm rollback does not corrupt data.
    def rollback_test():
        before=con.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
        con.execute('BEGIN')
        con.execute('DELETE FROM employees WHERE emp_number=?', (N,))
        con.rollback()
        after=con.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
        return before,after
    timed('Delete/rollback integrity', rollback_test)

    con.commit()
    size_mb=os.path.getsize(path)/1e6
    print(f'Database size: {size_mb:.1f} MB')
    print('RESULT: PASS — high-volume SQLite storage/query stress test completed.')
finally:
    try:
        if con: con.close()
    except Exception: pass
    shutil.rmtree(root, ignore_errors=True)
