import os
import sqlite3
import calendar
import shutil
import zipfile
import tempfile
import time
import json
import hashlib
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import date, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_NAME = 'WorkerPay'
APP_VERSION = '4.5.0'

# Installed program files belong on the Windows system drive (normally C:\Program Files\WorkerPay).
# User data stays in the user's C: drive AppData location so Program Files can remain read-only.
_LOCAL_BASE = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
_ROAMING_BASE = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
# Windows: new installations use Local AppData (still on C: by default).
# Non-Windows test/dev runs continue to honor APPDATA so the existing isolated test harnesses remain isolated.
if os.name == 'nt':
    DATA_DIR = os.path.join(_LOCAL_BASE, APP_NAME)
    _LEGACY_DATA_DIR = os.path.join(_ROAMING_BASE, APP_NAME)
else:
    DATA_DIR = os.path.join(_ROAMING_BASE, APP_NAME)
    _LEGACY_DATA_DIR = ''
os.makedirs(DATA_DIR, exist_ok=True)

# Migrate the older Roaming-AppData database once, preserving the original as a safety copy.
_DB_NAME = 'workerpay.db'
DB = os.path.join(DATA_DIR, _DB_NAME)
_LEGACY_DB = os.path.join(_LEGACY_DATA_DIR, _DB_NAME) if _LEGACY_DATA_DIR else ''
if _LEGACY_DB and not os.path.exists(DB) and os.path.isfile(_LEGACY_DB):
    try:
        legacy_backup = os.path.join(DATA_DIR, 'pre_localappdata_migration.db')
        shutil.copy2(_LEGACY_DB, legacy_backup)
        shutil.copy2(_LEGACY_DB, DB)
    except Exception:
        # Continue using the legacy location only when migration cannot be completed.
        DATA_DIR = _LEGACY_DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        DB = os.path.join(DATA_DIR, _DB_NAME)
LOG_FILE = os.path.join(DATA_DIR, 'workerpay.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

BG = '#111318'
PANEL = '#191c22'
PANEL2 = '#232832'
TEXT = '#f3f4f6'
MUTED = '#9ca3af'
ACCENT = '#3b82f6'
RED = '#ef4444'
BORDER = '#303642'
EMPLOYEE_PAGE_SIZE = 120
SCHEMA_VERSION = 305
TEST_OUTPUT_ENV = 'WORKERPAY_TEST_OUTPUT'

DEFAULT_RULES = [
    ('A', 'Absent', 0.0),
    ('P/2', 'Half day', 0.5),
    ('P', 'Full day', 1.0),
    ('P+P/2', 'Full day + half', 1.5),
    ('2P', 'Double/full extra', 2.0),
]


def safe_float(value, label='Number'):
    try:
        return float(str(value).strip() or 0)
    except ValueError:
        raise ValueError(f'{label} must be a number.')


def enable_windows_dpi_awareness():
    """Ask Windows for per-monitor DPI-aware rendering so text/UI stay crisp on HD/2K/4K screens."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # Per-monitor v2 context; available on modern Windows 10/11.
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except Exception:
                pass
    except Exception:
        pass



class ModernScrollbar(tk.Canvas):
    """Modern arrow-free scrollbar with a slightly thicker, easier-to-grab thumb."""
    def __init__(self, master, command, orient='vertical', thickness=16, **kwargs):
        self.orient = orient
        self.command = command
        self.thickness = max(int(thickness), 18 if orient == 'vertical' else 15)
        kwargs.setdefault('highlightthickness', 0)
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('bg', PANEL)
        if orient == 'vertical': kwargs.setdefault('width', thickness)
        else: kwargs.setdefault('height', thickness)
        super().__init__(master, **kwargs)
        self.first=0.0; self.last=1.0; self.drag_offset=0.0; self.dragging=False; self._hover=False
        self.bind('<Configure>', lambda _e: self._redraw())
        self.bind('<Button-1>', self._press); self.bind('<B1-Motion>', self._drag); self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Enter>', lambda _e: (setattr(self,'_hover',True), self._redraw()))
        self.bind('<Leave>', lambda _e: (setattr(self,'_hover',False), self._redraw()))
        self._redraw()
    @staticmethod
    def _rounded_points(x1,y1,x2,y2,r):
        import math
        pts=[]
        for cx,cy,start in ((x2-r,y1+r,270),(x2-r,y2-r,0),(x1+r,y2-r,90),(x1+r,y1+r,180)):
            for a in range(start,start+91,30):
                rad=math.radians(a); pts.extend((cx+r*math.cos(rad),cy+r*math.sin(rad)))
        return pts
    def _draw_round_rect(self,x1,y1,x2,y2,fill,tag=None):
        if x2<=x1 or y2<=y1:return
        r=max(3.0,min(8.0,(x2-x1)/2,(y2-y1)/2)); self.create_polygon(self._rounded_points(x1,y1,x2,y2,r),fill=fill,outline='',tags=tag)
    def set(self,first,last):
        try:self.first=float(first);self.last=float(last)
        except Exception:return
        self._redraw()
    def _redraw(self):
        try:
            self.delete('all')
            span=max(0.0,min(1.0,self.last-self.first))
            if self.orient=='vertical':
                w=max(1,self.winfo_width());h=max(1,self.winfo_height());self._draw_round_rect(2,1,w-2,h-1,'#151922','track')
                if span>=.999:return
                thumb_len=max(70.0,(h-2)*span);top=1+(h-2)*max(0.0,min(1.0,self.first));bottom=min(h-1,top+thumb_len)
                self._draw_round_rect(1,top,w-1,bottom,'#667085' if self._hover else '#596575','thumb')
            else:
                w=max(1,self.winfo_width());h=max(1,self.winfo_height());self._draw_round_rect(1,2,w-1,h-2,'#151922','track')
                if span>=.999:return
                thumb_len=max(72.0,(w-2)*span);left=1+(w-2)*max(0.0,min(1.0,self.first));right=min(w-1,left+thumb_len)
                self._draw_round_rect(left,1,right,h-1,'#667085' if self._hover else '#596575','thumb')
        except tk.TclError: pass
    def _metrics(self):
        if self.orient=='vertical': length=max(1,self.winfo_height()); viewport=max(1.0,length-2); minimum=70.0
        else: length=max(1,self.winfo_width()); viewport=max(1.0,length-2); minimum=72.0
        thumb=max(minimum,viewport*max(0.0,self.last-self.first)); usable=max(1.0,viewport-thumb)
        return length,thumb,usable
    def _press(self,event):
        length,thumb,usable=self._metrics(); pos=event.y if self.orient=='vertical' else event.x
        start=1+(length-2)*self.first; end=start+thumb
        if start<=pos<=end:
            self.dragging=True;self.drag_offset=pos-start;return
        target=(pos-1-thumb/2)/usable if usable else self.first;self.command('moveto',max(0.0,min(1.0,target)))
    def _drag(self,event):
        if not self.dragging:return
        length,thumb,usable=self._metrics();pos=event.y if self.orient=='vertical' else event.x
        raw=(pos-1-self.drag_offset)/usable if usable else self.first
        self.command('moveto',max(0.0,min(1.0,raw)))
    def _release(self,_event):self.dragging=False


class WorkerPay(tk.Tk):
    def __init__(self):
        super().__init__()
        self._after_jobs = set()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self._page_key = None
        self._page_generation = 0
        self._loading_started = time.perf_counter()
        self._splash_anim_job = None
        self._finish_loading_job = None
        self._zoom_job = None
        self._bg = ThreadPoolExecutor(max_workers=2, thread_name_prefix='WorkerPayBG')
        self._startup_health_note = ''
        self._make_splash()
        # Let Tk/Windows handle the native DPI scale.  Do not apply a second manual
        # scaling factor: doing so can make controls and labels larger than their
        # containers on 125%/150%/200%/4K displays.
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        start_w = min(1700, max(1200, screen_w - 60))
        start_h = min(980, max(700, screen_h - 80))
        self.geometry(f'{start_w}x{start_h}')
        self.minsize(1080, 680)
        self.withdraw()
        self.update_idletasks()
        try: self.update()
        except tk.TclError: pass
        self.db = sqlite3.connect(DB, timeout=30.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.execute('PRAGMA journal_mode = WAL')
        self.db.execute('PRAGMA synchronous = NORMAL')
        self.db.execute('PRAGMA temp_store = MEMORY')
        self.db.execute('PRAGMA busy_timeout = 30000')
        self.db.execute('PRAGMA cache_size = -65536')
        self.db.execute('PRAGMA wal_autocheckpoint = 2000')
        self.db.execute('PRAGMA mmap_size = 268435456')
        # Make a safety snapshot once when opening an older non-empty database.
        # This protects legacy migrations such as the v3.1 audit_log repair.
        try:
            old_version = int(self.db.execute('PRAGMA user_version').fetchone()[0])
            if old_version < SCHEMA_VERSION and os.path.exists(DB) and os.path.getsize(DB) > 0:
                stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
                self._pre_migration_backup = os.path.join(DATA_DIR, f'pre_migration_{stamp}.db')
                self._snapshot_database(self._pre_migration_backup)
            else:
                self._pre_migration_backup = ''
        except Exception:
            self._pre_migration_backup = ''
            logging.exception('pre-migration safety snapshot failed')
        self.init_db()
        self._repair_foreign_key_issues()
        try:
            health=self.db.execute('PRAGMA quick_check').fetchone()[0]
            fkc=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
            audit_ok=self.verify_audit_log()
            if health != 'ok' or fkc:
                self._startup_health_note = f'Database integrity needs attention: quick_check={health}; foreign-key issues={fkc}. A safety backup is recommended before major edits.'
            elif not audit_ok:
                repaired = False
                try:
                    audit_rows = int(self.db.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0])
                    if audit_rows:
                        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        safety = os.path.join(DATA_DIR, f'pre_audit_repair_{stamp}.db')
                        self._snapshot_database(safety)
                        repaired = self._reseal_audit_chain()
                        if repaired:
                            logging.info('Legacy audit hash chain repaired; safety copy kept at %s', safety)
                except Exception:
                    logging.exception('audit chain repair failed')
                if not repaired:
                    self._startup_health_note = 'Audit history needs review: the audit hash chain could not be fully verified. Your stored business records were not changed by this check. Create a backup before making major edits.'
        except Exception:
            logging.exception('startup health verification failed')
        try: self.db.execute('PRAGMA optimize')
        except Exception: pass
        self.styles()
        self.bind('<F11>', lambda e: self.rules_window())
        self._active_scroll_canvas = None
        self._active_vertical_canvas = None
        self._active_horizontal_canvas = None
        self._scroll_areas = []
        self._scroll_targets = {}
        self._scroll_jobs = {}
        self._default_vertical_target = None
        self._default_horizontal_target = None
        self._transition_job = None
        self._transition_busy = False
        self._in_navigation = False
        self.bind_all('<Motion>', self._track_scroll_area, add='+')
        self.bind_all('<MouseWheel>', self._on_mousewheel, add='+')
        self.bind_all('<Button-4>', self._on_button_scroll, add='+')
        self.bind_all('<Button-5>', self._on_button_scroll, add='+')
        self.bind_all('<Shift-MouseWheel>', self._on_shift_mousewheel, add='+')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.build_shell()
        self.dashboard()
        self._page_key = 'dashboard'
        if os.name == 'nt':
            self._zoom_job = self.after(80, lambda: self.state('zoomed'))
        self._finish_loading_job = self.after(120, self._finish_loading)

    def after(self, ms, func=None, *args):
        token = super().after(ms, func, *args)
        try:
            self._after_jobs.add(token)
        except Exception:
            pass
        return token

    def after_cancel(self, token):
        try:
            return super().after_cancel(token)
        finally:
            try:self._after_jobs.discard(token)
            except Exception:pass

    def _cancel_all_after_jobs(self):
        jobs=list(getattr(self,'_after_jobs',()))
        try:self._after_jobs.clear()
        except Exception:pass
        for token in jobs:
            try:super().after_cancel(token)
            except Exception:pass

    def destroy(self):
        # Cancel outstanding Tcl callbacks before tearing down the interpreter.
        # This prevents late splash/transition/scroll callbacks from becoming
        # "invalid command name" errors during fast shutdown/test teardown.
        self._cancel_all_after_jobs()
        try:
            splash=getattr(self,'splash',None)
            if splash is not None and splash.winfo_exists(): splash.destroy()
        except Exception:pass
        try:super().destroy()
        except tk.TclError:pass

    def _resource_path(self, name):
        """Resolve bundled resources for both source runs and PyInstaller one-file builds."""
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, name)

    def _apply_window_icon(self, window):
        if os.name != 'nt':
            return
        try:
            window.iconbitmap(self._resource_path('workerpay.ico'))
        except Exception:
            pass

    def _draw_workerpay_logo(self, canvas, size=96):
        """Draw the same WorkerPay mark used by the Windows EXE icon."""
        s=float(size); pad=max(2,s*0.07)
        canvas.create_rectangle(pad,pad,s-pad,s-pad,fill='#172033',outline='#3b82f6',width=max(2,int(s*0.025)))
        r=s*0.29; c=s/2
        canvas.create_oval(c-r,c-r,c+r,c+r,fill='#3b82f6',outline='')
        canvas.create_text(c,c,text='W',fill='white',font=('Segoe UI',max(18,int(s*.31)),'bold'))
        canvas.create_line(s*.36,s*.76,s*.64,s*.76,fill='#a9c7ff',width=max(2,int(s*.04)),capstyle='round')

    def _make_splash(self):
        self.splash = tk.Toplevel(self)
        self.splash.overrideredirect(True)
        self.splash.configure(bg='#0d0f13')
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 560, 350
        x, y = max(0,(sw-w)//2), max(0,(sh-h)//2)
        self.splash.geometry(f'{w}x{h}+{x}+{y}')
        self.splash.attributes('-topmost', True)
        wrap = tk.Frame(self.splash, bg='#0d0f13')
        wrap.pack(fill='both', expand=True, padx=36, pady=28)
        logo = tk.Canvas(wrap, width=96, height=96, bg='#0d0f13', highlightthickness=0)
        logo.pack(pady=(6, 4))
        self._draw_workerpay_logo(logo, 96)
        tk.Label(wrap,text=APP_NAME,bg='#0d0f13',fg='white',font=('Segoe UI',27,'bold')).pack()
        tk.Label(wrap,text='Worker and salary management',bg='#0d0f13',fg='#9ca3af',font=('Segoe UI',10)).pack(pady=(4,18))
        self._splash_status = tk.Label(wrap,text='Preparing your workspace…',bg='#0d0f13',fg='#8ab4ff',font=('Segoe UI',10,'bold'))
        self._splash_status.pack()
        bar_bg=tk.Frame(wrap,bg='#1b2029',height=6)
        bar_bg.pack(fill='x',pady=(18,0))
        self._splash_bar=tk.Frame(bar_bg,bg='#3b82f6',height=6,width=40)
        self._splash_bar.pack(side='left',fill='y')
        self._splash_phase=0
        self._animate_splash()

    def _animate_splash(self):
        if not hasattr(self,'splash') or not self.splash.winfo_exists(): return
        self._splash_phase=(self._splash_phase+1)%100
        pos=20+(self._splash_phase%41)*11
        self._splash_bar.place_forget(); self._splash_bar.place(relx=min(0.88,pos/100),rely=0,relwidth=0.22,relheight=1)
        self._splash_anim_job = self.after(35,self._animate_splash)

    def _finish_loading(self):
        elapsed=time.perf_counter()-self._loading_started
        target=0.25 if os.environ.get('WORKERPAY_TEST_MODE')=='1' else 3.6
        wait=max(0.0,target-elapsed)
        self._finish_loading_job = self.after(int(wait*1000),self._close_splash)

    def _close_splash(self):
        if self._splash_anim_job is not None:
            try:self.after_cancel(self._splash_anim_job)
            except Exception:pass
            self._splash_anim_job=None
        self._finish_loading_job = None
        try:
            if self.splash.winfo_exists(): self.splash.destroy()
        except Exception: pass
        self.deiconify()
        if os.name=='nt':
            try: self.state('zoomed')
            except Exception: pass

    # ---------- database ----------
    def init_db(self):
        self._rule_month_cache = {}
        self._rate_month_cache = {}
        c = self.db.cursor()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empid TEXT UNIQUE NOT NULL,
            emp_number INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            daily_rate REAL NOT NULL DEFAULT 0,
            start TEXT NOT NULL,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS plots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            plot_no TEXT NOT NULL,
            daily_rate REAL NOT NULL DEFAULT 0,
            active INTEGER DEFAULT 1,
            UNIQUE(employee_id, plot_no),
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS plot_rate_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plot_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL,
            daily_rate REAL NOT NULL,
            UNIQUE(plot_id, effective_from),
            FOREIGN KEY(plot_id) REFERENCES plots(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            plot_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            code TEXT NOT NULL,
            UNIQUE(employee_id, plot_id, day),
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            FOREIGN KEY(plot_id) REFERENCES plots(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS rules(
            code TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            mult REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rule_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            mult REAL NOT NULL,
            UNIQUE(code, effective_from)
        );
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            amount REAL NOT NULL,
            paid_on TEXT NOT NULL,
            note TEXT DEFAULT '',
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS advances(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            advance_date TEXT NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,action TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT DEFAULT '',details TEXT NOT NULL,prev_hash TEXT NOT NULL,row_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS data_quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT,table_name TEXT NOT NULL,row_id INTEGER,reason TEXT NOT NULL,row_json TEXT NOT NULL,quarantined_at TEXT NOT NULL);
        ''')
        self.migrate_schema()
        self.db.executescript('''
        CREATE INDEX IF NOT EXISTS idx_employees_empid ON employees(empid);
        CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_employees_active_name_id ON employees(active,name COLLATE NOCASE,id);
        CREATE INDEX IF NOT EXISTS idx_employees_active_empid ON employees(active,empid);
        CREATE INDEX IF NOT EXISTS idx_employees_emp_number ON employees(emp_number);
        CREATE INDEX IF NOT EXISTS idx_employees_active_emp_number ON employees(active,emp_number,id);
        CREATE INDEX IF NOT EXISTS idx_plots_employee_active ON plots(employee_id,active);
        CREATE INDEX IF NOT EXISTS idx_plots_plot_no ON plots(plot_no COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_plots_employee_active_plot ON plots(employee_id,active,plot_no COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_attendance_day ON attendance(day);
        CREATE INDEX IF NOT EXISTS idx_attendance_emp_plot_day ON attendance(employee_id,plot_id,day);
        CREATE INDEX IF NOT EXISTS idx_attendance_plot_day ON attendance(plot_id,day);
        CREATE INDEX IF NOT EXISTS idx_rate_history_plot_date ON plot_rate_history(plot_id,effective_from,id);
        CREATE INDEX IF NOT EXISTS idx_rule_history_code_date ON rule_history(code,effective_from,id);
        CREATE INDEX IF NOT EXISTS idx_payments_employee_month ON payments(employee_id,month);
        CREATE INDEX IF NOT EXISTS idx_payments_month ON payments(month);
        CREATE INDEX IF NOT EXISTS idx_advances_employee_date ON advances(employee_id,advance_date,id);
        CREATE INDEX IF NOT EXISTS idx_advances_date ON advances(advance_date);
        CREATE INDEX IF NOT EXISTS idx_advances_reason ON advances(reason COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at,id);
        CREATE INDEX IF NOT EXISTS idx_quarantine_time ON data_quarantine(quarantined_at,id);
        ''')
        for code, label, mult in DEFAULT_RULES:
            c.execute('INSERT OR IGNORE INTO rules(code,label,mult) VALUES(?,?,?)', (code, label, mult))
            c.execute('INSERT OR IGNORE INTO rule_history(code,effective_from,mult) VALUES(?,?,?)',
                      (code, '2000-01-01', mult))
        self.db.commit()

    def columns(self, table):
        return [r[1] for r in self.db.execute(f'PRAGMA table_info({table})').fetchall()]

    def _ensure_column(self, table, column, definition):
        """Add a missing legacy column without assuming the table was created by v3+."""
        cols = self.columns(table)
        if column not in cols:
            self.db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
            return True
        return False

    def _migrate_audit_schema(self):
        """Repair older audit tables before any indexes reference their columns.

        Older WorkerPay hardening builds could contain an audit_log table without
        created_at. CREATE TABLE IF NOT EXISTS does not alter an existing table,
        so v3.2 could crash while creating idx_audit_created. This migration adds
        missing columns, seeds deterministic timestamps, then re-seals the chain.
        """
        before = set(self.columns('audit_log'))
        self._ensure_column('audit_log', 'created_at', 'TEXT')
        self._ensure_column('audit_log', 'action', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column('audit_log', 'entity', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column('audit_log', 'entity_id', "TEXT DEFAULT ''")
        self._ensure_column('audit_log', 'details', "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column('audit_log', 'prev_hash', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column('audit_log', 'row_hash', "TEXT NOT NULL DEFAULT ''")

        cols = set(self.columns('audit_log'))
        # Reuse a legacy time column when available. Otherwise use a deterministic
        # timestamp based on row id so migration is repeatable and auditable.
        legacy_time = next((c for c in ('timestamp', 'time', 'created', 'logged_at') if c in cols), None)
        if legacy_time:
            self.db.execute(f'UPDATE audit_log SET created_at=COALESCE(NULLIF(created_at,""),CAST("{legacy_time}" AS TEXT))')
        self.db.execute("UPDATE audit_log SET created_at=COALESCE(NULLIF(created_at, ''), '2000-01-01T00:00:00') WHERE created_at IS NULL OR created_at=''")

        rows = self.db.execute('SELECT id,created_at,action,entity,entity_id,details,prev_hash,row_hash FROM audit_log ORDER BY id').fetchall()
        if rows and ('created_at' not in before or any(not r['row_hash'] or not r['prev_hash'] for r in rows)):
            prev = ''
            for r in rows:
                try:
                    parsed = json.loads(r['details'] or '{}')
                except Exception:
                    parsed = {}
                payload = json.dumps({
                    'action': r['action'] or '',
                    'entity': r['entity'] or '',
                    'entity_id': str(r['entity_id'] or ''),
                    'details': parsed if isinstance(parsed, dict) else {},
                }, ensure_ascii=False, sort_keys=True, default=str)
                row_hash = hashlib.sha256((prev + '|' + str(r['created_at']) + '|' + payload).encode('utf-8')).hexdigest()
                self.db.execute('UPDATE audit_log SET prev_hash=?,row_hash=? WHERE id=?',(prev,row_hash,r['id']))
                prev = row_hash

    def _migrate_auxiliary_schema(self):
        # CREATE TABLE IF NOT EXISTS never repairs an existing older table.
        # Ensure all columns used by v3.x exist before indexes or queries touch them.
        for name, definition in (
            ('note', "TEXT DEFAULT ''"),
        ):
            self._ensure_column('payments', name, definition)
        for name, definition in (
            ('table_name', "TEXT NOT NULL DEFAULT 'unknown'"),
            ('row_id', 'INTEGER'),
            ('reason', "TEXT NOT NULL DEFAULT ''"),
            ('row_json', "TEXT NOT NULL DEFAULT '{}'"),
            ('quarantined_at', "TEXT NOT NULL DEFAULT '2000-01-01T00:00:00'"),
        ):
            self._ensure_column('data_quarantine', name, definition)
        self._migrate_audit_schema()
        self.db.execute('''CREATE TABLE IF NOT EXISTS advances(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            advance_date TEXT NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )''')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_advances_employee_date ON advances(employee_id,advance_date,id)')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_advances_date ON advances(advance_date)')

    def migrate_schema(self):
        """Open older LaborPay / EmployeePay / WorkerPay backups safely."""
        ec = self.columns('employees')
        if 'emp_number' not in ec:
            self.db.execute('ALTER TABLE employees ADD COLUMN emp_number INTEGER NOT NULL DEFAULT 0')
            ec = self.columns('employees')
        self.db.execute("UPDATE employees SET emp_number=CAST(substr(UPPER(empid),4) AS INTEGER) WHERE UPPER(empid) GLOB 'EMP[0-9]*' AND COALESCE(emp_number,0)=0")
        self._canonicalize_legacy_employee_ids()
        if 'daily_rate' not in ec:
            self.db.execute('ALTER TABLE employees ADD COLUMN daily_rate REAL NOT NULL DEFAULT 0')
            ec = self.columns('employees')
        # Old LaborPay stored monthly salary. Convert it to the new daily model.
        if 'salary' in ec:
            self.db.execute('''UPDATE employees SET daily_rate=
                CASE WHEN COALESCE(daily_rate,0)=0 THEN COALESCE(salary,0)/30.0 ELSE daily_rate END''')

        # plots was new to EmployeePay. If an old database has no plot table, create a Legacy plot.
        if not self.columns('plots'):
            self.db.execute('''CREATE TABLE plots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                plot_no TEXT NOT NULL,
                daily_rate REAL NOT NULL DEFAULT 0,
                active INTEGER DEFAULT 1,
                UNIQUE(employee_id, plot_no)
            )''')

        pc = self.columns('plots')
        if 'daily_rate' not in pc:
            self.db.execute('ALTER TABLE plots ADD COLUMN daily_rate REAL NOT NULL DEFAULT 0')
        if 'active' not in pc:
            self.db.execute('ALTER TABLE plots ADD COLUMN active INTEGER DEFAULT 1')

        # Old versions stored one employee rate. Use it only to seed plot rates that are blank.
        self.db.execute('''UPDATE plots SET daily_rate=(
            SELECT COALESCE(e.daily_rate,0) FROM employees e WHERE e.id=plots.employee_id
        ) WHERE COALESCE(daily_rate,0)=0''')

        ac = self.columns('attendance')
        if 'plot_id' not in ac:
            self.db.execute('ALTER TABLE attendance ADD COLUMN plot_id INTEGER')
            for e in self.db.execute('SELECT id,daily_rate,start FROM employees').fetchall():
                p = self.db.execute('SELECT id FROM plots WHERE employee_id=? ORDER BY id LIMIT 1', (e['id'],)).fetchone()
                if not p:
                    cur = self.db.execute(
                        'INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',
                        (e['id'], 'Legacy', e['daily_rate'] or 0))
                    pid = cur.lastrowid
                else:
                    pid = p['id']
                self.db.execute('UPDATE attendance SET plot_id=? WHERE employee_id=? AND plot_id IS NULL',
                                (pid, e['id']))

        # Add history tables/rows for any existing plots.
        self.db.execute('''CREATE TABLE IF NOT EXISTS plot_rate_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plot_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL,
            daily_rate REAL NOT NULL,
            UNIQUE(plot_id, effective_from)
        )''')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_plot_rate_seed ON plot_rate_history(plot_id,effective_from,id)')
        self.db.execute('''
            INSERT OR IGNORE INTO plot_rate_history(plot_id,effective_from,daily_rate)
            SELECT p.id, COALESCE(e.start,'2000-01-01'), COALESCE(p.daily_rate,0)
            FROM plots p JOIN employees e ON e.id=p.employee_id
            LEFT JOIN plot_rate_history h ON h.plot_id=p.id
            WHERE h.id IS NULL
        ''')

        self.db.execute('''CREATE TABLE IF NOT EXISTS rule_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            mult REAL NOT NULL,
            UNIQUE(code, effective_from)
        )''')
        for r in self.db.execute('SELECT code,mult FROM rules').fetchall():
            self.db.execute('INSERT OR IGNORE INTO rule_history(code,effective_from,mult) VALUES(?,?,?)',
                            (r['code'], '2000-01-01', r['mult']))
        # Repair auxiliary legacy schemas before init_db creates indexes that depend on them.
        self._migrate_auxiliary_schema()
        self._dedupe_attendance_rows()
        # Legacy attendance tables may predate the inline UNIQUE constraint. Recreate
        # the invariant explicitly after deduplication so future edits cannot create
        # duplicate employee/plot/day cells.
        self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_emp_plot_day ON attendance(employee_id,plot_id,day)')
        self.db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        self.db.commit()

    def _dedupe_attendance_rows(self):
        """Collapse accidental legacy duplicate attendance cells.

        Attendance is a calendar grid: one employee + one plot + one date can have
        exactly one code. Older databases may not have enforced that UNIQUE key, so
        duplicated rows could make 6 entered days calculate as 7P/8P. Keep the newest
        row (highest id) for each cell and quarantine the discarded duplicates.
        """
        rows = self.db.execute(
            'SELECT id,employee_id,plot_id,day,code FROM attendance '
            'ORDER BY employee_id,plot_id,day,id'
        ).fetchall()
        keep = {}
        duplicates = []
        for r in rows:
            key = (r['employee_id'], r['plot_id'], r['day'])
            if key in keep:
                duplicates.append(r)
            else:
                keep[key] = r
        if not duplicates:
            return 0
        stamp = datetime.now().isoformat(timespec='seconds')
        for r in duplicates:
            self.db.execute(
                'INSERT INTO data_quarantine(table_name,row_id,reason,row_json,quarantined_at) '
                'VALUES(?,?,?,?,?)',
                ('attendance', r['id'], 'Duplicate employee/plot/day attendance cell; newest row retained',
                 json.dumps(dict(r), ensure_ascii=False, sort_keys=True, default=str), stamp)
            )
            self.db.execute('DELETE FROM attendance WHERE id=?', (r['id'],))
        return len(duplicates)

    def _canonicalize_legacy_employee_ids(self):
        """Normalize legacy numeric/EMP IDs to the canonical EMPXXX presentation.

        Plot / Place values are deliberately untouched: only the Employee ID field is
        normalized here. Existing IDs that would collide after normalization are left
        unchanged so migration never overwrites a real worker record.
        """
        rows = self.db.execute('SELECT id, empid FROM employees ORDER BY id').fetchall()
        for row in rows:
            raw = str(row['empid'] or '').strip().upper()
            n = None
            if raw.isdigit() and int(raw) > 0:
                n = int(raw)
            elif raw.startswith('EMP') and raw[3:].isdigit() and int(raw[3:]) > 0:
                n = int(raw[3:])
            if n is None:
                continue
            canonical = f'EMP{n:03d}'
            if raw == canonical:
                self.db.execute('UPDATE employees SET emp_number=? WHERE id=?', (n, row['id']))
                continue
            conflict = self.db.execute('SELECT 1 FROM employees WHERE empid=? AND id<>? LIMIT 1',
                                        (canonical, row['id'])).fetchone()
            if not conflict:
                self.db.execute('UPDATE employees SET empid=?, emp_number=? WHERE id=?',
                                (canonical, n, row['id']))

    # ---------- ui helpers ----------
    def styles(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('TFrame', background=BG)
        s.configure('TLabel', background=BG, foreground=TEXT, font=('Segoe UI', 10))
        s.configure('TButton', background=PANEL2, foreground=TEXT, padding=(14, 9), font=('Segoe UI', 10, 'bold'))
        s.map('TButton', background=[('active', ACCENT), ('pressed', '#2f6dcc')], foreground=[('active', 'white')])
        s.configure('Accent.TButton', background=ACCENT, foreground='white', padding=(16, 10), font=('Segoe UI', 10, 'bold'))
        s.map('Accent.TButton', background=[('active', '#4f93ff'), ('pressed', '#2f6dcc')], foreground=[('active', 'white')])
        s.configure('TEntry', fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT, padding=(8, 7))
        s.configure('TCheckbutton', background=PANEL, foreground=TEXT, font=('Segoe UI', 10))
        s.map('TCheckbutton', background=[('active', PANEL)])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=36, font=('Segoe UI', 10))
        s.configure('Treeview.Heading', background=PANEL2, foreground=TEXT, font=('Segoe UI', 10, 'bold'), padding=(8, 8))
        s.map('Treeview', background=[('selected', '#244d82')], foreground=[('selected', 'white')])
        s.configure('Treeview', rowheight=38)

    def _snapshot_database(self,destination):
        dst=None
        try:
            self.db.commit();dst=sqlite3.connect(destination);self.db.backup(dst,pages=5000,sleep=0.01);dst.commit()
        finally:
            try:
                if dst:dst.close()
            except Exception:pass
    def _repair_foreign_key_issues(self):
        try:issues=self.db.execute('PRAGMA foreign_key_check').fetchall()
        except Exception:return
        if not issues:return
        safety=os.path.join(DATA_DIR,f'recovery_before_repair_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
        try:
            self._snapshot_database(safety);self.db.execute('BEGIN');moved=0
            for table,rowid,parent,fkid in issues:
                row=self.db.execute(f'SELECT * FROM "{table}" WHERE rowid=?',(rowid,)).fetchone()
                if row is None:continue
                self.db.execute('INSERT INTO data_quarantine(table_name,row_id,reason,row_json,quarantined_at) VALUES(?,?,?,?,?)',(table,rowid,f'Foreign-key reference missing in {parent}',json.dumps(dict(row),ensure_ascii=False,sort_keys=True,default=str),datetime.now().isoformat(timespec='seconds')))
                self.db.execute(f'DELETE FROM "{table}" WHERE rowid=?',(rowid,));moved+=1
            self.db.commit()
            remaining=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
            if remaining:
                self._startup_health_note=f'WorkerPay quarantined {moved} invalid legacy reference(s), but {remaining} reference(s) still need attention. Safety copy: {os.path.basename(safety)}.'
            elif moved:
                self._startup_health_note=f'WorkerPay repaired {moved} invalid legacy database reference(s). A safety copy was kept as {os.path.basename(safety)}; original orphan rows remain recoverable in Data Recovery.'
            logging.warning(getattr(self,'_startup_health_note',''))
        except Exception:
            try:self.db.rollback()
            except Exception:pass
            logging.exception('foreign-key repair failed')
    def audit(self,action,entity,entity_id='',details=None):
        try:
            prev=self.db.execute('SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1').fetchone();prev_hash=str(prev['row_hash']) if prev else ''
            details_json=json.dumps(details or {},ensure_ascii=False,sort_keys=True,default=str)
            payload=json.dumps({'action':action,'entity':entity,'entity_id':str(entity_id),'details':json.loads(details_json)},ensure_ascii=False,sort_keys=True,default=str)
            created=datetime.now().isoformat(timespec='seconds')
            row_hash=hashlib.sha256((prev_hash+'|'+created+'|'+payload).encode('utf-8')).hexdigest()
            self.db.execute('INSERT INTO audit_log(created_at,action,entity,entity_id,details,prev_hash,row_hash) VALUES(?,?,?,?,?,?,?)',(created,action,entity,str(entity_id),details_json,prev_hash,row_hash))
        except Exception:logging.exception('audit log write failed')
    def _reseal_audit_chain(self):
        """Repair legacy audit hashes without altering business tables.

        Some older WorkerPay builds used slightly different audit payload envelopes.
        We preserve every audit row's business-facing fields and only recompute the
        cryptographic link fields so the current verifier can validate the history.
        A safety database snapshot is created before this repair is attempted.
        """
        rows = self.db.execute('SELECT id,created_at,action,entity,entity_id,details FROM audit_log ORDER BY id').fetchall()
        if not rows:
            return True
        prev = ''
        for r in rows:
            raw = r['details'] or '{}'
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict) and {'action','entity','entity_id','details'} <= set(parsed):
                payload = json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
            else:
                payload = json.dumps({
                    'action': r['action'] or '',
                    'entity': r['entity'] or '',
                    'entity_id': str(r['entity_id'] or ''),
                    'details': parsed if isinstance(parsed, dict) else {},
                }, ensure_ascii=False, sort_keys=True, default=str)
            row_hash = hashlib.sha256((prev + '|' + str(r['created_at']) + '|' + payload).encode('utf-8')).hexdigest()
            self.db.execute('UPDATE audit_log SET prev_hash=?,row_hash=? WHERE id=?', (prev, row_hash, r['id']))
            prev = row_hash
        self.db.commit()
        return self.verify_audit_log()

    def verify_audit_log(self):
        prev=''
        first = True
        for r in self.db.execute('SELECT * FROM audit_log ORDER BY id').fetchall():
            if r['created_at'] in (None, '') or r['row_hash'] in (None, ''):
                return False
            if first and (r['prev_hash'] or '') != '':
                return False
            if not first and r['prev_hash'] in (None, ''):
                return False
            raw=r['details'] or '{}'
            try: parsed=json.loads(raw)
            except Exception: return False
            if isinstance(parsed,dict) and {'action','entity','entity_id','details'} <= set(parsed):
                payload=json.dumps(parsed,ensure_ascii=False,sort_keys=True,default=str)
            else:
                payload=json.dumps({
                    'action': r['action'],
                    'entity': r['entity'],
                    'entity_id': str(r['entity_id']),
                    'details': parsed if isinstance(parsed,dict) else {},
                },ensure_ascii=False,sort_keys=True,default=str)
            expected=hashlib.sha256((prev+'|'+r['created_at']+'|'+payload).encode('utf-8')).hexdigest()
            if r['prev_hash']!=prev or r['row_hash']!=expected:return False
            prev=r['row_hash']
            first = False
        return True

    def database_health(self, repair=True):
        """Run SQLite integrity diagnostics; safely quarantine legacy orphan rows when requested."""
        quick=self.db.execute('PRAGMA quick_check').fetchone()[0]
        foreign=self.db.execute('PRAGMA foreign_key_check').fetchall()
        if foreign and repair:
            self._repair_foreign_key_issues()
            foreign=self.db.execute('PRAGMA foreign_key_check').fetchall()
        return quick == 'ok' and not foreign, quick, len(foreign)

    def close(self):
        def cancel_job(attr):
            job=getattr(self,attr,None)
            if job:
                try:self.after_cancel(job)
                except Exception:pass
                setattr(self,attr,None)
        cancel_job('_splash_anim_job')
        cancel_job('_finish_loading_job')
        cancel_job('_zoom_job')
        if self._transition_job is not None:
            try:self.after_cancel(self._transition_job)
            except Exception:pass
            self._transition_job=None
        for job in list(getattr(self,'_scroll_jobs',{}).values()):
            try:self.after_cancel(job)
            except Exception:pass
        try:
            self.db.commit()
            self.db.close()
        finally:
            try: self._bg.shutdown(wait=False, cancel_futures=True)
            except Exception: pass
            try: self.destroy()
            except tk.TclError: pass

    def navigate(self,target,duration=1250,key=None):
        """Build the destination first, then slide it in once from the right.

        The old page remains underneath until the eased transition reaches 100%.
        A busy guard prevents stacked/repeated animations and blank-frame flashes.
        """
        old=getattr(self,'main',None)
        old_page=getattr(self,'_page_key',None)
        target_name=key or getattr(target,'__name__',repr(target))
        if getattr(self,'_transition_busy',False):
            return
        if old is not None and old_page==target_name and target_name:
            return
        self._transition_busy=True
        self._in_navigation=True
        try:
            target()
        except Exception:
            self._in_navigation=False
            self._transition_busy=False
            raise
        finally:
            self._in_navigation=False
        new=getattr(self,'main',None)
        if new is old or new is None:
            self._transition_busy=False
            return
        self._page_key=target_name
        try:self.update_idletasks()
        except Exception:pass
        self._animate_page_transition(old,new,duration)

    def _animate_page_transition(self,old,new,duration=1650):
        if self._transition_job is not None:
            try:self.after_cancel(self._transition_job)
            except Exception:pass
            self._transition_job=None
        try:
            total=max(0,min(2000,int(duration)))
        except Exception:
            total=1650
        if total<=0:
            try:
                new.place_configure(relx=0,rely=0,relwidth=1,relheight=1)
                new.lift()
                if old is not None and old.winfo_exists(): old.destroy()
            except tk.TclError:
                pass
            self._transition_busy=False
            return
        try:
            new.place_configure(relx=1.0,rely=0,relwidth=1,relheight=1)
            new.lift()
            self.update_idletasks()
        except tk.TclError:
            self._transition_busy=False
            return
        started=time.perf_counter()
        def tick():
            try:
                if not new.winfo_exists():
                    self._transition_job=None
                    self._transition_busy=False
                    return
                elapsed_ms=(time.perf_counter()-started)*1000.0
                t=max(0.0,min(1.0,elapsed_ms/float(total)))
                eased=1.0-(1.0-t)**3
                new.place_configure(relx=1.0-eased)
                if t<1.0:
                    self._transition_job=self.after(16,tick)
                    return
                new.place_configure(relx=0,rely=0,relwidth=1,relheight=1)
                self.update_idletasks()
                self._transition_job=None
                self._transition_busy=False
                if old is not None and old.winfo_exists():
                    old.destroy()
            except tk.TclError:
                self._transition_job=None
                self._transition_busy=False
        self._transition_job=self.after(0,tick)

    # ---------- smooth/native scrolling ----------
    def _widget_alive(self,w):
        try:return bool(w is not None and w.winfo_exists())
        except Exception:return False
    def _prune_scroll_areas(self):
        self._scroll_areas=[x for x in self._scroll_areas if self._widget_alive(x[0]) and self._widget_alive(x[1])]
    def _pointer_inside(self,w):
        try:
            px,py=self.winfo_pointerx(),self.winfo_pointery();x,y=w.winfo_rootx(),w.winfo_rooty()
            return x<=px<=x+w.winfo_width() and y<=py<=y+w.winfo_height()
        except Exception:return False
    def _is_descendant(self,w,a):
        try:
            while w is not None:
                if w is a:return True
                w=w.master
        except Exception:pass
        return False
    def _resolve_scroll_targets(self,horizontal=False):
        self._prune_scroll_areas();px,py=self.winfo_pointerx(),self.winfo_pointery();pw=self.winfo_containing(px,py);ys=[];xs=[]
        for container,canvas,axis in self._scroll_areas:
            if not(self._widget_alive(container) and self._widget_alive(canvas)):continue
            try:
                if not container.winfo_ismapped():continue
                inside=self._pointer_inside(container) or self._is_descendant(pw,container)
                if axis=='y' and inside:ys.append(canvas)
                elif axis=='x' and inside:
                    cy=container.winfo_rooty();ch=max(1,container.winfo_height());xs.append((abs(cy+ch/2-py),canvas))
            except Exception:continue
        vertical=ys[0] if ys else self._default_vertical_target
        horizontal=None
        if xs:
            xs.sort(key=lambda q:q[0]);horizontal=xs[0][1]
        if horizontal is None and self.page_host.winfo_ismapped():
            try:
                hx,hy=self.page_host.winfo_rootx(),self.page_host.winfo_rooty();hw,hh=self.page_host.winfo_width(),self.page_host.winfo_height()
                if hx<=px<=hx+hw and hy<=py<=hy+hh:
                    candidates=[]
                    for container,canvas,axis in self._scroll_areas:
                        if axis!='x' or not self._widget_alive(container):continue
                        cy=container.winfo_rooty();ch=max(1,container.winfo_height());candidates.append((abs(cy+ch/2-py),canvas))
                    if candidates:candidates.sort(key=lambda q:q[0]);horizontal=candidates[0][1]
            except Exception:pass
        self._active_vertical_canvas=vertical;self._active_horizontal_canvas=horizontal
        return vertical,horizontal
    def _track_scroll_area(self,event=None):self._resolve_scroll_targets(False)
    def register_scroll_area(self,container,canvas,axis='y',default=False):
        self._prune_scroll_areas();item=(container,canvas,axis)
        if item not in self._scroll_areas:self._scroll_areas.append(item)
        if axis=='y' and default:self._default_vertical_target=canvas
        if axis=='x' and default:self._default_horizontal_target=canvas
    def _scroll_extent(self,canvas,axis):
        try:
            if isinstance(canvas,tk.Canvas):
                b=canvas.bbox('all')
                if not b:return 0.0,0.0
                extent=float((b[3]-b[1]) if axis=='y' else (b[2]-b[0]));viewport=float(canvas.winfo_height() if axis=='y' else canvas.winfo_width());return max(0,extent),max(0,viewport)
            first,last=(canvas.yview() if axis=='y' else canvas.xview());span=max(0,float(last)-float(first));return (1/span if span else 0),1
        except Exception:return 0.0,0.0
    def _queue_smooth_scroll(self,canvas,delta,axis='y'):
        if not self._widget_alive(canvas):return
        extent,viewport=self._scroll_extent(canvas,axis)
        try:current=float((canvas.yview() if axis=='y' else canvas.xview())[0])
        except tk.TclError:return
        key=(str(canvas),axis);target=float(self._scroll_targets.get(key,current));d=max(-500,min(500,float(delta)))
        if isinstance(canvas,tk.Canvas):
            max_px=max(0,extent-viewport)
            if max_px<=0:return
            gain=0.62 if axis=='y' else 0.40;target=max(0,min(1,(target*max_px-d*gain)/max_px))
        else:
            step=0.0018 if axis=='y' else 0.00115;target=max(0,min(1,target-d*step))
        self._scroll_targets[key]=target
        if key not in self._scroll_jobs:self._scroll_jobs[key]=self.after(8,lambda c=canvas,a=axis,k=key:self._animate_scroll(c,a,k))
    def _animate_scroll(self,canvas,axis,key):
        try:
            if not self._widget_alive(canvas):raise tk.TclError
            current=float((canvas.yview() if axis=='y' else canvas.xview())[0]);target=float(self._scroll_targets.get(key,current));diff=target-current
            if abs(diff)<0.00045:
                (canvas.yview_moveto(target) if axis=='y' else canvas.xview_moveto(target));self._scroll_jobs.pop(key,None);return
            pos=current+diff*0.46;(canvas.yview_moveto(pos) if axis=='y' else canvas.xview_moveto(pos));self._scroll_jobs[key]=self.after(8,lambda c=canvas,a=axis,k=key:self._animate_scroll(c,a,k))
        except tk.TclError:self._scroll_jobs.pop(key,None);self._scroll_targets.pop(key,None)
    def _on_mousewheel(self,event):
        d=float(getattr(event,'delta',0) or 0)
        if not d:return
        v,h=self._resolve_scroll_targets(bool(getattr(event,'state',0)&0x0001))
        if bool(getattr(event,'state',0)&0x0001) and h is not None:self._queue_smooth_scroll(h,d,'x');return 'break'
        if v is not None:self._queue_smooth_scroll(v,d,'y');return 'break'
    def _on_shift_mousewheel(self,event):
        d=float(getattr(event,'delta',0) or 0)
        if not d:return 'break'
        _,h=self._resolve_scroll_targets(True)
        if h is not None:self._queue_smooth_scroll(h,d,'x')
        return 'break'
    def _on_button_scroll(self,event):
        v,_=self._resolve_scroll_targets(False)
        if v is not None:self._queue_smooth_scroll(v,-120 if event.num==4 else 120,'y')
        return 'break'

    def build_shell(self):
        side = tk.Frame(self, bg='#0d0f13', width=220)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        tk.Label(side, text=APP_NAME, bg='#0d0f13', fg='white', font=('Segoe UI', 21, 'bold')).pack(pady=(22, 4))
        tk.Label(side, text='Attendance • Plots • Salary', bg='#0d0f13', fg=MUTED, font=('Segoe UI', 9)).pack(pady=(0, 20))
        for title, func, key in [
            ('Dashboard', self.dashboard, 'dashboard'),
            ('Employees', self.employees, 'employees'),
            ('Salary / Filter', self.salary_filter, 'salary_filter'),
            ('Advance Money', self.advance_money, 'advance_money'),
            ('Salary Payments', self.salary_payments, 'salary_payments'),
            ('Backup / Restore', self.backup, 'backup'),
            ('Export / Print', self.export_print, 'export_print'),
        ]:
            tk.Button(side, text=title, command=lambda f=func, k=key: self.navigate(f, key=k), anchor='w', bg='#0d0f13', fg=TEXT,
                      activebackground=ACCENT, activeforeground='white', relief='flat', bd=0,
                      font=('Segoe UI', 11, 'bold'), padx=20, pady=12).pack(fill='x')
        tk.Label(side, text='F11  Custom Rules', bg='#0d0f13', fg='#8ab4ff',
                 font=('Segoe UI', 9, 'bold')).pack(side='bottom', pady=20)
        self.page_host = tk.Frame(self, bg=BG)
        self.page_host.pack(side='left', fill='both', expand=True)
        self.main = tk.Frame(self.page_host, bg=BG)
        self.main.place(relx=0, rely=0, relwidth=1, relheight=1)

    def clear(self):
        self._page_generation += 1
        pending=getattr(self,'_attendance_render_pending',None)
        if pending is not None:
            try:
                job=pending.get('job')
                if job is not None:self.after_cancel(job)
            except Exception:pass
            self._attendance_render_pending=None
        old = getattr(self, 'main', None)
        if old is not None and not getattr(self, '_in_navigation', False):
            try: old.destroy()
            except Exception: pass
            old = None
        new = tk.Frame(self.page_host, bg=BG)
        starting_in_transition = bool(getattr(self, '_in_navigation', False) and old is not None and old.winfo_exists())
        new.place(relx=1 if starting_in_transition else 0, rely=0, relwidth=1, relheight=1)
        if starting_in_transition:
            try:new.lower(old)
            except tk.TclError:pass
        self.main = new
        self._scroll_areas.clear()
        self._active_scroll_canvas = None
        self._active_vertical_canvas = None
        self._active_horizontal_canvas = None
        self._default_vertical_target = None
        self._default_horizontal_target = None
        self._scroll_targets.clear()
        for job in list(self._scroll_jobs.values()):
            try: self.after_cancel(job)
            except Exception: pass
        self._scroll_jobs.clear()

    def header(self, title, sub=''):
        f = tk.Frame(self.main, bg=BG)
        f.pack(fill='x', padx=26, pady=(20, 8))
        tk.Label(f, text=title, bg=BG, fg=TEXT, font=('Segoe UI', 25, 'bold')).pack(anchor='w')
        if sub:
            sub_lbl = tk.Label(f, text=sub, bg=BG, fg=MUTED, font=('Segoe UI', 10), justify='left', anchor='w', wraplength=900)
            sub_lbl.pack(anchor='w', fill='x', pady=(2, 0))
        rules = ('Attendance key:  P = Full Day (1P)  •  P/2 = Half Day (0.5P)  •  '
                 'P+P/2 = Full Day + Half Night (1.5P)  •  2P = Full Day + Full Night (2P)  •  A = Absent (0P)')
        rule_lbl = tk.Label(f, text=rules, bg=BG, fg='#8ab4ff', font=('Segoe UI', 9, 'bold'),
                            justify='left', anchor='w', wraplength=900)
        rule_lbl.pack(anchor='w', fill='x', pady=(7, 0))
        f.bind('<Configure>', lambda ev: (sub_lbl.configure(wraplength=max(500, ev.width-10)) if sub else None), add='+')
        f.bind('<Configure>', lambda ev: rule_lbl.configure(wraplength=max(500, ev.width-10)), add='+')

    # ---------- calculation ----------
    @staticmethod
    def normalize_employee_id(raw):
        s = str(raw or '').strip().upper()
        if s.isdigit():
            n = int(s)
            if n <= 0:
                raise ValueError('Employee ID must be EMP + a positive number, for example EMP001 or EMP010.')
            return f'EMP{n:03d}', n
        if s.startswith('EMP') and s[3:].isdigit():
            n = int(s[3:])
            if n <= 0:
                raise ValueError('Employee ID must be EMP + a positive number, for example EMP001 or EMP010.')
            return f'EMP{n:03d}', n
        raise ValueError('Employee ID must use the EMPXXX format, for example EMP001, EMP010 or EMP1000.')

    def next_employee_id(self):
        row = self.db.execute('SELECT COALESCE(MAX(emp_number),0)+1 AS n FROM employees').fetchone()
        n = max(1, int(row['n'] or 1))
        return f'EMP{n:03d}'

    def normalize_employee_filter(self, raw):
        s = str(raw or '').strip().upper()
        if not s:
            return ''
        try:
            return self.normalize_employee_id(s)[0]
        except Exception:
            return s

    def employees_rows(self):
        return self.db.execute('SELECT * FROM employees ORDER BY active DESC, emp_number, id').fetchall()

    def plots(self, eid, include_inactive=False):
        sql = 'SELECT * FROM plots WHERE employee_id=?'
        if not include_inactive:
            sql += ' AND active=1'
        sql += ' ORDER BY id'
        return self.db.execute(sql, (eid,)).fetchall()

    def rules(self, on_date=None):
        if on_date:
            rows = self.db.execute('''SELECT code,mult FROM rule_history h
                WHERE effective_from<=? AND h.id=(SELECT h2.id FROM rule_history h2
                WHERE h2.code=h.code AND h2.effective_from<=? ORDER BY h2.effective_from DESC,h2.id DESC LIMIT 1)''',
                                   (on_date, on_date)).fetchall()
            return {r['code']: r['mult'] for r in rows}
        return {r['code']: r['mult'] for r in self.db.execute('SELECT code,mult FROM rules')}

    def rate_for_plot_day(self, plot_id, day):
        row = self.db.execute('''SELECT daily_rate FROM plot_rate_history
            WHERE plot_id=? AND effective_from<=?
            ORDER BY effective_from DESC,id DESC LIMIT 1''', (plot_id, day)).fetchone()
        if row:
            return float(row['daily_rate'])
        p = self.db.execute('SELECT daily_rate FROM plots WHERE id=?', (plot_id,)).fetchone()
        return float(p['daily_rate']) if p else 0.0

    def _rule_map_for_month(self,month):
        month=self.month_valid(month)
        cache=getattr(self,'_rule_month_cache',{})
        if month in cache:return cache[month]
        y,m=map(int,month.split('-'));days=calendar.monthrange(y,m)[1];before=f'{month}-32'
        rows=self.db.execute('SELECT code,effective_from,mult FROM rule_history WHERE effective_from<? ORDER BY code,effective_from,id',(before,)).fetchall()
        hist={}
        for r in rows:hist.setdefault(r['code'],[]).append((r['effective_from'],float(r['mult'])))
        out={}
        for d in range(1,days+1):
            ds=f'{month}-{d:02d}';out[ds]={}
            for code,arr in hist.items():
                val=0.0
                for eff,mult in arr:
                    if eff<=ds:val=mult
                    else:break
                out[ds][code]=val
        cache[month]=out;self._rule_month_cache=cache;return out

    def _rate_month_map(self,plot_ids,month):
        month=self.month_valid(month);ids=tuple(sorted({int(x) for x in plot_ids}));key=(ids,month)
        cache=getattr(self,'_rate_month_cache',{})
        if key in cache:return cache[key]
        if not ids:return {}
        y,m=map(int,month.split('-'));days=calendar.monthrange(y,m)[1];q=','.join('?'*len(ids))
        rows=self.db.execute(f'SELECT plot_id,effective_from,daily_rate FROM plot_rate_history WHERE plot_id IN ({q}) AND effective_from<? ORDER BY plot_id,effective_from,id',(*ids,f'{month}-32')).fetchall()
        hist={}
        for r in rows:hist.setdefault(int(r['plot_id']),[]).append((r['effective_from'],float(r['daily_rate'])))
        out={pid:{} for pid in ids}
        for pid in ids:
            arr=hist.get(pid,[]);idx=0;cur=0.0
            for d in range(1,days+1):
                ds=f'{month}-{d:02d}'
                while idx<len(arr) and arr[idx][0]<=ds:cur=arr[idx][1];idx+=1
                out[pid][ds]=cur
        cache[key]=out;self._rate_month_cache=cache;return out


    def month_total_amount(self, month, start=1, end=None, active_only=False):
        month=self.month_valid(month);y,m=map(int,month.split('-'));maxday=calendar.monthrange(y,m)[1]
        start=max(1,int(start));end=min(maxday,int(end if end is not None else maxday));end=max(start,end)
        lo,hi=f'{month}-{start:02d}',f'{month}-{end:02d}';active_clause=' AND e.active=1' if active_only else ''
        row=self.db.execute(f'''SELECT COALESCE(SUM(
            COALESCE((SELECT rh.mult FROM rule_history rh WHERE rh.code=a.code AND rh.effective_from<=a.day ORDER BY rh.effective_from DESC,rh.id DESC LIMIT 1),0.0)
            * COALESCE((SELECT ph.daily_rate FROM plot_rate_history ph WHERE ph.plot_id=a.plot_id AND ph.effective_from<=a.day ORDER BY ph.effective_from DESC,ph.id DESC LIMIT 1),p.daily_rate)
        ),0.0) FROM attendance a JOIN employees e ON e.id=a.employee_id{active_clause} JOIN plots p ON p.id=a.plot_id AND p.active=1 WHERE a.day>=? AND a.day<=?''',(lo,hi)).fetchone()
        return float(row[0] or 0.0)

    def month_summary(self,month,start=1,end=None,name_filter='',empid_filter='',plot_filter='',active_only=False,limit=None,offset=0):
        """Exact plot-level monthly summary with SQL-side filtering and pagination."""
        month=self.month_valid(month);y,m=map(int,month.split('-'));maxday=calendar.monthrange(y,m)[1]
        start=max(1,int(start));end=min(maxday,int(end if end is not None else maxday));end=max(start,end)
        lo,hi=f'{month}-{start:02d}',f'{month}-{end:02d}'
        where=['e.id IS NOT NULL','p.active=1'];args=[]
        if active_only:where.append('e.active=1')
        nf=str(name_filter or '').strip();idf=str(empid_filter or '').strip();pf=str(plot_filter or '').strip()
        if nf:where.append('e.name LIKE ? COLLATE NOCASE');args.append(f'%{nf}%')
        if idf:where.append('e.empid LIKE ? COLLATE NOCASE');args.append(f'%{idf}%')
        if pf:where.append('p.plot_no LIKE ? COLLATE NOCASE');args.append(f'%{pf}%')
        where_sql=' AND '.join(where)
        params=[hi]+[lo,hi]+args
        base=f'''
            SELECT e.id AS employee_id,e.empid,e.emp_number,e.name,e.active,p.id AS plot_id,p.plot_no,
                   COALESCE(SUM(COALESCE((SELECT rh.mult FROM rule_history rh
                       WHERE rh.code=a.code AND rh.effective_from<=a.day
                       ORDER BY rh.effective_from DESC,rh.id DESC LIMIT 1),0.0)),0.0) AS units,
                   COALESCE(SUM(COALESCE((SELECT rh.mult FROM rule_history rh
                       WHERE rh.code=a.code AND rh.effective_from<=a.day
                       ORDER BY rh.effective_from DESC,rh.id DESC LIMIT 1),0.0) *
                       COALESCE((SELECT ph.daily_rate FROM plot_rate_history ph
                           WHERE ph.plot_id=a.plot_id AND ph.effective_from<=a.day
                           ORDER BY ph.effective_from DESC,ph.id DESC LIMIT 1),p.daily_rate)),0.0) AS amount,
                   COALESCE((SELECT ph2.daily_rate FROM plot_rate_history ph2
                       WHERE ph2.plot_id=p.id AND ph2.effective_from<=?
                       ORDER BY ph2.effective_from DESC,ph2.id DESC LIMIT 1),p.daily_rate) AS rate
            FROM employees e
            JOIN plots p ON p.employee_id=e.id AND p.active=1
            LEFT JOIN attendance a ON a.employee_id=e.id AND a.plot_id=p.id AND a.day>=? AND a.day<=?
            WHERE {where_sql}
            GROUP BY p.id
        '''
        sql=f'''WITH grouped AS ({base})
            SELECT grouped.*, COUNT(*) OVER() AS total_count,
                   COALESCE(SUM(grouped.amount) OVER(),0.0) AS grand_amount
            FROM grouped
            ORDER BY grouped.active DESC, grouped.emp_number, grouped.plot_id'''
        if limit is not None:sql += ' LIMIT ? OFFSET ?';params += [max(1,int(limit)),max(0,int(offset))]
        rows=self.db.execute(sql,params).fetchall()
        return rows

    def calc_plot(self,eid,pid,month,start=1,end=None):
        month=self.month_valid(month); y,m=map(int,month.split('-')); maxday=calendar.monthrange(y,m)[1]
        start=max(1,int(start)); end=min(maxday,int(end if end is not None else maxday))
        if end < start:
            end=start
        rows=self.db.execute(
            'SELECT id,day,code FROM attendance WHERE employee_id=? AND plot_id=? '
            'AND day>=? AND day<=? ORDER BY day,id',
            (eid,pid,f'{month}-{start:02d}',f'{month}-{end:02d}')
        ).fetchall()
        # One calendar date = one attendance value. This is intentionally keyed by
        # the date string, so even a legacy database containing duplicate rows cannot
        # inflate salary/present-day totals.
        day_map={}
        for r in rows:
            day=str(r['day'] or '')
            if len(day) >= 10 and day[:7] == month:
                day_map[day]=self.normalize_code(r['code'])
        rmap=self._rule_map_for_month(month)
        rates=self._rate_month_map([pid],month).get(pid,{})
        units=money=0.0
        clean_rows=[]
        for day, code in day_map.items():
            mult=rmap.get(day,{}).get(code,0.0)
            if mult == 0.0 and code not in ('A', ''):
                continue
            rr=rates.get(day,self.rate_for_plot_day(pid,day))
            units += float(mult)
            money += float(mult) * float(rr)
            clean_rows.append((day, code))
        current_rate=rates.get(f'{month}-{maxday:02d}',self.rate_for_plot_day(pid,f'{month}-{maxday:02d}'))
        return round(units,4),round(money,2),clean_rows,current_rate

    def calc_employee(self,eid,month,start=1,end=None):
        units=money=0.0;details=[]
        for p in self.plots(eid):
            u,a,rows,rate=self.calc_plot(eid,p['id'],month,start,end);units+=u;money+=a;details.append((p,u,a,rows,rate))
        return units,money,details

    def month_valid(self, month):
        try:
            y, m = map(int, str(month).strip().split('-'))
            if len(str(month).strip()) != 7 or y < 1 or not 1 <= m <= 12:
                raise ValueError
            calendar.monthrange(y, m)
            return f'{y:04d}-{m:02d}'
        except Exception:
            raise ValueError('Month must be YYYY-MM, for example 2026-09.')

    def previous_month(self, month):
        y, m = map(int, month.split('-'))
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return f'{y:04d}-{m:02d}'

    def employee_paid_amount(self, employee_id, month):
        row = self.db.execute('SELECT COALESCE(SUM(amount),0) AS paid FROM payments WHERE employee_id=? AND month=?',
                              (employee_id, month)).fetchone()
        return float(row['paid'] or 0)

    def employee_advance_amount(self, employee_id, month):
        month=self.month_valid(month); y,m=map(int,month.split('-')); hi=f'{month}-{calendar.monthrange(y,m)[1]:02d}'
        row=self.db.execute('SELECT COALESCE(SUM(amount),0) AS total FROM advances WHERE employee_id=? AND advance_date>=? AND advance_date<=?',
                            (employee_id,f'{month}-01',hi)).fetchone()
        return float(row['total'] or 0)

    def month_advance_total(self, month, active_only=False):
        month=self.month_valid(month); y,m=map(int,month.split('-')); hi=f'{month}-{calendar.monthrange(y,m)[1]:02d}'
        active_clause=' JOIN employees e ON e.id=a.employee_id AND e.active=1' if active_only else ''
        row=self.db.execute(f'SELECT COALESCE(SUM(a.amount),0) FROM advances a{active_clause} WHERE a.advance_date>=? AND a.advance_date<=?',(f'{month}-01',hi)).fetchone()
        return float(row[0] or 0)

    @staticmethod
    def display_advance_date(iso_date):
        return datetime.strptime(str(iso_date), '%Y-%m-%d').strftime('%d.%m.%y')

    def advance_rows(self, employee_id, month):
        month=self.month_valid(month); y,m=map(int,month.split('-')); hi=f'{month}-{calendar.monthrange(y,m)[1]:02d}'
        return self.db.execute('SELECT * FROM advances WHERE employee_id=? AND advance_date>=? AND advance_date<=? ORDER BY advance_date,id',
                                (employee_id,f'{month}-01',hi)).fetchall()

    def payment_rows(self,month,offset=0,limit=None):
        month=self.month_valid(month)
        sql='SELECT * FROM employees WHERE active=1 ORDER BY emp_number,id'
        args=[]
        if limit is not None:
            sql+=' LIMIT ? OFFSET ?';args=[int(limit),max(0,int(offset))]
        es=self.db.execute(sql,args).fetchall();out=[]
        for e in es:
            earned=float(self.calc_employee(e['id'],month)[1])
            paid=self.employee_paid_amount(e['id'],month)
            advance=self.employee_advance_amount(e['id'],month)
            out.append((e,earned,paid,advance,max(earned-advance-paid,0.0)))
        return out

    def mark_employee_paid(self, employee_id, month):
        try:
            month = self.month_valid(month)
            e = self.db.execute('SELECT * FROM employees WHERE id=?', (employee_id,)).fetchone()
            if not e:
                return
            earned = float(self.calc_employee(employee_id, month)[1])
            paid = self.employee_paid_amount(employee_id, month)
            advance = self.employee_advance_amount(employee_id, month)
            due = max(earned - advance - paid, 0.0)
            if due <= 0.005:
                messagebox.showinfo('Salary Payment', f'{e["name"]} is already fully paid for {month}.', parent=self)
                return
            self.db.execute('INSERT INTO payments(employee_id,month,amount,paid_on,note) VALUES(?,?,?,?,?)',
                            (employee_id, month, due, date.today().isoformat(), 'Marked as fully paid'))
            self.audit('MARK_PAID','payment',employee_id,{'month':month,'amount':due})
            self.db.commit()
            self.salary_payments(month)
        except Exception as ex:
            messagebox.showerror('Salary Payment', str(ex), parent=self)

    def mark_all_paid(self, month):
        try:
            month = self.month_valid(month)
            total_count=int(self.db.execute('SELECT COUNT(*) FROM employees WHERE active=1').fetchone()[0])
            due_total=0.0
            offset=0
            while offset < total_count:
                rows=self.payment_rows(month,offset,EMPLOYEE_PAGE_SIZE)
                if not rows:break
                due_total += sum(due for *_,due in rows if due > 0.005)
                offset += len(rows)
            if due_total <= 0.005:
                messagebox.showinfo('Salary Payment', f'No unpaid salary remains for {month}.', parent=self)
                return
            if not messagebox.askyesno('Mark Salaries Paid',
                    f'Mark all currently unpaid salary for {month} as paid?\n\nTotal to mark paid: ৳{due_total:,.2f}',
                    parent=self):
                return
            paid_on=date.today().isoformat()
            offset=0
            self.db.execute('BEGIN')
            try:
                while offset < total_count:
                    rows=self.payment_rows(month,offset,EMPLOYEE_PAGE_SIZE)
                    if not rows:break
                    for e,earned,paid,advance,due in rows:
                        if due > 0.005:
                            self.db.execute('INSERT INTO payments(employee_id,month,amount,paid_on,note) VALUES(?,?,?,?,?)',
                                            (e['id'],month,due,paid_on,'Marked all as paid'))
                    offset += len(rows)
                self.audit('MARK_ALL_PAID','payment',month,{'total_amount':due_total,'worker_count':total_count})
                self.db.commit()
            except Exception:
                self.db.rollback();raise
            self.salary_payments(month)
        except Exception as ex:
            messagebox.showerror('Salary Payment', str(ex), parent=self)

    def salary_payments(self, month=None, page=0):
        self._page_key = 'salary_payments'
        self.clear();month=month or date.today().strftime('%Y-%m')
        try:month=self.month_valid(month)
        except Exception:month=date.today().strftime('%Y-%m')
        self.header('Salary Payments','Record salary payments. Advance money is shown separately and deducted from the net salary still unpaid.')
        top=tk.Frame(self.main,bg=BG);top.pack(fill='x',padx=26,pady=8)
        tk.Label(top,text='Month (YYYY-MM)',bg=BG,fg=MUTED,font=('Segoe UI',10,'bold')).pack(side='left');mv=tk.StringVar(value=month);ent=ttk.Entry(top,textvariable=mv,width=11);ent.pack(side='left',padx=7)
        ttk.Button(top,text='MARK ALL UNPAID AS PAID',style='Accent.TButton',command=lambda:self.mark_all_paid(mv.get())).pack(side='left',padx=5)
        ttk.Button(top,text='REFRESH',command=lambda:self.salary_payments(mv.get(),0)).pack(side='left',padx=5)
        wrap=tk.Frame(self.main,bg=BG);wrap.pack(fill='both',expand=True,padx=26,pady=8)
        # Treeview belongs to tw, not wrap. The old build created it in wrap and then
        # attempted to grid it into tw, which caused the TclError:
        # "cannot use geometry manager grid ... already has slaves managed by pack".
        tw=tk.Frame(wrap,bg=BG)
        tw.pack(fill='both',expand=True)
        cols=('id','name','earned','advance','paid','due','status');tree=ttk.Treeview(tw,columns=cols,show='headings')
        for c,h,w,a in [('id','Employee ID',170,'e'),('name','Worker',190,'w'),('earned','Earned Salary',165,'e'),('advance','Advance',150,'e'),('paid','Already Paid',165,'e'),('due','Still Unpaid',165,'e'),('status','Status',110,'center')]:tree.heading(c,text=h);tree.column(c,width=w,anchor=a)
        tw.grid_rowconfigure(0,weight=1);tw.grid_columnconfigure(0,weight=1)
        sb=ModernScrollbar(tw,command=tree.yview,orient='vertical',thickness=15)
        hs=ModernScrollbar(tw,command=tree.xview,orient='horizontal',thickness=12,height=12)
        tree.configure(yscrollcommand=sb.set,xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew')
        sb.grid(row=0,column=1,sticky='ns',padx=(6,4))
        hs.grid(row=1,column=0,sticky='ew',pady=(5,4))
        self.register_scroll_area(tw,tree,'y',default=True);self.register_scroll_area(tw,tree,'x')
        total_count=int(self.db.execute('SELECT COUNT(*) FROM employees WHERE active=1').fetchone()[0]);maxp=max(0,(total_count-1)//EMPLOYEE_PAGE_SIZE);page=max(0,min(int(page),maxp));rows=self.payment_rows(month,page*EMPLOYEE_PAGE_SIZE,EMPLOYEE_PAGE_SIZE)
        selected={'id':None}
        for e,earned,paid,advance,due in rows:tree.insert('', 'end',iid=str(e['id']),values=(e['empid'],e['name'],f'৳{earned:,.2f}',f'৳{advance:,.2f}',f'৳{paid:,.2f}',f'৳{due:,.2f}','PAID' if due<=0.005 else 'UNPAID'))
        foot=tk.Frame(self.main,bg='#0d0f13',highlightbackground=BORDER,highlightthickness=1);foot.pack(fill='x',padx=26,pady=(0,8));stat=tk.Label(foot,text=f'Showing {page*EMPLOYEE_PAGE_SIZE+1 if rows else 0}–{page*EMPLOYEE_PAGE_SIZE+len(rows)} of {total_count} active workers  •  Page {page+1}/{maxp+1}',bg='#0d0f13',fg=MUTED,font=('Segoe UI',9));stat.pack(side='left',padx=14,pady=8)
        nav=tk.Frame(foot,bg='#0d0f13');nav.pack(side='right',padx=8,pady=5);prev=ttk.Button(nav,text='‹  PREVIOUS',command=lambda:self.salary_payments(month,page-1));prev.state(['disabled'] if page<=0 else ['!disabled']);prev.pack(side='left',padx=3);nxt=ttk.Button(nav,text='NEXT  ›',command=lambda:self.salary_payments(month,page+1));nxt.state(['disabled'] if page>=maxp else ['!disabled']);nxt.pack(side='left',padx=3)
        actions=tk.Frame(self.main,bg='#0d0f13',highlightbackground=BORDER,highlightthickness=1);actions.pack(fill='x',padx=26,pady=(0,10))
        def select(_=None):
            s=tree.selection();selected['id']=int(s[0]) if s else None
        tree.bind('<<TreeviewSelect>>',select);tree.bind('<Double-1>',lambda _e:self.mark_employee_paid(selected['id'],mv.get()) if selected['id'] else None)
        ttk.Button(actions,text='MARK SELECTED AS PAID',style='Accent.TButton',command=lambda:self.mark_employee_paid(selected['id'],mv.get()) if selected['id'] else messagebox.showinfo('Salary Payment','Select a worker first.',parent=self)).pack(side='right',padx=14,pady=9)
        total_due=max(self.month_total_amount(month,active_only=True)-self.month_advance_total(month,active_only=True)-float(self.db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE month=?',(month,)).fetchone()[0] or 0),0.0)
        tk.Label(self.main,text=f'Net salary still unpaid for {month}: ৳{total_due:,.2f}',bg=BG,fg=('#ff8181' if total_due>0.005 else '#8ab4ff'),font=('Segoe UI',16,'bold')).pack(anchor='e',padx=30,pady=(0,12))
        ent.bind('<Return>',lambda _e:self.salary_payments(mv.get(),0))

    # ---------- dashboard ----------
    def dashboard(self):
        self._page_key = 'dashboard'
        self.clear();month=date.today().strftime('%Y-%m')
        self.header('Dashboard','Monthly worker and plot summary. Open a worker to see every plot attendance chart. Large lists are loaded in pages for a responsive interface.')
        total_workers=int(self.db.execute('SELECT COUNT(*) FROM employees WHERE active=1').fetchone()[0]);today=date.today().isoformat()
        pres=int(self.db.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE day=? AND code!='A'",(today,)).fetchone()[0]);absn=int(self.db.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE day=? AND code='A'",(today,)).fetchone()[0])
        totalpay=self.month_total_amount(month,active_only=True);advances_total=self.month_advance_total(month,active_only=True);paid=float(self.db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE month=?',(month,)).fetchone()[0] or 0);due=max(totalpay-advances_total-paid,0.0)
        previous=self.previous_month(month)
        previous_total=self.month_total_amount(previous,active_only=True)
        previous_paid=float(self.db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE month=?',(previous,)).fetchone()[0] or 0)
        previous_due=max(previous_total-previous_paid,0.0)
        if previous_due>0.005:
            notice=tk.Frame(self.main,bg='#281719',highlightbackground='#6b3033',highlightthickness=1)
            notice.pack(fill='x',padx=26,pady=(2,8))
            tk.Label(notice,text='PAYMENT REMINDER',bg='#281719',fg='#ff9898',font=('Segoe UI',10,'bold')).pack(side='left',padx=14,pady=10)
            tk.Label(notice,text=f'{previous}: ৳{previous_due:,.2f} is still unpaid.',bg='#281719',fg=TEXT,font=('Segoe UI',10)).pack(side='left',padx=3,pady=10)
            ttk.Button(notice,text='REVIEW & PAY',style='Accent.TButton',command=lambda m=previous:self.salary_payments(m)).pack(side='right',padx=10,pady=6)
        if getattr(self,'_startup_health_note',''):
            note=tk.Frame(self.main,bg='#221b12',highlightbackground='#7c5a25',highlightthickness=1);note.pack(fill='x',padx=26,pady=(0,8))
            note_title = 'DATABASE RECOVERY' if ('Database integrity' in self._startup_health_note or 'foreign-key' in self._startup_health_note) else 'AUDIT REVIEW'
            tk.Label(note,text=note_title,bg='#221b12',fg='#f2c777',font=('Segoe UI',9,'bold')).pack(side='left',padx=12,pady=8)
            tk.Label(note,text=self._startup_health_note,bg='#221b12',fg=TEXT,font=('Segoe UI',9),justify='left',anchor='w',wraplength=900).pack(side='left',fill='x',expand=True,pady=8)
            ttk.Button(note,text='DISMISS',command=lambda:(setattr(self,'_startup_health_note',''),note.destroy())).pack(side='right',padx=8,pady=6)
        cards=tk.Frame(self.main,bg=BG);cards.pack(fill='x',padx=20,pady=8)
        for lab,val in [('Total Workers',total_workers),('Present Today',pres),('Absent Today',absn),('Gross Salary This Month',f'৳{totalpay:,.2f}'),('Salary Still Unpaid',f'৳{due:,.2f}')]:
            f=tk.Frame(cards,bg=PANEL,highlightbackground=BORDER,highlightthickness=1);f.pack(side='left',fill='both',expand=True,padx=4)
            tk.Label(f,text=lab,bg=PANEL,fg=MUTED,font=('Segoe UI',9)).pack(anchor='w',padx=12,pady=(12,3));tk.Label(f,text=str(val),bg=PANEL,fg=TEXT,font=('Segoe UI',16,'bold')).pack(anchor='w',padx=12,pady=(0,12))
        filters=tk.Frame(self.main,bg=BG);filters.pack(fill='x',padx=26,pady=(4,8));name_f,empid_f,plot_f=tk.StringVar(),tk.StringVar(),tk.StringVar()
        for label,var,width in [('Name',name_f,16),('Employee ID',empid_f,14),('Plot / Place',plot_f,16)]:
            tk.Label(filters,text=label,bg=BG,fg=MUTED,font=('Segoe UI',9,'bold')).pack(side='left',padx=(6,3));ttk.Entry(filters,textvariable=var,width=width).pack(side='left')
        holder=tk.Frame(self.main,bg=BG);holder.pack(fill='both',expand=True,padx=26,pady=4)
        wrap=tk.Frame(holder,bg=BG)
        wrap.pack(fill='both',expand=True)
        wrap.grid_rowconfigure(0,weight=1);wrap.grid_columnconfigure(0,weight=1)
        cols=('empid','name','plots','rates','present','amount');tree=ttk.Treeview(wrap,columns=cols,show='headings')
        for c,h,w,a in [('empid','Employee ID',170,'e'),('name','Name',190,'w'),('plots','Plot / Place',220,'w'),('rates','Daily Salary by Plot',280,'w'),('present','Present Day (P)',175,'e'),('amount','Total Amount',190,'e')]:tree.heading(c,text=h);tree.column(c,width=w,anchor=a,stretch=c in ('name','plots','rates'))
        sb=ModernScrollbar(wrap,command=tree.yview,orient='vertical',thickness=15)
        hs=ModernScrollbar(wrap,command=tree.xview,orient='horizontal',thickness=12,height=12)
        tree.configure(yscrollcommand=sb.set,xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew')
        sb.grid(row=0,column=1,sticky='ns',padx=(6,4))
        hs.grid(row=1,column=0,sticky='ew',pady=(5,4))
        self.register_scroll_area(wrap,tree,'y',default=True);self.register_scroll_area(wrap,tree,'x')
        page={'n':0,'total':0,'job':None};foot=tk.Frame(self.main,bg='#0d0f13',highlightbackground=BORDER,highlightthickness=1);foot.pack(fill='x',padx=26,pady=(5,10));status=tk.Label(foot,text='',bg='#0d0f13',fg=MUTED,font=('Segoe UI',9));status.pack(side='left',padx=14,pady=8);nav=tk.Frame(foot,bg='#0d0f13');nav.pack(side='right',padx=8,pady=5)
        def load(reset=True):
            if reset:page['n']=0
            nt,ni,np=name_f.get().strip(),empid_f.get().strip(),plot_f.get().strip();where=['e.active=1'];args=[]
            if nt:where.append('e.name LIKE ? COLLATE NOCASE');args.append(f'%{nt}%')
            ni=self.normalize_employee_filter(ni)
            if ni:where.append('e.empid LIKE ? COLLATE NOCASE');args.append(f'%{ni}%')
            if np:where.append('EXISTS (SELECT 1 FROM plots px WHERE px.employee_id=e.id AND px.active=1 AND px.plot_no LIKE ? COLLATE NOCASE)');args.append(f'%{np}%')
            wsql=' AND '.join(where);page['total']=int(self.db.execute(f'SELECT COUNT(*) FROM employees e WHERE {wsql}',args).fetchone()[0]);maxp=max(0,(page['total']-1)//EMPLOYEE_PAGE_SIZE);page['n']=min(page['n'],maxp);offset=page['n']*EMPLOYEE_PAGE_SIZE
            es=self.db.execute(f'SELECT e.* FROM employees e WHERE {wsql} ORDER BY e.emp_number,e.id LIMIT ? OFFSET ?',args+[EMPLOYEE_PAGE_SIZE,offset]).fetchall();tree.delete(*tree.get_children())
            for e in es:
                u,a,details=self.calc_employee(e['id'],month);ps=', '.join(str(p['plot_no']) for p,*_ in details) or '—';rates=', '.join(f"{p['plot_no']}: ৳{rate:,.2f}/day" for p,_,_,_,rate in details) or '—';tree.insert('', 'end',iid=str(e['id']),values=(e['empid'],e['name'],ps,rates,f'{u:g}P',f'৳{a:,.2f}'))
            first=offset+1 if es else 0;last=offset+len(es);status.config(text=f'Showing {first}–{last} of {page["total"]} active workers  •  Page {page["n"]+1}/{maxp+1}')
            for c in nav.winfo_children():c.destroy()
            b=ttk.Button(nav,text='‹  PREVIOUS',command=lambda:change(-1));b.state(['disabled'] if page['n']<=0 else ['!disabled']);b.pack(side='left',padx=3);b=ttk.Button(nav,text='NEXT  ›',command=lambda:change(1));b.state(['disabled'] if page['n']>=maxp else ['!disabled']);b.pack(side='left',padx=3)
        def change(d):page['n']=max(0,page['n']+d);load(False)
        def schedule(*_):
            if page['job'] is not None:
                try:self.after_cancel(page['job'])
                except Exception:pass
            page['job']=self.after(160,lambda:load(True))
        for v in (name_f,empid_f,plot_f):v.trace_add('write',schedule)
        tree.bind('<Double-1>',lambda _e:self.open_from_tree(tree,month));load(True)

    def open_from_tree(self, tree, month):
        s = tree.selection()
        if s:
            self.navigate(lambda: self.open_employee(int(s[0]), month), key='attendance')

    # ---------- employees ----------
    def employees(self):
        self._page_key = 'employees'
        """Scalable employee browser: only one page of rows is rendered into Tk."""
        self.clear()
        self.header('Employees','Add, edit or remove workers. Daily salary is set separately for each plot or place. Filter by Name, Employee ID or Plot / Place.')
        filters=tk.Frame(self.main,bg=BG);filters.pack(fill='x',padx=26,pady=(8,5))
        name_f,empid_f,plot_f=tk.StringVar(),tk.StringVar(),tk.StringVar()
        for label,var,width in [('Name',name_f,18),('Employee ID',empid_f,15),('Plot / Place',plot_f,17)]:
            tk.Label(filters,text=label,bg=BG,fg=MUTED,font=('Segoe UI',9,'bold')).pack(side='left',padx=(7,4))
            ttk.Entry(filters,textvariable=var,width=width).pack(side='left',padx=(0,8))
        actions=tk.Frame(self.main,bg=BG);actions.pack(fill='x',padx=26,pady=(3,8))
        ttk.Button(actions,text='Add Employee',style='Accent.TButton',command=lambda:self.navigate(self.employee_editor)).pack(side='left')
        holder=tk.Frame(self.main,bg=BG);holder.pack(fill='both',expand=True,padx=26,pady=(0,4))
        wrap=tk.Frame(holder,bg=BG);wrap.pack(fill='both',expand=True)
        wrap.grid_rowconfigure(0,weight=1);wrap.grid_columnconfigure(0,weight=1)
        cols=('id','name','plots','rates','present','money','active')
        tree=ttk.Treeview(wrap,columns=cols,show='headings',selectmode='extended')
        for c,h,w,a in [('id','Employee ID',170,'e'),('name','Name',190,'w'),('plots','Plot / Place',220,'w'),('rates','Daily Salary by Plot',280,'w'),('present','Current Month P',145,'e'),('money','Current Month Earned',195,'e'),('active','Active',80,'center')]:
            tree.heading(c,text=h);tree.column(c,width=w,anchor=a,stretch=c in ('name','plots','rates'))
        sb=ModernScrollbar(wrap,command=tree.yview,orient='vertical',thickness=15)
        hs=ModernScrollbar(wrap,command=tree.xview,orient='horizontal',thickness=12,height=12)
        tree.configure(yscrollcommand=sb.set,xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew')
        sb.grid(row=0,column=1,sticky='ns',padx=(6,4))
        hs.grid(row=1,column=0,sticky='ew',pady=(5,4))
        self.register_scroll_area(wrap,tree,'y',default=True);self.register_scroll_area(wrap,tree,'x')
        state={'page':0,'total':0,'job':None}
        footer=tk.Frame(self.main,bg='#0d0f13',highlightbackground=BORDER,highlightthickness=1);footer.pack(fill='x',padx=26,pady=(4,10))
        status=tk.Label(footer,text='',bg='#0d0f13',fg=MUTED,font=('Segoe UI',9));status.pack(side='left',padx=14,pady=8)
        nav=tk.Frame(footer,bg='#0d0f13');nav.pack(side='right',padx=8,pady=5)

        def load(reset=True):
            if reset: state['page']=0
            nt,ni,np=name_f.get().strip(),empid_f.get().strip(),plot_f.get().strip();where=['1=1'];args=[]
            if nt:where.append('e.name LIKE ? COLLATE NOCASE');args.append(f'%{nt}%')
            ni=self.normalize_employee_filter(ni)
            if ni:where.append('e.empid LIKE ? COLLATE NOCASE');args.append(f'%{ni}%')
            if np:where.append('EXISTS (SELECT 1 FROM plots px WHERE px.employee_id=e.id AND px.active=1 AND px.plot_no LIKE ? COLLATE NOCASE)');args.append(f'%{np}%')
            wsql=' AND '.join(where)
            state['total']=int(self.db.execute(f'SELECT COUNT(*) FROM employees e WHERE {wsql}',args).fetchone()[0])
            maxp=max(0,(state['total']-1)//EMPLOYEE_PAGE_SIZE);state['page']=min(state['page'],maxp);offset=state['page']*EMPLOYEE_PAGE_SIZE
            rows=self.db.execute(f'SELECT e.* FROM employees e WHERE {wsql} ORDER BY e.active DESC,e.emp_number,e.id LIMIT ? OFFSET ?',args+[EMPLOYEE_PAGE_SIZE,offset]).fetchall()
            tree.delete(*tree.get_children())
            month=date.today().strftime('%Y-%m')
            for e in rows:
                u,a,details=self.calc_employee(e['id'],month)
                ps=', '.join(str(p['plot_no']) for p,*_ in details) or '—'
                rates=', '.join(f"{p['plot_no']}: ৳{rate:,.2f}/day" for p,_,_,_,rate in details) or '—'
                tree.insert('', 'end',iid=str(e['id']),values=(e['empid'],e['name'],ps,rates,f'{u:g}P',f'৳{a:,.2f}','Yes' if e['active'] else 'No'))
            first=offset+1 if rows else 0;last=offset+len(rows);status.config(text=f'Showing {first}–{last} of {state["total"]} employees  •  Page {state["page"]+1}/{maxp+1}')
            for child in nav.winfo_children():child.destroy()
            b=ttk.Button(nav,text='‹  PREVIOUS',command=lambda:change(-1));b.state(['disabled'] if state['page']<=0 else ['!disabled']);b.pack(side='left',padx=3)
            b=ttk.Button(nav,text='NEXT  ›',command=lambda:change(1));b.state(['disabled'] if state['page']>=maxp else ['!disabled']);b.pack(side='left',padx=3)
        def change(delta):
            state['page']=max(0,state['page']+delta);load(False);tree.selection_remove(tree.selection());tree.yview_moveto(0)
        def schedule(*_):
            if state['job'] is not None:
                try:self.after_cancel(state['job'])
                except Exception:pass
            state['job']=self.after(180,lambda:load(True))
        for v in (name_f,empid_f,plot_f):v.trace_add('write',schedule)
        ttk.Button(actions,text='Edit Selected',command=lambda:self.edit_selected(tree)).pack(side='left',padx=6)
        ttk.Button(actions,text='Open Attendance',command=lambda:self.open_selected(tree)).pack(side='left')
        ttk.Button(actions,text='Remove Selected',command=lambda:self.remove_selected(tree)).pack(side='left',padx=6)
        tree.bind('<Double-1>',lambda _e:self.open_selected(tree))
        load(True)
        return tree

    def edit_selected(self, tree):
        s = tree.selection()
        if not s:
            messagebox.showinfo('Employee', 'Select an employee first.')
            return
        self.employee_editor(int(s[0]))

    def open_selected(self, tree):
        s = tree.selection()
        if s:
            self.navigate(lambda: self.open_employee(int(s[0]), date.today().strftime('%Y-%m')), key='attendance')

    def employee_editor(self, eid=None):
        self._page_key = 'employee_editor'
        """Full-window, landscape employee editor. Keeps all controls visible."""
        e = self.db.execute('SELECT * FROM employees WHERE id=?', (eid,)).fetchone() if eid else None
        self.clear()
        mode = 'EDIT EMPLOYEE' if e else 'ADD EMPLOYEE'
        self.header(mode, 'Enter worker information, then add each plot/location with its own daily salary. Every control remains inside the main WorkerPay window.')

        root = tk.Frame(self.main, bg=BG)
        root.pack(fill='both', expand=True, padx=22, pady=(4, 12))
        root.grid_columnconfigure(0, weight=1, uniform='editor')
        root.grid_columnconfigure(1, weight=1, uniform='editor')
        root.grid_rowconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=0)

        left = tk.Frame(root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        right = tk.Frame(root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

        vals = {}

        def field(parent, row, label, value, rule):
            tk.Label(parent, text=label, bg=PANEL, fg=TEXT,
                     font=('Segoe UI', 11, 'bold')).grid(row=row, column=0, sticky='w', padx=20, pady=(16, 5))
            v = tk.StringVar(value=value)
            ent = ttk.Entry(parent, textvariable=v, font=('Segoe UI', 11), justify='right' if label == 'Employee ID' else 'left')
            ent.grid(row=row + 1, column=0, sticky='ew', padx=20, pady=(0, 3), ipady=4)
            rule_lbl = tk.Label(parent, text=rule, bg=PANEL, fg=MUTED,
                                font=('Segoe UI', 9), justify='left', anchor='w', wraplength=320)
            rule_lbl.grid(row=row + 2, column=0, sticky='ew', padx=20, pady=(0, 9))
            parent.bind('<Configure>', lambda ev, lbl=rule_lbl, pref=parent:
                        lbl.configure(wraplength=max(260, pref.winfo_width()-42)), add='+')
            vals[label] = v
            return ent

        left.grid_columnconfigure(0, weight=1)
        id_ent = field(left, 0, 'Employee ID', e['empid'] if e else self.next_employee_id(),
                       'Rule: Use a unique Employee ID in EMP + digits format. Examples: EMP001, EMP010, EMP1000. Plot / Place numbers are separate and are never converted to EMP IDs.')
        field(left, 3, 'Name', e['name'] if e else '',
              'Rule: Enter the worker’s full name exactly as it should appear in attendance, salary reports and exports. Example: Mamun.')
        field(left, 6, 'Start Date', e['start'] if e else date.today().isoformat(),
              'Rule: Enter the worker’s starting date in YYYY-MM-DD format. Example: 2026-09-26.')

        tk.Label(left, text='Worker Status', bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 11, 'bold')).grid(row=9, column=0, sticky='w', padx=20, pady=(12, 4))
        active = tk.BooleanVar(value=bool(e['active']) if e else True)
        ttk.Checkbutton(left, text='Active employee', variable=active).grid(row=10, column=0, sticky='w', padx=20, pady=(0, 4))
        status_rule = tk.Label(left,
            text='Rule: Keep this enabled while the worker is active. Disable it after the worker leaves. Existing attendance, salary history and payment records remain available.',
            bg=PANEL, fg=MUTED, font=('Segoe UI', 9), justify='left', anchor='w', wraplength=320)
        status_rule.grid(row=11, column=0, sticky='ew', padx=20, pady=(0, 12))
        left.bind('<Configure>', lambda ev: status_rule.configure(wraplength=max(260, ev.width-42)), add='+')

        tk.Label(right, text='PLOTS / PLACES & DAILY SALARY', bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=20, pady=(16, 4))
        plot_rule = tk.Label(right,
            text=('Rule: One row = one plot or work location. Enter the plot/place exactly as it is used in your records. The salary beside it is this worker’s Daily Salary for ONE complete P-day at THAT plot. Different plots may use different daily rates. Example: 1250 → ৳600/day; 1356 → ৳650/day.'),
            bg=PANEL, fg='#a9c7ff', font=('Segoe UI', 9), justify='left', anchor='w', wraplength=300)
        plot_rule.pack(fill='x', padx=20, pady=(0, 10))
        right.bind('<Configure>', lambda ev: plot_rule.configure(wraplength=max(240, ev.width-40)), add='+')

        plot_box = tk.Frame(right, bg='#141821', highlightbackground=BORDER, highlightthickness=1)
        plot_box.pack(fill='both', expand=True, padx=18, pady=(0, 8))
        hdr = tk.Frame(plot_box, bg='#141821')
        hdr.pack(fill='x', padx=10, pady=(10, 5))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, minsize=170)
        hdr.grid_columnconfigure(2, minsize=82)
        tk.Label(hdr, text='PLOT / PLACE', bg='#141821', fg=MUTED,
                 font=('Segoe UI', 9, 'bold'), anchor='w').grid(row=0, column=0, sticky='ew')
        tk.Label(hdr, text='DAILY SALARY (৳/DAY)', bg='#141821', fg=MUTED,
                 font=('Segoe UI', 9, 'bold'), anchor='w').grid(row=0, column=1, padx=(8, 6), sticky='ew')
        tk.Label(hdr, text='ACTION', bg='#141821', fg=MUTED,
                 font=('Segoe UI', 9, 'bold'), anchor='center').grid(row=0, column=2, sticky='ew')

        rows_canvas = tk.Canvas(plot_box, bg='#141821', highlightthickness=0)
        rows_scroll = ModernScrollbar(plot_box, orient='vertical', command=rows_canvas.yview, thickness=16)
        rows_frame = tk.Frame(rows_canvas, bg='#141821')
        rows_window = rows_canvas.create_window((0, 0), window=rows_frame, anchor='nw')
        rows_frame.bind('<Configure>', lambda ev: rows_canvas.configure(scrollregion=rows_canvas.bbox('all')))
        rows_canvas.bind('<Configure>', lambda ev: rows_canvas.itemconfigure(rows_window, width=max(1, ev.width-4)))
        rows_canvas.configure(yscrollcommand=rows_scroll.set)
        rows_canvas.pack(side='left', fill='both', expand=True, padx=(8, 0), pady=4)
        rows_scroll.pack(side='right', fill='y', padx=(0, 8), pady=4)
        self.register_scroll_area(plot_box, rows_canvas, axis='y', default=True)
        plot_rows = []

        def add_plot_row(plot_no='', rate='', scroll_to=False):
            row = tk.Frame(rows_frame, bg='#141821')
            row.pack(fill='x', padx=4, pady=4)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, minsize=150)
            row.grid_columnconfigure(2, minsize=82)
            pn = tk.Entry(row, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                          relief='solid', bd=1, highlightthickness=1,
                          highlightbackground='#46505f', highlightcolor=ACCENT,
                          font=('Segoe UI', 10))
            if plot_no != '': pn.insert(0, str(plot_no))
            pn.grid(row=0, column=0, sticky='ew', ipady=6)
            rr = tk.Entry(row, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                          relief='solid', bd=1, highlightthickness=1,
                          highlightbackground='#46505f', highlightcolor=ACCENT,
                          font=('Segoe UI', 10))
            if rate != '': rr.insert(0, str(rate))
            rr.grid(row=0, column=1, sticky='ew', padx=(8, 8), ipady=6)
            holder = {'row': row, 'pn': pn, 'rr': rr}
            def remove():
                if len(plot_rows) == 1:
                    pn.delete(0, 'end'); rr.delete(0, 'end'); pn.focus_set(); return
                row.destroy(); plot_rows.remove(holder)
                rows_frame.update_idletasks(); rows_canvas.configure(scrollregion=rows_canvas.bbox('all'))
            tk.Button(row, text='REMOVE', command=remove, bg=PANEL2, fg=TEXT,
                      activebackground=RED, activeforeground='white', relief='flat', bd=0,
                      cursor='hand2', font=('Segoe UI', 9, 'bold'), padx=7, pady=7).grid(row=0, column=2, sticky='ew')
            plot_rows.append(holder)
            rows_frame.update_idletasks(); rows_canvas.configure(scrollregion=rows_canvas.bbox('all'))
            if scroll_to:
                self.after_idle(lambda: rows_canvas.yview_moveto(1.0))
            return holder

        existing = self.plots(eid, include_inactive=True) if e else []
        if existing:
            for p in existing: add_plot_row(p['plot_no'], p['daily_rate'])
        else:
            add_plot_row()
        self.after_idle(lambda: rows_canvas.yview_moveto(0.0))
        tk.Button(right, text='+  ADD PLOT / PLACE', command=lambda: add_plot_row(scroll_to=True),
                  bg=ACCENT, fg='white', activebackground='#4f93ff', activeforeground='white',
                  relief='flat', bd=0, cursor='hand2', font=('Segoe UI', 10, 'bold'),
                  padx=18, pady=9).pack(anchor='w', padx=18, pady=(0, 12))

        action = tk.Frame(root, bg='#0d0f13', highlightbackground=BORDER, highlightthickness=1)
        action.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        info_lbl = tk.Label(action, text='Information is saved to the WorkerPay database when you confirm.',
                            bg='#0d0f13', fg=MUTED, font=('Segoe UI', 9), anchor='w', justify='left')
        info_lbl.pack(side='left', fill='x', expand=True, padx=16, pady=9)

        def back():
            self.employees()

        def save():
            try:
                empid, emp_number = self.normalize_employee_id(vals['Employee ID'].get())
                vals['Employee ID'].set(empid)
                name = vals['Name'].get().strip()
                st = vals['Start Date'].get().strip()
                datetime.strptime(st, '%Y-%m-%d')
                if not empid: raise ValueError('Employee ID is required.')
                if not name: raise ValueError('Name is required.')
                parsed, seen = [], set()
                for item in list(plot_rows):
                    pn = item['pn'].get().strip(); rate_text = item['rr'].get().strip()
                    if not pn and not rate_text: continue
                    if not pn: raise ValueError('Every plot row must contain a Plot / Place.')
                    if any(ch in pn for ch in '\t\r\n'): raise ValueError('Plot / Place cannot contain line breaks.')
                    key = pn.casefold()
                    if key in seen: raise ValueError(f'Duplicate plot / place: {pn}')
                    rate = safe_float(rate_text, f'Daily Salary for plot {pn}')
                    if rate < 0: raise ValueError(f'Daily Salary for plot {pn} cannot be negative.')
                    seen.add(key); parsed.append((pn, rate))
                if not parsed: raise ValueError('Add at least one Plot / Place with its Daily Salary.')
                now = date.today().isoformat()
                if e:
                    eid2 = e['id']
                    self.db.execute('UPDATE employees SET empid=?,emp_number=?,name=?,start=?,active=? WHERE id=?',
                                    (empid, emp_number, name, st, int(active.get()), eid2))
                    current = self.db.execute('SELECT * FROM plots WHERE employee_id=?', (eid2,)).fetchall()
                    ci = {str(r['plot_no']).casefold(): r for r in current}; keep=set()
                    for pn, rate in parsed:
                        old = ci.get(pn.casefold())
                        if old:
                            keep.add(old['id'])
                            if abs(float(old['daily_rate'])-rate) > 1e-9:
                                self.db.execute('UPDATE plots SET plot_no=?,daily_rate=?,active=1 WHERE id=?',(pn,rate,old['id']))
                                self.db.execute('INSERT OR REPLACE INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(old['id'],now,rate))
                            else:
                                self.db.execute('UPDATE plots SET plot_no=?,active=1 WHERE id=?',(pn,old['id']))
                        else:
                            cur=self.db.execute('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',(eid2,pn,rate))
                            keep.add(cur.lastrowid)
                            self.db.execute('INSERT OR REPLACE INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(cur.lastrowid,st,rate))
                    for old in current:
                        if old['id'] not in keep: self.db.execute('UPDATE plots SET active=0 WHERE id=?',(old['id'],))
                else:
                    cur=self.db.execute('INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,?)',(empid,emp_number,name,0,st,int(active.get())))
                    eid2=cur.lastrowid
                    for pn,rate in parsed:
                        curp=self.db.execute('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',(eid2,pn,rate))
                        self.db.execute('INSERT OR REPLACE INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(curp.lastrowid,st,rate))
                self.audit('EDIT_EMPLOYEE' if e else 'ADD_EMPLOYEE','employee',eid2,{'empid':empid,'name':name,'plots':parsed})
                self.db.commit()
                getattr(self,'_rate_month_cache',{}).clear()
                self.navigate(self.employees)
            except sqlite3.IntegrityError:
                messagebox.showerror('Employee', 'Employee ID must be unique. Use EMP001 / EMP010 / EMP1000 format. Plot / Place names must be unique within the same worker.', parent=self)
            except Exception as ex:
                messagebox.showerror('Employee', str(ex), parent=self)

        ttk.Button(action, text='CANCEL / BACK', command=lambda: self.navigate(back)).pack(side='right', padx=6, pady=7)
        ttk.Button(action, text=('SAVE CHANGES' if e else 'ADD EMPLOYEE'), style='Accent.TButton', command=save).pack(side='right', padx=(2, 14), pady=7, ipadx=8)
        try: self.unbind('<Control-Return>')
        except Exception: pass
        self.bind('<Control-Return>', lambda _e: save())
        id_ent.focus_set()

    def remove_selected(self, tree):
        """Remove all selected workers; the previous version only deleted the first row."""
        selected=list(tree.selection())
        if not selected:
            messagebox.showinfo('Employee','Select one or more employees first.',parent=self); return
        try: ids=[int(x) for x in selected]
        except (TypeError,ValueError):
            messagebox.showerror('Employee','The selected employee record could not be read.',parent=self); return
        q=','.join('?' for _ in ids)
        rows=self.db.execute(f'SELECT id,empid,name FROM employees WHERE id IN ({q}) ORDER BY id',ids).fetchall()
        if not rows:return
        if len(rows)==1: detail=f"Remove {rows[0]['name']} ({rows[0]['empid']})?"
        else:
            shown='\n'.join(f"• {r['name']} ({r['empid']})" for r in rows[:8]); more=f"\n• … and {len(rows)-8} more" if len(rows)>8 else ''
            detail=f"Remove {len(rows)} selected employees?\n\n{shown}{more}"
        detail+='\n\nThis permanently removes the selected worker records, their plots, attendance and payment records.'
        if not messagebox.askyesno('Remove Employee',detail,parent=self):return
        try:
            self.db.execute('BEGIN'); self.db.executemany('DELETE FROM employees WHERE id=?',[(i,) for i in ids]); self.audit('DELETE_EMPLOYEE','employee',','.join(map(str,ids)),{'count':len(ids)}); self.db.commit(); self.employees()
        except Exception as ex:
            try:self.db.rollback()
            except Exception:pass
            messagebox.showerror('Employee',f'Could not remove the selected employee(s): {ex}',parent=self)

    # ---------- attendance ----------
    def back_to_employees(self):
        # Back must never depend on the transient animation state or a lambda page key.
        if self._transition_job is not None:
            try:self.after_cancel(self._transition_job)
            except Exception:pass
            self._transition_job=None
        self.navigate(self.employees, duration=0, key='employees')

    def open_employee(self, eid, month):
        self._page_key = 'attendance'
        e = self.db.execute('SELECT * FROM employees WHERE id=?', (eid,)).fetchone()
        if not e:
            return
        self.clear()
        page_token = self._page_generation
        self.header(f"{e['name']}  •  {e['empid']}",
                    'Attendance is separated by plot. Every chart automatically shows Day 1 through the last day of the selected month.')

        top = tk.Frame(self.main, bg=BG)
        top.pack(fill='x', padx=26, pady=5)
        tk.Label(top, text='Month (YYYY-MM)', bg=BG, fg=MUTED, font=('Segoe UI', 10, 'bold')).pack(side='left')
        mv = tk.StringVar(value=month)
        month_entry = ttk.Entry(top, textvariable=mv, width=12)
        month_entry.pack(side='left', padx=6)
        tk.Label(top, text='Change the month and the attendance charts refresh automatically.',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(side='left', padx=8)
        ttk.Button(top, text='Edit Employee / Plots', command=lambda: self.navigate(lambda: self.employee_editor(eid), key='employee_editor')).pack(side='right', padx=6)
        ttk.Button(top, text='Back to Employees', style='Accent.TButton', command=self.back_to_employees).pack(side='right')

        scroll_holder = tk.Frame(self.main, bg=BG)
        scroll_holder.pack(fill='both', expand=True, padx=(26, 0), pady=8)
        canvas = tk.Canvas(scroll_holder, bg=BG, highlightthickness=0, bd=0)
        vs = ModernScrollbar(scroll_holder, command=canvas.yview, orient='vertical', thickness=13, width=13)
        outer = tk.Frame(canvas, bg=BG)
        outer_window = canvas.create_window((0, 0), window=outer, anchor='nw')
        def sync_outer(_ev=None):
            try:
                canvas.itemconfigure(outer_window, width=max(1, canvas.winfo_width()-2))
                canvas.configure(scrollregion=canvas.bbox('all'))
            except tk.TclError:
                pass
        outer.bind('<Configure>', lambda ev: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', sync_outer)
        canvas.configure(yscrollcommand=vs.set, confine=True)
        canvas.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y', padx=(3, 5), pady=2)
        self.register_scroll_area(scroll_holder, canvas, axis='y', default=True)
        self.after_idle(sync_outer)

        status = tk.Label(self.main, text='', bg=BG, fg=RED, font=('Segoe UI', 9, 'bold'))
        status.pack(fill='x', padx=26, pady=(0, 6))

        pending = {'job': None, 'alive': True}
        self._attendance_render_pending = pending

        def render_charts(*_):
            if pending['job'] is not None:
                try:
                    self.after_cancel(pending['job'])
                except Exception:
                    pass
            pending['job'] = self.after(90, do_render)

        def do_render():
            pending['job'] = None
            if getattr(self,'_attendance_render_pending',None) is not pending or page_token != self._page_generation or not self.winfo_exists():
                return
            value = mv.get().strip()
            try:
                y, m = map(int, value.split('-'))
                if len(value) != 7 or y < 1 or not (1 <= m <= 12):
                    raise ValueError
                days = calendar.monthrange(y, m)[1]
            except Exception:
                try:
                    status.config(text='Enter a valid month in YYYY-MM format, for example 2026-09.')
                except tk.TclError:
                    return
                return
            try:
                status.config(text=f'{value}: attendance chart refreshed for Day 1 through Day {days}.', fg='#8ab4ff')
            except tk.TclError:
                return
            try: canvas.yview_moveto(0.0)
            except tk.TclError: pass
            for child in outer.winfo_children():
                child.destroy()
            self._prune_scroll_areas()
            active_plots = self.plots(eid)
            if not active_plots:
                tk.Label(outer, text='No active plots. Edit the employee and add a plot.', bg=BG, fg=MUTED).pack(pady=30)
                return
            # Render a couple of plot cards per idle slice. This avoids one long UI
            # block when a worker has many plot/location records.
            state={'i':0,'plots':active_plots}
            def render_chunk():
                if getattr(self,'_attendance_render_pending',None) is not pending or page_token != self._page_generation or not self.winfo_exists():return
                for _ in range(2):
                    if state['i']>=len(state['plots']):break
                    self.plot_chart(outer,e,state['plots'][state['i']],value);state['i']+=1
                sync_outer()
                if state['i']<len(state['plots']):self.after_idle(render_chunk)
                else:
                    sep=tk.Frame(outer,bg=BG,height=1);sep.pack(fill='x',pady=(10,0))
                    self.build_advance_section(outer, e, value)
                    sync_outer()
                    self.after(25,lambda token=page_token: (canvas.yview_moveto(0.0) if token == self._page_generation and canvas.winfo_exists() else None))
            self.after_idle(render_chunk)

        # Live month refresh: changing 2026-09 to 2026-10 immediately rebuilds every plot chart to 31 days.
        mv.trace_add('write', render_charts)
        render_charts()
        month_entry.focus_set()
        month_entry.selection_range(0, 'end')

    def build_advance_section(self, parent, e, month):
        """Employee-wide advance ledger with add/edit/delete and explicit save."""
        card=tk.Frame(parent,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        card.pack(fill='x',pady=(14,12))
        tk.Label(card,text='ADVANCE MONEY — EMPLOYEE-WIDE',bg=PANEL,fg=TEXT,font=('Segoe UI',14,'bold')).pack(anchor='w',padx=14,pady=(12,2))
        tk.Label(card,text="Record money given in advance for this employee. Date: DD.MM.YY. Advances are employee-wide, not plot-specific, and are deducted once from the selected month's net salary.",bg=PANEL,fg=MUTED,font=('Segoe UI',9),wraplength=900,justify='left').pack(anchor='w',padx=14,pady=(0,10))
        form=tk.Frame(card,bg=PANEL2);form.pack(fill='x',padx=12,pady=(0,10))
        tk.Label(form,text='Date (DD.MM.YY)',bg=PANEL2,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=0,column=0,padx=(10,5),pady=(10,4),sticky='w')
        date_var=tk.StringVar(value=f"01.{datetime.strptime(month+'-01','%Y-%m-%d').strftime('%m.%y')}")
        ttk.Entry(form,textvariable=date_var,width=13).grid(row=1,column=0,padx=(10,5),pady=(0,10),sticky='ew')
        tk.Label(form,text='Amount',bg=PANEL2,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=0,column=1,padx=5,pady=(10,4),sticky='w')
        amount_var=tk.StringVar();ttk.Entry(form,textvariable=amount_var,width=14).grid(row=1,column=1,padx=5,pady=(0,10),sticky='ew')
        tk.Label(form,text='Reason',bg=PANEL2,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=0,column=2,padx=5,pady=(10,4),sticky='w')
        reason_var=tk.StringVar();ttk.Entry(form,textvariable=reason_var).grid(row=1,column=2,padx=5,pady=(0,10),sticky='ew')
        form.grid_columnconfigure(2,weight=1)
        state={'selected_id':None}

        table=tk.Frame(card,bg=PANEL);table.pack(fill='x',padx=12,pady=(0,8))
        cols=('date','amount','reason','id')
        tree=ttk.Treeview(table,columns=cols,show='headings',height=5,displaycolumns=('date','amount','reason'))
        for c,h,w,a in [('date','Date',120,'center'),('amount','Advance Amount',170,'e'),('reason','Reason',560,'w'),('id','',1,'center')]:
            tree.heading(c,text=h);tree.column(c,width=w,anchor=a,stretch=c=='reason')
        sb=ModernScrollbar(table,command=tree.yview,orient='vertical',thickness=14)
        tree.configure(yscrollcommand=sb.set);tree.pack(side='left',fill='both',expand=True);sb.pack(side='right',fill='y',padx=(4,0));self.register_scroll_area(table,tree,'y')
        total_lbl=tk.Label(card,text='',bg=PANEL,fg='#8ab4ff',font=('Segoe UI',11,'bold'));total_lbl.pack(anchor='e',padx=16,pady=(0,12))

        def clear_form():
            state['selected_id']=None
            date_var.set(f"01.{datetime.strptime(month+'-01','%Y-%m-%d').strftime('%m.%y')}")
            amount_var.set('');reason_var.set('')
            tree.selection_remove(tree.selection())

        def load_selected(_event=None):
            sel=tree.selection()
            if not sel:return
            rid=int(sel[0]);row=self.db.execute('SELECT * FROM advances WHERE id=? AND employee_id=?',(rid,e['id'])).fetchone()
            if not row:return
            state['selected_id']=rid
            date_var.set(self.display_advance_date(row['advance_date']))
            amount_var.set(f"{float(row['amount']):g}")
            reason_var.set(row['reason'] or '')

        def refresh():
            tree.delete(*tree.get_children());total=0.0
            for r in self.advance_rows(e['id'],month):
                amount=float(r['amount']);total+=amount
                tree.insert('', 'end', iid=str(r['id']), values=(self.display_advance_date(r['advance_date']),f'৳{amount:,.2f}',r['reason'],str(r['id'])))
            total_lbl.config(text=f'Total advance for {month}: ৳{total:,.2f}')
            if state['selected_id'] is not None and not tree.exists(str(state['selected_id'])):
                clear_form()

        def validate_form():
            dt=datetime.strptime(date_var.get().strip(),'%d.%m.%y').date()
            if dt.strftime('%Y-%m')!=month:
                raise ValueError(f'Advance date must be inside the selected month ({month}).')
            amount=safe_float(amount_var.get(),'Advance amount')
            if amount<=0:raise ValueError('Advance amount must be greater than 0.')
            reason=reason_var.get().strip()
            if not reason:raise ValueError('Reason is required for an advance.')
            return dt,amount,reason

        def add_advance():
            try:
                dt,amount,reason=validate_form()
                self.db.execute('INSERT INTO advances(employee_id,advance_date,amount,reason,created_at) VALUES(?,?,?,?,?)',
                                (e['id'],dt.isoformat(),amount,reason,datetime.now().isoformat(timespec='seconds')))
                self.audit('ADD_ADVANCE','advance',e['id'],{'date':dt.isoformat(),'amount':amount,'reason':reason})
                self.db.commit();clear_form();refresh()
            except Exception as ex:
                self.db.rollback()
                messagebox.showerror('Advance Money',str(ex),parent=self)

        def edit_selected():
            if state['selected_id'] is None:
                messagebox.showwarning('Advance Money','Select an advance record first.',parent=self);return
            try:
                row=self.db.execute('SELECT * FROM advances WHERE id=? AND employee_id=?',(state['selected_id'],e['id'])).fetchone()
                if not row:raise ValueError('The selected advance no longer exists.')
                dt,amount,reason=validate_form()
                old_data={'date':row['advance_date'],'amount':float(row['amount']),'reason':row['reason']}
                self.db.execute('UPDATE advances SET advance_date=?,amount=?,reason=? WHERE id=? AND employee_id=?',
                                (dt.isoformat(),amount,reason,state['selected_id'],e['id']))
                self.audit('EDIT_ADVANCE','advance',state['selected_id'],{'employee_id':e['id'],'before':old_data,'after':{'date':dt.isoformat(),'amount':amount,'reason':reason}})
                self.db.commit();refresh()
            except Exception as ex:
                self.db.rollback()
                messagebox.showerror('Advance Money',str(ex),parent=self)

        def delete_selected():
            rid=state['selected_id']
            if rid is None:
                sel=tree.selection()
                if sel:rid=int(sel[0])
            if rid is None:return
            row=self.db.execute('SELECT * FROM advances WHERE id=? AND employee_id=?',(rid,e['id'])).fetchone()
            if not row:return
            if not messagebox.askyesno('Delete Advance',f"Delete advance ৳{float(row['amount']):,.2f} dated {self.display_advance_date(row['advance_date'])}?",parent=self):return
            try:
                self.db.execute('DELETE FROM advances WHERE id=? AND employee_id=?',(rid,e['id']))
                self.audit('DELETE_ADVANCE','advance',rid,{'employee_id':e['id'],'date':row['advance_date'],'amount':float(row['amount']),'reason':row['reason']})
                self.db.commit();clear_form();refresh()
            except Exception as ex:
                self.db.rollback();messagebox.showerror('Advance Money',str(ex),parent=self)

        actions=tk.Frame(form,bg=PANEL2);actions.grid(row=1,column=3,padx=(5,10),pady=(0,10),sticky='e')
        for label,cmd,style in [
            ('ADD ADVANCE',add_advance,'Accent.TButton'),
            ('EDIT SELECTED',edit_selected,None),
            ('DELETE SELECTED',delete_selected,None),
            ('CANCEL',clear_form,None),
            ('SAVE CHANGES',edit_selected,'Accent.TButton'),
        ]:
            ttk.Button(actions,text=label,command=cmd,style=style or 'TButton').pack(side='left',padx=3)
        tree.bind('<<TreeviewSelect>>',load_selected)
        tree.bind('<Double-1>',load_selected)
        refresh()

    def advance_money(self):
        """Dedicated employee-wide advance ledger with a clear edit-first layout."""
        self.clear()
        self.header('Advance Money','Employee-wide advance records. Add or edit an advance at the top, filter below it, and review matching records in the large center table.')

        # ---------- add / edit ----------
        form=tk.Frame(self.main,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        form.pack(fill='x',padx=26,pady=(6,8))
        tk.Label(form,text='ADD / EDIT ADVANCE',bg=PANEL,fg=TEXT,font=('Segoe UI',12,'bold')).grid(row=0,column=0,columnspan=5,sticky='w',padx=14,pady=(12,3))
        tk.Label(form,text='Select a record to edit. Employee Name is filled automatically from Employee ID.',bg=PANEL,fg=MUTED,font=('Segoe UI',9)).grid(row=0,column=5,columnspan=2,sticky='e',padx=14,pady=(12,3))

        form_vars={k:tk.StringVar() for k in ('empid','name','date','amount','reason')}
        fields=[('Employee ID','empid',15),('Employee Name','name',24),('Date (DD.MM.YY)','date',14),('Advance Amount','amount',15),('Reason','reason',30)]
        entries={}
        for i,(label,key,width) in enumerate(fields):
            tk.Label(form,text=label,bg=PANEL,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=1,column=i,padx=6,pady=(8,3),sticky='w')
            state='readonly' if key=='name' else 'normal'
            ent=ttk.Entry(form,textvariable=form_vars[key],width=width,state=state)
            ent.grid(row=2,column=i,padx=6,pady=(0,10),sticky='ew')
            entries[key]=ent
            form.grid_columnconfigure(i,weight=1,minsize=120)

        actions=tk.Frame(form,bg='#0d0f13')
        actions.grid(row=3,column=0,columnspan=5,sticky='w',padx=8,pady=(2,12))
        form_state={'selected_id':None}

        def clear_form():
            form_state['selected_id']=None
            form_vars['empid'].set('')
            form_vars['name'].set('')
            form_vars['date'].set(datetime.now().strftime('%d.%m.%y'))
            form_vars['amount'].set('')
            form_vars['reason'].set('')
            tree.selection_remove(tree.selection())

        def employee_from_id():
            raw=form_vars['empid'].get().strip()
            if not raw:
                form_vars['name'].set('')
                return None
            empid=self.normalize_employee_id(raw)
            row=self.db.execute('SELECT * FROM employees WHERE empid=? OR CAST(emp_number AS TEXT)=? LIMIT 1',(empid,raw)).fetchone()
            form_vars['name'].set(row['name'] if row else '')
            return row

        def validate_form():
            row=employee_from_id()
            if row is None: raise ValueError('Enter a valid Employee ID.')
            dt=datetime.strptime(form_vars['date'].get().strip(),'%d.%m.%y').date()
            amount=safe_float(form_vars['amount'].get(),'Advance amount')
            if amount<=0: raise ValueError('Advance amount must be greater than 0.')
            reason=form_vars['reason'].get().strip()
            if not reason: raise ValueError('Reason is required for an advance.')
            return row,dt,amount,reason

        def refresh():
            for iid in tree.get_children(): tree.delete(iid)
            clauses=[];params=[]
            def date_value(key):
                raw=filter_vars[key].get().strip()
                if not raw:return None
                return datetime.strptime(raw,'%d.%m.%y').date().isoformat()
            try:
                df=date_value('date_from');dt=date_value('date_to')
                if df:clauses.append('a.advance_date>=?');params.append(df)
                if dt:clauses.append('a.advance_date<=?');params.append(dt)
                name=filter_vars['name'].get().strip()
                if name:clauses.append('e.name LIKE ? COLLATE NOCASE');params.append('%'+name+'%')
                empraw=filter_vars['empid'].get().strip()
                if empraw:
                    empnorm=self.normalize_employee_filter(empraw)
                    clauses.append('(e.empid LIKE ? COLLATE NOCASE OR CAST(e.emp_number AS TEXT)=?)')
                    params.extend([f'%{empnorm}%',empraw])
                reason=filter_vars['reason'].get().strip()
                if reason:clauses.append('a.reason LIKE ? COLLATE NOCASE');params.append('%'+reason+'%')
                if filter_vars['min'].get().strip():clauses.append('a.amount>=?');params.append(safe_float(filter_vars['min'].get(),'Minimum amount'))
                if filter_vars['max'].get().strip():clauses.append('a.amount<=?');params.append(safe_float(filter_vars['max'].get(),'Maximum amount'))
                sql='SELECT a.id,a.advance_date,a.amount,a.reason,e.empid,e.name FROM advances a JOIN employees e ON e.id=a.employee_id'
                if clauses:sql+=' WHERE '+' AND '.join(clauses)
                sql+=' ORDER BY a.advance_date DESC,e.emp_number,e.id,a.id DESC'
                rows=self.db.execute(sql,params).fetchall()
                total=sum(float(r['amount']) for r in rows)
                for r in rows:
                    tree.insert('', 'end', iid=str(r['id']), values=(self.display_advance_date(r['advance_date']),r['empid'],r['name'],f'৳{float(r["amount"]):,.2f}',r['reason']))
                result_lbl.config(text=f'{len(rows):,} record(s) • Filtered total: ৳{total:,.2f}',fg='#8ab4ff')
            except Exception as ex:
                result_lbl.config(text=f'Filter error: {ex}',fg=RED)

        def load_selected(_event=None):
            sel=tree.selection()
            if not sel:return
            rid=int(sel[0])
            row=self.db.execute('SELECT a.*,e.empid,e.name FROM advances a JOIN employees e ON e.id=a.employee_id WHERE a.id=?',(rid,)).fetchone()
            if not row:return
            form_state['selected_id']=rid
            form_vars['empid'].set(row['empid'])
            form_vars['name'].set(row['name'])
            form_vars['date'].set(self.display_advance_date(row['advance_date']))
            form_vars['amount'].set(f'{float(row["amount"]):g}')
            form_vars['reason'].set(row['reason'] or '')

        def add_advance():
            try:
                row,dt,amount,reason=validate_form()
                self.db.execute('INSERT INTO advances(employee_id,advance_date,amount,reason,created_at) VALUES(?,?,?,?,?)',(row['id'],dt.isoformat(),amount,reason,datetime.now().isoformat(timespec='seconds')))
                self.audit('ADD_ADVANCE','advance',row['id'],{'date':dt.isoformat(),'amount':amount,'reason':reason})
                self.db.commit();refresh();clear_form()
            except Exception as ex:
                self.db.rollback();messagebox.showerror('Advance Money',str(ex),parent=self)

        def edit_selected():
            rid=form_state['selected_id']
            if rid is None:
                sel=tree.selection()
                if sel:rid=int(sel[0])
            if rid is None:
                messagebox.showwarning('Advance Money','Select an advance record first.',parent=self);return
            try:
                row,dt,amount,reason=validate_form()
                old=self.db.execute('SELECT * FROM advances WHERE id=?',(rid,)).fetchone()
                if old is None:raise ValueError('The selected advance no longer exists.')
                self.db.execute('UPDATE advances SET employee_id=?,advance_date=?,amount=?,reason=? WHERE id=?',(row['id'],dt.isoformat(),amount,reason,rid))
                self.audit('EDIT_ADVANCE','advance',rid,{'before':{'employee_id':old['employee_id'],'date':old['advance_date'],'amount':float(old['amount']),'reason':old['reason']},'after':{'employee_id':row['id'],'date':dt.isoformat(),'amount':amount,'reason':reason}})
                self.db.commit();refresh()
            except Exception as ex:
                self.db.rollback();messagebox.showerror('Advance Money',str(ex),parent=self)

        def delete_selected():
            rid=form_state['selected_id']
            if rid is None:
                sel=tree.selection()
                if sel:rid=int(sel[0])
            if rid is None:return
            row=self.db.execute('SELECT a.*,e.empid,e.name FROM advances a JOIN employees e ON e.id=a.employee_id WHERE a.id=?',(rid,)).fetchone()
            if row is None:return
            if not messagebox.askyesno('Delete Advance',f'Delete {row["empid"]} — ৳{float(row["amount"]):,.2f} dated {self.display_advance_date(row["advance_date"])}?',parent=self):return
            try:
                self.db.execute('DELETE FROM advances WHERE id=?',(rid,))
                self.audit('DELETE_ADVANCE','advance',rid,{'employee_id':row['employee_id'],'date':row['advance_date'],'amount':float(row['amount']),'reason':row['reason']})
                self.db.commit();refresh();clear_form()
            except Exception as ex:
                self.db.rollback();messagebox.showerror('Advance Money',str(ex),parent=self)

        for label,cmd,style in [('ADD ADVANCE',add_advance,'Accent.TButton'),('EDIT SELECTED',edit_selected,None),('DELETE SELECTED',delete_selected,None),('CANCEL',clear_form,None),('SAVE CHANGES',edit_selected,'Accent.TButton')]:
            ttk.Button(actions,text=label,command=cmd,style=style or 'TButton').pack(side='left',padx=3)

        # ---------- filters ----------
        filter_card=tk.Frame(self.main,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        filter_card.pack(fill='x',padx=26,pady=(0,8))
        tk.Label(filter_card,text='FILTERS',bg=PANEL,fg=TEXT,font=('Segoe UI',12,'bold')).grid(row=0,column=0,columnspan=7,sticky='w',padx=14,pady=(10,3))
        filter_vars={k:tk.StringVar() for k in ('date_from','date_to','name','empid','reason','min','max')}
        filter_labels=[('date_from','Date From',12),('date_to','Date To',12),('name','Name',15),('empid','Employee ID',15),('reason','Reason',18),('min','Minimum Amount',15),('max','Maximum Amount',15)]
        for i,(key,label,width) in enumerate(filter_labels):
            tk.Label(filter_card,text=label,bg=PANEL,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=1,column=i,padx=5,pady=(5,3),sticky='w')
            ttk.Entry(filter_card,textvariable=filter_vars[key],width=width).grid(row=2,column=i,padx=5,pady=(0,10),sticky='ew')
            filter_card.grid_columnconfigure(i,weight=1,minsize=110)

        # ---------- records ----------
        body=tk.Frame(self.main,bg=BG)
        body.pack(fill='both',expand=True,padx=(26,0),pady=(0,4))
        table_frame=tk.Frame(body,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        table_frame.pack(fill='both',expand=True)
        cols=('date','empid','name','amount','reason')
        tree=ttk.Treeview(table_frame,columns=cols,show='headings')
        for c,h,w,a in [('date','Date',105,'center'),('empid','Employee ID',115,'center'),('name','Employee Name',210,'w'),('amount','Advance Amount',145,'e'),('reason','Reason',430,'w')]:
            tree.heading(c,text=h);tree.column(c,width=w,anchor=a,stretch=c=='reason')
        sb=ModernScrollbar(table_frame,command=tree.yview,orient='vertical',thickness=15)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left',fill='both',expand=True)
        sb.pack(side='right',fill='y',padx=(4,6),pady=4)
        self.register_scroll_area(table_frame,tree,'y',default=True)

        footer=tk.Frame(self.main,bg=BG)
        footer.pack(fill='x',padx=26,pady=(4,10))
        result_lbl=tk.Label(footer,text='',bg=BG,fg='#8ab4ff',font=('Segoe UI',10,'bold'))
        result_lbl.pack(side='left')
        for v in filter_vars.values():
            v.trace_add('write',lambda *_: self.after(140,refresh))
        tree.bind('<<TreeviewSelect>>',load_selected)
        tree.bind('<Double-1>',load_selected)
        refresh()
        clear_form()

    def normalize_code(self, raw):
        s = str(raw).strip().upper().replace(' ', '')
        aliases = {
            'HALF': 'P/2', '0.5P': 'P/2', '1P': 'P', '1.0P': 'P',
            '1.5P': 'P+P/2', '2.0P': '2P', '2.0': '2P',
            '2P': '2P', 'A': 'A', 'P': 'P', 'P/2': 'P/2', 'P+P/2': 'P+P/2'
        }
        return aliases.get(s, s)

    def save_attendance_cell(self, employee_id, plot_id, month, day_no, raw_code):
        month=self.month_valid(month)
        y,m=map(int,month.split('-'));days=calendar.monthrange(y,m)[1]
        day_no=int(day_no)
        if not 1 <= day_no <= days:
            raise ValueError('Attendance day is outside the selected month.')
        code=self.normalize_code(raw_code)
        valid=set(self.rules())
        if code and code not in valid:
            raise ValueError('Invalid code. Use A, P/2, P, P+P/2 or 2P.')
        day_value=f'{month}-{day_no:02d}'
        if code:
            self.db.execute(
                'INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?) '
                'ON CONFLICT(employee_id,plot_id,day) DO UPDATE SET code=excluded.code',
                (employee_id,plot_id,day_value,code))
        else:
            self.db.execute('DELETE FROM attendance WHERE employee_id=? AND plot_id=? AND day=?',
                            (employee_id,plot_id,day_value))
        self.audit('EDIT_ATTENDANCE','attendance',f'{employee_id}:{plot_id}:{day_value}',{'code':code})
        self.db.commit()
        return code

    def plot_chart(self, parent, e, p, month):
        """Render one lightweight attendance chart.

        Most of the grid is drawn directly on Canvas. Only the cell being edited is
        temporarily represented by a real Entry widget. This keeps vertical scrolling
        smooth even when a worker has many plots.
        """
        try:
            y, m = map(int, month.split('-'))
            days = calendar.monthrange(y, m)[1]
        except Exception:
            messagebox.showerror('Month', 'Use YYYY-MM, for example 2026-09', parent=self)
            return

        box = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill='x', pady=8)
        u, a, _, current_rate = self.calc_plot(e['id'], p['id'], month)
        title = tk.Label(box,
                         text=f"Plot {p['plot_no']}   •   ৳{current_rate:,.2f}/day   •   Present: {u:g}P   •   Total: ৳{a:,.2f}",
                         bg=PANEL, fg=TEXT, font=('Segoe UI', 13, 'bold'))
        title.pack(anchor='w', padx=14, pady=(11, 6))

        key_frame = tk.Frame(box, bg=PANEL)
        key_frame.pack(fill='x', padx=14, pady=(0, 5))
        tk.Label(key_frame, text='ATTENDANCE KEY', bg=PANEL, fg='#8ab4ff',
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 10))
        key_text = (
            'P = Full Day (1P)   •   P/2 = Half Day (0.5P)   •   '
            'P+P/2 = Full Day + Half Night (1.5P)   •   '
            '2P = Full Day + Full Night (2P)   •   A = Absent (0P)'
        )
        key_lbl = tk.Label(key_frame, text=key_text, bg=PANEL, fg=TEXT,
                           font=('Segoe UI', 9), justify='left', anchor='w')
        key_lbl.pack(side='left', fill='x', expand=True)
        box.bind('<Configure>', lambda ev: key_lbl.configure(wraplength=max(460, ev.width-145)), add='+')

        rule_lbl = tk.Label(
            box,
            text='Rule: Each numbered box is exactly one calendar day in the selected month. Blank boxes are not attendance and contribute 0P. Click a box to edit it; Enter, Tab or clicking another day saves only the currently edited day.',
            bg=PANEL, fg=MUTED, font=('Segoe UI', 9), justify='left', anchor='w')
        rule_lbl.pack(fill='x', padx=14, pady=(0, 9))
        box.bind('<Configure>', lambda ev: rule_lbl.configure(wraplength=max(460, ev.width-28)), add='+')

        hframe = tk.Frame(box, bg=PANEL)
        hframe.pack(fill='x', padx=10, pady=(0, 11))
        grid_canvas = tk.Canvas(hframe, bg=PANEL, height=82, highlightthickness=0,
                                bd=0, xscrollincrement=1)
        hs = ModernScrollbar(hframe, command=grid_canvas.xview, orient='horizontal', thickness=12, height=12)
        grid_canvas.configure(xscrollcommand=hs.set)
        grid_canvas.pack(fill='x')
        hs.pack(fill='x', pady=(4, 0))
        self.register_scroll_area(hframe, grid_canvas, axis='x')

        col_w = 66
        total_w = days * col_w + 6
        grid_canvas.configure(scrollregion=(0, 0, total_w, 82))
        lo=f'{month}-01';hi=f'{month}-{days:02d}'
        existing_rows=self.db.execute('SELECT day,code FROM attendance WHERE employee_id=? AND plot_id=? AND day>=? AND day<=? ORDER BY day,id',(e['id'],p['id'],lo,hi)).fetchall()
        existing={}
        for r in existing_rows:
            try:d=int(str(r['day'])[8:10])
            except Exception:continue
            if 1<=d<=days:existing[d]=self.normalize_code(r['code'])
        codes = dict(existing)
        valid = set(self.rules())
        entry_holder = {'widget': None, 'window_id': None, 'day': None, 'var': None, 'closing': False}

        def draw():
            grid_canvas.delete('all')
            for d in range(1, days + 1):
                x0 = 3 + (d - 1) * col_w
                grid_canvas.create_text(x0 + col_w / 2, 13, text=str(d), fill=MUTED,
                                        font=('Segoe UI', 9, 'bold'), tags=(f'day:{d}',))
                grid_canvas.create_rectangle(x0 + 2, 29, x0 + col_w - 3, 67,
                                             fill=PANEL2, outline=BORDER, width=1,
                                             tags=(f'day:{d}', 'cell'))
                code = codes.get(d, '')
                if code:
                    grid_canvas.create_text(x0 + col_w / 2, 48, text=code, fill=TEXT,
                                            font=('Segoe UI', 10, 'bold'), tags=(f'day:{d}', 'celltext'))
            grid_canvas.configure(scrollregion=(0, 0, total_w, 82))

        def refresh_header():
            try:
                uu, aa, _, rr = self.calc_plot(e['id'], p['id'], month)
                title.config(text=f"Plot {p['plot_no']}   •   ৳{rr:,.2f}/day   •   Present: {uu:g}P   •   Total: ৳{aa:,.2f}")
            except Exception:
                pass

        def close_editor(save_first=True):
            ent = entry_holder['widget']
            if ent is None:
                return True
            if entry_holder['closing']:
                return True
            entry_holder['closing'] = True
            day_no = entry_holder['day']
            var = entry_holder['var']
            raw = var.get() if var is not None else ''
            code = self.normalize_code(raw)
            try:
                if save_first:
                    if code and code not in valid:
                        ent.configure(highlightbackground=RED)
                        return False
                    code=self.save_attendance_cell(e['id'],p['id'],month,day_no,code)
                    if code:
                        codes[day_no]=code
                    else:
                        codes.pop(day_no,None)
                    getattr(self,'_rule_month_cache',{}).clear(); getattr(self,'_rate_month_cache',{}).clear()
                    refresh_header()
                if entry_holder['window_id'] is not None:
                    try: grid_canvas.delete(entry_holder['window_id'])
                    except tk.TclError: pass
                try: ent.destroy()
                except tk.TclError: pass
                entry_holder.update(widget=None, window_id=None, day=None, var=None)
                draw()
                return True
            finally:
                entry_holder['closing'] = False

        def edit_day(day_no, move=False):
            if day_no < 1 or day_no > days:
                return
            if entry_holder['widget'] is not None and not close_editor(True):
                return
            var = tk.StringVar(value=codes.get(day_no, ''))
            x0 = 3 + (day_no - 1) * col_w
            ent = tk.Entry(grid_canvas, textvariable=var, width=6, justify='center',
                           bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                           relief='flat', bd=0, highlightthickness=2,
                           highlightbackground=ACCENT, highlightcolor=ACCENT,
                           font=('Segoe UI', 10, 'bold'))
            win = grid_canvas.create_window(x0 + 4, 30, anchor='nw',
                                            width=col_w - 8, height=36, window=ent)
            entry_holder.update(widget=ent, window_id=win, day=day_no, var=var, closing=False)
            ent.focus_set()
            ent.selection_range(0, 'end')

            def commit_move(_event=None, step=1):
                if not close_editor(True):
                    messagebox.showerror('Attendance',
                                         'Invalid code. Use A, P/2, P, P+P/2 or 2P.', parent=self)
                    return 'break'
                if move and 1 <= day_no + step <= days:
                    self.after_idle(lambda d=day_no + step: edit_day(d, False))
                return 'break'

            ent.bind('<Return>', lambda ev: commit_move(ev, 1))
            ent.bind('<Tab>', lambda ev: commit_move(ev, 1))
            ent.bind('<Left>', lambda ev: commit_move(ev, -1))
            ent.bind('<Right>', lambda ev: commit_move(ev, 1))
            ent.bind('<Escape>', lambda ev: (close_editor(False), 'break')[1])
            ent.bind('<FocusOut>', lambda _ev: None)

        def on_canvas_click(event):
            x = grid_canvas.canvasx(event.x)
            yv = grid_canvas.canvasy(event.y)
            if not (29 <= yv <= 67):
                return
            day_no = int((x - 3) / col_w) + 1
            if 1 <= day_no <= days:
                edit_day(day_no, False)

        grid_canvas.bind('<Button-1>', on_canvas_click)
        # Save the currently edited cell only when the user intentionally moves to
        # another grid cell. Avoid a FocusOut callback racing with a new editor and
        # accidentally writing a neighbouring day.
        def on_cell_click(event):
            if entry_holder['widget'] is not None:
                close_editor(True)
            on_canvas_click(event)
        grid_canvas.unbind('<Button-1>')
        grid_canvas.bind('<Button-1>', on_cell_click)
        if entry_holder['widget'] is not None:
            pass
        draw()

    # ---------- salary/filter ----------
    def salary_filter(self):
        self._page_key = 'salary_filter'
        self.clear()
        self.header('Salary / Filter', 'Filter by worker Name, Employee ID, Plot / Place, month and day range. Results calculate from saved attendance and each plot’s own Daily Salary.')

        card=tk.Frame(self.main,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        card.pack(fill='x',padx=26,pady=(8,8))
        tk.Label(card,text='FILTER SALARY',bg=PANEL,fg=TEXT,font=('Segoe UI',12,'bold')).grid(row=0,column=0,columnspan=8,sticky='w',padx=16,pady=(12,5))
        card.grid_columnconfigure(1,weight=1);card.grid_columnconfigure(3,weight=1);card.grid_columnconfigure(5,weight=1)
        name,empid,plot,month,start_day,end_day=(tk.StringVar() for _ in range(6))
        month.set(date.today().strftime('%Y-%m'))
        start_day.set('1')
        end_day.set(str(calendar.monthrange(date.today().year,date.today().month)[1]))
        def frow(row,label,var,width,col):
            tk.Label(card,text=label,bg=PANEL,fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=row,column=col,sticky='w',padx=(12,5),pady=(2,10))
            ttk.Entry(card,textvariable=var,width=width).grid(row=row,column=col+1,sticky='ew',padx=(0,10),pady=(2,10))
        frow(1,'Name',name,16,0);frow(1,'Employee ID',empid,14,2);frow(1,'Plot / Place',plot,15,4)
        ttk.Button(card,text='CLEAR FILTERS',command=lambda:[v.set('') for v in (name,empid,plot)]).grid(row=1,column=6,columnspan=2,sticky='e',padx=(8,16),pady=(2,10))
        frow(2,'Month',month,9,0);frow(2,'From day',start_day,7,2);frow(2,'To day',end_day,7,4)
        tk.Label(card,text='Tip: enter EMP010 or just 10 in Employee ID.',bg=PANEL,fg='#8ab4ff',font=('Segoe UI',8,'bold')).grid(row=2,column=6,columnspan=2,sticky='e',padx=(8,16),pady=(2,10))

        out=tk.Frame(self.main,bg=BG);out.pack(fill='both',expand=True,padx=26,pady=(0,8))
        state={'page':0,'job':None,'token':0}

        def run(reset=True):
            if reset:state['page']=0
            state['token']+=1
            token=state['token']
            try:
                y,m=map(int,month.get().strip().split('-'))
                maxday=calendar.monthrange(y,m)[1]
                sday=max(1,min(maxday,int(start_day.get())))
                eday=max(sday,min(maxday,int(end_day.get())))
                ni=self.normalize_employee_filter(empid.get())
                rows=self.month_summary(month.get(),sday,eday,name.get().strip(),ni,plot.get().strip(),False,EMPLOYEE_PAGE_SIZE,state['page']*EMPLOYEE_PAGE_SIZE)
            except Exception as ex:
                for w in out.winfo_children():w.destroy()
                tk.Label(out,text=str(ex),bg=BG,fg='#ff8181',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=10)
                return
            total_count=int(rows[0]['total_count']) if rows else 0
            grand=float(rows[0]['grand_amount']) if rows else 0.0
            maxp=max(0,(total_count-1)//EMPLOYEE_PAGE_SIZE)
            state['page']=min(state['page'],maxp)
            if state['page']*EMPLOYEE_PAGE_SIZE>0 and not rows:
                state['page']=maxp
                rows=self.month_summary(month.get(),sday,eday,name.get().strip(),ni,plot.get().strip(),False,EMPLOYEE_PAGE_SIZE,state['page']*EMPLOYEE_PAGE_SIZE)
            for w in out.winfo_children():w.destroy()

            holder=tk.Frame(out,bg=BG,highlightbackground=BORDER,highlightthickness=1)
            holder.pack(fill='both',expand=True)
            vwrap=tk.Frame(holder,bg=BG);vwrap.pack(fill='both',expand=True)
            vwrap.grid_rowconfigure(0,weight=1);vwrap.grid_columnconfigure(0,weight=1)
            cols=('id','name','plot','rate','p','money')
            tree=ttk.Treeview(vwrap,columns=cols,show='headings')
            for c,h,w,a in [('id','Employee ID',150,'e'),('name','Name',190,'w'),('plot','Plot / Place',220,'w'),('rate','Daily Salary',150,'e'),('p','Present Day (P)',150,'e'),('money','Total Money',190,'e')]:
                tree.heading(c,text=h);tree.column(c,width=w,anchor=a,stretch=c in ('name','plot'))
            vs=ModernScrollbar(vwrap,command=tree.yview,orient='vertical',thickness=14)
            hs=ModernScrollbar(vwrap,command=tree.xview,orient='horizontal',thickness=12,height=12)
            tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
            tree.grid(row=0,column=0,sticky='nsew')
            vs.grid(row=0,column=1,sticky='ns',padx=(6,4))
            hs.grid(row=1,column=0,sticky='ew',pady=(5,4))
            self.register_scroll_area(vwrap,tree,'y',default=True)
            self.register_scroll_area(vwrap,tree,'x')
            for r in rows:
                tree.insert('', 'end',values=(r['empid'],r['name'],r['plot_no'],f"৳{float(r['rate']):,.2f}/day",f"{float(r['units']):g}P",f"৳{float(r['amount']):,.2f}"))

            footer=tk.Frame(out,bg='#0d0f13',highlightbackground=BORDER,highlightthickness=1)
            footer.pack(fill='x',pady=(7,0))
            st=tk.Label(footer,text=f'Showing {state["page"]*EMPLOYEE_PAGE_SIZE+1 if rows else 0}–{state["page"]*EMPLOYEE_PAGE_SIZE+len(rows)} of {total_count} plot records  •  Page {state["page"]+1}/{maxp+1}',bg='#0d0f13',fg=MUTED,font=('Segoe UI',9))
            st.pack(side='left',padx=14,pady=8)
            nav=tk.Frame(footer,bg='#0d0f13');nav.pack(side='right',padx=8,pady=5)
            prev=ttk.Button(nav,text='‹  PREVIOUS',command=lambda:page(-1));prev.state(['disabled'] if state['page']<=0 else ['!disabled']);prev.pack(side='left',padx=3)
            nxt=ttk.Button(nav,text='NEXT  ›',command=lambda:page(1));nxt.state(['disabled'] if state['page']>=maxp else ['!disabled']);nxt.pack(side='left',padx=3)
            tk.Label(out,text=f'Instant Total for the filtered range: ৳{grand:,.2f}',bg=BG,fg='#8ab4ff',font=('Segoe UI',18,'bold')).pack(anchor='e',pady=9)

        def page(delta):
            state['page']=max(0,state['page']+delta);run(False)

        def schedule(*_):
            if state['job'] is not None:
                try:self.after_cancel(state['job'])
                except Exception:pass
            state['job']=self.after(180,lambda:run(True))

        for v in (name,empid,plot,month,start_day,end_day):v.trace_add('write',schedule)
        run(True)

    # ---------- rules ----------
    def rules_window(self):
        w = tk.Toplevel(self)
        w.title(f'{APP_NAME} — Custom Rules')
        w.configure(bg=BG)
        w.transient(self)
        w.resizable(True, True)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f'{min(1100, sw-80)}x{min(700, sh-100)}')
        w.minsize(820, 560)

        top = tk.Frame(w, bg='#0d0f13')
        top.pack(fill='x')
        tk.Label(top, text='CUSTOM ATTENDANCE RULES', bg='#0d0f13', fg=TEXT,
                 font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=24, pady=(18, 4))
        tk.Label(top, text='F11 opens this screen. Each key has a defined attendance meaning, and its multiplier determines how many P-units that day contributes to salary.',
                 bg='#0d0f13', fg=MUTED, font=('Segoe UI', 10), wraplength=max(620, sw-160), justify='left').pack(anchor='w', padx=26, pady=(0, 16))

        body = tk.Frame(w, bg=BG)
        body.pack(fill='both', expand=True, padx=22, pady=18)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        right = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        tk.Label(left, text='KEY / MEANING', bg=PANEL, fg=TEXT, font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=18, pady=(16, 10))
        meanings = [
            ('P', 'Full Day — real 1-day attendance (1P)'),
            ('P/2', 'Half Day — half-day attendance (0.5P)'),
            ('P+P/2', 'Full Day + Half Night (1.5P)'),
            ('2P', 'Full Day + Full Night / Double Day (2P)'),
            ('A', 'Absent — no payable P-units (0P)'),
        ]
        for code, meaning in meanings:
            f = tk.Frame(left, bg=PANEL)
            f.pack(fill='x', padx=18, pady=7)
            tk.Label(f, text=code, bg=PANEL2, fg='#8ab4ff', font=('Segoe UI', 11, 'bold'),
                     width=9, pady=7).pack(side='left')
            tk.Label(f, text=meaning, bg=PANEL, fg=TEXT, font=('Segoe UI', 9),
                     justify='left', anchor='w', wraplength=350).pack(side='left', fill='x', expand=True, padx=10)

        tk.Label(right, text='MULTIPLIERS', bg=PANEL, fg=TEXT, font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=18, pady=(16, 4))
        tk.Label(right, text='Set the P-unit value used when that code is entered. Changes are recorded with today’s effective date.',
                 bg=PANEL, fg=MUTED, font=('Segoe UI', 9), wraplength=620, justify='left').pack(anchor='w', padx=18, pady=(0, 10))
        vars_ = {}
        ordered = ['P', 'P/2', 'P+P/2', '2P', 'A']
        rows = {r['code']: r for r in self.db.execute('SELECT * FROM rules')}
        for code in ordered:
            r = rows.get(code)
            if not r: continue
            f = tk.Frame(right, bg='#141821', highlightbackground=BORDER, highlightthickness=1)
            f.pack(fill='x', padx=18, pady=6)
            tk.Label(f, text=code, bg='#141821', fg=TEXT, font=('Segoe UI', 10, 'bold'), width=12, anchor='w').pack(side='left', padx=12, pady=10)
            tk.Label(f, text=r['label'], bg='#141821', fg=MUTED, font=('Segoe UI', 9), anchor='w').pack(side='left', fill='x', expand=True)
            v = tk.StringVar(value=f"{float(r['mult']):g}")
            vars_[code] = v
            ttk.Entry(f, textvariable=v, width=12, justify='center', font=('Segoe UI', 10)).pack(side='right', padx=12, pady=8)

        bottom = tk.Frame(w, bg='#0d0f13', highlightbackground=BORDER, highlightthickness=1)
        bottom.pack(fill='x')
        def save():
            try:
                eff = date.today().isoformat()
                for code, v in vars_.items():
                    mult = safe_float(v.get(), f'Multiplier for {code}')
                    if mult < 0: raise ValueError(f'Multiplier for {code} cannot be negative.')
                    self.db.execute('UPDATE rules SET mult=? WHERE code=?', (mult, code))
                    self.db.execute('INSERT OR REPLACE INTO rule_history(code,effective_from,mult) VALUES(?,?,?)', (code, eff, mult))
                self.audit('EDIT_RULES','rules',eff,{'multipliers':{k:float(v.get()) for k,v in vars_.items()}})
                self.db.commit(); getattr(self,'_rule_month_cache',{}).clear(); getattr(self,'_rate_month_cache',{}).clear(); w.destroy()
            except Exception as ex:
                messagebox.showerror('Custom Rules', str(ex), parent=w)
        ttk.Button(bottom, text='CLOSE', command=w.destroy).pack(side='right', padx=8, pady=10)
        ttk.Button(bottom, text='SAVE RULES', style='Accent.TButton', command=save).pack(side='right', padx=(2, 18), pady=8)

    # ---------- backup / restore ----------
    def backup(self):
        self._page_key = 'backup'
        self.clear()
        self.header('Backup / Restore', 'Back up the complete WorkerPay database. Older LaborPay / EmployeePay database backups are migrated when restored.')
        f = tk.Frame(self.main, bg=BG)
        f.pack(anchor='w', padx=26, pady=20)
        ttk.Button(f, text='Create Backup', style='Accent.TButton', command=self.create_backup).pack(side='left', padx=5)
        ttk.Button(f, text='Restore Backup', command=self.restore_backup).pack(side='left', padx=5)
        tk.Label(self.main, text='Accepted backup files: .db and .zip containing a WorkerPay/EmployeePay/LaborPay .db database.',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=31)

    def create_backup(self):
        p=filedialog.asksaveasfilename(defaultextension='.db',initialfile=f'WorkerPay_Backup_{datetime.now().strftime("%Y-%m-%d_%H%M%S")}.db',filetypes=[('WorkerPay database','*.db'),('All files','*.*')])
        if not p:return
        try:self._snapshot_database(p);messagebox.showinfo('Backup','Backup created successfully and verified.',parent=self)
        except Exception as ex:logging.exception('backup failed');messagebox.showerror('Backup',f'Could not create a consistent backup:\n{ex}',parent=self)

    def extract_backup_db(self, path):
        if path.lower().endswith('.db'):
            return path, None
        if not path.lower().endswith('.zip'):
            raise ValueError('Choose a .db backup or a .zip backup containing a .db file.')
        tempdir = tempfile.mkdtemp(prefix='workerpay_restore_')
        with zipfile.ZipFile(path, 'r') as z:
            candidates = [n for n in z.namelist() if n.lower().endswith('.db') and not n.endswith('/')]
            if not candidates:
                shutil.rmtree(tempdir, ignore_errors=True)
                raise ValueError('The ZIP does not contain a .db database.')
            chosen = sorted(candidates, key=lambda n: ('workerpay' not in n.lower(), 'employeepay' not in n.lower(), 'laborpay' not in n.lower(), len(n)))[0]
            target = os.path.join(tempdir, os.path.basename(chosen))
            with z.open(chosen) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return target, tempdir

    def validate_database(self, candidate):
        con = sqlite3.connect(candidate)
        try:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if 'employees' not in names or 'attendance' not in names:
                raise ValueError('This file is not a recognized attendance database.')
        finally:
            con.close()

    def restore_backup(self):
        p=filedialog.askopenfilename(filetypes=[('Database or ZIP backup','*.db *.zip'),('Database','*.db'),('ZIP backup','*.zip'),('All files','*.*')])
        if not p:return
        if not messagebox.askyesno('Restore','Replace current WorkerPay data with this backup? A verified safety copy will be created first.',parent=self):return
        candidate=tempdir=None;safety=DB+'.before_restore.db'
        try:
            candidate,tempdir=self.extract_backup_db(p);self.validate_database(candidate)
            c=sqlite3.connect(candidate)
            try:
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('The selected backup failed SQLite quick_check.')
            finally:c.close()
            self._snapshot_database(safety);self.db.close()
            for side in (DB+'-wal',DB+'-shm'):
                try:
                    if os.path.exists(side):os.remove(side)
                except OSError:pass
            src2=sqlite3.connect(candidate);dst2=sqlite3.connect(DB);src2.backup(dst2,pages=5000,sleep=0.01);src2.close();dst2.close()
            self.db=sqlite3.connect(DB,timeout=30.0);self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=30000');self.db.execute('PRAGMA synchronous=NORMAL');self.db.execute('PRAGMA temp_store=MEMORY');self.db.execute('PRAGMA cache_size=-65536');self.db.execute('PRAGMA wal_autocheckpoint=2000');self.db.execute('PRAGMA mmap_size=268435456');self.init_db();self._repair_foreign_key_issues();self.dashboard();messagebox.showinfo('Restore','Restore completed and validated successfully.',parent=self)
        except Exception as ex:
            logging.exception('restore failed')
            try:
                if os.path.exists(safety):
                    try:self.db.close()
                    except Exception:pass
                    src2=sqlite3.connect(safety);dst2=sqlite3.connect(DB);src2.backup(dst2,pages=5000,sleep=0.01);src2.close();dst2.close();self.db=sqlite3.connect(DB,timeout=30.0);self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=30000');self.init_db()
            except Exception:logging.exception('restore rollback failed')
            messagebox.showerror('Restore',f'Backup could not be restored safely:\n{ex}',parent=self)
        finally:
            if tempdir:shutil.rmtree(tempdir,ignore_errors=True)


    def export_print(self):
        self._page_key = 'export_print'
        self.clear()
        self.header('Export / Print', 'Export the selected month directly as Excel or PDF. CSV is not used.')
        month = tk.StringVar(value=date.today().strftime('%Y-%m'))
        f = tk.Frame(self.main, bg=BG)
        f.pack(anchor='w', padx=26, pady=20)
        tk.Label(f, text='Month', bg=BG, fg=MUTED).pack(side='left', padx=4)
        ttk.Entry(f, textvariable=month, width=12).pack(side='left')
        ttk.Button(f, text='Export Excel', style='Accent.TButton',
                   command=lambda: self.export_excel(month.get())).pack(side='left', padx=(10, 5))
        ttk.Button(f, text='Export PDF', style='Accent.TButton',
                   command=lambda: self.export_pdf(month.get())).pack(side='left', padx=5)

        tk.Label(self.main,
                 text='Excel contains a monthly summary and daily attendance records. PDF contains the monthly summary.',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=31, pady=(0, 10))

    def _export_rows(self,month):
        month=self.month_valid(month);rows=[];daily=[];summaries=self.month_summary(month,active_only=False)
        for r in summaries:rows.append({'Employee ID':r['empid'],'Name':r['name'],'Plot No.':r['plot_no'],'Daily Salary (BDT/day)':r['rate'],'Present Day (P)':r['units'],'Total Amount (BDT)':r['amount']})
        y,m=map(int,month.split('-'));lo=f'{month}-01';hi=f'{month}-{calendar.monthrange(y,m)[1]:02d}';ars=self.db.execute('SELECT employee_id,plot_id,day,code FROM attendance WHERE day>=? AND day<=? ORDER BY day,employee_id,plot_id',(lo,hi)).fetchall()
        pinfo={r['plot_id']:r for r in summaries};rmap=self._rule_map_for_month(month);rates=self._rate_month_map(list(pinfo),month) if pinfo else {};emps={e['id']:e for e in self.employees_rows()}
        for a in ars:
            if a['plot_id'] not in pinfo:continue
            mult=rmap.get(a['day'],{}).get(a['code'],0.0);rr=rates.get(a['plot_id'],{}).get(a['day'],pinfo[a['plot_id']]['rate']);e=emps.get(a['employee_id'])
            daily.append({'Date':a['day'],'Employee ID':e['empid'] if e else '','Name':e['name'] if e else '','Plot No.':pinfo[a['plot_id']]['plot_no'],'Code':a['code'],'P Units':mult,'Daily Salary (BDT/day)':rr,'Amount (BDT)':mult*rr})
        return rows,daily

    def export_excel(self, month):
        try:
            rows, daily = self._export_rows(month)
        except Exception as ex:
            messagebox.showerror('Export Excel', str(ex), parent=self)
            return
        p = filedialog.asksaveasfilename(
            defaultextension='.xlsx', initialfile=f'WorkerPay_{month}.xlsx',
            filetypes=[('Excel workbook', '*.xlsx')])
        if not p:
            return
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            ws = wb.active
            ws.title = 'Monthly Summary'
            headers = list(rows[0].keys()) if rows else ['Employee ID', 'Name', 'Plot No.', 'Daily Salary (BDT/day)', 'Present Day (P)', 'Total Amount (BDT)']
            ws.append(headers)
            for c in ws[1]:
                c.font = Font(bold=True)
                c.alignment = Alignment(horizontal='center')
            for r in rows:
                ws.append([r[h] for h in headers])
            for col in range(1, len(headers) + 1):
                ws.column_dimensions[get_column_letter(col)].width = max(16, min(30, max(len(str(ws.cell(row=i, column=col).value or '')) for i in range(1, ws.max_row + 1)) + 2))
            ws.freeze_panes = 'A2'

            wd = wb.create_sheet('Daily Attendance')
            dheaders = ['Date', 'Employee ID', 'Name', 'Plot No.', 'Code', 'P Units', 'Daily Salary (BDT/day)', 'Amount (BDT)']
            wd.append(dheaders)
            for c in wd[1]:
                c.font = Font(bold=True)
                c.alignment = Alignment(horizontal='center')
            for r in daily:
                wd.append([r[h] for h in dheaders])
            wd.freeze_panes = 'A2'
            for col in range(1, len(dheaders) + 1):
                wd.column_dimensions[get_column_letter(col)].width = max(14, min(30, max(len(str(wd.cell(row=i, column=col).value or '')) for i in range(1, wd.max_row + 1)) + 2))

            wb.save(p)
            messagebox.showinfo('Export Excel', f'Excel export completed:\n{p}', parent=self)
        except Exception as ex:
            messagebox.showerror('Export Excel', f'Could not create Excel file:\n{ex}', parent=self)

    def export_pdf(self, month):
        try:
            rows, _ = self._export_rows(month)
        except Exception as ex:
            messagebox.showerror('Export PDF', str(ex), parent=self)
            return
        p = filedialog.asksaveasfilename(
            defaultextension='.pdf', initialfile=f'WorkerPay_{month}.pdf',
            filetypes=[('PDF document', '*.pdf')])
        if not p:
            return
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            # Prefer a common Windows font so the document remains readable.
            font_name = 'Helvetica'
            for fp in (
                r'C:\Windows\Fonts\segoeui.ttf',
                r'C:\Windows\Fonts\arial.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
            ):
                if os.path.exists(fp):
                    try:
                        pdfmetrics.registerFont(TTFont('WorkerPaySans', fp))
                        font_name = 'WorkerPaySans'
                        break
                    except Exception:
                        pass

            doc = SimpleDocTemplate(p, pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
            styles = getSampleStyleSheet()
            title_style = styles['Title']
            title_style.fontName = font_name
            body_style = styles['BodyText']
            body_style.fontName = font_name
            y,m=map(int,month.split('-'));month_name=calendar.month_name[m]
            gross_total=sum(float(r['Total Amount (BDT)']) for r in rows)
            advance_total=self.month_advance_total(month,active_only=False)
            paid_total=float(self.db.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE month=?',(month,)).fetchone()[0] or 0)
            net_unpaid=max(gross_total-advance_total-paid_total,0.0)
            story = [Paragraph(f'WorkerPay — Monthly Salary Report — {month} ({month_name} {y})', title_style), Spacer(1, 6)]
            data = [['Employee ID', 'Name', 'Plot No.', 'Daily Salary (BDT/day)', 'Present Day (P)', 'Total Amount (BDT)']]
            for r in rows:
                data.append([r['Employee ID'], r['Name'], r['Plot No.'], f"{r['Daily Salary (BDT/day)']:,.2f}", f"{r['Present Day (P)']:g}P", f"{r['Total Amount (BDT)']:,.2f}"])
            if len(data) == 1:
                data.append(['—', 'No records', '—', '0.00', '0P', '0.00'])
            table = Table(data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#232832')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,-1), font_name),
                ('FONTNAME', (0,0), (-1,0), font_name),
                ('GRID', (0,0), (-1,-1), 0.4, colors.grey),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f3f4f6')]),
                ('FONTSIZE', (0,0), (-1,-1), 8),
                ('ALIGN', (3,1), (-1,-1), 'RIGHT'),
            ]))
            story.append(table)
            story.append(Spacer(1, 8))
            totals_data=[['Month',f'{month} ({month_name} {y})'],['Grand Total — All Employee Plots',f'{gross_total:,.2f} BDT'],['Total Advance Money',f'{advance_total:,.2f} BDT'],['Salary Payments Recorded',f'{paid_total:,.2f} BDT'],['Net Salary Still Unpaid',f'{net_unpaid:,.2f} BDT']]
            totals=Table(totals_data,colWidths=[70*mm,55*mm],hAlign='RIGHT');totals.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font_name),('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.35,colors.grey),('ALIGN',(1,0),(1,-1),'RIGHT'),('FONTNAME',(0,0),(-1,0),font_name)]))
            story.append(totals);story.append(Spacer(1, 10))
            advance_rows=self.db.execute('''SELECT a.advance_date,e.empid,e.name,a.amount,a.reason FROM advances a JOIN employees e ON e.id=a.employee_id WHERE a.advance_date>=? AND a.advance_date<=? ORDER BY a.advance_date,e.emp_number,e.id,a.id''',(f'{month}-01',f'{month}-{calendar.monthrange(y,m)[1]:02d}')).fetchall()
            story.append(Paragraph('Advance Money — Employee Detail', body_style));story.append(Spacer(1, 4))
            adata=[['Date','Employee ID','Name','Amount (BDT)','Reason']]
            for arow in advance_rows:
                adata.append([self.display_advance_date(arow['advance_date']),arow['empid'],arow['name'],f"{float(arow['amount']):,.2f}",arow['reason']])
            if len(adata)==1: adata.append(['—','—','No advance records','0.00','—'])
            at=Table(adata,repeatRows=1,colWidths=[24*mm,28*mm,50*mm,32*mm,65*mm])
            at.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#232832')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,-1),font_name),('GRID',(0,0),(-1,-1),0.35,colors.grey),('FONTSIZE',(0,0),(-1,-1),8),('ALIGN',(3,1),(3,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
            story.append(at);story.append(Spacer(1, 8))
            story.append(Paragraph(f'Report period: {month} ({month_name} {y}) • All employee/plot totals above are for this month only. Rules: P = 1P • P/2 = 0.5P • P+P/2 = 1.5P • 2P = 2P • A = 0P', body_style))
            doc.build(story)
            messagebox.showinfo('Export PDF', f'PDF export completed:\n{p}', parent=self)
        except Exception as ex:
            messagebox.showerror('Export PDF', f'Could not create PDF file:\n{ex}', parent=self)


def run_current_database_health():
    # Run against the real current %APPDATA%\WorkerPay database. Startup migration
    # and repair make a safety snapshot first when an older non-empty DB is detected.
    os.environ['WORKERPAY_TEST_MODE']='1'
    app=WorkerPay()
    try:
        quick=app.db.execute('PRAGMA quick_check').fetchone()[0]
        fk=app.db.execute('PRAGMA foreign_key_check').fetchall()
        audit_ok=app.verify_audit_log()
        backup=getattr(app,'_pre_migration_backup','')
        lines=[
            f'Database: {DB}',
            f'Quick check: {quick}',
            f'Foreign-key issues: {len(fk)}',
            f'Audit chain: {"OK" if audit_ok else "NEEDS REVIEW"}',
            f'Schema version: {app.db.execute("PRAGMA user_version").fetchone()[0]}',
        ]
        if backup: lines.append(f'Pre-migration safety backup: {backup}')
        ok=(quick=='ok' and not fk and audit_ok)
        return _write_test_report('Current Database Health',lines,'PASS' if ok else 'FAIL')
    finally:
        app.destroy()


def _write_test_report(title, lines, status='PASS'):
    out=os.environ.get(TEST_OUTPUT_ENV)
    text='\n'.join([f'WorkerPay {title}', '='*(len('WorkerPay '+title)), *lines, f'RESULT: {status}'])+'\n'
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding='utf-8')
    print(text, end='')
    return status == 'PASS'


def run_embedded_benchmark():
    import tempfile,shutil,sqlite3,time
    n=int(os.environ.get('WORKERPAY_BENCHMARK_N','100000'))
    # Allow a numeric CLI argument when launched by the Windows .bat runner.
    for arg in sys.argv[1:]:
        if arg.isdigit(): n=int(arg); break
    n=max(1,n)
    root=tempfile.mkdtemp(prefix='workerpay_bench_');path=os.path.join(root,'bench.db');c=sqlite3.connect(path)
    c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=NORMAL');c.execute('PRAGMA temp_store=MEMORY');c.execute('PRAGMA cache_size=-131072');c.execute('PRAGMA foreign_keys=ON')
    c.executescript('CREATE TABLE employees(id INTEGER PRIMARY KEY,empid TEXT UNIQUE,emp_number INTEGER,name TEXT,start TEXT,active INTEGER);CREATE TABLE plots(id INTEGER PRIMARY KEY,employee_id INTEGER,plot_no TEXT,daily_rate REAL,active INTEGER,FOREIGN KEY(employee_id) REFERENCES employees(id));CREATE TABLE attendance(id INTEGER PRIMARY KEY,employee_id INTEGER,plot_id INTEGER,day TEXT,code TEXT,FOREIGN KEY(employee_id) REFERENCES employees(id),FOREIGN KEY(plot_id) REFERENCES plots(id));CREATE INDEX e_num ON employees(emp_number);CREATE INDEX e_id ON employees(empid);CREATE INDEX p_no ON plots(plot_no);CREATE INDEX p_e ON plots(employee_id,active);CREATE INDEX a_d ON attendance(day);CREATE INDEX a_epd ON attendance(employee_id,plot_id,day);')
    timings=[];b=20000
    def tm(label,fn):
        t=time.perf_counter();r=fn();timings.append((label,time.perf_counter()-t));return r
    def ie():
        for st in range(1,n+1,b):
            en=min(n,st+b-1);c.executemany('INSERT INTO employees(empid,emp_number,name,start,active) VALUES(?,?,?,?,1)',[(f'EMP{i:03d}',i,f'Worker {i}','2026-09-01') for i in range(st,en+1)])
        c.commit()
    def ip():
        for st in range(1,n+1,b):
            en=min(n,st+b-1);rows=[]
            for i in range(st,en+1):rows.extend([(i,f'{1000000+i}',600.0,1),(i,f'{2000000+i}',650.0,1)])
            c.executemany('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,?)',rows)
        c.commit()
    def ia():
        codes=('P','P/2','P+P/2','2P','A');cur=c.execute('SELECT id,employee_id FROM plots ORDER BY id')
        while True:
            rows=cur.fetchmany(b)
            if not rows:break
            c.executemany('INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?)',[(eid,pid,'2026-09-01',codes[(eid+pid)%5]) for pid,eid in rows])
        c.commit()
    tm('Insert employees',ie);tm('Insert plots',ip);tm('Insert attendance',ia);tm('Count employees',lambda:c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]);tm('EMP010 lookup',lambda:c.execute('SELECT * FROM employees WHERE empid=?',('EMP010',)).fetchone());tm('Plot filter',lambda:c.execute('SELECT employee_id FROM plots WHERE plot_no=?',('1000100',)).fetchone());tm('Salary aggregate',lambda:c.execute("SELECT SUM(CASE code WHEN 'P' THEN 1.0 WHEN 'P/2' THEN .5 WHEN 'P+P/2' THEN 1.5 WHEN '2P' THEN 2.0 ELSE 0 END * CASE WHEN plot_id%2=0 THEN 650 ELSE 600 END) FROM attendance").fetchone()[0]);tm('SQLite quick_check',lambda:c.execute('PRAGMA quick_check').fetchone()[0])
    size=os.path.getsize(path)/1e6
    lines=[f'Rows tested: {n:,} employees / {n*2:,} plots / {n*2:,} attendance rows',*[(f'{label}: {secs:.3f}s') for label,secs in timings],f'Database size: {size:.1f} MB']
    c.close();shutil.rmtree(root,ignore_errors=True)
    return _write_test_report('High-Volume Benchmark',lines,'PASS')


def _make_test_app(prefix):
    global DATA_DIR, DB, LOG_FILE
    os.environ['APPDATA']=tempfile.mkdtemp(prefix=prefix)
    os.environ['WORKERPAY_TEST_MODE']='1'
    DATA_DIR=os.path.join(os.environ['APPDATA'], APP_NAME)
    os.makedirs(DATA_DIR, exist_ok=True)
    DB=os.path.join(DATA_DIR, 'workerpay.db')
    LOG_FILE=os.path.join(DATA_DIR, 'workerpay.log')
    app=WorkerPay();return app


def run_embedded_feature_regression_test():
    app=_make_test_app('workerpay_feature_regression_');fail=[]
    try:
        def walk(w):
            yield w
            for c in w.winfo_children():yield from walk(c)
        eid=app.db.execute("INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,1)",('EMP010',10,'Kajol',0,'2026-10-01')).lastrowid
        pid=app.db.execute('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',(eid,'1250',600)).lastrowid
        app.db.execute('INSERT INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(pid,'2026-10-01',600));app.db.commit()
        for d in range(1,7):
            app.save_attendance_cell(eid,pid,'2026-10',d,'P')
        # Blank days must remain physically absent from the database, not represented
        # as hidden/default attendance rows. Day 7 and Day 8 are the critical boundary.
        rows_1_6=app.db.execute('SELECT day,code FROM attendance WHERE employee_id=? AND plot_id=? ORDER BY day',(eid,pid)).fetchall()
        if [str(r['day']) for r in rows_1_6] != [f'2026-10-{d:02d}' for d in range(1,7)]:
            fail.append(f'Attendance cell mapping regression: {[str(r["day"]) for r in rows_1_6]}')
        units,money,_,_=app.calc_plot(eid,pid,'2026-10')
        if units!=6.0 or money!=3600.0:fail.append(f'Blank day 7 regression: units={units}, money={money}')
        if app.db.execute('SELECT 1 FROM attendance WHERE employee_id=? AND plot_id=? AND day=?',(eid,pid,'2026-10-07')).fetchone():
            fail.append('Blank Day 7 unexpectedly exists before user entry')
        app.save_attendance_cell(eid,pid,'2026-10',7,'P')
        app.db.commit()
        units,money,_,_=app.calc_plot(eid,pid,'2026-10')
        if units!=7.0 or money!=4200.0:fail.append(f'Day 7 insertion regression: units={units}, money={money}')
        try:
            app.db.execute('INSERT INTO attendance(employee_id,plot_id,day,code) VALUES(?,?,?,?)',(eid,pid,'2026-10-07','P'))
            app.db.commit()
            fail.append('Attendance UNIQUE(employee,plot,day) did not block duplicate cell')
        except sqlite3.IntegrityError:
            app.db.rollback()
        units,money,_,_=app.calc_plot(eid,pid,'2026-10')
        if units!=7.0 or money!=4200.0:fail.append(f'Duplicate attendance regression: units={units}, money={money}')
        units,money,_,_=app.calc_plot(eid,pid,'2026-10',1,8)
        if units!=7.0 or money!=4200.0:fail.append(f'Blank day 8 regression: units={units}, money={money}')
        app.save_attendance_cell(eid,pid,'2026-10',7,'')
        units,money,_,_=app.calc_plot(eid,pid,'2026-10')
        if units!=6.0 or money!=3600.0:fail.append(f'Cleared day 7 regression: units={units}, money={money}')
        if app.db.execute('SELECT 1 FROM attendance WHERE employee_id=? AND plot_id=? AND day=?',(eid,pid,'2026-10-08')).fetchone():
            fail.append('Blank Day 8 unexpectedly exists after Day 7 clear')
        app.save_attendance_cell(eid,pid,'2026-10',7,'P')
        app.build_advance_section if hasattr(app,'build_advance_section') else None
        app.db.execute('INSERT INTO advances(employee_id,advance_date,amount,reason,created_at) VALUES(?,?,?,?,?)',(eid,'2026-10-07',500,'Family need','2026-10-07T10:00:00'));app.db.commit()
        if app.employee_advance_amount(eid,'2026-10')!=500.0:fail.append('Advance amount calculation incorrect')
        rows=app.payment_rows('2026-10');
        if not rows or rows[0][3]!=500.0 or rows[0][4]!=3700.0:fail.append(f'Net due regression: {rows[0][3:5] if rows else None}')
        app.navigate(lambda: app.open_employee(eid,'2026-10'))
        deadline=time.time()+1.5
        while time.time()<deadline:
            app.update(); app.update_idletasks()
            if any(isinstance(w,tk.Label) and str(w.cget('text')).startswith('ADVANCE MONEY') for w in walk(app)): break
            time.sleep(0.01)
        if not any(isinstance(w,tk.Label) and str(w.cget('text')).startswith('ADVANCE MONEY') for w in walk(app)):
            fail.append('Advance Money section did not render under attendance page')
        app.navigate(lambda: app.salary_payments('2026-10',0), duration=0);app.update_idletasks()
        if not any(isinstance(w,ttk.Treeview) for w in walk(app)): fail.append('Salary Payments page did not render')
        app.navigate(lambda: app.open_employee(eid,'2026-10'));app.update_idletasks()
        deadline=time.time()+2.2
        while time.time()<deadline and getattr(app,'_transition_busy',False):
            app.update();time.sleep(0.01)
        # Find the Back button and invoke it directly.
        backs=[]
        for w in walk(app):
            if isinstance(w,ttk.Button) and w.cget('text')=='Back to Employees':backs.append(w)
        if not backs:fail.append('Back to Employees button not found')
        else:
            backs[0].invoke();app.update();app.update_idletasks()
            if app._page_key!='employees':fail.append(f'Back navigation page key is {app._page_key!r}')
        return _write_test_report('Feature Regression',[f'Errors: {len(fail)}',*fail],'PASS' if not fail else 'FAIL')
    finally: app.destroy()


def run_embedded_health_test():
    app=_make_test_app('workerpay_health_')
    try:
        quick=app.db.execute('PRAGMA quick_check').fetchone()[0]
        fk=app.db.execute('PRAGMA foreign_key_check').fetchall()
        audit=app.verify_audit_log()
        ok=(quick=='ok' and not fk and audit)
        lines=[f'Quick check: {quick}',f'Foreign-key issues after startup repair: {len(fk)}',f'Audit chain: {"OK" if audit else "FAILED"}']
        return _write_test_report('Database Health',lines,'PASS' if ok else 'FAIL')
    finally: app.destroy()


def run_embedded_geometry_test():
    import tkinter as tk
    app=_make_test_app('workerpay_geometry_');errors=[]
    def walk(w):
        yield w
        for c in w.winfo_children():yield from walk(c)
    try:
        for fn in (app.dashboard,app.employees,lambda:app.salary_filter()):
            try:fn();app.update_idletasks()
            except Exception as ex:errors.append(repr(ex))
        for parent in walk(app):
            managers={c.winfo_manager() for c in parent.winfo_children() if c.winfo_manager()}
            if 'pack' in managers and 'grid' in managers:errors.append('Mixed pack/grid in '+str(parent))
        return _write_test_report('Geometry Health', [f'Errors: {len(errors)}', *errors[:20]], 'PASS' if not errors else 'FAIL')
    finally: app.destroy()


def run_embedded_attendance_scroll_test():
    import tkinter as tk
    app=_make_test_app('workerpay_scroll_');fail=[]
    try:
        cur=app.db.execute("INSERT INTO employees(empid,emp_number,name,daily_rate,start,active) VALUES(?,?,?,?,?,1)",('EMP900010',900010,'Scroll Test','0','2026-09-01'));eid=cur.lastrowid
        for i in range(1,21):
            pid=app.db.execute('INSERT INTO plots(employee_id,plot_no,daily_rate,active) VALUES(?,?,?,1)',(eid,str(1200+i),600+i)).lastrowid
            app.db.execute('INSERT INTO plot_rate_history(plot_id,effective_from,daily_rate) VALUES(?,?,?)',(pid,'2026-09-01',600+i))
        app.db.commit();app.open_employee(eid,'2026-09')
        deadline=time.time()+2.5
        while time.time()<deadline:
            app.update();app.update_idletasks()
            if sum(1 for _,c,a in app._scroll_areas if a=='x' and isinstance(c,tk.Canvas))>=20:break
            time.sleep(0.01)
        vx=app._default_vertical_target;xs=[c for _,c,a in app._scroll_areas if a=='x' and isinstance(c,tk.Canvas)]
        if not vx or len(xs)!=20:fail.append(f'Expected 20 horizontal grids; found {len(xs)}')
        else:
            y0=float(vx.yview()[0]);app._queue_smooth_scroll(vx,-240,'y');
            deadline=time.time()+0.5
            while time.time()<deadline:app.update();time.sleep(0.01)
            if float(vx.yview()[0])<=y0:fail.append('Vertical scroll did not move')
            x0=float(xs[0].xview()[0]);app._queue_smooth_scroll(xs[0],-240,'x');deadline=time.time()+0.5
            while time.time()<deadline:app.update();time.sleep(0.01)
            if float(xs[0].xview()[0])<=x0:fail.append('Horizontal scroll did not move')
        return _write_test_report('Attendance Scroll', [f'Horizontal grids: {len(xs)}', *fail], 'PASS' if not fail else 'FAIL')
    finally: app.destroy()


if __name__ == '__main__':
    if '--performance-test' in sys.argv or '--benchmark' in sys.argv:
        raise SystemExit(0 if run_embedded_benchmark() else 1)
    if '--database-health-test' in sys.argv:
        raise SystemExit(0 if run_embedded_health_test() else 1)
    if '--current-database-health' in sys.argv:
        raise SystemExit(0 if run_current_database_health() else 1)
    if '--geometry-test' in sys.argv:
        raise SystemExit(0 if run_embedded_geometry_test() else 1)
    if '--attendance-scroll-test' in sys.argv:
        raise SystemExit(0 if run_embedded_attendance_scroll_test() else 1)
    if '--feature-regression-test' in sys.argv:
        raise SystemExit(0 if run_embedded_feature_regression_test() else 1)
    if '--self-test' in sys.argv:
        statuses = [
            run_embedded_health_test(),
            run_embedded_geometry_test(),
            run_embedded_attendance_scroll_test(),
            run_embedded_feature_regression_test(),
            run_embedded_benchmark(),
        ]
        raise SystemExit(0 if all(statuses) else 1)
    enable_windows_dpi_awareness();WorkerPay().mainloop()