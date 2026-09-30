"""계절성 대상 시계열 — 원본 `Downloads/계절성` 의 이름을 그대로 쓴다.

(key, 표시이름, 묶음, 블룸버그 티커, Yahoo 심볼, 이어붙이기)

Yahoo 심볼은 2026-09 부터 이어 붙일 원천이다(실측, 계획 §검증 로그):
  - 섹터 지수(S5xxxx)는 Yahoo 에 이력이 없어 **SPDR 섹터 ETF** 로 잇는다.
  - CSI300 은 Yahoo 에 이력이 없어 **ASHR**(CSI300 추종, 달러) 로 잇는다 → 'proxy'.
  - 창업판(ChiNext)은 대신할 원천이 없어 2026-08 에서 **동결** → 'frozen'(사용자 결정).
  - IT(XLK)·COMM(XLC)·COND(XLY)도 **동결**(2026-09-26 사용자 결정 7). 대용 ETF 가 대형주 비중 상한
    때문에 지수와 구조적으로 달랐다 — 겹침 12개월 월수익률 차이 평균/최대 %p:
    XLC 3.46/13.33 · XLK 1.55/4.51 · XLY 1.22/3.12 (나머지 SPDR 0.13~0.65/0.26~1.63).
"""

SERIES = [
    # ── 지수 8 ────────────────────────────────────────────────────────────
    ("SPX", "S&P 500", "index", "SPX Index", "^GSPC", "direct"),
    ("CCMP", "나스닥 종합", "index", "CCMP Index", "^IXIC", "direct"),
    ("RTY", "러셀 2000", "index", "RTY Index", "^RUT", "direct"),
    ("KOSPI", "코스피", "index", "KOSPI Index", "^KS11", "direct"),
    ("KOSDAQ", "코스닥", "index", "KOSDAQ Index", "^KQ11", "direct"),
    ("CSI300", "CSI 300", "index", "SHSZ300 Index", "ASHR", "proxy"),
    ("ChiNext", "창업판", "index", "SZ399006 Index", None, "frozen"),
    ("HSI", "항셍", "index", "HSI Index", "^HSI", "direct"),
    # ── 섹터 11 ───────────────────────────────────────────────────────────
    ("SOX", "필라델피아 반도체", "sector", "SOX Index", "^SOX", "direct"),
    ("IT", "IT", "sector", "S5INFT Index", None, "frozen"),
    ("COMM", "커뮤니케이션", "sector", "S5TELS Index", None, "frozen"),
    ("ENRS", "에너지", "sector", "S5ENRS Index", "XLE", "proxy"),
    ("UTIL", "유틸리티", "sector", "S5UTIL Index", "XLU", "proxy"),
    ("HLTH", "헬스케어", "sector", "S5HLTH Index", "XLV", "proxy"),
    ("FINL", "금융", "sector", "S5FINL Index", "XLF", "proxy"),
    ("COND", "경기소비재", "sector", "S5COND Index", None, "frozen"),
    ("CONS", "필수소비재", "sector", "S5CONS Index", "XLP", "proxy"),
    ("INDU", "산업재", "sector", "S5INDU Index", "XLI", "proxy"),
    ("MATR", "소재", "sector", "S5MATR Index", "XLB", "proxy"),
]
