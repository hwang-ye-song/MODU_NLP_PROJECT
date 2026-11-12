# 02b_korean_registers_mt: 말투 데이터의 번역 후 판정 (PLAN E4)

korean-prompt-injection-registers의 한국어 7개 말투 1,547행을 `Helsinki-NLP/opus-mt-ko-en`으로 영어로 옮긴 뒤 Jev(`jev-1.14.0`)로 판정한 결과입니다. 설계, 결과 표, 해석, 한계는 [`../02b_korean_registers/README.md`](../02b_korean_registers/README.md)의 "번역 후 판정 (E4)" 절에 원문 결과와 함께 있습니다.

| 항목 | 값 |
| --- | --- |
| 입력 | `../02b_korean_registers/translation/registers_ko_to_en.jsonl` (md5 `b5626b96ba14f74a4cde5065715843b1`), `experiments/translate_registers.py`가 CPU에서 만듦 |
| uid | 원문과 같은 `<항목 id>-<말투>`. 원문 판정은 `../02b_korean_registers/{Q2,QL}_predictions.csv` |
| 질문 | Q2, QL (3회 평균 p, 임계값 0.5) |
| 호출 | 2026-11-12 UTC, Q2 4,641회 10:13~10:20, QL 4,641회 10:20~10:27, 오류·재시도 0. 입력 토큰 Q2 1,380,159 / QL 2,206,257 ($0.058 / $0.093) |
| 결과 (7개 합침) | Q2 TPR 73.0% (66.3–79.9), FPR 2.6% (1.6–3.6), AUC 0.940 (0.918–0.960) / QL TPR 71.9% (64.7–79.2), FPR 5.5% (4.2–6.6), AUC 0.931 (0.907–0.952). 괄호는 항목 부트스트랩 95% 구간 (한 항목의 7개 버전이 독립이 아니므로). 원문 대비 TPR −8.7%p / −7.1%p, FPR −1.5%p / −1.7%p |

## 파일

| 파일 | 내용 |
| --- | --- |
| `raw/Q2_raw.jsonl`, `raw/QL_raw.jsonl` | 호출 4,641건씩의 원본 응답 |
| `Q2_predictions.csv`, `QL_predictions.csv` | 행별 `uid`, `label`, `p`, `latency_s`, 판정, 회차별 p, 항목 id, 말투 |
| `summary.json` | 질문별 지표 (`overall` = 번역 1,547행, `by_register`), 실행 정보, `analysis` (번역 후 지표, 번역 전후·영어 원문 대비 짝 비교, 번역 점검, 비용). `analysis`와 `overall`의 `TPR_ci95`·`FPR_ci95`·`AUC_ci95`(항목 부트스트랩; 행 단위 Wilson은 `*_row_wilson`, 참고용)는 `experiments/analyze_02b_korean_registers.py`가 씀. 표와 그림은 `../02b_korean_registers/tables/e4_*.csv`, `figures/f10_mt_deltas.png` |

## 다시 실행

이 폴더만 따로 만들 수 없습니다. 원문 판정과 번역 파일이 필요하므로 [`../02b_korean_registers/README.md`](../02b_korean_registers/README.md)의 "다시 실행" 블록(clone, `pip install`, `fetch_korean_registers.py`, `judge`, 번역, `judge-mt`, 분석)을 처음부터 실행합니다. 그중 이 폴더에 해당하는 부분은 아래와 같습니다 (깨끗한 clone에서는 그 앞의 clone·설치·`fetch`·`judge`를 먼저).

```bash
MT_DEVICE=cpu python experiments/translate_registers.py      # torch + transformers 환경; 번역 파일이 있으면 새로 번역하지 않음
python experiments/run_02b_korean_registers.py judge-mt       # 번역 1,547행 x Q2/QL x 3회; raw/에 있는 호출은 건너뜀
python experiments/analyze_02b_korean_registers.py           # 두 폴더의 summary.json "analysis"와 overall 구간, 02b 표·그림 (API 없음)
```

- `raw/*.jsonl`이 있으면 `judge-mt`는 새 호출을 하지 않습니다 (시작할 때 키가 있는지만 확인). `judge-mt`는 `summary.json`을 다시 쓰고 `overall` 구간을 행 단위 Wilson으로 되돌리므로 마지막 줄을 꼭 다시 실행합니다.
- 옛 첫 점검 명령 `run_02b_korean_registers.py analyze`는 쓰지 않습니다. 실행했다면 마지막 줄을 다시 실행합니다.
- Windows에서는 `python -X utf8 ...`로 실행합니다.
