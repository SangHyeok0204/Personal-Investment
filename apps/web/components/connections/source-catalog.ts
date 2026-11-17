// 연동/설정 화면에 카드로 세우는 외부 데이터 소스 목록.
//
// ★2026-10-28 사용자 요청: 계좌 연동 칸을 "연결되는 소스마다 카드"로 — 어떤 소스, 무슨 형태,
//   받는 데이터, 최근 연결 확인, 출처, 저장 여부를 짧게. 키움·토스 밖에 실제로 부르는 곳
//   (Investing.com, 환율 등)도 전부 올린다.
// ⚠️여기 적힌 형태·주기·저장은 **코드에서 확인한 사실**이다(2026-10-28 조사). 핸들러를 바꾸면 같이 고친다.
// ⚠️`statusKeys` 는 `source_status` 의 source 값이다(/api/v1/jobs/sources). 비어 있으면 그 경로는
//   성공/실패를 기록하지 않는다 — 화면은 '상태 기록 안 함'으로 정직하게 보여 준다(추측해서 '정상'이라 하지 않는다).

export type StoreKind = "db" | "cache" | "none";

export interface SourceCard {
  id: string;
  name: string;
  /** 접속 형태 — REST · RSS · CSV · 크롬 크롤 · MCP · CLI */
  form: string;
  /** 받는 데이터(짧게) */
  data: string;
  /** 언제 부르나 */
  cadence: string;
  store: StoreKind;
  /** 저장 위치(테이블) 또는 캐시 수명 */
  storeDetail: string;
  /** 출처 호스트 */
  origin: string;
  statusKeys: string[];
  /** 시세 경로 상태(/price-sources)의 id — 토스·야후만 */
  priceSourceId?: string;
  /** 꼭 알아야 할 제약 한 줄 */
  caveat?: string;
  /** '최근 확인' 대신 쓸 말 — 상태가 바뀔 때만 기록하는 소스는 마지막 성공이 '확인'이 아니다 */
  okLabel?: string;
}

export interface SourceGroup {
  id: string;
  title: string;
  hint: string;
  cards: SourceCard[];
}

export const KIWOOM_CARD: SourceCard = {
  id: "kiwoom",
  name: "키움증권 REST OpenAPI",
  form: "REST · OAuth 키",
  data: "계좌·잔고·보유·주문·체결·배당·실현손익·일별 성과",
  cadence: "영업일 16:30 이후 전체 동기화(실패 시 2시간 뒤 재시도) · 장중 잔고 5초",
  store: "db",
  storeDetail: "trades · positions · realized_pnl 외 + 원본 응답 storage/raw",
  origin: "api.kiwoom.com",
  statusKeys: ["kiwoom"],
  // 잔고 응답의 조회 시점 가격 — 토스·야후가 모두 안 될 때의 폴백 시세
  priceSourceId: "kiwoom-quote",
  caveat: "서버 공인 IP 허용목록 필수 — 안 하면 키가 맞아도 8050 거부",
};

export const SOURCE_GROUPS: SourceGroup[] = [
  {
    id: "quote",
    title: "시세 · 환율",
    hint: "지금 얼마인가",
    cards: [
      {
        id: "toss",
        name: "토스증권 Open API",
        form: "REST · OAuth2",
        data: "미국 종목 현재가(데이·프리장 포함) · 실적 반응용 1분봉",
        cadence: "화면 시세 요청마다(캐시 4초)",
        store: "cache",
        storeDetail: "현재가는 4초 캐시 · 실적 반응값만 earnings_results",
        origin: "openapi.tossinvest.com",
        statusKeys: ["toss"],
        priceSourceId: "toss",
        // ⚠️quote_cache 는 토스 상태가 **바뀔 때만** 기록한다 — 성공 시각은 '정상이 된 때'다
        okLabel: "정상 전환",
        caveat: "IP 허용목록 필요 · 클라이언트당 유효 토큰 1개",
      },
      {
        id: "yahoo",
        name: "Yahoo Finance",
        form: "REST · 키 없음",
        data: "장외 현재가 · 52주 범위 · 일봉(봉차트) · 지수 월말 종가",
        cadence: "현재가 4초 · 일봉·봉차트 1시간 캐시 · 월말 종가는 매월 1회",
        store: "cache",
        storeDetail: "대부분 캐시 · 지수 월말 종가만 monthly_closes",
        origin: "query1.finance.yahoo.com",
        statusKeys: ["yahoo"],
        priceSourceId: "yahoo",
        caveat: "상태 기록은 월말 종가 수집만 남긴다",
      },
      {
        id: "naver-fx",
        name: "네이버 환율",
        form: "REST · 키 없음",
        data: "USD/KRW (하나은행 고시 회차)",
        cadence: "포트폴리오 화면 요청 때(캐시 40~80초 무작위)",
        store: "cache",
        storeDetail: "캐시만 · 실패 시 마지막 값을 '지연'으로",
        origin: "api.stock.naver.com",
        statusKeys: [],
      },
      {
        id: "naver-name",
        name: "네이버 종목 검색",
        form: "REST · 자동완성",
        data: "처음 보는 티커의 한글 종목명",
        cadence: "관심종목에 새 티커를 넣을 때",
        store: "none",
        storeDetail: "이 경로는 저장하지 않음",
        origin: "ac.stock.naver.com",
        statusKeys: [],
      },
    ],
  },
  {
    id: "earnings",
    title: "실적 · 공시",
    hint: "언제 무엇을 발표하나",
    cards: [
      {
        id: "nasdaq",
        name: "Nasdaq 실적 캘린더",
        form: "REST · 키 없음",
        data: "발표 일정 · EPS 컨센·실적·서프라이즈",
        cadence: "매일 07:10 이후 · 화면 6시간 캐시",
        store: "db",
        storeDetail: "earnings_events · earnings_results",
        origin: "api.nasdaq.com",
        statusKeys: ["nasdaq"],
      },
      {
        id: "investing",
        name: "Investing.com",
        form: "크롬 크롤(화면 있는 크롬)",
        data: "매출 컨센 · 지난 분기 매출 실적",
        cadence: "매일 07:20 이후 1회(Cloudflare 때문에 크롬은 회차당 1번)",
        store: "db",
        storeDetail: "earnings_events · earnings_results",
        origin: "www.investing.com",
        statusKeys: ["investing", "job:EARNINGS_REVENUE"],
        caveat: "맥 로그인 세션에서만 돈다(도커 불가)",
      },
      {
        id: "earnings-result",
        name: "실적 결과 수집",
        form: "SEC 8-K + 토스 1분봉 조합",
        data: "보도자료 링크 · 발표 직후 주가 반응",
        cadence: "발표 시간대가 끝난 뒤 15분마다",
        store: "db",
        storeDetail: "earnings_results (+ LLM 구조화 작업 연결)",
        origin: "sec.gov · tossinvest",
        statusKeys: ["earnings_result"],
      },
      {
        id: "sec",
        name: "SEC EDGAR",
        form: "REST · XML (연락처 UA 필수)",
        data: "13F 보유 · Form 4 내부자 · 13D/G 지분 · 8-K/10-Q 공시",
        cadence: "Form 4 매시간 · 13D/G 12시간 · 13F 시즌 매일",
        store: "db",
        storeDetail: "sec_filings · holdings_13f · form4_transactions · ownership_events",
        origin: "sec.gov · data.sec.gov",
        statusKeys: ["sec", "sec_form4", "sec_13f", "sec_13dg"],
        caveat: "초당 10회 넘거나 UA 없으면 403 + 일시 차단",
      },
      {
        id: "openfigi",
        name: "OpenFIGI",
        form: "REST",
        data: "CUSIP → 티커 매핑(13F 해석용)",
        cadence: "하루 1회",
        store: "db",
        storeDetail: "cusip_map",
        origin: "api.openfigi.com",
        statusKeys: ["openfigi"],
      },
    ],
  },
  {
    id: "macro",
    title: "매크로 · 한국 ETF",
    hint: "시장 전체",
    cards: [
      {
        id: "fred",
        name: "FRED (세인트루이스 연준)",
        form: "CSV 내려받기 · 키 없음",
        data: "금리·물가·고용 등 매크로 시계열",
        cadence: "매크로 화면 요청 때(1시간 캐시)",
        store: "cache",
        storeDetail: "캐시만",
        origin: "fred.stlouisfed.org",
        statusKeys: [],
      },
      {
        id: "krx",
        name: "KRX 정보데이터시스템",
        form: "REST · 로그인 세션",
        data: "ETF 목록·구성종목·상장일 거래·개인 순매수",
        cadence: "하루 1회(상장일은 16:00 뒤 한 번 더)",
        store: "cache",
        storeDetail: "메모리 캐시만",
        origin: "data.krx.co.kr",
        statusKeys: ["etf_krx"],
      },
      {
        id: "dart",
        name: "OpenDART",
        form: "REST · 공시 원문 XML",
        data: "상장 예정 ETF 공시",
        cadence: "KRX 수집 성공 뒤 하루 1회",
        store: "cache",
        storeDetail: "메모리 캐시만",
        origin: "opendart.fss.or.kr",
        statusKeys: ["etf_dart"],
      },
    ],
  },
  {
    id: "media",
    title: "뉴스 · 영상 · 요약",
    hint: "읽을거리",
    cards: [
      {
        id: "google-news",
        name: "구글 뉴스 RSS",
        form: "RSS · 키 없음",
        data: "보유 종목·시장 토픽 뉴스",
        cadence: "뉴스 화면 요청 때(30분 캐시)",
        store: "cache",
        storeDetail: "캐시만 · 개인 비상업 용도",
        origin: "news.google.com",
        statusKeys: [],
      },
      {
        id: "plaud",
        name: "Plaud 녹음",
        form: "MCP (@plaud-ai/mcp)",
        data: "최근 14일 영상 녹음 목록·전사문·AI 요약",
        cadence: "매일 07:40 이후 · '지금 확인' 버튼",
        store: "db",
        storeDetail: "video_digests",
        origin: "Plaud 클라우드",
        statusKeys: ["plaud_video"],
      },
      {
        id: "claude",
        name: "Claude (claude -p)",
        form: "CLI",
        data: "관전포인트 · 보도자료 구조화 · 결과 판정 · 영상 요약",
        cadence: "실적 일정에 맞춰 · 하루 상한 40회",
        store: "db",
        storeDetail: "earnings_watchpoints · earnings_guidance · video_digests",
        origin: "로컬 Claude Code",
        statusKeys: ["claude"],
      },
    ],
  },
  {
    id: "ai",
    title: "AI 산업 지표",
    hint: "AI 수요의 대리 지표",
    cards: [
      {
        id: "ai-live",
        name: "AI 사용량 소스 5곳",
        form: "REST · ZIP/CSV",
        data: "npm 다운로드 · Ramp 도입률 · OpenRouter 토큰 순위 · 툴콜 토큰 · Epoch 칩·데이터센터",
        cadence: "AI 화면 요청 때(6시간 캐시)",
        store: "cache",
        storeDetail: "캐시만(마지막 정상값 유지)",
        origin: "npmjs · ramp · openrouter · epoch.ai",
        statusKeys: ["ai_npm", "ai_ramp", "ai_openrouter", "ai_tool_calling", "ai_epoch"],
      },
      {
        id: "ai-snapshot",
        name: "AI 개발도구 일별 스냅샷",
        form: "REST",
        data: "VS Code 확장 설치 누적 · PyPI 패키지 다운로드",
        cadence: "하루 1회",
        store: "db",
        storeDetail: "ai_metric_snapshot",
        origin: "marketplace.visualstudio.com · pypistats.org",
        statusKeys: ["ai_vscode", "ai_pypi"],
      },
    ],
  },
];
