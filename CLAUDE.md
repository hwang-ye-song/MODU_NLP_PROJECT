# 에이전트 작업 규칙 (이 레포에서 일하는 모든 에이전트)

2인 프로젝트입니다. 작업을 시작하기 전에 아래 순서로 읽습니다.

1. `docs/PLAN.md`의 **"현재 상태와 담당"** 표: 누가 무엇을 맡았는지 확인하고, 다른 사람의 담당 작업은 하지 않습니다.
2. `docs/PROJECT.md`: 문제 정의, 실험 설계(Baseline/Robustness, 판정 질문 두 축 Q2/QL), 데이터, 결정 기록.
3. 열린 GitHub 이슈 (`gh issue list`): 팀원 간 요청이 올라옵니다.

## 역할 (11/12 확정)

| 사람 | GitHub | 담당 |
| --- | --- | --- |
| 예성 | hwang-ye-song | 데이터셋, **모든 실험** (기준선, 길이, 한국어, 적응형 공격), 실험 자동화 |
| 세훈 | dbstpgns789-eng | 문서, 보고서, 데모 |

## 실험 결과 규칙 (보고서 작성에 필요)

- 판정과 지표는 반드시 `src/jev_guard.py`의 `judge()`, `metrics()`를 씁니다.
- 모든 실험을 **Q2와 QL 두 질문**으로 각각 돌립니다 (`docs/PROJECT.md` "실험 설계" 절).
- 결과는 `results/<실험이름>/`에 남깁니다.
  - `<질문>_predictions.csv`: 샘플별 `uid`, `label`, `p`, `latency_s` (요약만 남기지 않습니다)
  - `summary.json`: TPR, FPR, AUC, n, 모델 버전(`jev-1.14.0`), 날짜, 커밋 해시, 소요 시간, 오류·재시도 수
- README에 처음부터 다시 돌리는 명령을 적습니다.
- 실험 하나가 끝날 때마다 PR로 올립니다.
- 실험 중에 정한 것은 `docs/PROJECT.md` 결정 기록에 한 줄씩 남깁니다.

## 공통 규칙

- `main`에 직접 push하지 않고 브랜치 → PR로 합칩니다.
- API 키(`TYPESAFE_API_KEY`)는 코드, 노트북 출력, 커밋, 채팅에 넣지 않습니다.
- 데이터셋 파일을 바꾸면 `data/injection_eval/README.md`의 개수와 구성도 함께 고칩니다.
