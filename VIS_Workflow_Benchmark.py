import os, sys, csv, json, math, time, threading, ctypes
from ctypes import wintypes
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "VIS Workflow Benchmark"
VERSION = "0.6 USB Builder - Safe Mouse Capture"
IS_WINDOWS = sys.platform.startswith("win")
INACTIVITY_THRESHOLD = 3.0
VK_F6, VK_F7, VK_F8, VK_F9, VK_F12 = 0x75, 0x76, 0x77, 0x78, 0x7B

class State:
    def __init__(self): self.reset()
    def reset(self):
        self.running=False; self.started=None; self.finished=None
        self.clicks_left=0; self.clicks_right=0; self.clicks_middle=0
        self.actions=0; self.decisions=0; self.wait_total=0.0; self.wait_started=None
        self.last_input=None; self.inactive=0.0; self.mouse_distance=0.0
    def elapsed(self):
        if not self.started: return 0.0
        return max(0.0,(self.finished or time.perf_counter())-self.started)
    def wait_elapsed(self):
        x=self.wait_total
        if self.wait_started is not None: x += time.perf_counter()-self.wait_started
        return x

state=State(); lock=threading.Lock(); root=None; labels={}; vars_={}; current_meta=None

def fmt_time(s):
    s=max(0,int(round(s))); return f"{s//60:02d}:{s%60:02d}"

def base_dir():
    return os.path.dirname(sys.executable) if getattr(sys,'frozen',False) else os.path.dirname(os.path.abspath(__file__))

def results_dir():
    p=os.path.join(base_dir(),'Results'); os.makedirs(p,exist_ok=True); return p

def safe_name(s):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in s).strip('_')[:50] or 'Task'

def app_call(action):
    if root:
        try: root.after(0, lambda: dispatch(action))
        except: pass

def _register_activity(now=None):
    now=now or time.perf_counter()
    with lock:
        if not state.running: return
        if state.last_input is not None and state.wait_started is None:
            gap=now-state.last_input
            if gap>INACTIVITY_THRESHOLD: state.inactive += gap
        state.last_input=now

if IS_WINDOWS:
    user32=ctypes.windll.user32
    VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01,0x02,0x04
    def _down(vk): return bool(user32.GetAsyncKeyState(vk) & 0x8000)
    def safe_poll_thread():
        watched=(VK_LBUTTON,VK_RBUTTON,VK_MBUTTON,VK_F6,VK_F7,VK_F8,VK_F9,VK_F12)
        prev={vk:False for vk in watched}; pt=wintypes.POINT(); last_pt=None
        while True:
            now=time.perf_counter(); cur={vk:_down(vk) for vk in watched}
            for vk in watched:
                if cur[vk] and not prev[vk]:
                    if vk==VK_F6: app_call('start')
                    elif vk==VK_F7: app_call('action')
                    elif vk==VK_F8: app_call('decision')
                    elif vk==VK_F9: app_call('wait')
                    elif vk==VK_F12: app_call('stop')
                    else:
                        counted=False
                        with lock:
                            if state.running:
                                if vk==VK_LBUTTON: state.clicks_left+=1; counted=True
                                elif vk==VK_RBUTTON: state.clicks_right+=1; counted=True
                                elif vk==VK_MBUTTON: state.clicks_middle+=1; counted=True
                        if counted: _register_activity(now)
            prev=cur
            with lock: running=state.running
            if running and user32.GetCursorPos(ctypes.byref(pt)):
                p=(pt.x,pt.y)
                if last_pt is not None:
                    d=math.hypot(p[0]-last_pt[0],p[1]-last_pt[1])
                    if d>0:
                        with lock:
                            state.mouse_distance += d; state.last_input=now
                last_pt=p
            else: last_pt=None
            time.sleep(0.01)
else:
    def safe_poll_thread(): pass

def meta_from_form():
    task=vars_['task'].get().strip()
    if not task: raise ValueError('Enter a task name first.')
    return {
        'test_id':datetime.now().strftime('%Y%m%d-%H%M%S'),'pair':vars_['pair'].get().strip(),
        'task':task,'method':vars_['method'].get().strip() or 'Unspecified',
        'tool':vars_['tool'].get().strip(),'tester':vars_['tester'].get().strip(),
        'department':vars_['department'].get().strip() or 'VIS','frequency':vars_['frequency'].get().strip(),
        'users':vars_['users'].get().strip(),'notes':vars_['notes'].get().strip()
    }

def current_record(meta):
    with lock:
        total=state.elapsed(); wait=state.wait_elapsed(); inactive=state.inactive
        active=max(0.0,total-wait-inactive)
        return {
            'Test_ID':meta['test_id'],'Pair_ID':meta['pair'],'Timestamp':datetime.now().isoformat(timespec='seconds'),
            'Task':meta['task'],'Method':meta['method'],'Tool_Version':meta['tool'],'Tester':meta['tester'],
            'Department':meta['department'],'Total_Time_sec':round(total,3),'Active_Time_sec':round(active,3),
            'Inactive_Assessment_sec':round(inactive,3),'Software_Wait_sec':round(wait,3),
            'Clicks_Total':state.clicks_left+state.clicks_right+state.clicks_middle,
            'Clicks_Left':state.clicks_left,'Clicks_Right':state.clicks_right,'Clicks_Middle':state.clicks_middle,
            'Keystrokes':0,'Action_Markers':state.actions,'Decision_Markers':state.decisions,
            'Mouse_Travel_px':round(state.mouse_distance,1),'Frequency_Per_Month':meta['frequency'],
            'Users_Affected':meta['users'],'Notes':meta['notes'],'Recorder_Version':VERSION,
            'Capture_Mode':'Safe mouse polling; keyboard text/count disabled'
        }

FIELDS=['Test_ID','Pair_ID','Timestamp','Task','Method','Tool_Version','Tester','Department','Total_Time_sec','Active_Time_sec','Inactive_Assessment_sec','Software_Wait_sec','Clicks_Total','Clicks_Left','Clicks_Right','Clicks_Middle','Keystrokes','Action_Markers','Decision_Markers','Mouse_Travel_px','Frequency_Per_Month','Users_Affected','Notes','Recorder_Version','Capture_Mode']

def append_csv(rec):
    p=os.path.join(results_dir(),'VIS_Workflow_Benchmark_Data.csv'); exists=os.path.exists(p)
    with open(p,'a',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        if not exists: w.writeheader()
        w.writerow(rec)
    return p

def save_json(rec):
    p=os.path.join(results_dir(),f"{rec['Test_ID']}_{safe_name(rec['Task'])}.json")
    with open(p,'w',encoding='utf-8') as f: json.dump(rec,f,indent=2)

def load_pair(pair_id):
    p=os.path.join(results_dir(),'VIS_Workflow_Benchmark_Data.csv')
    if not pair_id or not os.path.exists(p): return []
    with open(p,newline='',encoding='utf-8-sig') as f:
        return [r for r in csv.DictReader(f) if r.get('Pair_ID')==pair_id]

def num(r,k):
    try:return float(r.get(k,0) or 0)
    except:return 0.0

def draw_pie(c,r,x,y,w,h,title):
    try:
        from reportlab.graphics.shapes import Drawing,String,Rect
        from reportlab.graphics.charts.piecharts import Pie3d
        from reportlab.graphics import renderPDF
        from reportlab.lib import colors
        vals=[max(0,num(r,'Active_Time_sec')),max(0,num(r,'Inactive_Assessment_sec')),max(0,num(r,'Software_Wait_sec'))]
        if sum(vals)<=0: vals=[1,0,0]
        d=Drawing(w,h); p=Pie3d(); p.x=8;p.y=8;p.width=min(w*.58,150);p.height=min(h*.70,95);p.data=vals;p.labels=None
        cols=[colors.HexColor('#2B7A78'),colors.HexColor('#F0A04B'),colors.HexColor('#8A9399')]
        names=['Active','Assessment','Software wait']
        for i,col in enumerate(cols): p.slices[i].fillColor=col
        d.add(p); d.add(String(8,h-11,title,fontName='Helvetica-Bold',fontSize=8,fillColor=colors.HexColor('#172A3A')))
        total=max(sum(vals),.001); lx=min(w*.64,175); ly=h-35
        for i,(name,val,col) in enumerate(zip(names,vals,cols)):
            yy=ly-i*20; d.add(Rect(lx,yy-6,8,8,fillColor=col,strokeColor=None)); d.add(String(lx+13,yy-5,f'{name} {fmt_time(val)} ({val/total*100:.0f}%)',fontName='Helvetica',fontSize=7,fillColor=colors.HexColor('#172A3A')))
        renderPDF.draw(d,c,x,y)
    except: pass

def generate_reports(rec,pair_rows):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4,A3,landscape
        from reportlab.lib import colors
    except: return []
    navy=colors.HexColor('#172A3A'); light=colors.HexColor('#EEF3F5'); outs=[]
    other=None
    for r in reversed(pair_rows):
        if r.get('Test_ID')!=rec['Test_ID']: other=r; break
    p=os.path.join(results_dir(),f"{rec['Test_ID']}_{safe_name(rec['Task'])}_A4_Report.pdf")
    c=canvas.Canvas(p,pagesize=A4);W,H=A4;c.setFillColor(navy);c.rect(0,H-105,W,105,fill=1,stroke=0);c.setFillColor(colors.white);c.setFont('Helvetica-Bold',20);c.drawString(36,H-50,'VIS WORKFLOW BENCHMARK');c.setFont('Helvetica',11);c.drawString(36,H-72,rec['Task'])
    y=H-145; metrics=[('TOTAL TIME','Total_Time_sec','t'),('CLICKS','Clicks_Total','i'),('ACTIONS','Action_Markers','i'),('DECISIONS','Decision_Markers','i'),('SOFTWARE WAIT','Software_Wait_sec','t'),('MOUSE TRAVEL','Mouse_Travel_px','i')];cw=(W-72)/3
    for i,(lab,key,typ) in enumerate(metrics):
        x=36+(i%3)*cw; yy=y-(i//3)*80;c.setFillColor(light);c.roundRect(x,yy-55,cw-8,62,6,fill=1,stroke=0);c.setFillColor(navy);c.setFont('Helvetica-Bold',9);c.drawString(x+10,yy-8,lab);v=num(rec,key);txt=fmt_time(v) if typ=='t' else str(int(round(v)));c.setFont('Helvetica-Bold',20);c.drawString(x+10,yy-38,txt)
    c.setFont('Helvetica',8);c.setFillColor(colors.grey);c.drawString(36,H-350,'SAFE MODE: keyboard text/keystroke count is not captured. Mouse clicks are counted globally.')
    if other: draw_pie(c,other,36,72,245,118,f"{other.get('Method','Other')} - time composition"); draw_pie(c,rec,305,72,245,118,f"{rec.get('Method','Current')} - time composition")
    c.save();outs.append(p)
    p2=os.path.join(results_dir(),f"{rec['Test_ID']}_{safe_name(rec['Task'])}_A3_Presentation.pdf");c=canvas.Canvas(p2,pagesize=landscape(A3));W,H=landscape(A3);c.setFillColor(colors.white);c.rect(0,0,W,H,fill=1,stroke=0);c.setFillColor(navy);c.rect(0,H-120,W,120,fill=1,stroke=0);c.setFillColor(colors.white);c.setFont('Helvetica-Bold',27);c.drawString(55,H-58,rec['Task'].upper());c.setFont('Helvetica',13);c.drawString(55,H-84,'Workflow benchmark - time, clicks, actions, decisions and software wait')
    c.setFillColor(navy);c.setFont('Helvetica-Bold',46);c.drawString(55,H-235,fmt_time(num(rec,'Total_Time_sec')));c.setFont('Helvetica-Bold',15);c.drawString(58,H-260,'TOTAL TASK TIME')
    vals=[('CLICKS','Clicks_Total'),('ACTIONS','Action_Markers'),('DECISIONS','Decision_Markers'),('SOFTWARE WAIT','Software_Wait_sec')];cw=(W-110)/4;y=H-410
    for i,(lab,key) in enumerate(vals):
        x=55+i*cw;v=num(rec,key);txt=fmt_time(v) if 'sec' in key else str(int(v));c.setFillColor(light);c.roundRect(x,y,cw-25,100,8,fill=1,stroke=0);c.setFillColor(navy);c.setFont('Helvetica-Bold',30);c.drawString(x+18,y+48,txt);c.setFont('Helvetica-Bold',10);c.drawString(x+18,y+22,lab)
    c.setFillColor(colors.grey);c.setFont('Helvetica',8);c.drawString(55,50,'SAFE MODE: global mouse clicks only; keyboard text/count is not captured.');c.save();outs.append(p2);return outs

def set_status(t,c):
    if 'status' in labels: labels['status'].config(text=t,foreground=c)

def start_test():
    global current_meta
    if not IS_WINDOWS: messagebox.showerror(APP_NAME,'Safe mouse capture is Windows-only.'); return
    with lock:
        if state.running:return
    try: current_meta=meta_from_form()
    except Exception as e: messagebox.showwarning(APP_NAME,str(e));return
    with lock: state.reset();state.running=True;state.started=time.perf_counter();state.last_input=state.started
    set_status('RUNNING - SAFE MOUSE CAPTURE','#0A7B34')

def stop_test():
    with lock:
        if not state.running:return
        now=time.perf_counter()
        if state.wait_started is not None: state.wait_total += now-state.wait_started; state.wait_started=None
        state.finished=now;state.running=False
    set_status('FINISHED','#8B1E1E');rec=current_record(current_meta);csvp=append_csv(rec);save_json(rec);pdfs=generate_reports(rec,load_pair(rec['Pair_ID']));messagebox.showinfo(APP_NAME,'Test saved.\n\nCSV: '+csvp+'\n\nReports:\n'+'\n'.join(os.path.basename(x) for x in pdfs))

def mark_action():
    with lock:
        if state.running:state.actions+=1

def mark_decision():
    with lock:
        if state.running:state.decisions+=1

def toggle_wait():
    with lock:
        if not state.running:return
        now=time.perf_counter()
        if state.wait_started is None:state.wait_started=now
        else:state.wait_total += now-state.wait_started;state.wait_started=None;state.last_input=now

def dispatch(a):
    {'start':start_test,'stop':stop_test,'action':mark_action,'decision':mark_decision,'wait':toggle_wait}.get(a,lambda:None)()

def update_ui():
    with lock:
        labels['time'].config(text=fmt_time(state.elapsed()));labels['clicks'].config(text=str(state.clicks_left+state.clicks_right+state.clicks_middle));labels['keys'].config(text='OFF');labels['actions'].config(text=str(state.actions));labels['decisions'].config(text=str(state.decisions));labels['wait'].config(text=fmt_time(state.wait_elapsed()))
        if state.running and state.wait_started is not None:set_status('SOFTWARE WAIT','#A55A00')
        elif state.running:set_status('RUNNING - SAFE MOUSE CAPTURE','#0A7B34')
    root.after(200,update_ui)

def build_gui():
    global root
    root=tk.Tk();root.title(f'{APP_NAME} - {VERSION}');root.geometry('790x595');root.resizable(False,False);outer=ttk.Frame(root,padding=18);outer.pack(fill='both',expand=True)
    ttk.Label(outer,text='VIS WORKFLOW BENCHMARK',font=('Segoe UI',18,'bold')).grid(row=0,column=0,columnspan=4,sticky='w');ttk.Label(outer,text='Controlled pure-task benchmarking for Vectorworks workflows').grid(row=1,column=0,columnspan=4,sticky='w');ttk.Label(outer,text='SAFE MODE: global mouse clicks only. Keyboard text/keystroke count is not captured.',foreground='#8A5A00',font=('Segoe UI',9,'bold')).grid(row=2,column=0,columnspan=4,sticky='w',pady=(2,10))
    fields=[('Task','task','Pirate Playground Marking'),('Method','method','Manual'),('Pair ID','pair','PIRATE-001'),('Tool / workflow version','tool','Existing'),('Tester','tester',''),('Department','department','VIS'),('Frequency / month','frequency',''),('Users affected','users','')]
    for i,(lab,key,default) in enumerate(fields):
        r=3+i//2;c=(i%2)*2;ttk.Label(outer,text=lab).grid(row=r,column=c,sticky='w',pady=4);v=tk.StringVar(value=default);vars_[key]=v;ttk.Entry(outer,textvariable=v,width=29).grid(row=r,column=c+1,sticky='w',pady=4)
    ttk.Label(outer,text='Notes').grid(row=7,column=0,sticky='w');vars_['notes']=tk.StringVar();ttk.Entry(outer,textvariable=vars_['notes'],width=71).grid(row=7,column=1,columnspan=3,sticky='we');ttk.Separator(outer,orient='horizontal').grid(row=8,column=0,columnspan=4,sticky='we',pady=14);labels['status']=ttk.Label(outer,text='READY - SAFE MOUSE CAPTURE',font=('Segoe UI',13,'bold'));labels['status'].grid(row=9,column=0,columnspan=4,sticky='w')
    defs=[('TIME','time'),('CLICKS','clicks'),('KEYS*','keys'),('ACTIONS','actions'),('DECISIONS','decisions'),('SOFTWARE WAIT','wait')]
    for i,(lab,key) in enumerate(defs):
        c=i%3;r=10+(i//3)*2;ttk.Label(outer,text=lab,font=('Segoe UI',8,'bold')).grid(row=r,column=c,sticky='w',pady=(10,0));labels[key]=ttk.Label(outer,text='00:00' if key in ('time','wait') else ('OFF' if key=='keys' else '0'),font=('Segoe UI',24,'bold'));labels[key].grid(row=r+1,column=c,sticky='w')
    ttk.Separator(outer,orient='horizontal').grid(row=14,column=0,columnspan=4,sticky='we',pady=14);ttk.Button(outer,text='START F6',command=start_test).grid(row=15,column=0,sticky='we',padx=4);ttk.Button(outer,text='ACTION +1 F7',command=mark_action).grid(row=15,column=1,sticky='we',padx=4);ttk.Button(outer,text='DECISION +1 F8',command=mark_decision).grid(row=15,column=2,sticky='we',padx=4);ttk.Button(outer,text='WAIT START/END F9',command=toggle_wait).grid(row=16,column=0,columnspan=2,sticky='we',padx=4,pady=8);ttk.Button(outer,text='FINISH + REPORT F12',command=stop_test).grid(row=16,column=2,columnspan=2,sticky='we',padx=4,pady=8);ttk.Label(outer,text='*KEYS is intentionally OFF in Safe Mode. No typed text, screenshots or clipboard data are captured.').grid(row=17,column=0,columnspan=4,sticky='w')
    for c in range(4):outer.columnconfigure(c,weight=1)
    root.after(200,update_ui);return root

if __name__=='__main__':
    if IS_WINDOWS:threading.Thread(target=safe_poll_thread,daemon=True).start()
    build_gui().mainloop()
