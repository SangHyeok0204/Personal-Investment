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
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

# worker 패키지(brokers/, prices/)를 재사용한다 — API 가 같은 계약을 두 번 쓰지 않는다.
_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from app.core import credentials_store  # noqa: E402
from app.core.market_history import Series, fetch_history  # noqa: E402
from prices import CompositePriceSource, Quote, YahooPriceSource  # noqa: E402
from prices.toss import TossAuthError, TossIpNotAllowed, TossPriceSource  # noqa: E402

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
# 심볼 → (저장시각, 일봉 시계열 | None). 52주 범위와 같은 1시간 주기 — 일 종가는
# 하루에 한 번 바뀐다. None 도 캐시한다(못 받는 심볼을 5초마다 다시 묻지 않는다).
_history_cache: dict[str, tuple[float, Series | None]] = {}

# ★2026-10-04 시장 리서치 표의 5D/20D/60D — **거래일** 기준(달력일이 아니다).
TRADING_DAY_PERIODS: tuple[int, ...] = (5, 20, 60)
# 60거래일 + 기준 1개 = 61개가 필요하다. 3mo 는 휴장이 끼면 모자랄 수 있어 6mo 로 받는다.
_HISTORY_RANGE = "6mo"

# ★2026-10-05: 맥의 공인 IP 가 바뀌어 토스가 토큰 발급을 403(IP 미허용)으로 거부했는데,
#   5초마다(종목 수만큼!) 토큰을 다시 두드리면서 화면은 '토스 사용 중'이라 했다 — 실제
#   시세는 전부 야후였다. 토큰 단계 실패 뒤엔 이 시간 동안 토스를 사슬에서 빼고(야후가
#   대신 준다), 지나면 다시 한 번 시도한다.
TOSS_COOLDOWN_SECONDS = 600.0
# 토스 상태 — 화면(/brokerage/price-sources)이 읽는다. state: None(아직 모름)|ok|ip_blocked|error.
# ⚠️토큰을 새로 받아 확인하지 않는다 — 시세 경로가 실제로 겪은 결과만 적는다.
_toss_status: dict = {"state": None, "message": None, "at": None}
_toss_skip_until = 0.0  # time.monotonic() 기준


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
    # ★토큰 단계에서 막힌 직후면 토스를 끼우지 않는다 — 막힌 동안 5초마다 토큰 엔드포인트를
    #   두드리지 않는다. 쿨다운이 지나면 다시 끼워 한 번 시도한다.
    if toss_in_cooldown():
        return CompositePriceSource([yahoo])

    toss = _shared_toss(client_id, client_secret)
    order = [toss, yahoo] if us_regular_session_open() else [yahoo, toss]
    return CompositePriceSource(order)


class _SharedToss:
    """프로세스에 하나뿐인 토스 소스를 감싼다 — 사슬의 `close()` 가 공유 클라이언트를 닫지 않게,
    동시 요청이 토큰을 두 번 받지 않게(잠금)."""

    name = "toss"

    def __init__(self, inner: TossPriceSource):
        self._inner = inner
        self._lock = threading.Lock()

    def quotes(self, symbols):
        with self._lock:
            return self._inner.quotes(symbols)

    def close(self):
        pass


_toss_shared: tuple[tuple[str, str], _SharedToss] | None = None


def _shared_toss(client_id: str, client_secret: str) -> _SharedToss:
    """★2026-10-05: 예전에는 캐시가 빌 때마다(≈5초) `TossPriceSource` 를 새로 만들어 **토큰도 매번 새로**
    받았다. 토스는 클라이언트당 유효 토큰이 1개라, 같은 키를 쓰는 다른 수집기를 계속 끊는다.
    → 키가 같으면 인스턴스(와 토큰)를 재사용한다. 키를 바꾸면 새로 만든다."""
    global _toss_shared
    key = (client_id, client_secret)
    with _lock:
        if _toss_shared is None or _toss_shared[0] != key:
            if _toss_shared is not None:
                _toss_shared[1]._inner.close()
            _toss_shared = (key, _SharedToss(TossPriceSource(client_id, client_secret)))
        return _toss_shared[1]


def toss_in_cooldown() -> bool:
    return time.monotonic() < _toss_skip_until


def toss_status() -> dict:
    """토스 시세 경로의 마지막 상태(복사본) + 쿨다운 중인지."""
    with _lock:
        out = dict(_toss_status)
    out["cooldown"] = toss_in_cooldown()
    return out


def _note_toss(source: CompositePriceSource, bind) -> None:
    """이번 호출에서 토스가 어떻게 됐는지 적는다. **상태가 바뀔 때만** source_status 에 쓴다.

    ⚠️5초마다 같은 오류를 쓰지 않는다 — 수집 상태 화면엔 '바뀐 순간'만 있으면 된다.
    ⚠️기록 실패가 시세 응답을 바꾸면 안 된다 — 삼킨다. `bind` 가 없으면 메모리 상태만 바꾼다.
    """
    global _toss_skip_until
    if "toss" not in source.attempted:
        return  # 앞 소스(야후)가 다 채워 토스는 불리지 않았다 — 아는 게 없다.
    exc = source.last_errors.get("toss")
    if exc is None:
        state, message = "ok", None
    elif isinstance(exc, TossIpNotAllowed):
        state, message = "ip_blocked", str(exc)
    else:
        state, message = "error", f"{type(exc).__name__}: {exc}"[:500]
    with _lock:
        if isinstance(exc, TossAuthError):
            _toss_skip_until = time.monotonic() + TOSS_COOLDOWN_SECONDS
        changed = _toss_status["state"] != state
        if changed or state != "ok":
            _toss_status.update(
                state=state, message=message,
                at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
    if not changed or bind is None:
        return
    try:
        from source_health import record_error, record_ok

        if state == "ok":
            record_ok(bind, "toss")
        else:
            # IP 미허용은 'config'(설정 필요) — 키움 8050 과 같은 분류.
            record_error(bind, "toss", "config" if state == "ip_blocked" else "other", message or "")
    except Exception:  # noqa: BLE001
        pass


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


def _probe_toss_if_stuck(symbol: str, bind) -> None:
    """토스가 막혀 있다고 기억하는데 이번 호출에서 불리지 않았으면(장 마감 중엔 야후가 먼저라 토스를 안 부른다)
    쿨다운이 지난 뒤 **한 종목만** 물어 상태를 고친다. 값은 쓰지 않는다(장 마감 중 토스 값은 얇은 체결가).

    ★2026-10-07: 사용자가 IP 를 등록했는데 연동 화면은 다음 정규장(22:30)까지 'IP 미허용'으로 남았다.
    ⚠️'ok' 가 아닐 때만(막힘·오류·재시작 직후 모름), 쿨다운(10분)마다 한 번 — 'ok' 가 되면 멈춘다.
      모름(None)도 넣는 이유: 재시작하면 메모리 상태가 비어 수집 상태의 옛 'IP 미허용' 줄을 아무도 고치지 않는다.
    """
    if _toss_status["state"] == "ok" or toss_in_cooldown():
        return
    client_id = credentials_store.read_env_value("TOSS_CLIENT_ID")
    client_secret = credentials_store.read_env_value("TOSS_CLIENT_SECRET")
    if not (client_id and client_secret):
        return
    probe = CompositePriceSource([_shared_toss(client_id, client_secret)])
    try:
        probe.quotes([symbol])
        _note_toss(probe, bind)
    except Exception:  # noqa: BLE001 — 상태 확인일 뿐, 시세 응답을 바꾸지 않는다
        pass


def get_quotes(
    symbols: list[str], with_range: bool = False, bind=None
) -> tuple[dict[str, Quote], int]:
    """심볼별 시세와 **상류에서 새로 받아온 개수**.

    캐시가 살아 있는 심볼은 그대로 쓰고, 만료된 것만 묶어서 한 번에 받아온다.

    `with_range` 면 52주 고저까지 채운다. 5초마다 도는 보유종목 경로는 그게
    필요 없어서 기본으로 끈다 — 필요 없는 상류 호출을 만들지 않는다.

    `bind` — 토스 상태가 바뀌면 source_status 에 적을 연결(요청 세션의 `db.get_bind()`).
    ⚠️모듈 전역 engine 을 쓰지 않는다 — 테스트(get_db 오버라이드)가 실제 DB 에 쓰지 않게.
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
        _note_toss(source, bind)
    finally:
        source.close()
    _probe_toss_if_stuck(stale[0], bind)

    stored = time.monotonic()
    with _lock:
        for symbol, quote in fetched.items():
            _cache[symbol] = (stored, quote)
    out.update(fetched)
    # ⚠️못 받은 심볼은 out 에 없다. 호출부가 "—" 로 그린다 — 0 으로 채우지 않는다.
    return (_fill_52w(out) if with_range else out), len(fetched)


def trading_day_changes(
    closes: list[Decimal], periods: tuple[int, ...] = TRADING_DAY_PERIODS
) -> dict[int, Decimal | None]:
    """마지막 종가 vs N거래일 전 종가의 변화율(비율). `closes` 는 오름차순·완결 봉만.

    ★N거래일 전 = `closes[-1 - N]`. 5D 면 닫힌 봉 6개가 필요하다.
    ⚠️모자라면 None 이다 — 있는 만큼으로 줄여 계산하면 기간이 통째로 틀린 값이 된다.
    ⚠️기준 종가가 0 이하면 None(나눗셈이 의미가 없다).
    """
    out: dict[int, Decimal | None] = {}
    for n in periods:
        if len(closes) < n + 1 or closes[-1 - n] <= 0:
            out[n] = None
        else:
            out[n] = closes[-1] / closes[-1 - n] - 1
    return out


def _completed_closes(series: Series, now: datetime | None = None) -> list[Decimal]:
    """진행 중인 오늘 봉을 걷어낸 **완결 일봉 종가**.

    ★5D/20D/60D 는 마지막 **완결** 일 종가 기준이다(2026-10-04 사용자 지정).
      장중에는 야후 일봉 마지막 칸이 '지금 가격'이라, 그대로 쓰면 값이 5초마다
      흔들리고 1시간 캐시와도 어긋난다. 당일 등락은 옆 칸(실시간)이 맡는다.
    ⚠️KRW(한국)는 15:30 KST 마감, 그 외는 미국 정규장(`us_session_finished_for`)으로 본다.
    """
    if not series.dates:
        return []
    last = series.dates[-1]
    if series.currency == "KRW":
        kst = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Seoul"))
        done = last < kst.date() or (
            last == kst.date() and kst.hour * 60 + kst.minute >= 15 * 60 + 30
        )
    else:
        done = us_session_finished_for(last, now)
    return list(series.closes if done else series.closes[:-1])


def get_trading_changes(
    symbols: list[str], now: datetime | None = None
) -> dict[str, dict[int, Decimal | None]]:
    """심볼별 5D/20D/60D 변화율. 시계열을 못 받은 심볼은 값이 전부 None.

    일봉 시계열은 `RANGE_TTL_SECONDS`(1시간) 캐시한다 — 5초 폴링마다 60일치를
    다시 받지 않는다. 완결 봉 판정은 매 호출 다시 한다(캐시 중 장이 닫혀도 맞게).
    """
    wanted = [s for s in dict.fromkeys(symbols) if s]
    if not wanted:
        return {}
    series_by = _cached_history(wanted)
    out: dict[str, dict[int, Decimal | None]] = {}
    for symbol in wanted:
        series = series_by.get(symbol)
        closes = _completed_closes(series, now) if series else []
        out[symbol] = trading_day_changes(closes)
    return out


def _cached_history(wanted: list[str]) -> dict[str, Series | None]:
    """심볼별 일봉 시계열(`RANGE_TTL_SECONDS` 캐시). 못 받으면 None — 예외를 내지 않는다."""
    mono = time.monotonic()
    with _lock:
        need = [
            s
            for s in wanted
            if (hit := _history_cache.get(s)) is None
            or mono - hit[0] >= RANGE_TTL_SECONDS
        ]
    if need:
        try:
            fetched = fetch_history(need, range_=_HISTORY_RANGE)
        except Exception:
            fetched = {}
        stored = time.monotonic()
        with _lock:
            for symbol in need:
                _history_cache[symbol] = (stored, fetched.get(symbol))
    with _lock:
        return {s: (hit[1] if (hit := _history_cache.get(s)) else None) for s in wanted}


def us_session_dates(now: datetime | None = None) -> list[date] | None:
    """**끝난** 미국 정규장 날짜(ET) 오름차순 — ^GSPC 일봉에서 읽는다. 못 받으면 None.

    ★공휴일 파일을 두지 않는다(2026-10-04) — 지수에 봉이 있으면 장이 열린 날이다.
      진행 중인 오늘 봉은 뺀다(`us_session_finished_for`). 열려 있는지는
      `us_regular_session_open` 이 따로 본다.
    """
    series = _cached_history(["^GSPC"]).get("^GSPC")
    if series is None or not series.dates:
        return None
    return [d for d in series.dates if us_session_finished_for(d, now)]


def clear_cache() -> None:
    """테스트용. 프로덕션 경로에서는 부르지 않는다."""
    global _toss_skip_until, _toss_shared
    with _lock:
        _toss_shared = None
        _cache.clear()
        _range_cache.clear()
        _history_cache.clear()
        _toss_status.update(state=None, message=None, at=None)
        _toss_skip_until = 0.0
