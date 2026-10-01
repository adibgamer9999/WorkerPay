import os, tempfile, sys, tkinter as tk, time, traceback
os.environ['APPDATA']=tempfile.mkdtemp(prefix='workerpay_scroll_')
sys.path.insert(0, os.path.dirname(__file__))
from app import WorkerPay
app=WorkerPay(); failures=[]
try:
    # Seed one employee with several plots to exercise the nested attendance charts.
    cur=app.db.execute("INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,1)",("EMP010",10,"Scroll Test","0","2026-09-01"));eid=cur.lastrowid
    for i in range(1,31):
        pid=app.db.execute("INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)",(eid,str(1200+i),600+i)).lastrowid
        app.db.execute("INSERT INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)",(pid,'2026-09-01',600+i))
    app.db.commit();app.open_employee(eid,'2026-09')
    # Let chunked plot rendering complete without freezing the UI.
    deadline=time.time()+2.0
    while time.time()<deadline:
        app.update(); app.update_idletasks()
        if sum(1 for _,c,a in app._scroll_areas if a=='x' and isinstance(c,tk.Canvas))>=30: break
        time.sleep(0.01)
    vcanvas=app._default_vertical_target
    xcanvases=[c for _,c,axis in app._scroll_areas if axis=='x' and isinstance(c,tk.Canvas)]
    if not vcanvas or len(xcanvases)!=30: failures.append(f'expected vertical + 30 horizontal canvases, got {bool(vcanvas)} + {len(xcanvases)}')
    else:
        y0=float(vcanvas.yview()[0]);app._queue_smooth_scroll(vcanvas,-240,'y')
        deadline=time.time()+0.6
        while time.time()<deadline:
            app.update(); time.sleep(0.01)
        if float(vcanvas.yview()[0])<=y0: failures.append('vertical scroll did not move')
        x0=float(xcanvases[0].xview()[0]);app._queue_smooth_scroll(xcanvases[0],-240,'x')
        deadline=time.time()+0.6
        while time.time()<deadline:
            app.update(); time.sleep(0.01)
        if float(xcanvases[0].xview()[0])<=x0: failures.append('horizontal scroll did not move')
    print('ATTENDANCE_SCROLL_TEST:', 'PASS' if not failures else 'FAIL')
except Exception:
    traceback.print_exc();failures.append('exception')
finally:
    try:app.destroy()
    except Exception:pass
if failures:
    for f in failures:print('FAIL:',f)
    raise SystemExit(1)
