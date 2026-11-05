import json, statistics as st
from collections import defaultdict
rows=[json.loads(l) for l in open("trials_run.jsonl")]
TV={1:12.706,2:4.303,3:3.182,4:2.776}
ci=lambda v: TV.get(len(v)-1,2)*st.stdev(v)/len(v)**.5 if len(v)>1 else float("nan")
m=lambda s,a=0,b=None:st.mean(x[1] for x in s[a:b] if x[1] is not None)
print("A windows")
for r in rows:
    if r["phase"]=="A": print(" ",r["ts"][11:16],r["disk"],round(m(r["samples"]),3),"sd",round(st.stdev(x[1] for x in r["samples"]),3),"cpu",r["cpu_idle"],"E-idle",r["soc"].get("E-Cluster_idle_ratio"),"PS-idle",r["soc"].get("PS-Cluster_idle_ratio"))
print("B sequence: baseline first15/last15, job, prev rate")
prev=None; res=defaultdict(list)
for r in rows:
    if r["phase"]!="B": continue
    bs=r["baseline"]; first=m(bs,0,15); last=m(bs,-15); job=m(r["samples"],5,-1)
    pv=prev; prev=r["rate"]
    print(" ",r["ts"][11:19],f'{r["disk"]:8} {r["op"]:5} {r["rate"]:>3} base {first:.3f}/{last:.3f} job {job:.3f} prev {pv} peak {max(x[1] for x in bs):.2f} n {len(bs)}')
    ok=abs(last-7.825)<0.05
    res[(r["op"],r["rate"],r["disk"])].append((job-last,ok,r["job"]["mb_s"],r["job"]["secs"],r["job"]["bytes"]))
print("B dW = job minus LAST 15 s of own baseline; only trials with that baseline within 0.05 W of 7.825")
for k in sorted(res,key=lambda x:(x[0],x[1] or 1e9,x[2])):
    v=[x[0] for x in res[k] if x[1]]
    print(" ",k,"n",len(v),"of",len(res[k]),"dW",round(st.mean(v),3) if v else None,"+-",round(ci(v),3) if len(v)>1 else None,[round(x,3) for x in v],"J/GB",round(st.mean(x[0]*x[3]/(x[4]/1e9) for x in res[k] if x[1]),2) if v else None)
print("C per run, in time order")
for r in rows:
    if r["phase"]!="C": continue
    s=r["samples"];t=r["tail_s"]
    print(" ",r["ts"][11:16],f'{r["arm"]:17} rep{r["rep"]} cpu {r["cpu_idle"]} base {m(r["baseline"],5):.3f} enc {m(s,3,-t):.3f} d {m(s,3,-t)-m(r["baseline"],5):.3f} T {len(s)-t} bytes {r["output_bytes"]} tail {m(s,-t):.3f}')
