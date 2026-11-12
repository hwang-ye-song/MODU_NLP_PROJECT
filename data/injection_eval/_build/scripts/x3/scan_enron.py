import re,sys,json,collections
import pyarrow.parquet as pq
d=sys.argv[1]
REQ=re.compile(r"(?i)\b(please|pls|could you|can you|would you|will you|let me know|let us know|make sure|be sure to|need you to|i need|we need|kindly|don't forget|do not forget|remember to|feel free to|call me|give me a call|send me|forward|review|i would appreciate|you should|you must|should you)\b")
IMP=re.compile(r"^(Please|Call|Send|Forward|Review|Let|Make|Check|Sign|Fax|Return|Bring|Contact|Reply|Respond|Complete|Submit|Attend|Note|Remember|Confirm|Plan|Provide|Give|Get|Have|Ask|Read|Print|Fill|Update|Email|E-mail|Add|Do|Don't|Be)\b")
n=0;tot=0;hist=collections.Counter()
for s in ("train","validation","test"):
  t=pq.read_table(f"{d}/{s}-00000-of-00001.parquet").to_pylist()
  for i,r in enumerate(t):
    body=r["email_body"] or ""
    tot+=1
    if len(body)<1150: continue
    lines=[x for x in body.split("\n") if x.strip()]
    nreq=sum(1 for x in lines if REQ.search(x) or IMP.match(x.strip()))
    hist[min(nreq,10)]+=1
print(tot,sorted(hist.items()))
print(t[0].keys())
print(t[5]["email_body"][:800])
