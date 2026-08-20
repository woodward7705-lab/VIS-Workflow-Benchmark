import os, sys, csv, json, math, time, threading, ctypes
from ctypes import wintypes
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "VIS Workflow Benchmark"
VERSION = "0.2 USB Builder"
INACTIVITY_THRESHOLD = 3.0

# Hotkeys (excluded from keystroke count)
VK_F6, VK_F7, VK_F8, VK_F9, VK_F12 = 0x75, 0x76, 0x77, 0x78, 0x7B
HOTKEYS = {VK_F6, VK_F7, VK_F8, VK_F9, VK_F12}

IS_WINDOWS = sys.platform.startswith("win")

class BenchmarkState:
    def __init__(self):
        self.reset()
    def reset(self):
        self.running = False
        self.started = None
        self.finished = None
        self.clicks_left = 0
        self.clicks_right = 0
        self.clicks_middle = 0
        self.scroll_events = 0
        self.keystrokes = 0
        self.input_events = 0
        self.action_markers = 0
        self.decision_markers = 0
        self.software_wait = 0.0
        self.wait_started = None
        self.inactive_time = 0.0
        self.last_input = None
        self.mouse_distance_px = 0.0
        self.last_mouse = None
        self.undo_shortcuts = 0
        self._ctrl_down = False
    def elapsed(self):
        if not self.started: return 0.0
        end = self.finished or time.perf_counter()
        return max(0.0, end - self.started)
    def wait_elapsed(self):
        total = self.software_wait
        if self.wait_started is not None:
            total += time.perf_counter() - self.wait_started
        return total

state = BenchmarkState()
state_lock = threading.Lock()

# -------- Windows low-level input hooks --------
if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_MOUSEWHEEL = 0x020A
    WM_LBUTTONDOWN = 0x0201
    WM_RBUTTONDOWN = 0x0204
    WM_MBUTTONDOWN = 0x0207
    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
    VK_Z = 0x5A

    ULONG_PTR = wintypes.WPARAM
    LRESULT = ctypes.c_ssize_t

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]
    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    LowLevelProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    def _register_input_event(now=None):
        now = now or time.perf_counter()
        with state_lock:
            if not state.running: return
            if state.last_input is not None and state.wait_started is None:
                gap = now - state.last_input
                if gap > INACTIVITY_THRESHOLD:
                    state.inactive_time += gap
            state.last_input = now
            state.input_events += 1

    @LowLevelProc
    def keyboard_proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            now = time.perf_counter()
            # Hotkeys are control signals and intentionally excluded from normal key count.
            if vk == VK_F6: app_call("start")
            elif vk == VK_F7: app_call("action")
            elif vk == VK_F8: app_call("decision")
            elif vk == VK_F9: app_call("wait")
            elif vk == VK_F12: app_call("stop")
            else:
                with state_lock:
                    if state.running:
                        state.keystrokes += 1
                        # Undo is a useful rework proxy.
                        if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                            state._ctrl_down = True
                        elif vk == VK_Z and (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000):
                            state.undo_shortcuts += 1
                _register_input_event(now)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    @LowLevelProc
    def mouse_proc(nCode, wParam, lParam):
        if nCode >= 0:
            event = False
            with state_lock:
                if state.running:
                    if wParam == WM_LBUTTONDOWN: state.clicks_left += 1; event = True
                    elif wParam == WM_RBUTTONDOWN: state.clicks_right += 1; event = True
                    elif wParam == WM_MBUTTONDOWN: state.clicks_middle += 1; event = True
                    elif wParam == WM_MOUSEWHEEL: state.scroll_events += 1; event = True
            if event: _register_input_event()
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def hook_thread():
        k_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, kernel32.GetModuleHandleW(None), 0)
        m_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, kernel32.GetModuleHandleW(None), 0)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
        if k_hook: user32.UnhookWindowsHookEx(k_hook)
        if m_hook: user32.UnhookWindowsHookEx(m_hook)

    def mouse_distance_thread():
        pt = wintypes.POINT()
        while True:
            time.sleep(0.05)
            with state_lock:
                running = state.running
            if running and user32.GetCursorPos(ctypes.byref(pt)):
                p = (pt.x, pt.y)
                with state_lock:
                    if state.last_mouse is not None:
                        dx, dy = p[0]-state.last_mouse[0], p[1]-state.last_mouse[1]
                        state.mouse_distance_px += math.hypot(dx,dy)
                    state.last_mouse = p
            else:
                with state_lock: state.last_mouse = None
else:
    def hook_thread(): pass
    def mouse_distance_thread(): pass

# -------- data/reporting --------
def base_dir():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def results_dir():
    d = os.path.join(base_dir(), "Results")
    os.makedirs(d, exist_ok=True)
    return d

def fmt_time(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds//60:02d}:{seconds%60:02d}"

def make_test_id(): return datetime.now().strftime("%Y%m%d-%H%M%S")

FIELDS = [
    "Test_ID","Pair_ID","Timestamp","Task","Method","Tool_Version","Tester","Department",
    "Total_Time_sec","Active_Time_sec","Inactive_Assessment_sec","Software_Wait_sec",
    "Clicks_Total","Clicks_Left","Clicks_Right","Clicks_Middle","Scroll_Events","Keystrokes",
    "Input_Events","Action_Markers","Decision_Markers","Undo_Shortcuts","Mouse_Travel_px",
    "Frequency_Per_Month","Users_Affected","Notes","Recorder_Version"
]

def current_record(meta):
    with state_lock:
        total = state.elapsed()
        wait = state.wait_elapsed()
        inactive = state.inactive_time
        # Capture trailing idle only if it exceeds threshold; exclude wait.
        if state.running is False and state.last_input and state.wait_started is None and state.finished:
            gap = state.finished - state.last_input
            if gap > INACTIVITY_THRESHOLD: inactive += gap
        # Inactivity can overlap wait only due to marking boundaries; clamp defensively.
        active = max(0.0, total - wait - inactive)
        clicks = state.clicks_left + state.clicks_right + state.clicks_middle
        rec = {
            "Test_ID": meta["test_id"], "Pair_ID": meta["pair_id"],
            "Timestamp": datetime.now().isoformat(timespec="seconds"), "Task": meta["task"],
            "Method": meta["method"], "Tool_Version": meta["tool_version"], "Tester": meta["tester"],
            "Department": meta["department"], "Total_Time_sec": round(total,3),
            "Active_Time_sec": round(active,3), "Inactive_Assessment_sec": round(inactive,3),
            "Software_Wait_sec": round(wait,3), "Clicks_Total": clicks,
            "Clicks_Left": state.clicks_left, "Clicks_Right": state.clicks_right,
            "Clicks_Middle": state.clicks_middle, "Scroll_Events": state.scroll_events,
            "Keystrokes": state.keystrokes, "Input_Events": state.input_events,
            "Action_Markers": state.action_markers, "Decision_Markers": state.decision_markers,
            "Undo_Shortcuts": state.undo_shortcuts, "Mouse_Travel_px": round(state.mouse_distance_px,1),
            "Frequency_Per_Month": meta["frequency"], "Users_Affected": meta["users"],
            "Notes": meta["notes"], "Recorder_Version": VERSION
        }
        return rec

def append_csv(rec):
    path = os.path.join(results_dir(), "VIS_Workflow_Benchmark_Data.csv")
    exists = os.path.exists(path)
    with open(path,"a",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f, fieldnames=FIELDS)
        if not exists: w.writeheader()
        w.writerow(rec)
    return path

def load_pair(pair_id):
    path = os.path.join(results_dir(), "VIS_Workflow_Benchmark_Data.csv")
    if not pair_id or not os.path.exists(path): return []
    with open(path,newline="",encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("Pair_ID")==pair_id]

def save_json(rec):
    path=os.path.join(results_dir(), f"{rec['Test_ID']}_{safe_name(rec['Task'])}.json")
    with open(path,"w",encoding="utf-8") as f: json.dump(rec,f,indent=2)
    return path

def safe_name(s):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in s).strip('_')[:50] or 'Task'

def _num(r,k):
    try:return float(r.get(k,0) or 0)
    except:return 0.0

def draw_time_pie3d(c, record, x, y, width, height, title):
    """Draw a 3D-style time-composition pie directly into a PDF canvas."""
    try:
        from reportlab.graphics.shapes import Drawing, String
        from reportlab.graphics.charts.piecharts import Pie3d
        from reportlab.graphics import renderPDF
        from reportlab.lib import colors

        vals = [
            max(0.0, _num(record, 'Active_Time_sec')),
            max(0.0, _num(record, 'Inactive_Assessment_sec')),
            max(0.0, _num(record, 'Software_Wait_sec')),
        ]
        if sum(vals) <= 0:
            vals = [1, 0, 0]
        d = Drawing(width, height)
        pie = Pie3d()
        pie.x = 8
        pie.y = 8
        pie.width = min(width * 0.58, 150)
        pie.height = min(height * 0.70, 95)
        pie.data = vals
        pie.labels = None
        pie.slices.strokeWidth = 0.4
        # Stable report palette; raw Power BI data is unchanged.
        palette = [colors.HexColor('#2B7A78'), colors.HexColor('#F0A04B'), colors.HexColor('#8A9399')]
        names = ['Active', 'Assessment', 'Software wait']
        for i, col in enumerate(palette):
            pie.slices[i].fillColor = col
        d.add(pie)
        d.add(String(8, height-11, title, fontName='Helvetica-Bold', fontSize=8,
                     fillColor=colors.HexColor('#172A3A')))
        # Compact legend avoids clipped pie labels on A4 and remains readable on A3.
        total = max(sum(vals), 0.001)
        lx = min(width * 0.64, 175)
        ly = height - 35
        from reportlab.graphics.shapes import Rect
        for i, (name, val, col) in enumerate(zip(names, vals, palette)):
            yy = ly - i * 20
            d.add(Rect(lx, yy-6, 8, 8, fillColor=col, strokeColor=None))
            pct = val / total * 100
            d.add(String(lx+13, yy-5, f'{name}  {fmt_time(val)}  ({pct:.0f}%)',
                         fontName='Helvetica', fontSize=7, fillColor=colors.HexColor('#172A3A')))
        renderPDF.draw(d, c, x, y)
        return True
    except Exception:
        return False

def generate_reports(rec, pair_rows):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4, A3, landscape
        from reportlab.lib import colors
    except Exception:
        return []
    outs=[]
    navy=colors.HexColor('#172A3A'); teal=colors.HexColor('#2B7A78'); light=colors.HexColor('#EEF3F5'); orange=colors.HexColor('#F0A04B')
    # Find the best comparison: latest other row in same pair.
    other=None
    for r in reversed(pair_rows):
        if r.get('Test_ID') != rec['Test_ID']:
            other=r; break
    rows=[other,rec] if other else [rec]

    # A4 evidence report
    p=os.path.join(results_dir(),f"{rec['Test_ID']}_{safe_name(rec['Task'])}_A4_Report.pdf")
    c=canvas.Canvas(p,pagesize=A4); W,H=A4
    c.setFillColor(navy); c.rect(0,H-105,W,105,fill=1,stroke=0)
    c.setFillColor(colors.white); c.setFont('Helvetica-Bold',20); c.drawString(36,H-50,"VIS WORKFLOW BENCHMARK")
    c.setFont('Helvetica',11); c.drawString(36,H-72,rec['Task']); c.drawRightString(W-36,H-72,rec['Method'])
    y=H-140
    metrics=[('TOTAL TIME','Total_Time_sec','time'),('CLICKS','Clicks_Total','int'),('ACTIONS','Action_Markers','int'),('DECISIONS','Decision_Markers','int'),('ASSESSMENT','Inactive_Assessment_sec','time'),('SOFTWARE WAIT','Software_Wait_sec','time'),('KEYSTROKES','Keystrokes','int'),('UNDO / REWORK','Undo_Shortcuts','int')]
    colw=(W-72)/4
    for i,(lab,key,typ) in enumerate(metrics):
        rr=rec; x=36+(i%4)*colw; yy=y-(i//4)*80
        c.setFillColor(light); c.roundRect(x,yy-55,colw-8,62,6,fill=1,stroke=0)
        c.setFillColor(navy); c.setFont('Helvetica-Bold',9); c.drawString(x+10,yy-8,lab)
        v=_num(rr,key); txt=fmt_time(v) if typ=='time' else str(int(round(v)))
        c.setFont('Helvetica-Bold',20); c.drawString(x+10,yy-38,txt)
    y2=y-185
    c.setFillColor(navy); c.setFont('Helvetica-Bold',12); c.drawString(36,y2,"TIME COMPOSITION")
    total=max(_num(rec,'Total_Time_sec'),0.001); parts=[('Active',_num(rec,'Active_Time_sec'),teal),('Assessment',_num(rec,'Inactive_Assessment_sec'),orange),('Software wait',_num(rec,'Software_Wait_sec'),colors.grey)]
    bx=36; by=y2-35; bw=W-72; bh=22; cursor=bx
    for lab,val,col in parts:
        ww=bw*(val/total); c.setFillColor(col); c.rect(cursor,by,ww,bh,fill=1,stroke=0); cursor+=ww
    c.setFillColor(colors.black); c.setFont('Helvetica',8); c.drawString(36,by-15,"Active / Assessment (>3 sec no input) / Software wait marked explicitly")
    y3=by-65
    if other:
        c.setFont('Helvetica-Bold',12); c.setFillColor(navy); c.drawString(36,y3,"PAIR COMPARISON")
        y3-=25
        compare=[('Total time','Total_Time_sec'),('Clicks','Clicks_Total'),('Actions','Action_Markers'),('Decisions','Decision_Markers'),('Assessment','Inactive_Assessment_sec'),('Software wait','Software_Wait_sec')]
        c.setFont('Helvetica-Bold',8); c.drawString(36,y3,'METRIC'); c.drawString(170,y3,other.get('Method','Other')[:20]); c.drawString(290,y3,rec['Method'][:20]); c.drawString(410,y3,'CHANGE')
        y3-=14
        for lab,key in compare:
            a,b=_num(other,key),_num(rec,key); change=((a-b)/a*100) if a else 0
            c.setFont('Helvetica',8); c.drawString(36,y3,lab)
            av=fmt_time(a) if 'Time' in key or 'sec' in key else str(int(a)); bv=fmt_time(b) if 'Time' in key or 'sec' in key else str(int(b))
            c.drawString(170,y3,av); c.drawString(290,y3,bv); c.setFont('Helvetica-Bold',8); c.drawString(410,y3,f"{change:+.1f}% saved" if a else '-')
            y3-=15
    # Supporting 3D time-composition visuals. They complement, rather than replace, the exact KPI table.
    if other:
        draw_time_pie3d(c, other, 36, 72, 245, 118, f"{other.get('Method','Other')} - time composition")
        draw_time_pie3d(c, rec, 305, 72, 245, 118, f"{rec.get('Method','Current')} - time composition")
    c.setFillColor(colors.grey); c.setFont('Helvetica',7); c.drawString(36,32,f"Test ID: {rec['Test_ID']} | Pair: {rec['Pair_ID'] or '-'} | Recorder: {VERSION}")
    c.save(); outs.append(p)

    # A3 presentation-style report
    p2=os.path.join(results_dir(),f"{rec['Test_ID']}_{safe_name(rec['Task'])}_A3_Presentation.pdf")
    c=canvas.Canvas(p2,pagesize=landscape(A3)); W,H=landscape(A3)
    c.setFillColor(colors.white); c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(navy); c.rect(0,H-120,W,120,fill=1,stroke=0)
    c.setFillColor(colors.white); c.setFont('Helvetica-Bold',27); c.drawString(55,H-58,rec['Task'].upper())
    c.setFont('Helvetica',13); c.drawString(55,H-84,"Workflow benchmark - evidence of time, interaction and cognitive load")
    if other:
        a=other; b=rec
        at=max(_num(a,'Total_Time_sec'),0.001); bt=_num(b,'Total_Time_sec'); save=(at-bt)/at*100
        c.setFillColor(navy); c.setFont('Helvetica-Bold',55); c.drawString(55,H-220,f"{save:.0f}%")
        c.setFont('Helvetica-Bold',15); c.drawString(58,H-245,"TOTAL TIME SAVED")
        # comparison cards
        card_y=H-390; card_w=(W-140)/2
        for j,r in enumerate([a,b]):
            x=55+j*(card_w+30); c.setFillColor(light); c.roundRect(x,card_y,card_w,120,10,fill=1,stroke=0)
            c.setFillColor(navy); c.setFont('Helvetica-Bold',14); c.drawString(x+20,card_y+91,r.get('Method','METHOD').upper()[:25])
            c.setFont('Helvetica-Bold',35); c.drawString(x+20,card_y+45,fmt_time(_num(r,'Total_Time_sec')))
            c.setFont('Helvetica',11); c.drawString(x+190,card_y+70,f"{int(_num(r,'Clicks_Total'))} clicks")
            c.drawString(x+190,card_y+50,f"{int(_num(r,'Action_Markers'))} actions")
            c.drawString(x+190,card_y+30,f"{int(_num(r,'Decision_Markers'))} decisions")
        # 3D time-composition pies: visual support for the headline comparison.
        draw_time_pie3d(c, a, 55, 175, 330, 150, f"{a.get('Method','Existing')} - where task time goes")
        draw_time_pie3d(c, b, 430, 175, 330, 150, f"{b.get('Method','Automated')} - where task time goes")
        # bottom KPI reductions
        y=90; keys=[('CLICKS','Clicks_Total'),('ACTIONS','Action_Markers'),('DECISIONS','Decision_Markers'),('ASSESSMENT','Inactive_Assessment_sec')]
        cw=(W-110)/4
        for i,(lab,key) in enumerate(keys):
            av,bv=_num(a,key),_num(b,key); pct=((av-bv)/av*100) if av else 0
            x=55+i*cw; c.setFillColor(teal); c.setFont('Helvetica-Bold',28); c.drawString(x,y+32,f"{pct:.0f}%")
            c.setFillColor(navy); c.setFont('Helvetica-Bold',10); c.drawString(x,y+12,lab+' REDUCTION')
    else:
        c.setFillColor(navy); c.setFont('Helvetica-Bold',46); c.drawString(55,H-235,fmt_time(_num(rec,'Total_Time_sec')))
        c.setFont('Helvetica-Bold',15); c.drawString(58,H-260,"TOTAL TASK TIME")
        y=H-410; vals=[('CLICKS','Clicks_Total'),('ACTIONS','Action_Markers'),('DECISIONS','Decision_Markers'),('SOFTWARE WAIT','Software_Wait_sec')]
        cw=(W-110)/4
        for i,(lab,key) in enumerate(vals):
            x=55+i*cw; v=_num(rec,key); txt=fmt_time(v) if 'sec' in key else str(int(v))
            c.setFillColor(light); c.roundRect(x,y,cw-25,100,8,fill=1,stroke=0); c.setFillColor(navy); c.setFont('Helvetica-Bold',30); c.drawString(x+18,y+48,txt); c.setFont('Helvetica-Bold',10); c.drawString(x+18,y+22,lab)
    c.setFillColor(colors.grey); c.setFont('Helvetica',8); c.drawRightString(W-45,30,f"VIS Workflow Benchmark | {rec['Test_ID']}")
    c.save(); outs.append(p2)
    return outs

# -------- GUI --------
root = None
labels = {}
vars_ = {}

def app_call(action):
    if root:
        try: root.after(0, lambda: dispatch(action))
        except: pass

def dispatch(action):
    if action=='start': start_test()
    elif action=='stop': stop_test()
    elif action=='action': mark_action()
    elif action=='decision': mark_decision()
    elif action=='wait': toggle_wait()

def meta_from_form():
    task=vars_['task'].get().strip()
    if not task: raise ValueError("Enter a task name first.")
    return {
        'test_id': make_test_id(), 'pair_id': vars_['pair'].get().strip(), 'task': task,
        'method': vars_['method'].get().strip() or 'Unspecified', 'tool_version': vars_['tool_version'].get().strip(),
        'tester': vars_['tester'].get().strip(), 'department': vars_['department'].get().strip() or 'VIS',
        'frequency': vars_['frequency'].get().strip(), 'users': vars_['users'].get().strip(), 'notes': vars_['notes'].get().strip()
    }

current_meta=None

def start_test():
    global current_meta
    if not IS_WINDOWS:
        messagebox.showerror(APP_NAME,"Global input recording is enabled only on Windows. Reports/data functions remain portable."); return
    with state_lock:
        if state.running: return
    try: meta=meta_from_form()
    except Exception as e: messagebox.showwarning(APP_NAME,str(e)); return
    current_meta=meta
    with state_lock:
        state.reset(); state.running=True; state.started=time.perf_counter(); state.last_input=state.started
    set_status("RUNNING", "#0A7B34")

def stop_test():
    global current_meta
    with state_lock:
        if not state.running: return
        now=time.perf_counter()
        if state.wait_started is not None:
            state.software_wait += now-state.wait_started; state.wait_started=None
        state.finished=now; state.running=False
    set_status("FINISHED", "#8B1E1E")
    rec=current_record(current_meta)
    csvp=append_csv(rec); save_json(rec); pair=load_pair(rec['Pair_ID']); pdfs=generate_reports(rec,pair)
    msg=f"Test saved.\n\nCSV: {csvp}"
    if pdfs: msg += "\n\nReports created:\n" + "\n".join(os.path.basename(p) for p in pdfs)
    messagebox.showinfo(APP_NAME,msg)

def mark_action():
    with state_lock:
        if state.running: state.action_markers += 1

def mark_decision():
    with state_lock:
        if state.running: state.decision_markers += 1

def toggle_wait():
    with state_lock:
        if not state.running: return
        now=time.perf_counter()
        if state.wait_started is None:
            state.wait_started=now
        else:
            state.software_wait += now-state.wait_started; state.wait_started=None; state.last_input=now

def set_status(text,color):
    if 'status' in labels:
        labels['status'].config(text=text, foreground=color)

def update_ui():
    with state_lock:
        labels['time'].config(text=fmt_time(state.elapsed()))
        labels['clicks'].config(text=str(state.clicks_left+state.clicks_right+state.clicks_middle))
        labels['keys'].config(text=str(state.keystrokes))
        labels['actions'].config(text=str(state.action_markers))
        labels['decisions'].config(text=str(state.decision_markers))
        labels['wait'].config(text=fmt_time(state.wait_elapsed()))
        if state.running and state.wait_started is not None: set_status("SOFTWARE WAIT", "#A55A00")
        elif state.running: set_status("RUNNING", "#0A7B34")
    root.after(200,update_ui)

def build_gui():
    global root
    root=tk.Tk(); root.title(f"{APP_NAME} - {VERSION}"); root.geometry('760x570'); root.resizable(False,False)
    style=ttk.Style();
    try: style.theme_use('vista')
    except: pass
    outer=ttk.Frame(root,padding=18); outer.pack(fill='both',expand=True)
    ttk.Label(outer,text="VIS WORKFLOW BENCHMARK",font=('Segoe UI',18,'bold')).grid(row=0,column=0,columnspan=4,sticky='w')
    ttk.Label(outer,text="Controlled pure-task benchmarking for Vectorworks workflows",font=('Segoe UI',10)).grid(row=1,column=0,columnspan=4,sticky='w',pady=(0,14))
    fields=[('Task','task','Pirate Playground Marking'),('Method','method','Manual'),('Pair ID','pair','PIRATE-001'),('Tool / workflow version','tool_version','Existing'),('Tester','tester',''),('Department','department','VIS'),('Frequency / month','frequency',''),('Users affected','users','')]
    for i,(lab,key,default) in enumerate(fields):
        r=2+i//2; c=(i%2)*2
        ttk.Label(outer,text=lab).grid(row=r,column=c,sticky='w',padx=(0,6),pady=4)
        v=tk.StringVar(value=default); vars_[key]=v; ttk.Entry(outer,textvariable=v,width=29).grid(row=r,column=c+1,sticky='w',pady=4)
    ttk.Label(outer,text='Notes').grid(row=6,column=0,sticky='w',pady=4); vars_['notes']=tk.StringVar(); ttk.Entry(outer,textvariable=vars_['notes'],width=71).grid(row=6,column=1,columnspan=3,sticky='we',pady=4)
    ttk.Separator(outer,orient='horizontal').grid(row=7,column=0,columnspan=4,sticky='we',pady=14)
    labels['status']=ttk.Label(outer,text='READY',font=('Segoe UI',13,'bold')); labels['status'].grid(row=8,column=0,columnspan=4,sticky='w')
    metric_defs=[('TIME','time'),('CLICKS','clicks'),('KEYS','keys'),('ACTIONS','actions'),('DECISIONS','decisions'),('SOFTWARE WAIT','wait')]
    for i,(lab,key) in enumerate(metric_defs):
        c=i%3; r=9+(i//3)*2
        ttk.Label(outer,text=lab,font=('Segoe UI',8,'bold')).grid(row=r,column=c,sticky='w',padx=(0,40),pady=(10,0))
        labels[key]=ttk.Label(outer,text='00:00' if key in ('time','wait') else '0',font=('Segoe UI',24,'bold')); labels[key].grid(row=r+1,column=c,sticky='w')
    ttk.Separator(outer,orient='horizontal').grid(row=13,column=0,columnspan=4,sticky='we',pady=14)
    ttk.Button(outer,text='START  F6',command=start_test).grid(row=14,column=0,sticky='we',padx=4)
    ttk.Button(outer,text='ACTION +1  F7',command=mark_action).grid(row=14,column=1,sticky='we',padx=4)
    ttk.Button(outer,text='DECISION +1  F8',command=mark_decision).grid(row=14,column=2,sticky='we',padx=4)
    ttk.Button(outer,text='WAIT START/END  F9',command=toggle_wait).grid(row=15,column=0,columnspan=2,sticky='we',padx=4,pady=8)
    ttk.Button(outer,text='FINISH + REPORT  F12',command=stop_test).grid(row=15,column=2,columnspan=2,sticky='we',padx=4,pady=8)
    ttk.Label(outer,text="F7 marks one meaningful workflow action; F8 marks one genuine decision. F9 brackets Vectorworks processing/waiting.\nNo keys, screen contents or typed text are stored - only counts and timings.",font=('Segoe UI',9)).grid(row=16,column=0,columnspan=4,sticky='w',pady=(6,0))
    for c in range(4): outer.columnconfigure(c,weight=1)
    root.after(200,update_ui)
    return root

if __name__=='__main__':
    if IS_WINDOWS:
        threading.Thread(target=hook_thread,daemon=True).start()
        threading.Thread(target=mouse_distance_thread,daemon=True).start()
    build_gui().mainloop()

