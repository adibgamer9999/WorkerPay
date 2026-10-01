import os,sys,tempfile,tkinter as tk
os.environ['APPDATA']=tempfile.mkdtemp(prefix='workerpay_geometry_')
sys.path.insert(0,os.path.dirname(__file__))
from app import WorkerPay
app=WorkerPay(); errors=[]

def walk(w):
    yield w
    for c in w.winfo_children(): yield from walk(c)

def check():
    app.update_idletasks()
    mixed=[]
    for parent in walk(app):
        managers={c.winfo_manager() for c in parent.winfo_children() if c.winfo_manager()}
        if 'pack' in managers and 'grid' in managers: mixed.append(str(parent))
    if mixed: errors.append('Mixed pack/grid parents: '+', '.join(mixed[:8]))
    else: print('GEOMETRY: PASS')
    app.after(50,app.destroy)
for fn in (app.dashboard,app.employees,lambda:app.salary_filter()):
    try: fn();app.update_idletasks()
    except Exception as e: errors.append(repr(e))
app.after(100,check);app.mainloop()
if errors:
    print('GEOMETRY: FAIL')
    for e in errors: print(e)
    raise SystemExit(1)
