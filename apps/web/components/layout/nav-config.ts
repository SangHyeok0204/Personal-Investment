import {
  BookOpen,
  LineChart,
  Newspaper,
  PiggyBank,
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
        label: "환노출",
        href: "/portfolio/fx",
        status: "live",
        hint: "USD/KRW 노출 · 환차손익 · 민감도",
      },
    ],
  },
  {
    label: "매매",
    icon: Receipt,
    children: [
      {
        label: "체결 내역",
        href: "/trading/executions",
        status: "live",
        hint: "일자별 매수/매도 체결",
      },
      {
        label: "주문/미체결",
        href: "/trading/orders",
        status: "live",
        hint: "당일 주문 상태",
      },
      {
        label: "실현손익",
        href: "/trading/realized",
        status: "live",
        hint: "종목별 · 기간별 실현 PnL",
      },
      {
        label: "매매일지",
        href: "/trading/journal",
        status: "live",
        hint: "진입 근거 · 복기 — 체결·손익과 함께",
      },
      {
        label: "수수료/세금",
        href: "/trading/costs",
        status: "live",
        hint: "거래비용 · 비용률 · 종목별",
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
      { label: "기간 리포트", status: "planned", hint: "월간 · 분기 요약" },
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
      { label: "공시", status: "planned", hint: "DART · SEC" },
    ],
  },
  {
    label: "뉴스",
    icon: Newspaper,
    children: [
      { label: "텔레그램", href: "/telegram-news", status: "placeholder",
        hint: "collector 필요 — 현재 미가동",
      },
      { label: "종토방", href: "/stock-discussion", status: "live" },
      { label: "기사", status: "planned" },
      { label: "보유종목 뉴스", status: "planned", hint: "내 포지션에 걸린 뉴스만" },
    ],
  },
  {
    label: "현금흐름",
    icon: PiggyBank,
    children: [
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
      { label: "월별 현금흐름", status: "planned" },
      { label: "세금", status: "planned", hint: "양도소득세 · 배당소득세 추정" },
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
      { label: "AI token usage", href: "/ai-token-usage", status: "live" },
      { label: "환경설정", href: "/settings", status: "live" },
      { label: "알림", status: "planned", hint: "가격 · 체결 · 배당 알림" },
    ],
  },
];
