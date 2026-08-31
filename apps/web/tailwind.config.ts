import type { Config } from "tailwindcss";

// GE 하우스 스타일 (S:\GE\_Team\07_회의자료\기타\GE_template.md).
// 하나의 블루 계열만 구조색으로 쓰고, 그레이 캔버스 위 흰색 카드 + 헤어라인으로 구획한다.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 서피스
        canvas: "#ffffff", // 흰색 카드/패널
        "canvas-soft": "#f4f6f9", // 페이지 캔버스 (page-bg)
        // 텍스트
        ink: "#3a4150", // 기본 본문
        "ink-secondary": "#5a6573",
        "ink-muted": "#8a94a6", // 보조 (sub)
        "ink-faint": "#9aa3b0", // 더 연한 보조 (sub-2)
        hairline: "#dde2e8", // 테두리·구분선 (line)
        // 구조색 — 블루 한 계열
        primary: "#4a7ab5", // 포인트 블루 — 액션·강조·액티브
        "primary-active": "#3a6199",
        // GE 브랜드 토큰
        "ge-main": "#6390bf", // 메인 블루 (헤더/브랜드)
        "ge-point": "#4a7ab5", // 포인트 블루
        "ge-navy": "#243b5e", // 딥 네이비 (제목/딥 배경)
        "ge-blue-bg": "#e7f0fb", // 연블루 강조 배경
        "ge-today": "#f0f6ff",
        "ge-th": "#eef2f7", // 표 헤더 배경
        // 카드 제목 띠 — 사용자 지정 대시보드 메인 색(2026-08-28). 다크 브라운이라
        // 블루 한 계열인 나머지 브랜드색과 충돌하지 않는다. 글자는 흰색 계열로.
        // ⚠️차트 계열색으로는 쓰지 말 것(명도가 낮아 축·격자와 구분이 약하다).
        "ge-header": "#483629",
        "ge-line-soft": "#d2d8e0",
        // 상태색 (감성형)
        "status-success": "#27ae60",
        "status-running": "#4a7ab5",
        "status-failed": "#e74c3c",
        // 호가창 — 구 뷰어 semantics(매도=시안/매수=레드)의 GE 라이트 번역
        ask: "#0a9bc4",
        "ask-soft": "#e6f4f9",
        bid: "#e74c3c",
        "bid-soft": "#fdefec",
      },
      borderRadius: {
        sm: "6px",
        md: "9px",
        lg: "12px",
        xl: "14px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(36, 59, 94, 0.05)",
        panel: "0 8px 30px rgba(80, 110, 170, 0.10)",
      },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "Malgun Gothic",
          "Apple SD Gothic Neo",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
