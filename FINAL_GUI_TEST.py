import os, sys, tempfile, sqlite3, tkinter as tk, time, traceback
from pathlib import Path
os.environ['APPDATA']=tempfile.mkdtemp(prefix='workerpay_final_gui_')
sys.path.insert(0,str(Path(__file__).parent))
from app import WorkerPay, messagebox

app=WorkerPay()
errors=[]

def descendants(widget, cls):
    out=[]
    for c in widget.winfo_children():
        if isinstance(c, cls): out.append(c)
        out.extend(descendants(c, cls))
    return out

def assert_true(cond,msg):
    if not cond: raise AssertionError(msg)

def seed(n=12):
    for i in range(1,n+1):
        cur=app.db.execute('INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,1)',(f'EMP{i:03d}',i,f'Worker {i}','0','2026-09-01'))
        eid=cur.lastrowid
        for j,(plot,rate) in enumerate([(f'12{i:02d}',600+i),(f'13{i:02d}',650+i)]):
            pid=app.db.execute('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',(eid,plot,rate)).lastrowid
            app.db.execute('INSERT INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(pid,'2026-09-01',rate))
            # Day 1–3 exercise all P-unit keys.
            codes=['P','P/2','P+P/2','2P']
            for d,code in enumerate(codes,1):
                app.db.execute('INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?)',(eid,pid,f'2026-09-{d:02d}',code))
    app.db.commit()
seed()

try:
    # Page structure / positions.
    app.dashboard(); app.update_idletasks();
    trees=descendants(app.main, __import__('tkinter').ttk.Treeview)
    assert_true(trees and all(t.winfo_y()==0 for t in trees), 'Dashboard table is not top-positioned.')

    tree=app.employees(); app.update_idletasks();
    assert_true(tree.winfo_y()==0, 'Employees table is not top-positioned.')
    ids=[tree.item(i,'values')[0] for i in tree.get_children()[:12]]
    assert_true(ids[9]=='EMP010', f'EMP010 alignment/order broken: {ids[8:11]}')
    assert_true(str(tree.cget('selectmode'))=='extended','Employee list is not multi-select.')

    # Multi-remove: select two rows and confirm programmatically.
    old_ask=messagebox.askyesno;messagebox.askyesno=lambda *a,**k: True
    items=list(tree.get_children());tree.selection_set(items[0],items[1])
    app.remove_selected(tree)
    remaining=int(app.db.execute('SELECT COUNT(*) FROM employees').fetchone()[0])
    assert_true(remaining==10,f'Multi-remove left {remaining} records instead of 10.')
    messagebox.askyesno=old_ask

    # Add editor: with EMP001..EMP010 still present, next ID must be EMP011.
    app.employee_editor(); app.update_idletasks();
    entries=descendants(app.main, tk.Entry)
    assert_true(entries and entries[0].get()=='EMP013','Employee ID auto-numbering is broken after removing lower IDs.')

    # Attendance: verify the charts render and horizontal scroll regions equal the selected month length.
    eid=int(app.db.execute("SELECT id FROM employees WHERE empid='EMP010'").fetchone()['id'])
    app.open_employee(eid,'2026-09')
    def check_attendance():
        canvases=[]
        for _,c,axis in app._scroll_areas:
            if axis=='x' and isinstance(c,tk.Canvas): canvases.append(c)
        assert_true(len(canvases)==2, f'Expected 2 plot attendance grids, got {len(canvases)}')
        regions=[c.cget('scrollregion') for c in canvases]
        assert_true(all(float(r.split()[2]) >= 30*66 for r in regions), f'Attendance grid width wrong: {regions}')
        # Month switch to October -> 31 days.
        ents=descendants(app.main,tk.Entry); assert_true(ents,'Attendance month input missing')
        month=ents[0];month.delete(0,'end');month.insert(0,'2026-10');app.update();
        app.after(180,check_oct)
    def check_oct():
        canvases=[c for _,c,axis in app._scroll_areas if axis=='x' and isinstance(c,tk.Canvas)]
        regions=[c.cget('scrollregion') for c in canvases]
        assert_true(all(float(r.split()[2]) >= 31*66 for r in regions), f'October attendance grid did not refresh to 31 days: {regions}')
        # Navigate away immediately; stale delayed callbacks must not raise TclError.
        app.salary_filter();app.update_idletasks();app.after(150,finish)
    def finish():
        # Verify salary filter table lives at its top, not below a blank region.
        trees=descendants(app.main,__import__('tkinter').ttk.Treeview)
        assert_true(trees and all(t.winfo_y()==0 for t in trees), 'Salary/Filter table is not top-positioned.')
        print('FINAL_GUI_TEST: PASS')
        app.after(50,app.destroy)
    app.after(150,check_attendance)
except Exception as ex:
    traceback.print_exc(); errors.append(str(ex)); app.after(50,app.destroy)
app.mainloop()
if errors: raise SystemExit(1)
