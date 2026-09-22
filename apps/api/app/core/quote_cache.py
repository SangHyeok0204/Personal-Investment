"""보유 종목 시세 — 시세 소스 조립 + 짧은 TTL 캐시.

★왜 서버에 캐시를 두나(2026-09-22):
  화면이 5초마다 `/portfolio/quotes` 를 부른다. 탭을 두 개 열거나 새로고침을
  연타하면 그만큼 야후 호출이 배로 늘어난다. TTL 안에서는 같은 결과를 돌려주어
  **상류 호출 수를 화면 수와 무관하게** 묶는다.

  TTL 은 화면 주기(5초)보다 **살짝 짧게** 둔다. 같게 두면 매번 만료 직전에 걸려
  캐시가 사실상 동작하지 않거나, 반대로 한 주기를 통째로 건너뛴다.

⚠️캐시는 프로세스 메모리다. uvicorn 워커가 여럿이면 워커마다 따로 채워진다.
  지금은 단일 프로세스라 문제가 없고, 늘릴 때는 Redis 로 옮겨야 한다.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

# worker 패키지(brokers/, prices/)를 재사용한다 — API 가 같은 계약을 두 번 쓰지 않는다.
_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from app.core import credentials_store  # noqa: E402
from prices import CompositePriceSource, Quote, YahooPriceSource  # noqa: E402
from prices.toss import TossPriceSource  # noqa: E402

TTL_SECONDS = 4.0

# 52주 고저는 하루에 한 번 바뀔까 말까 한 값이다. 가격과 **같은 주기로 받을 이유가
# 없어서** 따로, 훨씬 길게 캐시한다.
# ⚠️토스 일봉 응답에는 52주 범위가 없다. 정규장 중에는 토스가 주 소스라, 이걸
#   가격과 묶어 두면 장중 내내 "52주 위치 —" 가 된다(실제로 그렇게 나왔다).
#   그래서 범위만 야후에서 따로 받아 붙인다.
RANGE_TTL_SECONDS = 3600.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, Quote]] = {}
# 심볼 → (저장시각, 52주저점, 52주고점). 저점/고점이 None 이어도 캐시한다 —
# 못 받는 심볼을 매번 다시 묻지 않기 위해서다.
_range_cache: dict[str, tuple[float, Decimal | None, Decimal | None]] = {}


def us_regular_session_open(now: datetime | None = None) -> bool:
    """미국 정규장(평일 09:30~16:00 ET)이 열려 있나.

    공휴일은 보지 않는다 — 휴장일이면 두 소스 다 같은 전일 종가를 주므로
    순서를 어떻게 잡든 결과가 같다.
    """
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def us_session_finished_for(trade_date, now: datetime | None = None) -> bool:
    """그 거래일의 미국 정규장이 **이미 끝났나.**

    ⚠️한국 데이마켓 시간표를 **하드코딩하지 않는다.** 처음엔 09:00~16:50 으로
      박아 뒀는데 실측에서 틀렸다 — 17:53 KST 에도 봉이 자라고 있었다
      (SOXL 거래량 614,032 → 1,355,817). 브로커·ATS 마다 다르고 바뀐다.

    ★대신 토스가 주는 **봉 날짜**로 판단한다. 시간표가 필요 없다:
        · 봉 날짜 < 오늘(ET)            → 끝난 세션이다
        · 봉 날짜 == 오늘(ET), 16:00 ET 이후 → 끝난 세션이다
        · 그 외                          → 아직 정규장을 거치지 않은 봉이다
      주말·공휴일은 저절로 처리된다 — 그런 날엔 새 봉이 생기지 않는다.
    """
    if trade_date is None:
        return True  # 모르면 표시하지 않는다. 없는 경고를 만들지 않는다.
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    if trade_date < et.date():
        return True
    if trade_date > et.date():
        return False
    return et.hour * 60 + et.minute >= 16 * 60


def is_thin_session_quote(quote: Quote, now: datetime | None = None) -> bool:
    """이 시세가 **미국 정규장을 아직 거치지 않은 봉**에서 나왔나.

    ★2026-09-22 실측(KST 17:22 / 17:52 / 17:53, 세 번). 토스 당일 봉이 야후의
      전일 정규장 종가와 갈린다 — 그리고 **방향이 바뀐다**:
          17:22  NVDA +0.05%  SOXL +2.58%   (SOXL 거래량   108,875)
          17:52  NVDA +0.15%  SOXL +3.50%   (          614,032)
          17:53  NVDA -0.26%  SOXL -2.12%   (        1,355,817)
      거래량이 12배로 붙는 동안 괴리가 커졌다 작아졌다 부호까지 뒤집혔다.
      **살아 움직이는 시장이지 잡음이 아니다.** 그래서 값을 버리지 않는다 —
      한국 투자자는 그 가격에 실제로 체결할 수 있다.

    ⚠️다만 **정규장 종가인 척하게 두지 않는다.** 평소에는 순서가 야후를 먼저
      쓰므로 이 상황이 오지 않지만, 야후가 죽으면 사슬이 토스로 넘어가고
      화면은 아무 표시 없이 그 값을 "현재가"로 띄운다.
    """
    if quote.source != "toss":
        return False
    # ⚠️정규장 중에는 토스 봉이 **진행 중인 그 정규장**이다 — 진짜 현재가다.
    #   봉 날짜만 보면 이걸 thin 으로 잡는다(실제로 한 번 그렇게 짰다).
    if us_regular_session_open(now):
        return False
    return not us_session_finished_for(quote.trade_date, now)


def _build_source() -> CompositePriceSource:
    """시세 소스 사슬. **세션에 따라 순서가 바뀐다.**

    두 소스는 미국 정규장 중에는 값이 완전히 같다(2026-09-22 실측, 5종목
    소수점까지 +0.00%). 그래서 순서를 정하는 기준은 정확도가 아니라 **언제
    믿을 수 있는가** 다.

    ★정규장 중에도, 끝난 뒤에도 두 소스는 값이 같았다(2026-09-22 실측: 장중
      5종목 / 마감 후 7종목 전부 0.00% 차이). 둘 다 시간외 체결은 주지 않으므로
      마감 후에는 16:00 ET 종가가 그대로 보인다 — 가격이 안 움직이는 게 정상이다.

    ★단, **한국 데이마켓이 열려 있으면 그 일치가 깨진다**(2026-09-22 실측).
      토스에 당일 봉이 새로 생기고 야후와 갈린다 — SOXL 은 한때 +3.50%,
      한 시간 뒤엔 -2.12% 였다. 그동안 야후 값은 토스의 **전일 봉 종가와
      정확히 같았다**(NVDA 227.38). 즉 정규장이 닫힌 동안의 올바른 "현재가"는
      야후 쪽이고, 지금 순서가 그걸 고른다. `is_thin_session_quote`.

    ⚠️측정 시각을 처음엔 09:02/09:32 KST 로 적었는데 **기계 시계가 8시간 40분
      어긋나 있었다**(구글 HTTP Date 헤더로 확인). 실제로는 17:22/17:52 였다.
      그 잘못된 시각 위에 데이마켓 창을 09:00~16:50 으로 박아 놓았고, 그래서
      정작 데이마켓이 열려 있을 때 표시가 안 되는 코드가 됐다.
      → 시간표를 쓰지 않고 **봉 날짜**로 판단하도록 바꿨다.

    ⚠️토스의 미국 종목 당일 봉은 한국 **데이마켓**(KST 09:00~16:50) 체결을
      포함한다. 미국장이 닫혀 있는 동안 그 값은 거래량이 정규장의 1% 미만인
      얇은 체결가다(DailyPriceAgent 실측: NVDA 371,568주 vs 정규장 9,400만주).
      그걸 "현재가"로 쓰면 하루 등락률이 통째로 틀린다.
      → 정규장 중에는 토스 우선(사용자가 원한 소스), 닫혀 있으면 야후 우선.

    ⚠️토스 키가 없으면 토스를 아예 끼우지 않는다. 키 없이 두면 5초마다 토큰
      발급이 실패해 쓸모없는 왕복만 생긴다.
    ⚠️토스는 **클라이언트당 유효 토큰 1개**다. 같은 키를 쓰는 DailyPriceAgent 가
      돌면 서로 토큰을 무효화한다. 그때는 토스가 통째로 실패하고 사슬이 야후로
      넘어간다 — 화면은 비지 않는다.
    """
    yahoo = YahooPriceSource()
    # ⚠️os.environ 만 보면 안 된다 — 이 앱의 Settings 는 .env 를 로드하지 않고,
    #   load_into_environ 은 KIWOOM_* 만 올린다. 파일도 같이 본다.
    client_id = credentials_store.read_env_value("TOSS_CLIENT_ID")
    client_secret = credentials_store.read_env_value("TOSS_CLIENT_SECRET")
    if not (client_id and client_secret):
        return CompositePriceSource([yahoo])

    toss = TossPriceSource(client_id, client_secret)
    order = [toss, yahoo] if us_regular_session_open() else [yahoo, toss]
    return CompositePriceSource(order)


def _fill_52w(quotes: dict[str, Quote]) -> dict[str, Quote]:
    """주 소스가 52주 범위를 안 주면 야후에서 따로 받아 붙인다.

    가격과 다른 주기(1시간)로 캐시한다 — 52주 고저는 초 단위로 움직이지 않는다.
    """
    now = time.monotonic()
    need: list[str] = []
    for symbol, quote in quotes.items():
        if quote.fifty_two_week_high is not None:
            continue  # 주 소스가 이미 줬다(야후가 1순위였던 경우).
        hit = _range_cache.get(symbol)
        if hit is None or now - hit[0] >= RANGE_TTL_SECONDS:
            need.append(symbol)

    if need:
        source = YahooPriceSource()
        try:
            fetched = source.quotes(need)
        except Exception:
            fetched = {}
        finally:
            source.close()
        stored = time.monotonic()
        with _lock:
            for symbol in need:
                got = fetched.get(symbol)
                _range_cache[symbol] = (
                    stored,
                    got.fifty_two_week_low if got else None,
                    got.fifty_two_week_high if got else None,
                )

    out: dict[str, Quote] = {}
    for symbol, quote in quotes.items():
        if quote.fifty_two_week_high is not None:
            out[symbol] = quote
            continue
        hit = _range_cache.get(symbol)
        out[symbol] = (
            replace(quote, fifty_two_week_low=hit[1], fifty_two_week_high=hit[2])
            if hit
            else quote
        )
    return out


def get_quotes(
    symbols: list[str], with_range: bool = False
) -> tuple[dict[str, Quote], int]:
    """심볼별 시세와 **상류에서 새로 받아온 개수**.

    캐시가 살아 있는 심볼은 그대로 쓰고, 만료된 것만 묶어서 한 번에 받아온다.

    `with_range` 면 52주 고저까지 채운다. 5초마다 도는 보유종목 경로는 그게
    필요 없어서 기본으로 끈다 — 필요 없는 상류 호출을 만들지 않는다.
    """
    wanted = [s for s in dict.fromkeys(symbols) if s]
    if not wanted:
        return {}, 0

    now = time.monotonic()
    out: dict[str, Quote] = {}
    stale: list[str] = []

    with _lock:
        for symbol in wanted:
            hit = _cache.get(symbol)
            if hit and now - hit[0] < TTL_SECONDS:
                out[symbol] = hit[1]
            else:
                stale.append(symbol)

    if not stale:
        return (_fill_52w(out) if with_range else out), 0

    source = _build_source()
    try:
        fetched = source.quotes(stale)
    finally:
        source.close()

    stored = time.monotonic()
    with _lock:
        for symbol, quote in fetched.items():
            _cache[symbol] = (stored, quote)
    out.update(fetched)
    # ⚠️못 받은 심볼은 out 에 없다. 호출부가 "—" 로 그린다 — 0 으로 채우지 않는다.
    return (_fill_52w(out) if with_range else out), len(fetched)


def clear_cache() -> None:
    """테스트용. 프로덕션 경로에서는 부르지 않는다."""
    with _lock:
        _cache.clear()
        _range_cache.clear()
