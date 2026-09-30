/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  eslint: { ignoreDuringBuilds: true },
  // ★2026-09-21: dev 서버와 프로덕션 빌드가 같은 `.next` 를 쓰면, 개발 중에
  //   `npm run build` 를 돌리는 순간 dev 서버가 읽던 매니페스트가 덮여
  //   "Could not find the module ... in the React Client Manifest" 와 함께
  //   **CSS 가 통째로 빠진 화면**이 뜬다(개조 중 세 번 당했다).
  //   NEXT_DIST_DIR 로 출력 폴더를 갈라 두면 둘이 동시에 돌아도 충돌하지 않는다.
  //   예) 빌드 검증: NEXT_DIST_DIR=.next-build npm run build
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  // ★2026-09-27 계획 S2: 관심종목·시장 지표·계절성·AI Key Data 가 시장 리서치
  //   탭으로 합쳐졌다. 옛 주소(북마크)는 해당 탭으로 보낸다.
  //   ⚠️검증이 끝날 때까지는 permanent: false(307) — 브라우저가 캐시하지 않게.
  async redirects() {
    return [
      { source: "/watchlist", destination: "/research/market?tab=watchlist", permanent: false },
      { source: "/market", destination: "/research/market?tab=market", permanent: false },
      { source: "/market/seasonality", destination: "/research/market?tab=seasonality", permanent: false },
      { source: "/ai-key-data", destination: "/research/market?tab=ai", permanent: false },
    ];
  },
};

export default nextConfig;
