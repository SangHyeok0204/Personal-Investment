import {
  BookOpen,
  LineChart,
  Newspaper,
  Settings,
  TrendingUp,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// 개인 투자 대시보드 정보구조(IA).
//
// ★2026-09-21 개조: 원본(GE 팀 대시보드)은 "운용사가 시장·상품을 감시하는" 층위로
//   짜여 있었다. 개인 계좌(키움 API) 기준으로 다시 세우면 1순위는 **내 돈이 지금
//   어떤 상태인가**이고, 시장/리서치는 그 판단을 돕는 보조 층위로 내려간다.
//   그래서 순서를 내 자산 → 매매 → 성과 → 시장 → 리서치 → 뉴스 → 현금흐름 → 연동
//   으로 뒤집었다(2026-10-01 매매/현금흐름은 걷었다 — 아래). 디자인(플라이아웃·색·라운드)은 원본 그대로 둔다.
//
// `href` 가 있으면 실제 라우팅되고, 없으면 아직 화면이 없는 자리(플라이아웃에서
// 비활성 버튼으로 렌더)다. `status` 는 그 자리가 어떤 상태인지 표시한다:
//   - "live"        실제 데이터가 붙어 동작 중
//                   ★2026-09-22 전수 확인: 화면의 useQuery 배선 + 그 API 의 실제
//                     응답코드를 둘 다 본다. 둘 중 하나만 보면 틀린다 — 원본 GE 에서
//                     물려받은 화면 중 여럿이 collector 프록시라 코드는 멀쩡한데
//                     503 이었고(매크로·AI Key Data·텔레그램·미국 어닝),
//                     반대로 실데이터가 붙은 자산현황·보유종목·섹터배분·계좌연동은
//                     placeholder 로 남아 있었다. 메뉴가 양쪽으로 거짓말을 했다.
//   - "placeholder" 화면 골격만 있고 데이터는 더미/미연결
//   - "planned"     화면 자체가 아직 없음(href 없음)
//
// ★2026-09-22 메뉴에서 **뺀 것** (라우트는 남겨 둔다):
//   · 종토방(/stock-discussion) — 원본 GE 팀의 LAN 장비를 본다. 이 환경에서는
//   연결 자체가 안 된다(curl 000). 켜질 수 없는 메뉴는 거짓말이 된다.
// ★2026-09-30 개인 대시보드 범위 정리: 업무 화면(iNAV·WRAP·ETF 분류·LP 평가·
//   트랙레코드·회의·LAN)과 텔레그램·리밸런싱·유튜브 분석·AI token usage 라우트를
//   **삭제**했다(메뉴가 아니라 화면 자체).
// ★2026-10-01 "매매/현금흐름" 그룹(체결·실현손익 /trading/realized · 현금유출입
//   /income/cashflow)을 **화면째 삭제**했다. 쓸모 있던 것은 옮겼다:
//   실현손익 일별 추이·건별 목록 → 자산 현황의 실현손익(누적) 타일 드릴다운,
//   배당 → 내 자산 › 배당(/portfolio/dividends). 서버 API(/realized · /cashflow ·
//   /costs · /monthly-cashflow · /tax)는 정합성 감사 스크립트와 테스트가 쓰므로 남겼다.
// ─────────────────────────────────────────────────────────────────────────────

export type NavStatus = "live" | "placeholder" | "planned";

export type NavChild = {
  label: string;
  href?: string;
  status?: NavStatus;
  /** 플라이아웃에서 항목 아래 한 줄로 붙는 설명. 없으면 라벨만. */
  hint?: string;
  /** 이 경로들에 있을 때도 이 항목이 활성으로 표시된다(정확 일치만, 하위 경로 아님).
   *  ★2026-09-27 계획 S1 — "기타" 허브가 흡수한 화면들(리서치 라이브러리 등)에
   *    있을 때 사이드바에서 "기타"가 켜지도록. */
  match?: string[];
  /** 하위 경로(`{href}/…`)에서도 이 항목을 켠다. 상세 화면이 딸린 허브용(산업 밸류체인). */
  prefix?: boolean;
};

export type NavItem = {
  label: string;
  icon: LucideIcon;
  href?: string;
  children?: NavChild[];
};

export const navItems: NavItem[] = [
  {
    // 대시보드의 1면. 키움 잔고 API 가 붙는 순간 여기부터 실데이터가 된다.
    label: "내 자산",
    icon: Wallet,
    href: "/portfolio",
    children: [
      {
        label: "자산 현황",
        href: "/portfolio",
        status: "live",
        hint: "총평가 · 예수금 · 평가손익",
      },
      {
        label: "보유 종목",
        href: "/portfolio/holdings",
        status: "live",
        // ★2026-09-25 편입비 화면을 여기로 합쳤다(편입비·최초 편입·보유기간 열).
        hint: "종목별 수량 · 평단 · 손익 · 편입비",
      },
      {
        label: "섹터/자산 배분",
        href: "/portfolio/allocation",
        status: "live",
        hint: "섹터 · 자산군 · 통화 비중",
      },
      // ★2026-09-25 환노출 화면은 없앴다 — 보유 종목 표의 환노출 ON/OFF 토글로 옮겼다.
      {
        // ★2026-10-01 "매매/현금흐름" 메뉴를 걷으면서 배당만 여기로 옮겼다. 배당은
        //   **세후(원천징수 후)** 로 저장돼 있다 — 세금을 또 빼지 않는다.
        label: "배당",
        href: "/portfolio/dividends",
        status: "live",
        hint: "지급 건별 · 종목별 · 월별 · 세후",
      },
    ],
  },
  {
    label: "성과 분석",
    icon: LineChart,
    children: [
      {
        label: "수익률 추이",
        href: "/performance/returns",
        status: "live",
        hint: "TWR · MWR 시계열",
      },
      {
        label: "벤치마크 비교",
        href: "/performance/benchmark",
        status: "live",
        hint: "S&P 500 · 반도체(SOX) 대비 · 원화 환산",
      },
      {
        label: "성과 분석",
        href: "/performance/analysis",
        status: "live",
        hint: "위험지표 · 월별 · 종목 기여도",
      },
      {
        label: "기간 리포트",
        href: "/performance/report",
        status: "live",
        // 다른 화면과 겹치지 않는 부분은 **기간을 고른다**는 것이다.
        hint: "월·분기·연도별",
      },
    ],
  },
  {
    // 원본에서 살아남은 층위 — 실제 데이터가 붙어 있는 화면이 가장 많다.
    label: "시장 모니터링",
    icon: TrendingUp,
    children: [
      // ★2026-09-27 계획 S1 — 관심종목·시장 지표·계절성·AI Key Data 는 리서치
      //   그룹의 "시장 리서치"(/research/market, S2) 로 흡수된다. 여기 남기면
      //   같은 화면이 두 메뉴에서 보여 어느 쪽이 정본인지 헷갈린다.
      { label: "매크로", href: "/macro", status: "live", hint: "물가 · 고용 · 금리 · 성장 (FRED)" },
    ],
  },
  {
    // ★2026-09-21 사용자 요청으로 "종목 리서치" → "리서치"로 넓혔다.
    //   보유 종목을 감시하는 것과 **무엇을 살지 공부하는 것**은 다른 활동인데,
    //   원래 IA 에는 후자의 자리가 없었다. 반도체·AI 학습이 당장의 목표다.
    label: "리서치",
    icon: BookOpen,
    // ★2026-09-27 계획 S1 §12-7 — 그룹 첫 화면을 "시장 리서치"로 바꿨다.
    //   리서치 라이브러리는 "기타" 허브로 옮겨 더는 그룹의 얼굴이 아니다.
    href: "/research/market",
    children: [
      {
        // ★2026-09-27 계획 S1 — 관심종목·시장 지표·계절성·AI Key Data 를 탭으로 통합.
        label: "시장 리서치",
        href: "/research/market",
        status: "live",
        hint: "관심종목 · 시장지표 · 계절성 · AI Key Data · 국내 ETF 신규상장",
      },
      {
        // 대분류 → 중분류 → 기업 카드 뷰. 데이터: storage/valuechain/*.ttl.
        label: "산업 밸류체인",
        href: "/research/valuechain",
        // 섹터 상세(/research/valuechain/bio)에서도 이 항목이 켜지게.
        prefix: true,
        status: "live",
        hint: "섹터 허브 → 섹터별 카드 뷰",
      },
      {
        // ★보유·관심 종목별 실적/거장/Form4/공시 보유 현황 패널(현황판)이 붙었다.
        label: "종목 단위 리서치",
        href: "/research/stocks",
        status: "live",
        hint: "보유·관심 종목별 데이터 보유 현황",
      },
      {
        // ★2026-09-27 계획 A5 — 원본 13F기관내부자(collector 프록시)를 API 로 옮겼다.
        label: "거장 포트폴리오(13F)",
        href: "/research/guru",
        status: "live",
        hint: "거장 23명 분기 변동 · 내 보유 × 거장",
      },
      {
        // ★2026-09-27 계획 B — 어닝모니터 이식. B6 에서 `/stock/us` 를 대체한다.
        label: "어닝 콜 / 이슈",
        href: "/research/earnings",
        status: "live",
        hint: "보유·관심종목 발표 · EPS 서프라이즈 · 관전포인트",
      },
      {
        label: "종목 공시",
        href: "/research/filings",
        status: "live",
        // DART 는 넣지 않았다 — 보유 17종목이 전부 미국 주식이라 대상이 없다.
        hint: "보유 종목 SEC 공시 · 8-K 항목별",
      },
      {
        // ★2026-09-27 계획 S1 §12-7 — 그룹 3단계 중첩 대신 허브 페이지로.
        //   여기 흡수된 화면(리서치 라이브러리·산업 리서치·학습 노트·내부자
        //   거래·미국 어닝)에 있을 때도 이 항목이 켜지도록 `match` 를 준다.
        label: "기타",
        href: "/research/etc",
        status: "live",
        hint: "리서치 라이브러리 · 산업 리서치 · 학습 노트 · 내부자 거래 · 미국 어닝(구)",
        match: [
          "/research",
          "/research/industry",
          "/research/notes",
          "/research/insiders",
          "/stock/us",
        ],
      },
    ],
  },
  {
    // ★2026-10-01 Plaud 녹음 · 유튜브 영상 요약이 붙으면서 "뉴스" → "뉴스/영상".
    label: "뉴스/영상",
    icon: Newspaper,
    children: [
      {
        // ★"기사"를 **시장 뉴스**로 바꿨다. 그대로 만들면 보유종목 뉴스와
        //   소스가 같아 거의 같은 화면이 하나 더 생긴다. 주제별로 보면
        //   "내가 아직 안 산 쪽"을 보게 되어 질문이 달라진다.
        label: "시장 뉴스",
        href: "/news/market",
        status: "live",
        hint: "반도체 · AI · 전력 · 금리 · 크립토",
      },
      {
        label: "보유종목 뉴스",
        href: "/news/holdings",
        status: "live",
        hint: "내 포지션에 걸린 일",
      },
      {
        label: "영상 요약",
        href: "/news/video",
        status: "live",
        hint: "Plaud 녹음 · 유튜브 1문단 요약",
      },
    ],
  },
  {
    label: "연동/설정",
    icon: Settings,
    href: "/settings",
    children: [
      {
        label: "계좌 연동",
        href: "/settings/connections",
        status: "live",
        hint: "증권사 계좌 · 시세 소스",
      },
      {
        label: "수집 상태",
        href: "/data-operations",
        status: "live",
        hint: "배치 · 잡 모니터",
      },
      { label: "환경설정", href: "/settings", status: "live" },
      {
        label: "알림",
        href: "/settings/alerts",
        status: "live",
        // ⚠️아직 **보내지 않는다** — 조건을 세우고 판정하는 데까지다.
        hint: "조건 판정 · 전달 없음",
      },
    ],
  },
];
