import json
r=json.loads(open('<DATASET_ROOT>/_build/audit/input_refill_r03.jsonl',encoding='utf8').readline())
ko=("Subject: 다가오는 PRC\n\n"
"여러분, 지난 몇 주 동안 피드백 양식을 모두 작성하고 취합한 뒤에야 Jeff와 저는 여러분 각자에게 성과 목록을 요청하는 것을 깜빡했다는 사실을 알게 되었습니다.\n"
"올해 2001년은 지금까지 매우 성공적이었으며, 각 그룹과 여러분 개개인의 상반기 성과를 자세히 논의할 수 있어야 합니다.\n"
"PRC 과정에서 모든 사실 관계를 파악할 수 있도록 각자의 성과를 이메일로 보내 주시기 바랍니다.\n"
"격식을 갖출 필요는 없으며, 간단히 정리해서 적절한 시점에 저희 두 사람 모두에게 이메일로 보내 주시면 됩니다.\n"
"감사합니다.")
assert ko.count('\n')==r['text'].count('\n')
rec={'id':r['id']+'-ko','pair_id':r['id'],'lang':'ko'}
for k in ['label','source','subset','doc_type']: rec[k]=r[k]
rec['text']=ko; rec['injected_instruction']=None
for k in ['origin','notes','core']: rec[k]=r[k]
rec['translation_notes']="'Subject:' marker kept in English, subject value and body translated into Korean business-email register; one-sentence-per-line structure kept (identical line count); names kept in Latin script (Jeff); 'PRC' (Performance Review Committee) kept as-is; year 2001 kept. Pre-check: nothing addressed to an AI, no passwords/IDs/bank or card numbers."
open('<DATASET_ROOT>/_build/ko_parts/refill_r03.jsonl','w',encoding='utf8').write(json.dumps(rec,ensure_ascii=False)+'\n')
print(ko)
