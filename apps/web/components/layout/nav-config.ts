import {
  BookOpen,
  LineChart,
  Newspaper,
  Receipt,
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
//   으로 뒤집었다. 디자인(플라이아웃·색·라운드)은 원본 그대로 둔다.
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
//   · 종토방(/stock-discussion) · AI token usage(/ai-token-usage)
//   둘 다 원본 GE 팀의 **LAN 장비**(192.168.199.120:8002, collector:8100)를
//   본다. 이 환경에서 실측하면 연결 자체가 안 된다(curl 000). 켜질 수 없는
//   메뉴를 남겨 두면 계속 "언젠가 되겠지"로 읽히고, 그 사이 메뉴가 거짓말을
//   한다. 장비가 생기면 이 두 줄을 되살리면 된다 — 화면 코드는 그대로 있다.
// ─────────────────────────────────────────────────────────────────────────────

export type NavStatus = "live" | "placeholder" | "planned";

export type NavChild = {
  label: string;
  href?: string;
  status?: NavStatus;
  /** 플라이아웃에서 항목 아래 한 줄로 붙는 설명. 없으면 라벨만. */
  hint?: string;
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
        hint: "종목별 수량 · 평단 · 손익",
      },
      {
        label: "편입비",
        href: "/portfolio/inclusion",
        status: "live",
        hint: "비중 변화 · 신규 편입 · 청산",
      },
      {
        label: "섹터/자산 배분",
        href: "/portfolio/allocation",
        status: "live",
        hint: "섹터 · 자산군 · 통화 비중",
      },
      {
        // ★알림이 "비중 초과"를 잡아 주는데 **그래서 몇 주를 팔아야 하나**에
        //   답하는 자리가 없었다. 그 자리를 만든다.
        label: "리밸런싱",
        href: "/portfolio/rebalance",
        status: "live",
        hint: "목표 비중 대비 — 몇 주를 사고팔아야 하나",
      },
      {
        label: "환노출",
        href: "/portfolio/fx",
        status: "live",
        hint: "USD/KRW 노출 · 환차손익 · 민감도",
      },
    ],
  },
  {
    // ★2026-09-22 사용자 지정: 현금흐름을 따로 두지 않고 **매매와 한 묶음**으로
    //   본다. 사고파는 일과 돈이 들고 나는 일은 같은 이야기라, 메뉴가 갈려
    //   있으면 "그래서 얼마 벌었나"를 두 군데서 맞춰 봐야 했다.
    label: "매매/현금흐름",
    icon: Receipt,
    children: [
      {
        // ★체결 내역과 실현손익을 **한 화면으로 합쳤다.** 따로 두면 "무엇을
        //   팔았나"와 "그래서 얼마 벌었나"가 갈려 매번 두 화면을 오가야 했다.
        label: "체결·실현손익",
        href: "/trading/realized",
        status: "live",
        hint: "종목 수익 · 배당 · 수수료 · 세금으로 분해",
      },
      {
        label: "매매일지",
        href: "/trading/journal",
        status: "live",
        hint: "진입 근거 · 복기 — 계획 대비 결과까지",
      },
      {
        label: "배당 이력",
        href: "/income/dividends",
        status: "live",
        // ⚠️'캘린더'가 아니다 — 키움은 **받은 배당**만 준다(예상·배당락 없음).
        hint: "수령한 배당 · 월별 · 종목별",
      },
      {
        label: "입출금",
        href: "/income/transfers",
        status: "live",
        hint: "납입 · 인출 이력",
      },
      {
        label: "월별 현금흐름",
        href: "/income/monthly",
        status: "live",
        hint: "배당 − 비용 · 순납입 · 매매 회전",
      },
      {
        label: "수수료/세금",
        href: "/trading/costs",
        status: "live",
        hint: "거래비용 · 비용률 · 종목별",
      },
      {
        label: "세금",
        href: "/income/tax",
        status: "live",
        hint: "해외주식 양도소득 · 배당소득 (추정)",
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
        hint: "S&P 500 · 반도체(SOX) 대비 — 원화 환산",
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
        hint: "월·분기·연도별 — 무슨 일이 있었나",
      },
    ],
  },
  {
    // 원본에서 살아남은 층위 — 실제 데이터가 붙어 있는 화면이 가장 많다.
    label: "시장 모니터링",
    icon: TrendingUp,
    children: [
      {
        label: "관심종목",
        href: "/watchlist",
        status: "live",
        hint: "실시간 시세 · 목표가 · 52주 위치",
      },
      {
        label: "시장 지표",
        href: "/market",
        status: "live",
        hint: "지수 · 금리 · 환율 · 원자재 · 크립토",
      },
      { label: "매크로", href: "/macro", status: "live", hint: "물가 · 고용 · 금리 · 성장 (FRED)" },
      {
        label: "AI Key Data",
        href: "/ai-key-data",
        status: "live",
        hint: "AI 가속기 · SDK 채택 (Epoch AI · npm)",
      },
    ],
  },
  {
    // ★2026-09-21 사용자 요청으로 "종목 리서치" → "리서치"로 넓혔다.
    //   보유 종목을 감시하는 것과 **무엇을 살지 공부하는 것**은 다른 활동인데,
    //   원래 IA 에는 후자의 자리가 없었다. 반도체·AI 학습이 당장의 목표다.
    label: "리서치",
    icon: BookOpen,
    href: "/research",
    children: [
      {
        label: "리서치 라이브러리",
        href: "/research",
        status: "placeholder",
        hint: "보유 자료 인덱스 (05_리서치)",
      },
      {
        label: "종목 리서치",
        href: "/research/stocks",
        status: "placeholder",
        hint: "종목별 노트 · 투자 아이디어",
      },
      {
        label: "산업 리서치",
        href: "/research/industry",
        status: "placeholder",
        hint: "반도체 · AI · 2차전지",
      },
      {
        label: "영상 분석",
        href: "/research/video",
        status: "placeholder",
        hint: "YouTube 자막 수집 · 요약",
      },
      {
        label: "학습 노트",
        href: "/research/notes",
        status: "placeholder",
        hint: "반도체 · AI 개념 정리",
      },
      { label: "미국 어닝/이슈", href: "/stock/us", status: "live" },
      {
        label: "공시",
        href: "/research/filings",
        status: "live",
        // DART 는 넣지 않았다 — 보유 17종목이 전부 미국 주식이라 대상이 없다.
        hint: "보유 종목 SEC 공시 · 8-K 항목별",
      },
    ],
  },
  {
    label: "뉴스",
    icon: Newspaper,
    children: [
      { label: "텔레그램", href: "/telegram-news", status: "placeholder",
        hint: "collector 필요 — 현재 미가동",
      },
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
        hint: "내 포지션에 걸린 일 — 제목에 언급된 기사만",
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
        hint: "조건 판정 — 전달은 아직 없음",
      },
    ],
  },
];
