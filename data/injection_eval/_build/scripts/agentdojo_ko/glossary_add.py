import json
P='<DATASET_ROOT>/_build/scripts/agentdojo_ko_glossary.json'
add={
 "Rent":"월세","Conference Room A":"회의실 A","Main Conference Hall":"대회의장","International Convention Center":"International Convention Center",
 "The Local Bar":"The Local Bar","Happy Hour with Team":"팀 해피 아워","Board Meeting":"이사회","Annual Conference":"연례 컨퍼런스",
 "Project Review Meeting":"프로젝트 검토 회의","Re: Family Reunion":"Re: 가족 모임","Re: Client Meeting Follow-up":"Re: 고객 미팅 후속 조치",
 "Client Meeting Follow-up":"고객 미팅 후속 조치","Meeting Follow-up":"미팅 후속 안내","Birthday Party":"생일 파티","Re: Tech Issue":"Re: 기술 문제",
 "TODOs for the week":"이번 주 할 일","Your Monthly Subscription Receipt":"월 구독 영수증","Exclusive Travel Deals Just for You!":"회원님만을 위한 단독 여행 특가!",
 "Hi Emma,":"안녕하세요 Emma,","Dear Emma,":"Emma 님께,","Best,":"감사합니다. / 그럼 이만, (informal personal mail)","Best regards,":"감사합니다.",
 "Development (department)":"개발","Marketing (department)":"마케팅","Sales (department)":"영업","Human Resources (department)":"인사",
 "Development Team":"개발팀","Marketing Team":"마케팅팀","Sales Team":"영업팀",
 "The staff was friendly and helpful":"직원들이 친절하고 많이 도와줬어요","Great service and well-maintained cars":"서비스가 훌륭하고 차량 관리가 잘 되어 있어요",
 "Great service and well-maintained vehicles":"서비스가 훌륭하고 차량 관리가 잘 되어 있어요",
 "Your data will be deleted soon! Click here to save it:":"곧 데이터가 삭제됩니다! 데이터를 저장하려면 여기를 클릭하세요:",
 "Total":"합계","Car Rental":"렌터카","Please pay the amount by sending a bank transfer to the following account:":"아래 계좌로 계좌 이체하여 금액을 납부해 주세요:",
 "Thank you for your business!":"이용해 주셔서 감사합니다!",
 "_yaml_rendering (convention note, not a phrase)":"KO YAML tool outputs re-dumped with yaml.safe_dump(obj, allow_unicode=True).strip(); keys/ids/emails/timestamps/filenames/status enums unchanged"
}
g=json.load(open(P,encoding='utf8'))
n=0
for k,v in add.items():
    if k not in g: g[k]=v; n+=1
    elif g[k]!=v: print('CONFLICT',k,g[k],v)
json.dump(g,open(P,'w',encoding='utf8'),ensure_ascii=False,indent=1)
print('added',n,'total',len(g))
