"use client"

import * as React from "react"
import { Download, MailCheck, Plus, RefreshCw, Send, Settings2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"

type Recipient = { id:string; email:string; recipient_type:"TO"|"CC"|"BCC"; is_active:boolean; is_default:boolean; sort_order:number; created_at:string; updated_at:string; updated_by?:string|null }
type Schedule = { id:string; name:string; report_slot:string; execution_time:string; timezone:string; weekdays:number[]; is_active:boolean; backfill_enabled:boolean; grace_period_minutes:number; retry_count:number; retry_delays_seconds:number[]; version:number; updated_at:string; next_runs:string[] }
type Run = { id:string; report_date:string; report_slot:string; trigger_type:string; status:string; subject:string; recipients:string; attempt_count:number; gmail_message_id?:string|null; error_message?:string|null; created_at:string }
type Audit = { id:string; action:string; entity_type:string; actor_user_id?:string|null; created_at:string; before?:unknown; after?:unknown }
type Preview = { document:{subject:string;generated_at:string;source_generated_at:string;recipients:Record<string,string[]>}; html:string; plain_text:string; task_count:number; warning?:string|null }

const API = "/admin/primeflow-1h-reports"
const slots = ["10:00","11:00","11:50","14:10","14:20","16:00"]

export default function ReportManagementPage() {
  const { apiFetch, user } = useAuth()
  const canManage = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.full_name?.trim().toLocaleLowerCase() === "laurent hoxha"
  const [recipients,setRecipients] = React.useState<Recipient[]>([])
  const [schedules,setSchedules] = React.useState<Schedule[]>([])
  const [runs,setRuns] = React.useState<Run[]>([])
  const [audit,setAudit] = React.useState<Audit[]>([])
  const [loading,setLoading] = React.useState(true)
  const [date,setDate] = React.useState(new Date().toISOString().slice(0,10))
  const [slot,setSlot] = React.useState("10:00")
  const [preview,setPreview] = React.useState<Preview|null>(null)
  const [previewing,setPreviewing] = React.useState(false)
  const [sendOpen,setSendOpen] = React.useState(false)
  const [sending,setSending] = React.useState(false)
  const [reason,setReason] = React.useState("")
  const [newEmail,setNewEmail] = React.useState("")
  const [newType,setNewType] = React.useState("TO")
  const [scheduleOpen,setScheduleOpen] = React.useState(false)
  const [editingScheduleId,setEditingScheduleId] = React.useState<string|null>(null)
  const [scheduleForm,setScheduleForm] = React.useState({name:"",report_slot:"10:00",execution_time:"09:00"})

  const load = React.useCallback(async()=>{
    if (!canManage) { setLoading(false); return }
    setLoading(true)
    try {
      const [rr,sr,hr,ar] = await Promise.all([apiFetch(`${API}/recipients`),apiFetch(`${API}/schedules`),apiFetch(`${API}/runs`),apiFetch(`${API}/audit`)])
      if (![rr,sr,hr,ar].every(r=>r.ok)) throw new Error("load")
      setRecipients(await rr.json()); setSchedules(await sr.json()); setRuns(await hr.json()); setAudit(await ar.json())
    } catch { toast.error("Unable to load 1H report management data") } finally { setLoading(false) }
  },[apiFetch,canManage])
  React.useEffect(()=>{if(!canManage)return;const timer=window.setTimeout(()=>void load(),0);return()=>window.clearTimeout(timer)},[canManage,load])

  const previewReport = async(format="json")=>{
    setPreviewing(true)
    try {
      const res=await apiFetch(`${API}/preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({report_date:date,report_slot:slot,format,use_default_recipients:true})})
      if(!res.ok) throw new Error(await res.text())
      if(format!=="json"){const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=`PrimeFlow_1H_${date}_${slot.replace(":","-")}.${format}`;a.click();URL.revokeObjectURL(url)}
      else setPreview(await res.json())
    } catch(e){toast.error("Preview failed",{description:String(e)})} finally{setPreviewing(false)}
  }
  const sendNow=async()=>{
    if(!preview) return
    setSending(true)
    try{
      const res=await apiFetch(`${API}/send`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({report_date:date,report_slot:slot,format:"json",use_default_recipients:true,to:[],cc:[],bcc:[],reason,force:false})})
      const data=await res.json()
      if(!res.ok) throw new Error(JSON.stringify(data))
      if(data.status!=="SENT"||!data.gmail_message_id) throw new Error(`Gmail delivery failed (status: ${data.status||"unknown"})`)
      toast.success("Report sent",{description:`Message ID: ${data.gmail_message_id}`});setSendOpen(false);setPreview(null);await load()
    }catch(e){toast.error("Manual send failed",{description:String(e)})}finally{setSending(false)}
  }
  const addRecipient=async()=>{
    const res=await apiFetch(`${API}/recipients`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:newEmail,recipient_type:newType,is_active:true,sort_order:recipients.length*10+10})})
    if(res.ok){setNewEmail("");toast.success("Recipient added");await load()}else toast.error("Recipient could not be added",{description:await res.text()})
  }
  const toggleRecipient=async(row:Recipient)=>{
    const res=await apiFetch(`${API}/recipients/${row.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({is_active:!row.is_active})})
    if(res.ok) await load(); else toast.error("Recipient update blocked",{description:await res.text()})
  }
  const toggleSchedule=async(row:Schedule)=>{
    const res=await apiFetch(`${API}/schedules/${row.id}/${row.is_active?"disable":"enable"}`,{method:"POST"})
    if(res.ok){toast.success(`Schedule ${row.is_active?"disabled":"enabled"}; scheduler refreshes within 45 seconds`);await load()}else toast.error("Schedule update failed",{description:await res.text()})
  }
  const addSchedule=async()=>{
    const existing=schedules.find(s=>s.id===editingScheduleId)
    const body={...scheduleForm,timezone:"Europe/Tirane",weekdays:existing?.weekdays||[0,1,2,3,4],is_active:existing?.is_active||false,backfill_enabled:existing?.backfill_enabled??true,predecessor_schedule_id:null,grace_period_minutes:existing?.grace_period_minutes||30,retry_count:existing?.retry_count||3,retry_delays_seconds:existing?.retry_delays_seconds||[0,2,5],sort_order:schedules.length*10+10}
    const res=await apiFetch(editingScheduleId?`${API}/schedules/${editingScheduleId}`:`${API}/schedules`,{method:editingScheduleId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
    if(res.ok){toast.success(editingScheduleId?"Schedule updated":"Inactive schedule added");setScheduleOpen(false);setEditingScheduleId(null);await load()}else toast.error("Schedule validation failed",{description:await res.text()})
  }
  const editSchedule=(row:Schedule)=>{setEditingScheduleId(row.id);setScheduleForm({name:row.name,report_slot:row.report_slot,execution_time:row.execution_time});setScheduleOpen(true)}
  const changeRecipientType=async(row:Recipient,value:string)=>{const res=await apiFetch(`${API}/recipients/${row.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({recipient_type:value})});if(res.ok)await load();else toast.error("Recipient update failed")}
  const removeRecipient=async(row:Recipient)=>{if(!window.confirm(`Remove ${row.email}?`))return;const res=await apiFetch(`${API}/recipients/${row.id}`,{method:"DELETE"});if(res.ok)await load();else toast.error("Recipient removal blocked",{description:await res.text()})}
  const downloadRun=async(run:Run,format:"docx"|"png"|"txt")=>{
    const res=await apiFetch(`${API}/runs/${run.id}/download.${format}`)
    if(!res.ok){toast.error("Download unavailable",{description:await res.text()});return}
    const blob=await res.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=`PrimeFlow_1H_${run.report_date}_${run.report_slot.replace(":","-")}.${format}`;a.click();URL.revokeObjectURL(url)
  }
  if(!user) return <div className="rounded-lg border p-8">Sign in to access 1H reports.</div>
  if(!canManage) return <div className="mx-auto max-w-[1400px] space-y-5">
    <div><h1 className="text-2xl font-semibold">1H Reports</h1><p className="text-sm text-muted-foreground">Generate and download a fresh report for any date and slot.</p></div>
    <div className="space-y-4 rounded-xl border bg-white p-5">
      <div className="grid gap-3 md:grid-cols-4">
        <div><Label>Date</Label><Input type="date" value={date} onChange={e=>{setDate(e.target.value);setPreview(null)}}/></div>
        <div><Label>Slot</Label><Select value={slot} onValueChange={v=>{setSlot(v);setPreview(null)}}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent>{slots.map(v=><SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent></Select></div>
        <div className="flex items-end"><Button onClick={()=>void previewReport()} disabled={previewing}>{previewing?<RefreshCw className="animate-spin"/>:<MailCheck/>}Generate report</Button></div>
      </div>
      {preview ? <><div className="grid gap-3 text-sm md:grid-cols-3"><div><b>Subject</b><br/>{preview.document.subject}</div><div><b>Generated</b><br/>{preview.document.generated_at}</div><div><b>Tasks</b><br/>{preview.task_count}</div></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={()=>void previewReport("docx")}><Download/>Word</Button><Button variant="outline" onClick={()=>void previewReport("png")}><Download/>PNG</Button><Button variant="outline" onClick={()=>void previewReport("txt")}><Download/>Text</Button></div><iframe title="Email preview" srcDoc={preview.html} className="h-[620px] w-full rounded-lg border bg-white"/></> : null}
    </div>
  </div>

  const active=recipients.filter(r=>r.is_active)
  return <div className="mx-auto max-w-[1500px] space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">Report Management</h1><p className="text-sm text-muted-foreground">1H delivery, previews, schedules, recipients and audit history.</p></div><Button variant="outline" onClick={()=>void load()} disabled={loading}><RefreshCw/>Refresh</Button></div>
    <div className="rounded-xl border bg-gradient-to-r from-indigo-50 to-slate-50 p-5"><p className="text-xs font-medium uppercase tracking-wide text-indigo-700">Active default recipients</p><div className="mt-2 flex flex-wrap gap-2">{active.map(r=><span key={r.id} className="rounded-full border bg-white px-3 py-1 text-sm">{r.recipient_type} · {r.email}</span>)}</div></div>
    <Tabs defaultValue="overview"><TabsList className="flex h-auto flex-wrap"><TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="reports">Reports</TabsTrigger><TabsTrigger value="schedules">Schedules</TabsTrigger><TabsTrigger value="recipients">Recipients</TabsTrigger><TabsTrigger value="history">History</TabsTrigger><TabsTrigger value="settings">Settings</TabsTrigger></TabsList>
      <TabsContent value="overview"><div className="space-y-5"><div className="grid gap-4 md:grid-cols-3">{[["Active 1H recipients",active.length],["Active 1H schedules",schedules.filter(s=>s.is_active).length],["Recent successful 1H runs",runs.filter(r=>["SENT","ALREADY_SENT"].includes(r.status)).length]].map(([label,value])=><div className="rounded-xl border p-5" key={String(label)}><p className="text-sm text-muted-foreground">{label}</p><p className="mt-2 text-3xl font-semibold">{value}</p></div>)}</div></div></TabsContent>
      <TabsContent value="reports"><div className="space-y-4 rounded-xl border p-5"><div className="grid gap-3 md:grid-cols-4"><div><Label>Date</Label><Input type="date" value={date} onChange={e=>{setDate(e.target.value);setPreview(null)}}/></div><div><Label>Slot</Label><Select value={slot} onValueChange={v=>{setSlot(v);setPreview(null)}}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent>{slots.map(v=><SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent></Select></div><div className="flex items-end"><Button onClick={()=>void previewReport()} disabled={previewing}>{previewing?<RefreshCw className="animate-spin"/>:<MailCheck/>}Preview fresh report</Button></div></div>
        {preview&&<><div className="grid gap-3 md:grid-cols-4 text-sm"><div><b>Subject</b><br/>{preview.document.subject}</div><div><b>Generated</b><br/>{preview.document.generated_at}</div><div><b>Tasks</b><br/>{preview.task_count}{preview.warning&&<span className="text-amber-600"> · {preview.warning}</span>}</div><div><b>Recipients</b><br/>{Object.values(preview.document.recipients).flat().join(", ")}</div></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={()=>void previewReport("docx")}><Download/>Word</Button><Button variant="outline" onClick={()=>void previewReport("png")}><Download/>PNG</Button><Button variant="outline" onClick={()=>void previewReport("txt")}><Download/>Text</Button><Button onClick={()=>setSendOpen(true)}><Send/>Send report now</Button></div><iframe title="Email preview" srcDoc={preview.html} className="h-[620px] w-full rounded-lg border bg-white"/></>}</div></TabsContent>
      <TabsContent value="schedules"><div className="rounded-xl border"><div className="flex items-center justify-between p-4"><div><h2 className="font-semibold">Delivery schedules</h2><p className="text-xs text-muted-foreground">Changes hot-reload within 45 seconds.</p></div><Button onClick={()=>{setEditingScheduleId(null);setScheduleForm({name:"",report_slot:"10:00",execution_time:"09:00"});setScheduleOpen(true)}}><Plus/>Add</Button></div><Table><TableHeader><TableRow>{["Name","Active","Report slot","Execution","Timezone","Next run","Retry","Version","Actions"].map(x=><TableHead key={x}>{x}</TableHead>)}</TableRow></TableHeader><TableBody>{schedules.map(s=><TableRow key={s.id}><TableCell>{s.name}</TableCell><TableCell>{s.is_active?"Enabled":"Disabled"}</TableCell><TableCell>{s.report_slot}</TableCell><TableCell>{s.execution_time}</TableCell><TableCell>{s.timezone}</TableCell><TableCell>{s.next_runs?.[0]?.slice(0,16)||"—"}</TableCell><TableCell>{s.retry_count} · {s.retry_delays_seconds.join("/")}</TableCell><TableCell>v{s.version}</TableCell><TableCell><div className="flex gap-1"><Button size="sm" variant="outline" onClick={()=>editSchedule(s)}>Edit</Button><Button size="sm" variant="outline" onClick={()=>void toggleSchedule(s)}>{s.is_active?"Disable":"Enable"}</Button></div></TableCell></TableRow>)}</TableBody></Table></div></TabsContent>
      <TabsContent value="recipients"><div className="space-y-4 rounded-xl border p-4"><div className="flex flex-wrap gap-2"><Input className="max-w-sm" type="email" placeholder="recipient@example.com" value={newEmail} onChange={e=>setNewEmail(e.target.value)}/><Select value={newType} onValueChange={setNewType}><SelectTrigger className="w-28"><SelectValue/></SelectTrigger><SelectContent>{["TO","CC","BCC"].map(v=><SelectItem value={v} key={v}>{v}</SelectItem>)}</SelectContent></Select><Button onClick={()=>void addRecipient()} disabled={!newEmail}><Plus/>Add</Button></div><Table><TableHeader><TableRow>{["Email","Type","State","Default","Added","Updated","Updated by","Action"].map(x=><TableHead key={x}>{x}</TableHead>)}</TableRow></TableHeader><TableBody>{recipients.map(r=><TableRow key={r.id}><TableCell>{r.email}</TableCell><TableCell><Select value={r.recipient_type} onValueChange={v=>void changeRecipientType(r,v)}><SelectTrigger className="w-24"><SelectValue/></SelectTrigger><SelectContent>{["TO","CC","BCC"].map(v=><SelectItem value={v} key={v}>{v}</SelectItem>)}</SelectContent></Select></TableCell><TableCell>{r.is_active?"Active":"Inactive"}</TableCell><TableCell>{r.is_default?"Yes":"No"}</TableCell><TableCell>{r.created_at?.slice(0,10)}</TableCell><TableCell>{r.updated_at?.slice(0,16)}</TableCell><TableCell>{r.updated_by||"System"}</TableCell><TableCell><div className="flex gap-1"><Button size="sm" variant="outline" onClick={()=>void toggleRecipient(r)}>{r.is_active?"Disable":"Enable"}</Button><Button size="sm" variant="ghost" onClick={()=>void removeRecipient(r)}>Remove</Button></div></TableCell></TableRow>)}</TableBody></Table></div></TabsContent>
      <TabsContent value="history"><div className="rounded-xl border"><Table><TableHeader><TableRow>{["Date","Slot","Trigger","Status","Subject","Attempts","Gmail","Error","Downloads"].map(x=><TableHead key={x}>{x}</TableHead>)}</TableRow></TableHeader><TableBody>{runs.map(r=><TableRow key={r.id}><TableCell>{r.report_date}</TableCell><TableCell>{r.report_slot}</TableCell><TableCell>{r.trigger_type}</TableCell><TableCell>{r.status}</TableCell><TableCell className="max-w-xs truncate">{r.subject}</TableCell><TableCell>{r.attempt_count}</TableCell><TableCell>{r.gmail_message_id||"—"}</TableCell><TableCell className="max-w-xs truncate">{r.error_message||"—"}</TableCell><TableCell><div className="flex gap-1">{(["docx","png","txt"] as const).map(f=><Button key={f} size="sm" variant="ghost" onClick={()=>void downloadRun(r,f)}>{f.toUpperCase()}</Button>)}</div></TableCell></TableRow>)}</TableBody></Table></div></TabsContent>
      <TabsContent value="settings"><div className="rounded-xl border p-5"><h2 className="font-semibold">Configuration audit</h2><div className="mt-4 space-y-2">{audit.map(a=><div className="rounded-lg border p-3 text-sm" key={a.id}><b>{a.action}</b> · {a.entity_type}<span className="float-right text-muted-foreground">{a.created_at}</span></div>)}</div></div></TabsContent>
    </Tabs>
    <Dialog open={sendOpen} onOpenChange={setSendOpen}><DialogContent><DialogHeader><DialogTitle>Send report immediately?</DialogTitle></DialogHeader>{preview&&<div className="space-y-3 text-sm"><p><b>{preview.document.subject}</b></p><p>{preview.task_count} tasks · Generated {preview.document.generated_at}</p><p>Recipients: {Object.values(preview.document.recipients).flat().join(", ")}</p><p className="rounded bg-amber-50 p-3 text-amber-800">This email will be sent immediately. Manual reports can be sent again whenever needed.</p><div><Label>Reason</Label><Input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Operational reason for manual send"/></div><Button className="w-full" disabled={sending||reason.trim().length<3} onClick={()=>void sendNow()}>{sending?<RefreshCw className="animate-spin"/>:<Send/>}Confirm and send</Button></div>}</DialogContent></Dialog>
    <Dialog open={scheduleOpen} onOpenChange={setScheduleOpen}><DialogContent><DialogHeader><DialogTitle>{editingScheduleId?"Edit":"Add"} delivery schedule</DialogTitle></DialogHeader><div className="space-y-3"><div><Label>Name</Label><Input value={scheduleForm.name} onChange={e=>setScheduleForm({...scheduleForm,name:e.target.value})}/></div><div className="grid grid-cols-2 gap-3"><div><Label>Report slot</Label><Select value={scheduleForm.report_slot} onValueChange={v=>setScheduleForm({...scheduleForm,report_slot:v})}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent>{slots.map(v=><SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent></Select></div><div><Label>Execution time</Label><Input type="time" value={scheduleForm.execution_time} onChange={e=>setScheduleForm({...scheduleForm,execution_time:e.target.value})}/></div></div><p className="text-xs text-muted-foreground">{editingScheduleId?"Saving increments the schedule version and hot-reloads the scheduler.":"New schedules start disabled so they can be reviewed before activation."}</p><Button className="w-full" onClick={()=>void addSchedule()}><Settings2/>Save schedule</Button></div></DialogContent></Dialog>
  </div>
}
