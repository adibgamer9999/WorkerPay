import os,sqlite3,tempfile,sys
os.environ['APPDATA']=tempfile.mkdtemp(prefix='workerpay_health_')
sys.path.insert(0,os.path.dirname(__file__))
from app import WorkerPay
app=WorkerPay();
print('QUICK:',app.db.execute('PRAGMA quick_check').fetchone()[0])
print('FK:',len(app.db.execute('PRAGMA foreign_key_check').fetchall()))
print('AUDIT:',app.verify_audit_log())
app.destroy()
if sqlite3.connect(os.path.join(os.environ['APPDATA'],'workerpay.db')).execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise SystemExit(1)
