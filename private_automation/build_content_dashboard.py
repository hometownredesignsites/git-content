#!/usr/bin/env python3
"""Generate the private ChatGPT content-generation dashboard."""
import argparse,csv,json,os,urllib.request
from datetime import datetime,timezone
from pathlib import Path

OWNER="hometownredesignsites"; REPO="git-content"

def load(path):
    try:
        value=json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value,dict) else {}
    except (OSError,json.JSONDecodeError): return {}

def dt(value):
    if not isinstance(value,str) or not value:return None
    try:
        value=datetime.fromisoformat(value.replace("Z","+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except ValueError:return None

def iso(value):return value.astimezone(timezone.utc).isoformat(timespec="seconds") if value else ""

def runs():
    headers={"Accept":"application/vnd.github+json","User-Agent":"private-chatgpt-content-dashboard"}
    token=os.environ.get("GITHUB_TOKEN")
    if token:headers["Authorization"]="Bearer "+token
    request=urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs?per_page=100",headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=20) as response: data=json.loads(response.read().decode())
        return {str(row.get("id")):row for row in data.get("workflow_runs",[])}
    except Exception:return {}

def duration(run):
    if not run:return None
    start=dt(run.get("run_started_at") or run.get("created_at"));end=dt(run.get("updated_at")) if run.get("status")=="completed" else datetime.now(timezone.utc)
    return max(0,int((end-start).total_seconds())) if start else None

def build(root,action_runs):
    jobs_dir=root/"private_automation/queue/jobs"; batches_dir=root/"private_automation/queue/batches"
    jobs={}
    for path in jobs_dir.glob("*.json") if jobs_dir.exists() else []:
        row=load(path)
        if row.get("job_id"):jobs[str(row["job_id"])]=row
    statuses={}
    for path in (root/"results").glob("*/run-*/status.json"):
        row=load(path); jid=str(row.get("job_id") or "")
        if jid and (jid not in statuses or int(row.get("public_workflow_run") or 0)>=int(statuses[jid].get("public_workflow_run") or 0)):
            statuses[jid]=row
    active_by_job={}
    for job_id in jobs:
        for run in action_runs.values():
            message=str((run.get("head_commit") or {}).get("message") or "")
            if job_id in message:active_by_job[job_id]=run;break
    job_rows=[]
    for jid,record in jobs.items():
        result=statuses.get(jid,{})
        run_id=result.get("public_workflow_run") or (active_by_job.get(jid) or {}).get("id")
        action=action_runs.get(str(run_id)) if run_id else active_by_job.get(jid)
        status=str(result.get("status") or (action.get("conclusion") if action and action.get("status")=="completed" else action.get("status") if action else "queued"))
        if status in {"None",""}:status="queued"
        reason=result.get("failure_reason") or result.get("error") or ""
        if not reason and status in {"failed","failure","cancelled","timed_out"}:
            evidence=result.get("access_gate_evidence") or result.get("non_retryable_access_classifications") or []
            reason="; ".join(str(v) for v in evidence) or "Reason not recorded in private status record"
        source=record.get("row") if isinstance(record.get("row"),dict) else {}
        successful=result.get("successful_candidates","")
        job_rows.append({"batch_id":record.get("batch_id",""),"job_id":jid,"business":source.get("business",""),
          "category":source.get("category",""),"location":source.get("location",""),"website":source.get("website",""),
          "result_slug":record.get("result_slug",""),"status":status,"successful_candidates":successful,
          "attempts":result.get("attempts",""),"failure_reason":reason,"run_id":run_id or "",
          "run_url":f"https://github.com/{OWNER}/{REPO}/actions/runs/{run_id}" if run_id else "",
          "started_at":(action or {}).get("run_started_at", ""),
          "finished_at":(action or {}).get("updated_at","") if (action or {}).get("status")=="completed" else "",
          "duration_seconds":duration(action)})
    job_rows.sort(key=lambda row:(row["started_at"] or "",row["job_id"]),reverse=True)
    batch_rows=[]
    for path in batches_dir.glob("*.json") if batches_dir.exists() else []:
        manifest=load(path)
        if not manifest:continue
        ids=[str(v) for v in manifest.get("job_ids",[])]; group=[row for row in job_rows if row["job_id"] in ids]
        in_flight=sum(1 for row in group if row["status"] in {"queued","waiting","in_progress","in progress"})
        failed=sum(1 for row in group if row["status"] in {"failed","failure","cancelled","timed_out"})
        passed=sum(1 for row in group if str(row.get("successful_candidates")) not in {"","None"} and int(row.get("successful_candidates") or 0)>=3)
        starts=[dt(row["started_at"]) for row in group if dt(row["started_at"])];ends=[dt(row["finished_at"]) for row in group if dt(row["finished_at"])]
        start=min(starts) if starts else None;end=max(ends) if ends else None
        if in_flight and start:end=datetime.now(timezone.utc)
        state="in progress" if any(row["status"] in {"in_progress","in progress"} for row in group) else "queued" if in_flight else "failed / partial" if failed else "completed" if ids and len(group)>=len(ids) else "queued / incomplete"
        batch_rows.append({"batch_id":manifest.get("batch_id",path.stem),"created_at":manifest.get("created_at",""),
          "target_count":manifest.get("target_count",len(ids)),"jobs_with_status":len(group),"three_pass_sites":passed,
          "queued_or_running":in_flight,"failed":failed,"status":state,"started_at":iso(start),"finished_at":iso(end),
          "duration_seconds":int((end-start).total_seconds()) if start and end else None,"continuation_of":manifest.get("continuation_of","")})
    batch_rows.sort(key=lambda row:str(row.get("created_at") or ""),reverse=True)
    counts={"queued":sum(1 for j in job_rows if j["status"] in {"queued","waiting"}),
      "running":sum(1 for j in job_rows if j["status"] in {"in_progress","in progress"}),
      "failed":sum(1 for j in job_rows if j["status"] in {"failed","failure","cancelled","timed_out"}),
      "three_pass":sum(1 for j in job_rows if str(j.get("successful_candidates")) not in {"","None"} and int(j.get("successful_candidates") or 0)>=3)}
    return {"generated_at":iso(datetime.now(timezone.utc)),"source_revision":os.environ.get("GITHUB_SHA",""),"counts":counts,"jobs":job_rows,"batches":batch_rows}

def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)

def render(data):
    packed=json.dumps(data,ensure_ascii=False,separators=(",",":")).replace("</","<\\/")
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ChatGPT Content Generation</title><style>
body{margin:0;background:#f3f6fa;color:#17283d;font:15px/1.45 system-ui,sans-serif}header{background:#17314e;color:#fff;padding:24px 5vw}main{max-width:1400px;margin:auto;padding:24px}section{background:#fff;border:1px solid #dce4ed;border-radius:10px;padding:18px;margin:14px 0}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#f6f8fb;border:1px solid #e1e7ef;border-radius:8px;padding:14px;min-width:170px}.card b{font-size:24px;display:block}.muted{color:#62738a;font-size:13px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid #e7edf3;vertical-align:top}th{background:#f4f7fa;position:sticky;top:0}.scroll{overflow:auto;max-height:560px;border:1px solid #e0e7ef;border-radius:7px}.pill{border-radius:15px;padding:3px 8px;background:#edf2f7}.failed{color:#ad3038;background:#fdebed}.in.progress,.queued{color:#9a6100;background:#fff4dc}input{padding:9px;border:1px solid #ccd7e4;border-radius:6px;width:min(100%,400px);margin:0 0 10px}.reason{white-space:normal;min-width:240px}a{color:#1b64bb}
</style><header><h1>ChatGPT Content-Generation Dashboard</h1><div>Private queue, batch timing, candidate passes, and failure reasons</div></header><main><div class="muted" id="generated"></div><section><h2>Current workload</h2><div class="cards" id="cards"></div></section><section><h2>Content batches</h2><div class="scroll" id="batches"></div></section><section><h2>Content jobs</h2><input id="f" placeholder="Filter business, city, status, or failure reason"><div class="scroll" id="jobs"></div></section><div class="muted">A site reaches the content completion gate after three passing candidates. A green Actions run alone does not count as a pass.</div></main><script>const D=__DATA__;const esc=x=>String(x==null?'':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const table=(rows,cols)=>'<table><thead><tr>'+cols.map(c=>'<th>'+c[1]+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>{let v=r[c[0]]||'';if(c[0]==='status')v='<span class="pill '+esc(r.status)+'">'+esc(r.status)+'</span>';else if(c[0]==='run_url'&&v)v='<a href="'+esc(v)+'">Actions</a>';return '<td class="'+(c[0]==='failure_reason'?'reason':'')+'">'+(c[0]==='status'||c[0]==='run_url'?v:esc(v))+'</td>'}).join('')+'</tr>').join('')+'</tbody></table>';document.getElementById('generated').textContent='Generated '+new Date(D.generated_at).toLocaleString()+' · '+D.source_revision;let C=D.counts||{};document.getElementById('cards').innerHTML=[['queued','Queued'],['running','In progress'],['three_pass','Sites with 3 passes'],['failed','Failed/cancelled']].map(x=>'<div class="card"><b>'+esc(C[x[0]]||0)+'</b><span>'+x[1]+'</span></div>').join('');let B=D.batches||[],J=D.jobs||[];document.getElementById('batches').innerHTML=table(B,[['batch_id','Batch ID'],['created_at','Created UTC'],['status','State'],['jobs_with_status','Jobs with status'],['target_count','Targets'],['three_pass_sites','3-pass sites'],['queued_or_running','Queued/running'],['failed','Failed'],['started_at','Started UTC'],['finished_at','Finished UTC'],['duration_seconds','Duration seconds']]);let cols=[['business','Business'],['category','Category'],['location','Location'],['website','Website'],['status','State'],['successful_candidates','Passing candidates'],['attempts','Attempts'],['started_at','Started UTC'],['finished_at','Finished UTC'],['duration_seconds','Duration seconds'],['failure_reason','Failure reason'],['run_url','Actions']];function draw(){let q=document.getElementById('f').value.toLowerCase();document.getElementById('jobs').innerHTML=table(J.filter(r=>Object.values(r).join(' ').toLowerCase().includes(q)),cols)}draw();document.getElementById('f').addEventListener('input',draw)</script></html>'''.replace("__DATA__",packed)

def main():
    p=argparse.ArgumentParser();p.add_argument("--content",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    data=build(a.content,runs());a.output.mkdir(parents=True,exist_ok=True)
    (a.output/"snapshot.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (a.output/"index.html").write_text(render(data),encoding="utf-8")
    write_csv(a.output/"content_jobs.csv",data["jobs"],["batch_id","job_id","business","category","location","website","result_slug","status","successful_candidates","attempts","failure_reason","run_id","run_url","started_at","finished_at","duration_seconds"])
    write_csv(a.output/"content_batches.csv",data["batches"],["batch_id","created_at","target_count","jobs_with_status","three_pass_sites","queued_or_running","failed","status","started_at","finished_at","duration_seconds","continuation_of"])

if __name__=="__main__": main()
