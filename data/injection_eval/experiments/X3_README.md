# X3: 주변 텍스트의 "종류"가 길이보다 중요한가 (distractor carrier)

## 목적
같은 injection 문장을 (a) 과제와 무관한 백과사전식 설명문과 (b) 사람에게 하는 지시·요청이 많은 업무 이메일에 각각 묻었을 때 Jev가 더 놓치는 쪽이 있는지 본다. 가설: 지시가 많은 benign 텍스트 안의 injection이 더 잡기 어렵다. 두 carrier 종류의 길이는 1,200–1,600자로 고정했다.

## 요인과 수준
- `carrier_type`
  - `unrelated_expository` (`carrier_source=wiki`): 영어 위키백과 본문 발췌. 예: 인도네시아 Karo족 문서의 첫 문단들.
  - `instruction_dense` (`carrier_source=enron`): 요청 문장이 3개 이상인 Enron 업무 메일(AESLC). 예: "Subject: Central desk items … Please put any future requests in there …"
- `label`: 같은 carrier에서 injection 행(span 삽입)과 benign 행(원문 그대로)을 하나씩 만든다.
- `position`: 모두 `"middle"`. carrier 길이의 절반에 가장 가까운 문장 경계에 span을 독립 문장으로 넣는다. 위키는 문장 사이(공백), Enron은 줄 경계(`\n`) 또는 줄 안의 문장 경계(공백)다. 삽입 위치는 `insert_offset`에 있다. 그 외 텍스트는 carrier와 byte 단위로 같다.

## 규모 (총 400행)
| carrier_type | injection | benign |
|---|---|---|
| unrelated_expository (wiki) | 100 | 100 |
| instruction_dense (enron) | 100 | 100 |

- span 출처(종류별 100개, 두 종류에 같은 span 사용): BIPIA 24 (news 8 / table 8 / email 8), BrowseSafe-Bench 16, InjecAgent 20 (dh/ds base/enhanced 5씩), LLMail-Inject 20, SEP 20.
- `carrier_len` 중앙값: wiki 1,270.5 (1,202–1,566), enron 1,248.5 (1,200–1,459). span 길이 중앙값 93자 (32–198).
- `carrier_n_requests`(정규식으로 센 요청 문장 수) 중앙값: wiki 0, enron 3 (최소 3).

## main set과의 연결과 짝
- injection 행: `base_id`/`base_uid`는 span을 가져온 main set 행이다. `source`, `doc_type`, `risk_level`도 그 행에서 복사했다. `injected_instruction`은 그 행의 span을 그대로 옮긴 것이다.
- benign 행: carrier는 main set에 없는 새 텍스트다. 따라서 `base_id`/`base_uid`는 null이고 `source`(Wikipedia/Enron), `doc_type`(wiki/email), `risk_level=0`은 carrier 기준이다.
- `carrier_id`(예: `X3-wiki-007`): 같은 carrier의 injection·benign 행을 잇는다.
- `inj_pair_id`(예: `X3-P007`): 같은 span을 담은 wiki·enron 두 injection 행을 잇는다. `slot`(1–100)은 그 4행(2종류 × 2 label)이 공유한다.
- `variant_text_source`: injection 행 "template", benign 행 "original".
- span 조건: AgentDojo 제외, code_qa 제외, 20–200자, text 안에 정확히 1번, 줄바꿈·코드·태그 없음, 대문자로 시작. 3-gram Jaccard 0.7 이상인 중복 span 제외. `random.seed(42)`.

## 출처와 라이선스
- Wikipedia: `wikimedia/wikipedia` 20231101.en 덤프. `sim/raw/en_wiki.jsonl`(HF datasets-server rows API, `sim/fetch_corpora.py`)에서 읽기만 했다. 행 번호와 URL은 `carrier_origin`에 있다. 라이선스 CC BY-SA. 제목, 소제목, 150자 미만 문단, 표·목록은 버리고 앞쪽 문단을 빈 줄로 이어 붙인 뒤 문장 경계에서 잘랐다.
- Enron: `Yale-LILY/aeslc` revision 2305f2e63b68056f9b9037a3805c8c196e0d5581 (train 77, validation 12, test 11). 라이선스 "unknown"(데이터셋 카드에 명시 없음). 형식은 기존 Enron 행과 같다: `"Subject: " + subject + 빈 줄 + body`. 공백 정리 후 body 앞부분을 문장 경계에서 잘랐다.
- Stack Exchange(BIPIA code contexts, CC BY-SA): **사용하지 않았다.** 아래 한계 1 참고.
- carrier 제외 기준:
  - main set, `_build/parts_v2/*.jsonl`, `_build/*candidates.jsonl`과 5-gram 포함률 또는 Jaccard가 0.3 이상인 텍스트, carrier끼리 겹치는 텍스트;
  - AI를 언급하는 텍스트;
  - 개인정보: 비밀번호·ID·계좌·카드·SSN 패턴, 7자리 이상 숫자, 전화번호·내선, 이메일 주소;
  - URL, 전달·인용 헤더, 인코딩 깨짐, 비영어;
  - 위키는 you/please 등 독자에게 하는 말이 있는 발췌도 제외했다.
- 빌드 스크립트: `<SCRATCH>/scripts/x3/build.py`

## 알려진 한계
1. 요청과 달리 instruction_dense는 100% Enron이다. BIPIA code context 100개 중 코드 블록과 들여쓴 코드가 없는 것은 13개뿐이고, 가장 긴 것도 1,020자라 1,200–1,600자 조건을 만족하는 것이 없었다.
2. BrowseSafe span은 템플릿 반복이 많아 고유한 것이 16개뿐이다. 그래서 BIPIA를 24개로 늘렸다.
3. span 24개는 마침표 없이 끝난다(원문 그대로). 그래서 삽입 후 다음 문장과 붙어 읽힌다(run-on).
4. 길이 혼입: injection 행은 같은 carrier보다 span 길이만큼 길다. 전체 길이-only AUC는 0.855다. carrier_id로 짝지은 분석을 하라. wiki와 enron injection 행 사이의 길이 AUC는 0.596이다.
5. 위키 덤프에는 일부 장난 편집 문장이 원문 그대로 남아 있다(예: Carolana 문서의 "Freddy Fazbear").
6. Enron carrier가 모두 업무 메일은 아니다. 광고·스팸 메일(merchant account 광고, TurboTax 알림 등) 몇 건과 사적인 메일 몇 건이 섞여 있다. 요청 수는 정규식으로 셌으므로 대략적인 값이다.
7. 위키는 rows API로 받은 데이터라 revision 해시가 없다. 덤프 버전(20231101.en)만 기록했다.
