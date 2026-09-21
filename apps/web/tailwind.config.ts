import type { Config } from "tailwindcss";

// 한국투자신탁운용 브랜드 가이드 (design_template.md §6 색상 / §7 표 / §8 그래프).
//
// ★2026-09-21 사용자 지시로 이 문서를 대시보드의 기본 UI 형태로 삼는다.
//   이전 토큰은 블루 한 계열(#4a7ab5·#243b5e 등)을 임의로 쓰고 있었는데, 가이드
//   팔레트에 없는 값들이었다. **클래스 이름은 그대로 두고 값만 교체**해 모든 화면이
//   한 번에 맞춰지게 한다(이름까지 바꾸면 수십 파일을 동시에 고쳐야 하고, 그 과정에서
//   빠뜨린 곳이 옛 색으로 남는다).
//
// 팔레트(가이드 §6) — 이 밖의 색은 쓰지 않는다:
//   BROWN #4C2C19(메인) · 포인트 #7B401F · BLUE #6390BF(보조) · LightBlue #BEDBE8
//   Black #000000 · DarkGray #595959 · Gray #7F7F7F · LightGray #F2F2F2 · White
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── 가이드 팔레트 원색 ────────────────────────────────────────────
        brand: "#4C2C19", // BROWN — 메인 브랜드
        "brand-point": "#7B401F", // 소제목 포인트
        "brand-blue": "#6390BF", // BLUE — 보조
        "brand-blue-soft": "#BEDBE8", // Light Blue — 강조 배경

        // ── 서피스 ────────────────────────────────────────────────────────
        canvas: "#FFFFFF",
        "canvas-soft": "#F2F2F2", // Light Gray — 페이지 배경

        // ── 텍스트 (가이드 §5.2) ──────────────────────────────────────────
        ink: "#000000", // 제목·본문
        "ink-secondary": "#595959", // Dark Gray — 표 본문
        "ink-muted": "#7F7F7F", // Gray — 보조·캡션
        "ink-faint": "#7F7F7F", // 가이드에 더 옅은 단계가 없다 — Gray 로 통일
        hairline: "#F2F2F2", // 표·카드 구분선

        // ── 별칭(기존 클래스 유지, 값만 브랜드로) ─────────────────────────
        primary: "#4C2C19",
        "primary-active": "#7B401F",
        "ge-main": "#6390BF", // 헤더 그라데이션 — 가이드 BLUE
        "ge-point": "#4C2C19", // 액션·강조 → 메인 브라운
        "ge-navy": "#000000", // 제목 → Black
        "ge-blue-bg": "#BEDBE8", // 강조 배경 → Light Blue
        "ge-today": "#F2F2F2",
        "ge-th": "#F2F2F2", // 표 헤더 배경 → Light Gray
        "ge-header": "#4C2C19", // 카드 제목 띠 → 메인 브라운(가이드 정확값)
        "ge-line-soft": "#F2F2F2",

        // ── 상태색 ────────────────────────────────────────────────────────
        // ⚠️가이드에 상태색 규정이 없다. 손익 표시는 국내 관행(상승=적/하락=청)이
        //   필수라 유지하되, 브랜드와 충돌하지 않게 채도를 낮춘다.
        "status-success": "#4C2C19",
        "status-running": "#6390BF",
        "status-failed": "#A33A2A",
        ask: "#3A6B96", // 하락·매도 — BLUE 계열 다크
        "ask-soft": "#EAF1F6",
        bid: "#A33A2A", // 상승·매수 — BROWN 계열 레드
        "bid-soft": "#F6EDEA",
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
