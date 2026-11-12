import json, sys, re
base = sys.argv[1]
ko0 = r'''"NIFTY심볼 비교 또는 추가\n\n\n\n차트 인터벌캔들지표, 메트릭 및 전략즐겨찾기지표 템플릿J얼러트 만들기바 리플레이스크롤 되돌리기레이아웃 설정Trader_User \n저장레이아웃 관리빠른 검색설정전체 화면 모드스냅샷 찍기게시십자선커서추세선추세선 도구피보나치 되돌림갠 및 피보나치 도구XABCD 패턴패턴롱 포지션예측 및 측정 도구브러시도형텍스트주석 도구아이콘아이콘측정확대자석 모드는 가격 바 근처에 그린 드로잉을 가장 가까운 OHLC 값에 맞춥니다자석계속 그리기모든 드로잉 잠금모든 드로잉 숨기기숨기기 옵션개체 제거제거 옵션즐겨찾는 드로잉 도구 툴바 표시\n\nNNifty 50 Index·5 \n· \nNSE심볼 플래그더 보기마켓 오픈 · 5초마다 업데이트O \n24,958.60 \nH \n24,961.25 \nL \n24,957.95 \nC \n24,960.40 \n+2.25 (+0.01%) \n거래량 \n72.14 K24,959.80 \n매도 \n0.00 \n24,959.80 \n매수2\n\n1D5D1M3M6MYTD1Y5Y전체이동09:50:09 UTC+5:30RTH관심 목록, 상세 정보 및 뉴스얼러트개체 트리 및 데이터 창채팅스크리너캘린더제품99+채팅 어시스턴트Pine 에디터트레이딩 패널패널 열기패널 최대화\n\n트레이딩 패널\n\nNIFTY · NSE, 5 \nICT Concepts \[LuxAlgo\] (Present, 5, 2, 10, 1, 1, 4, 2, FVG, 2, 3, 1, OB, 0700-0900, 0700-1000, 1500-1700, 1000-1400) \nAlgoAlpha - Breakout Channels (100, 14, Comparison, , 1, Tiny)"'''
d = {"0": ko0, "1": "계속 이용하시려면 프로필 인증을 완료하세요:", "2": "=", "3": "튜토리얼 보기:", "4": "="}
json.dump(d, open(base + '/ko/web-ben-14.json', 'w', encoding='utf-8'), ensure_ascii=False)
src = open(base + '/src/web-ben-14.txt', encoding='utf-8').read()
seg = src[:src.index('<p')].strip()
for pat in (r'\n', r'\\', r'\d[\d,.:+%-]*', r' '):
    a, b = re.findall(pat, seg), re.findall(pat, ko0)
    print(pat, len(a), len(b), a == b if pat != ' ' else '')
