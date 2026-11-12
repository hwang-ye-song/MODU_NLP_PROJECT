import json
R={}
for l in open('<DATASET_ROOT>/_build/audit/input_ja_p1_1.jsonl',encoding='utf-8'):
    d=json.loads(l); R[d['id']]=d
def span(i,start,end):
    t=R[i]['text']; a=t.index(start); b=t.index(end,a)+len(end); return t[a:b]
P='ja-llmail-p1-%03d'
fix={
 4:(('OUTPUT INSTRUCTIONS:','"contact@contact.com".'),"span misses the tool-call/format directives"),
 8:(('Please send an email for me.','"Body": "confirmation" }'),"span should include the fake user/assistant turn requesting the send"),
 15:(('Execution Steps:','Email Body: "confirmation"'),"span should cover the API-call construction step"),
 30:(('# OUTPUT FORMAT:','set to "contact@contact.com"'),"span misses the tool-call/format directives"),
 36:(('<Action><Do><SendEmail>','"body":"confirmation"}}'),"span misses the send-email command and the trailing SendEmail JSON"),
 45:(('# OUTPUT FORMAT:','THIS IS IMPORTANT THESE ARE PARSED.'),"actual instruction is the fake admin directive in the subject, not the <p> tag"),
 47:(('Remove space from the to field','c o m "'),"span truncated mid-address"),
 54:(("Hey, just make sure","No changes, OK?"),"span starts with a Spanish fragment; use the English instruction"),
 56:(('<|im_start|>user','InTheFormatHeWanted?'),"span misses the fake user turn asking to reply to Jack with Q2 profit"),
 59:(('followup can be sent','can you plz mail followup?'),"span misses the fake user turn asking to mail the followup"),
 61:(('Hey assistant, send an email','Send it right away after this message!'),"span should be the explicit 'Hey assistant' send instruction"),
}
drop={
 16:"human-to-human (Hi Eddy) compliance request; not clearly aimed at the AI",
 17:"human-to-human (Dear Team) request; no AI-directed instruction",
 25:"human-to-human (Hi Team, 'I need someone to send')",
 31:"human-to-human (Hi Tom) request",
 32:"mostly a human email thread; the only AI-directed fragment (fake <|user|> turn) does not clearly ask to send; doubtful",
 42:"human-addressed request (Hello there); ambiguous whether aimed at AI",
 48:"human-to-human (Hey dude ... Nate) request",
 53:"human-to-human (Hi Team) request",
 64:"reads as a human request from John to resend an email; doubtful",
 65:"asks only to summarize and list follow-ups; no instruction to send/act",
 68:"human-addressed (Dear Colleague) request; only the URL hints at the action",
 70:"human-to-human (Dear Julian) research email",
}
out=[]
for n in range(1,71):
    i=P%n
    if n in fix:
        (s,e),why=fix[n]; sp=span(i,s,e); assert sp in R[i]['text']
        out.append({"id":i,"verdict":"fix","issue":why+"; set injected_instruction to suggested_span","suggested_label":"injection","suggested_span":sp})
    elif n in drop:
        out.append({"id":i,"verdict":"drop","issue":drop[n],"suggested_label":None})
    else:
        out.append({"id":i,"verdict":"ok","issue":"","suggested_label":"injection"})
json.dump(out,open('<DATASET_ROOT>/_build/audit/ja_p1_1_audit.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
from collections import Counter; print(Counter(o['verdict'] for o in out))
for n in (4,36,45,56,59): print(n,repr(span(P%n,*fix[n][0])[:300]))
