# [종목 모니터] 차트 스크리닝 + 5대 축 편집 — 실행 계획 (2026-08-24)

> ⚠️ **2026-08-25 v3: 차트 스크리닝·실시간 뉴스 전면 은퇴(사용자 단호 지시).**
> 아래 v1·v2 기록은 이력이다. 현재 정본은 맨 아래 "v3 개편" 절.

## v3 개편 (2026-08-25, 구현·배포·검증됨)
- **삭제**(코드단): chart-screening.tsx, realtime-news-panel.tsx, collector `chart()`+`/stock-monitor/chart` 라우트, api `/chart` 프록시, lib StockChart 타입·클라이언트. 참조 0건 확인.
- **표 → 팝업**: '실시간 차트' 카드 **헤더 클릭** → LP평가 ETF 카드식 모달(`stock-table-modal.tsx`, `bg-ge-navy/40`+`shadow-panel` idiom). 컬럼 정렬 기계도 모달로 이사. ★축 편집 팝업은 표 모달 카드 **안**에 렌더 — 카드 stopPropagation 이 축 팝업 배경클릭을 삼켜 이중 닫힘 방지.
- **카드 몸통 = 실시간 이슈 헤드라인**(`realtime-issues.tsx`): monitor rows 클라이언트 계산(엔드포인트 신설 없음). 급등/급락 1위(|등락|≥2%) + 거래량 z≥3 (동일 종목 접기), 최대 3줄, 시각=asof(항목별 발화시각은 collector 이벤트화 때).
- **5대 축 편집 유지**(은퇴 대상 아님): 진입점 = 표 팝업 행 클릭. detail/save 엔드포인트·:rw 마운트 존치.
- 공용 표기 헬퍼 `format.ts` 분리(EMDASH·fmt*·moveColor·sigmaTone).
- ⚠️**잔여**: api·collector 이미지에 죽은 chart 라우트가 남아 있음(소스는 삭제됨).

## "collector 에 못 닿았습니다" 근본원인·수정 (2026-08-25 14:0x, 사용자 문의)
- ★실측: collector 직접 호출 10회 중 1회 **0.00s 즉시 503** = `database disk image is malformed` — 타임아웃 아님, 손상 캐시 판독 실패.
- ★기전: `_copy_when_quiet` 가 dst 를 **제자리 덮어쓰기** → 복사 1~2초 동안 다른 요청 스레드가 dst 를 열면 반쯤 덮인 파일 → malformed. 장중에만 나는 이유 = 원본이 매분 갱신돼 30초마다 복사가 돌기 때문(장마감 후엔 sig 동일로 복사 자체가 안 돎 — 8/24 검증에서 안 보인 이유).
- 형제 버그: index_window(KOSDAQ150) — 원자 교체는 하지만 **무결성 검사 없이 설치** → SMB 원본 쓰기와 겹친 torn copy 가 60초간 살아남음.
- **수정 완료(검증됨)**: stock_monitor = tmp+quick_check 통과분만 os.replace 원자 교체(+close 는 finally — 예외 경로 핸들 누수로 tmp 제거 실패 실측) / index_window = 설치 전 quick_check 게이트. torn copy 시뮬레이션: 설치 거부·기존 사본 무결·tmp 잔재 0.
- **배포 완료 14:5x** (사용자 "그냥 지금 리빌드해" — collector 만). 검증: 장중 20연타 실패 0/20(이전 10회 중 1회 503), malformed 로그 0, **KOSDAQ150 지수 스트립 회복**(1429.03 실시간). 죽은 chart 라우트도 이 빌드로 함께 제거됨.
  ⚠️api·web 은 **다른 세션이 병행 개발 중**(EtfFlowCard=ETF 순매수 모니터, 우상단 칸)이라 이쪽에서 재빌드하지 않는다 — 미완성 코드를 구워 배포할 위험. api 의 죽은 chart 라우트는 무해하므로 그쪽 세션의 다음 배포에 자연히 실려 나간다.

- 8/25 16:0x: 톱바 정렬 프리셋 버튼(거래대금/등락률/이상탐지) 제거(사용자 지시 "무의미") — 서버 정렬 거래대금 고정, 정렬 수단은 팝업 표 컬럼 헤더 클릭만. 배포·검증됨.

## 실시간 이슈 후보 (2026-08-25 제안, 사용자 검토 대기)
분봉+universe 통계만으로 지금 가능(항목별 발화 시각 나옴):
1. ✅ 당일 등락률 1위 급등/급락 (구현됨, ±2% 게이트)
2. 단기 가속 — 최근 5~10분 수익률 급변(±1.5%): "지금 막 움직이기 시작"
3. 거래량 스파이크 — 분봉 z≥4, 개장5분·마감봉 제외+연속접기(은퇴한 chart()에서 검증한 로직 재사용)
4. 등락σ 이상 — |당일등락/sigma_daily|≥2~3 ("그 종목답지 않은" 움직임)
5. 장중 신고/신저 경신
6. 장중 반전 — 당일 저점 대비 +x% 회복 / 고점 대비 −x% 반락
일봉 원천(price_monitor.xlsx·prc_vol_fsym.parquet) 합류 후:
7. 이평선 돌파(20·60일, 골든/데드크로스) 8. 52주 신고/신저 9. 시가 갭 ±x%
10. 기간수익률 자기분위수 상위(주간모니터의 "고정임계 폐기→실측 분위수" 교훈 재사용) 11. 변동성 체제 전환(5일 vs 60일 실현변동성)
외부 원천 필요: 12. 외인/기관 순매수(KRX 잠정) 13. VI 발동 14. 공매도 잔고 급변(T+2)

## 요구 (사용자, /loop 20분)
1. 대시보드 1페이지 하단 빈 영역(3×2 그리드의 아래 행) → **차트 스크리닝** 영역.
   - 시계열 차트 + 이벤트 마커(뉴스·거래량·외인 순매수 … 시점 표시). 예시: `S:\GE\raw\data\Toss_분봉_모니터\input\차트_뉴스 결합.png` (캔들 + 원형 하이라이트 + 화살표 라벨).
   - 퀀트지표는 미완 → 우선 지금 가진 원천(분봉 거래량 등)으로 마커 인프라를 세우고, 뉴스→축 매핑은 상류 AI 작업 후 이벤트 소스로 붙는다.
2. `input/raw/stock_info`(199 json, sector L1~L5·country·currency·news_axis)와 `stock_axis`(200 json, 5대 축 수기입력)는 다른 사람이 채운다.
3. **축 입력을 종목 모니터 화면 user input 으로** — 저장 시 S:의 `stock_axis/{이름}_axis.json` 을 수정.

## 원천 스키마 (실측 2026-08-24)
- `stock_info/{이름}.json`: `{name, symbol, sector:{L1..L5}, country, currency, news_axis}`
- `stock_axis/{이름}_axis.json`: `{name, symbol, news_axis, axes:[5 strings]}` (현재 axes 전부 빈 문자열)
- 파일 키는 **한글 이름**(심볼 아님). symbol 필드로 대조 가능.

## 설계
### 배선 (docker-compose collector)
- `/mnt/s/GE/raw/data/Toss_분봉_모니터/input/raw/stock_info` → `/srv/legacy/toss_input/stock_info` **:ro**
- `/mnt/s/GE/raw/data/Toss_분봉_모니터/input/raw/stock_axis` → `/srv/legacy/toss_input/stock_axis` **:rw**
  (perf_analysis output/funds 와 같은 "좁은 rw 중첩" 선례. 컨테이너가 쓰는 건 이 폴더의 `*_axis.json` 뿐)

### collector (stock_monitor.py + main.py 라우트 3개)
- `GET /stock-monitor/chart?symbol=&day=` → `{symbol, name, day, prev_close, bars:[{ts,o,h,l,c,v}], events:[{ts,kind,label}]}`
  - bars: 기존 스냅샷(_refresh/_connect) 재사용, 당일 분봉.
  - events v1: 거래량 스파이크(그날 그 종목 분봉 분포에서 z≥4, 최대 5건). kind 확장 슬롯: news / foreign / quant….
- `GET /stock-monitor/stock-detail?name=` → info+axis 병합 (SMB 2파일 직독 — 전량 스캔 금지, 회의탭 PoC 503 교훈)
- `POST /stock-monitor/stock-axis` `{name, symbol, axes[5], news_axis}` → 기존 파일 읽어 symbol 대조 후 tmp→os.replace 원자 교체. 파일 없으면 404(생성은 상류 소관). name 경로문자 검증.

### api (stock_monitor.py 프록시)
- GET 2개는 `_proxy_collector`(한글 name 은 quote). POST 는 본문 전달 헬퍼 신설(기존 `_proxy_collector_post` 는 본문 미지원).

### web (stock-monitor/page.tsx + components/stock-monitor/)
- 하단 행: 차트 스크리닝 `col-span-2`(상단 표와 같은 폭) + 종목 상세/축 편집 1칸(우하단, 섹터 카드 아래).
- 표 행 클릭 → selectedSymbol. 미선택 시 1위 행 자동.
- 차트: 손수 SVG 캔들 + 거래량 바 + 이벤트 마커(▲ + title 툴팁). 차트 라이브러리 안 씀(Spark 선례). 상승 rose-600/하락 blue-600.
- 축 편집: 5칸 텍스트 입력 + news_axis 토글 + 저장. sector/country/currency 는 읽기 전용 표시.

## 배포 주의
- web·collector 모두 빌드 이미지(바인드마운트 없음) → `docker compose build web collector && up -d` (WSL에서만).
- **collector 재기동은 15:30 장마감 후** (iNAV KIS 웹소켓 라인 살아있음).

## 진행 로그
- [x] 탐색: 원천·페이지·collector·프록시 구조 파악
- [x] compose 마운트 (stock_info :ro / stock_axis :rw)
- [x] collector chart/detail/save — 단위검증 ALL PASS (스크래치 사본, 삼성전자 391봉·15.3σ 스파이크 검출, save 200/409/404/400/경로문자/tmp잔재 전부 통과)
- [x] api 프록시 (GET chart·stock-detail + POST stock-axis 본문 전달, SLOW 타임아웃)
- [x] web lib/api.ts (StockChart/StockDetail/SaveStockAxisInput)
- [x] web UI — chart-screening.tsx(캔들+거래량 SVG, 마커·시각축은 HTML 오버레이) + stock-detail-panel.tsx(key={name} 리셋 편집기) + page.tsx 행클릭 배선
- [x] 빌드·배포·검증 (2026-08-24 15:5x) — api/collector/web 재빌드·up, 라이브 확인:
  - chart: 삼성전자 391봉 + 이벤트 4건 / detail: BGF리테일 병합 정상
  - identity save 라운드트립 200 → 실제 S: 파일 포맷·내용 보존 확인, symbol 불일치 409
  - web /stock-monitor 200
- [x] 거래량 스파이크 보정: 개장 5분·15:30 동시호가 봉 제외(둘 다 매일 전 종목 최대 = 무늬, 실측 마감봉 15.3σ·제외 후 09:01~04 클러스터) + 연속 분 접기(대표=구간 최대 z)
- ts 실측: minute_bars ts = "YYYY-MM-DD HH:MM:SS", 15:30 마감봉 존재
- [x] 화면 육안 검증 (2026-08-24 16:2x, Chrome 확장 미연결 → Playwright 헤드리스) —
  - 캔들·거래량·전일종가 점선·마커▲(주황 거래량 막대와 수직 정렬)·시각축 전부 정상, 콘솔 에러 0
  - 행 클릭(NAVER) → 차트·상세 패널 동시 전환 확인
  - 09:00 라벨 왼쪽 잘림 발견 → 가장자리 translateX clamp 수정·web 재배포·재검증 완료
  - ★상류가 이미 축을 채우기 시작(삼성전자: 메모리반도체·주주환원·HBM·패키징·노조, 뉴스-축 매핑 ON) — 편집기가 실값 정상 표시. 섹터 체계는 밸류체인 스타일(AI·기술›AI 인프라›반도체)

## v2 개편 (2026-08-24 사용자 지시, 구현·배포·검증됨)
- 축 편집: 우하단 카드 → 차트 스크리닝 헤더 [5대 축 편집] 버튼 → **팝업 카드**(`axis-editor-modal.tsx`, 백드롭 클릭 닫기). 구 `stock-detail-panel.tsx` 삭제.
- 우하단 칸 = **실시간 뉴스**(`realtime-news-panel.tsx`) placeholder. 삼성전자(005930)만 실데이터 목업:
  텔레그램모니터 `input/processed` 70방 CSV(`date,time,msg_id,topic,category`)에서 8/18~24 '삼성전자' 382건 → **1사건 1노출 21건** 큐레이션(주주환원 빌드업→8/21 공시→8/24 실망 급락 스토리라인). 파이프라인 붙으면 MOCK 상수·배지 걷어내고 chart events(kind:"news")와 **같은 원천** 사용할 것.
- ★버그: `bg-surface`는 **tailwind config에 없는 죽은 클래스**(선재 — 표 섹션도 투명하게 페이지 캔버스에 기대고 있었고 모달에서 노출) → 전부 `bg-canvas`(#fff 하우스 토큰)로 교체.

## 확인 필요(사용자)
- 산업 컬럼: stock_info sector(L1~L5)가 생겼으니 표의 빈 '산업' 컬럼을 L2 로 채울 수 있다(collector reshape 몇 줄). 우상단 '섹터별 등락률' 카드도 같은 매핑으로 가능. 넣을지, L 몇으로 할지.
- 이벤트 소스 다음 순번: 뉴스(5대 축 매핑 상류 대기) 전에 외인 순매수 등 붙일 원천이 있는지.
