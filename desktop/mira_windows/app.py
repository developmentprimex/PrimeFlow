"""Visible, manual Windows call notes companion."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from .audio import Capture
from .client import PrimeFlowClient
from .controller import Controller
from .storage import Vault


class App:
    def __init__(self, root, data_root=None, smoke=False):
        self.root = root;self.smoke = smoke;self.events = queue.Queue();self.client = None
        self.capture = None;self.controller = None;self.sid = None;self.busy = False
        self.vault = Vault(data_root);self.device_capture = None;self.started = None
        for item in self.vault.list_sessions():
            if item['state']=='CAPTURING':self.vault.update(item['id'],state='STOPPED',partial=True,error='Aplikacioni u mbyll gjatë dëgjimit.')
        root.title('Mira · Shënime nga thirrjet');root.geometry('820x810');root.minsize(720,680)
        root.configure(bg='#f4f5f7')
        style = ttk.Style();style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10));style.configure('TFrame',background='#f4f5f7')
        style.configure('TLabel',background='#f4f5f7');style.configure('TButton',padding=(12,8))
        main = ttk.Frame(root,padding=24);main.pack(fill='both',expand=True)
        ttk.Label(main,text='Mira',font=('Segoe UI Semibold',25)).pack(anchor='w')
        ttk.Label(main,text='Shënime nga Discord, Teams dhe thirrjet e tjera.',foreground='#475569').pack(anchor='w',pady=(0,16))
        login = ttk.LabelFrame(main,text='Llogaria PrimeFlow',padding=12);login.pack(fill='x')
        self.url = tk.StringVar(value='https://api-flow.primexeu.com')
        self.email = tk.StringVar();self.password = tk.StringVar()
        self.login_inputs = []
        for index,(label,var,hide) in enumerate([('Serveri API',self.url,False),('Email',self.email,False),('Fjalëkalimi',self.password,True)]):
            ttk.Label(login,text=label).grid(row=index,column=0,sticky='w',padx=(0,10),pady=3)
            entry = ttk.Entry(login,textvariable=var,show='●' if hide else '',width=55)
            entry.grid(row=index,column=1,sticky='ew',pady=3);self.login_inputs.append(entry)
        login.columnconfigure(1,weight=1)
        self.login_button = ttk.Button(login,text='Hyr në PrimeFlow',command=self.login);self.login_button.grid(row=3,column=1,sticky='e',pady=(8,0))
        source = ttk.LabelFrame(main,text='Audioja e thirrjes',padding=12);source.pack(fill='x',pady=12)
        self.output = ttk.Combobox(source,state='readonly');self.microphone = ttk.Combobox(source,state='readonly')
        ttk.Label(source,text='Kufjet / altoparlanti').grid(row=0,column=0,sticky='w')
        self.output.grid(row=0,column=1,sticky='ew',pady=3)
        ttk.Label(source,text='Mikrofoni').grid(row=1,column=0,sticky='w')
        self.microphone.grid(row=1,column=1,sticky='ew',pady=3)
        source.columnconfigure(1,weight=1)
        self.levels = {}
        for row,(name,label) in enumerate([('system','Thirrja'),('mic','Mikrofoni')],2):
            ttk.Label(source,text=label).grid(row=row,column=0,sticky='w')
            bar=ttk.Progressbar(source,maximum=1);bar.grid(row=row,column=1,sticky='ew',pady=3);self.levels[name]=bar
        self.refresh_button=ttk.Button(source,text='Rilexo pajisjet',command=self.devices)
        self.refresh_button.grid(row=4,column=1,sticky='e',pady=(6,0))
        ttk.Label(main,text='Zgjidh pajisjen që përdor thirrja. Kapet gjithë audioja që del prej saj.\nPërdor kufje që zëri i thirrjes të mos hyjë përsëri nga mikrofoni.',foreground='#475569').pack(anchor='w')
        self.title = tk.StringVar(value='Takim')
        title_row=ttk.Frame(main);title_row.pack(fill='x',pady=(12,4))
        ttk.Label(title_row,text='Titulli').pack(side='left',padx=(0,12));ttk.Entry(title_row,textvariable=self.title).pack(side='left',fill='x',expand=True)
        self.consent = tk.BooleanVar()
        self.check = ttk.Checkbutton(main,text='I kam njoftuar pjesëmarrësit që Mira do të marrë shënime.',variable=self.consent)
        self.check.pack(anchor='w',pady=8)
        actions = ttk.Frame(main);actions.pack(fill='x',pady=6)
        self.start_button=ttk.Button(actions,text='● Fillo shënimet',command=self.start,state='disabled');self.start_button.pack(side='left')
        self.stop_button=ttk.Button(actions,text='■ Përfundo',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=8)
        self.status = tk.StringVar(value='Hyr në PrimeFlow për të filluar.');self.timer=tk.StringVar(value='00:00')
        ttk.Label(actions,textvariable=self.timer,font=('Segoe UI Semibold',15)).pack(side='right')
        self.status_label=ttk.Label(main,textvariable=self.status,wraplength=745,foreground='#334155');self.status_label.pack(fill='x',pady=(4,10))
        recovery = ttk.Frame(main);recovery.pack(fill='x',pady=(0,8))
        self.sessions=ttk.Combobox(recovery,state='readonly');self.sessions.pack(side='left',fill='x',expand=True)
        self.recover_button=ttk.Button(recovery,text='Hap / vazhdo ruajtjen',command=self.recover);self.recover_button.pack(side='left',padx=(8,0))
        self.tabs=ttk.Notebook(main);self.tabs.pack(fill='both',expand=True)
        self.transcript=self.text_tab('Transkripti');self.notes=self.text_tab('Shënimet')
        footer=ttk.Frame(main);footer.pack(fill='x',pady=(8,0))
        ttk.Button(footer,text='Kopjo shënimet',command=self.copy_notes).pack(side='left')
        self.open_button=ttk.Button(footer,text='Hap PX Notes',command=self.open_notes,state='disabled');self.open_button.pack(side='right')
        self.refresh_sessions()
        if not smoke:self.devices()
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(150,self.poll)

    def text_tab(self,title):
        frame=ttk.Frame(self.tabs);self.tabs.add(frame,text=title)
        text=tk.Text(frame,wrap='word',font=('Segoe UI',10),padx=12,pady=12,relief='flat',state='disabled')
        scroll=ttk.Scrollbar(frame,command=text.yview);text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True);return text

    def show_text(self,widget,value):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',value);widget.configure(state='disabled')

    def notify(self,kind,payload):self.events.put((kind,payload))

    def devices(self):
        try:
            if self.device_capture:self.device_capture.close()
            self.device_capture=Capture(lambda *args:None)
            self.outputs,self.mics=self.device_capture.devices()
            self.output['values']=[f"{d['name']}" for d in self.outputs]
            self.microphone['values']=[f"{d['name']}" for d in self.mics]
            try:out,mic=self.device_capture.defaults()
            except (OSError,LookupError):out=mic=-1
            for combo,items,default in [(self.output,self.outputs,out),(self.microphone,self.mics,mic)]:
                if items:combo.current(next((i for i,d in enumerate(items) if d['index']==default),0))
        except Exception as exc:self.status.set('Pajisjet audio nuk u hapën: '+str(exc))

    def login(self):
        if self.busy:return
        self.set_busy(True);self.status.set('Po lidhem me PrimeFlow…')
        url,email,password=self.url.get(),self.email.get().strip(),self.password.get();self.password.set('')
        def work():
            client=None
            try:
                client=PrimeFlowClient(url);client.login(email,password)
                self.notify('login',client)
            except Exception as exc:
                if client:client.close()
                self.notify('login_error',str(exc))
        threading.Thread(target=work,daemon=True).start()

    def set_busy(self,busy):
        self.busy=busy
        self.start_button.configure(state='disabled' if busy or not self.client else 'normal')
        self.recover_button.configure(state='disabled' if busy else 'normal')
        self.login_button.configure(state='disabled' if busy else 'normal')
        self.refresh_button.configure(state='disabled' if busy else 'normal')
        self.check.configure(state='disabled' if busy else 'normal')
        for entry in self.login_inputs:entry.configure(state='disabled' if busy else 'normal')
        self.output.configure(state='disabled' if busy else 'readonly');self.microphone.configure(state='disabled' if busy else 'readonly')

    def start(self):
        if self.busy or not self.client:return
        if not self.consent.get():messagebox.showinfo('Njoftimi','Njoftoji pjesëmarrësit dhe konfirmo kutinë për të filluar.');return
        title=self.title.get().strip()
        if not 1<=len(title)<=200:messagebox.showerror('Titulli','Shkruaj titullin e takimit (deri 200 shkronja).');return
        if self.output.current()<0 or self.microphone.current()<0:
            messagebox.showerror('Audioja','Zgjidh pajisjen e thirrjes dhe mikrofonin.');return
        output_index=self.outputs[self.output.current()]['index'];mic_index=self.mics[self.microphone.current()]['index']
        self.set_busy(True);self.status.set('Po përgatis dëgjimin…')
        def work():
            capture=None;sid=None
            try:
                item=self.vault.create(self.client.base_url,self.client.user['id'],title);sid=item['id']
                self.client.create(item)
                capture=Capture(lambda wav,start,end:self.vault.append(sid,wav,start,end),
                    lambda source,level:self.notify('level',(source,level)))
                capture.start(output_index,mic_index)
                self.notify('started',(sid,capture))
            except Exception as exc:
                if capture:capture.close()
                if sid:self.vault.update(sid,state='STOPPED',partial=True,error=str(exc))
                self.notify('error',str(exc))
        threading.Thread(target=work,daemon=True).start()

    def stop(self):
        self.stop_button.configure(state='disabled');self.status.set('Po përfundoj dëgjimin…')
        capture=self.capture
        def work():
            try:
                capture.stop()
                item=self.vault.update(self.sid,state='STOPPED',partial=bool(capture.fault),error=capture.fault or '')
                self.notify('stopped',item)
            except Exception as exc:self.notify('error',str(exc))
        if capture:threading.Thread(target=work,daemon=True).start()

    def refresh_sessions(self):
        self.items=self.vault.list_sessions()
        if self.client:self.items=[i for i in self.items if i['owner']==str(self.client.user['id']) and i['base_url']==self.client.base_url]
        else:self.items=[]
        self.sessions['values']=[f"{i['title']} · {'ruajtur' if i['state']=='DONE' else 'në pritje'} · {i['id'][:8]}" for i in self.items]
        if self.items:self.sessions.current(0)
        else:self.sessions.set('')

    def display(self,item):
        self.show_text(self.transcript,'\n\n'.join(t for t in item['transcript'] if t))
        self.show_text(self.notes,item.get('notes',''))
        self.open_button.configure(state='normal' if item.get('note_id') else 'disabled')

    def recover(self):
        if self.busy or not self.client or self.sessions.current()<0:return
        item=self.items[self.sessions.current()];self.sid=item['id'];self.display(item)
        if item['state']=='DONE':return
        self.set_busy(True);self.status.set('Po vazhdoj ruajtjen e takimit…')
        self.controller=Controller(self.vault,self.client,self.notify);self.controller.run(self.sid)

    def poll(self):
        while True:
            try:kind,payload=self.events.get_nowait()
            except queue.Empty:break
            if kind=='login':
                if self.client:threading.Thread(target=self.client.close,daemon=True).start()
                self.client=payload;self.set_busy(False);self.refresh_sessions()
                self.status.set('U lidhe si '+(payload.user.get('full_name') or payload.user.get('email',''))+'. Gati për të filluar.')
            elif kind=='login_error':self.set_busy(False);self.status.set(payload)
            elif kind=='started':
                self.sid,self.capture=payload;self.started=time.monotonic()
                self.stop_button.configure(state='normal');self.status_label.configure(foreground='#b91c1c')
                self.status.set('● Mira po dëgjon. Audioja e thirrjes dhe mikrofoni janë aktivë.')
                self.controller=Controller(self.vault,self.client,self.notify);self.controller.run(self.sid,self.capture)
            elif kind=='level':self.levels[payload[0]]['value']=payload[1]
            elif kind=='progress':self.display(payload)
            elif kind=='status':self.status.set(payload)
            elif kind=='stopped':
                self.stop_button.configure(state='disabled');self.status_label.configure(foreground='#334155')
                self.status.set(('Dëgjimi u ndal: '+payload['error']+'. ' if payload.get('error') else '')+'Po ruaj takimin…')
            elif kind in ('done','error'):
                if self.capture:
                    try:self.capture.close()
                    except OSError:pass
                self.capture=None;self.started=None;self.set_busy(False);self.stop_button.configure(state='disabled')
                self.refresh_sessions();self.status_label.configure(foreground='#334155')
                if kind=='done':
                    self.display(payload)
                    self.status.set('Shënimet u ruajtën në PX Notes.' if payload.get('note_id') else 'Takimi përfundoi pa të folur të kuptueshëm.')
                else:self.status.set('Nuk u përfundua: '+payload+' Zgjidh takimin dhe vazhdo ruajtjen.')
        if self.started and self.capture:
            if not self.capture.stop_event.is_set():
                seconds=int(time.monotonic()-self.started);self.timer.set(f'{seconds//60:02d}:{seconds%60:02d}')
            elif self.capture.thread and not self.capture.thread.is_alive():
                item=self.vault.load(self.sid)
                if item['state']=='CAPTURING':
                    item=self.vault.update(self.sid,state='STOPPED',partial=bool(self.capture.fault),error=self.capture.fault or '')
                    self.notify('stopped',item)
        self.root.after(150,self.poll)

    def copy_notes(self):
        text=self.notes.get('1.0','end').strip()
        if text:self.root.clipboard_clear();self.root.clipboard_append(text)

    def open_notes(self):
        if self.client and self.client.frontend_url:webbrowser.open(self.client.frontend_url+'/ga-ka-notes')

    def close(self):
        if self.busy and not messagebox.askyesno('Mbyll Mira-n?',
            'Dëgjimi/përpunimi do të ndalet. Pjesët e ruajtura mbeten të enkriptuara dhe mund t’i vazhdosh pas hyrjes.'):return
        if self.controller:self.controller.stop_sync()
        if self.capture:
            try:
                was_recording=not self.capture.stop_event.is_set()
                self.capture.close()
                if self.sid:
                    item=self.vault.load(self.sid)
                    if item['state']!='DONE':
                        self.vault.update(self.sid,state='STOPPED',partial=item['partial'] or was_recording or bool(self.capture.fault))
            except OSError:pass
        if self.device_capture:self.device_capture.close()
        # Do not race an in-flight upload/refresh by closing its HTTP client.
        if self.client and not (self.controller and self.controller.thread and self.controller.thread.is_alive()):
            threading.Thread(target=self.client.close,daemon=True).start()
        self.root.destroy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--data-dir')
    parser.add_argument('--self-check',metavar='REPORT_JSON')
    args=parser.parse_args()
    if args.self_check:
        # Packaging verification only: no PyAudio instance, no live capture/login.
        import pyaudiowpatch
        import numpy as np
        from .audio import TimelineMixer, wav_bytes
        from .storage import protect, unprotect
        mixer=TimelineMixer();mixer.push('mic',np.ones((480,1),dtype=np.float32)*.1,48000,0)
        chunk=next(mixer.flush(.01,final=True))
        raw=wav_bytes(chunk[2]);assert unprotect(protect(raw))==raw
        Path(args.self_check).write_text(json.dumps({'ok':True,'capture_driver':pyaudiowpatch.__version__,
            'synthetic_frames':len(chunk[2]),'live_audio_captured':False}),encoding='utf-8')
        return
    # One visible companion per Windows session prevents duplicate uploads/capture.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,False,'Local\\PrimeFlowMiraWindows')
    if ctypes.get_last_error()==183:return
    root=tk.Tk();app=App(root,Path(args.data_dir) if args.data_dir else None,smoke=args.smoke_test)
    if args.smoke_test:root.after(500,root.destroy)
    root.mainloop()
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(mutex)


if __name__=='__main__':main()
