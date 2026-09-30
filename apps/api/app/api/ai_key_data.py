"""[AI Key Data] — AI 밸류체인 지표 카드 프록시 (2026-08-28).

collector 가 `input/raw` 마운트(:ro)에서 CSV·zip 을 직독해 만든 payload 를 그대로 나른다.
계산은 전부 collector 쪽이다 — 여기는 ETag 통과와 503 격리만 한다.

⚠️**동거 상태**: 같은 [AI Key Data] 페이지의 기존 카드 셋(`compute-index` · `policy-rate` ·
  `rate-topics`)은 아직 `/api/v1/stock-monitor` 밑에 있다. 역사적 표류(컴퓨팅 지수가 종목
  모니터에서 이 탭으로 이사했다)인데, 같이 옮기면 `lib/api.ts` 3곳과 컴포넌트 4개를
  동시에 고치는 breaking rename 이 되고 이번 기능과 무관한 회귀 위험이 생긴다.
  → 경로는 그대로 두고 **핸들러만** 이 파일 아래쪽 `legacy_router` 로 모아 뒀다
  ([종목 모니터] 화면 철거, 2026-09-23 — 그 화면의 `stock_monitor.py` 는 없어졌다).
  경로 이전은 여전히 별도 작업이다(ws2 설계 §2.3).

★`_proxy_collector` 는 `inav` 에서 가져다 쓴다. `macro.py` 가 같은 선례다 — 헬퍼 안에
  "httpx 의 timeout 은 DNS 해석을 안 묶는다" 같은 사연이 들어 있어서 복제하면 한쪽만
  고쳐진다.
"""
from fastapi import APIRouter, Header, Response

from app.api.inav import _proxy_collector

router = APIRouter(prefix="/api/v1/ai-key-data", tags=["ai-key-data"])


@router.get("/ai-token-usage")
async def get_ai_token_usage(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[AI 사용량] OpenRouter 일간 토큰 사용량 — 일별/주간 총량 + 벤더·모델 상위.

    원천은 AI Key Data 의 `tokens_daily_long.csv`(OpenRouter Datasets API, 매일 갱신).
    ★이건 전수집계가 아니라 **상위 50 모델 + `other` 버킷**이다(payload 의 `coverage`).
      총량 시계열은 유효하지만 모델별 "시장 점유율" 로 읽으면 틀린다.
    7일 평활(`totals.daily_ma7`)은 collector 가 계산해 내려보낸다 — 요일 효과가 1.3배라
    일별 원본만 그리면 톱니만 보인다.
    """
    return await _proxy_collector("/ai-token-usage", if_none_match)


@router.get("/npm-downloads")
async def get_npm_downloads(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[AI 사용량] 코딩 에이전트 CLI 의 npm 일별 다운로드.

    원천은 ws3 수집기가 굽는 `npm_downloads_long.csv`. ★배포 전에는 파일이 없고, 그때는
    503 이 아니라 200 + 빈 series + `note`("아직 수집이 시작되지 않았습니다")가 온다.
    주중/주말 스윙이 3.3배라 화면 기본값은 `ma7` 쪽이다.
    """
    return await _proxy_collector("/npm-downloads", if_none_match)


@router.get("/vscode-installs")
async def get_vscode_installs(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[AI 사용량] VS Code AI 확장 설치수 — 누적 스톡 + 스냅샷 차분.

    ★★이 파이프라인에서 **유일하게 누락일을 영구 복구할 수 없는 소스**다(시점 누적값,
      과거 조회 API 없음). 그래서 `source.irrecoverable` 이 여기서만 true 이고,
      `gaps[]` 에 든 날짜는 나중에 어떤 방법으로도 채울 수 없다 — 화면이 다른 색으로
      경고해야 사용자가 데몬을 즉시 되살린다.
    ⚠️`measure: "stock"` 이다. npm·토큰 카드의 일별 플로우와 축이 다르니 같이 겹치지 않는다.
    ⚠️`delta` 는 스냅샷이 2개 이상일 때만 생긴다. 1일치면 빈 배열 + `note` 로 정상 렌더다.
    ⚠️음수 델타는 clip 하지 않는다 — MS 의 소급 정정이고 그 사실 자체가 관측 대상이다
      (`delta_marks[i].negative` · `revisions[]`).
    """
    return await _proxy_collector("/vscode-installs", if_none_match)


@router.get("/epoch-companies")
async def get_epoch_companies(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[Epoch] AI Lab ARR(계단) + 조달 라운드(점). 그룹 2개, 그룹별 `note` 로 격리.

    ⚠️연속선이 아니라 **step** 이다 — 3년에 수십 행짜리 뉴스 이벤트라 직선으로 이으면
      없던 중간값이 생긴다(정책금리 카드와 같은 논리). payload 의 `kind` 가 정본.
    회사 목록의 정본은 collector `epoch_datasets.COMPANIES`.
    """
    return await _proxy_collector("/epoch-companies", if_none_match)


@router.get("/epoch-chips")
async def get_epoch_chips(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[Epoch] 제조사별 분기 AI 칩 출하(H100e 환산) — 플로우 + 공통 기산점 누적.

    ⚠️`incomplete_quarters` 에 든 분기는 **부분 분기**다. 마지막 분기는 제조사 한 곳만
      들어 있을 수 있어 그대로 그리면 "전체 출하 급감"으로 보인다 — 빗금/점선 처리한다.
    """
    return await _proxy_collector("/epoch-chips", if_none_match)


@router.get("/epoch-datacenters")
async def get_epoch_datacenters(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[Epoch] AI 데이터센터 빌드아웃 — IT 전력 · H100e · capex 의 분기 asof 곡선.

    ⚠️`totals.it_power_mw`(오늘 기준 실측)와 `totals.planned_it_power_mw`(미래 계획 포함)를
      **같은 자리에 렌더하면 안 된다** — 2.70배 차이라 계획을 현재로 발표하게 된다.
    ⚠️전력은 전부 `IT power` 기준이다. `total_power_mw` 는 PUE 를 먹인 총 시설전력이라
      KPI 로 쓰면 차트 끝점과 28% 어긋난다.
    """
    return await _proxy_collector("/epoch-datacenters", if_none_match)

@router.get("/tool-calling")
async def get_tool_calling(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[AI 사용량] OpenRouter tool-calling 토큰 - 배수(tool/non-tool)와 non-tool 절대량.

    ★★**비중(tool/total)은 화면에 그리지 않는다.** 598일 내내 99.28~99.46% 라 사실상
      상수다 - OpenRouter 의 `modality=tool_calling` 은 "툴콜을 쓴 요청"이 아니라 "툴콜을
      지원하는 모델" 에 가깝기 때문이다. payload 의 `series` 는 그래서 배수와 non-tool
      둘뿐이고, 비중은 `stats.share_pct` 에 숫자 한 개로만 실린다.
    """
    return await _proxy_collector("/tool-calling", if_none_match)


# ── 레거시 경로(`/api/v1/stock-monitor/…`) ───────────────────────────────────
# 이 세 카드는 [AI Key Data] 화면 것이지만 경로만 옛 [종목 모니터] 프리픽스에 남아
# 있다(파일 맨 위 "동거 상태" 참조). 그 화면을 철거하면서 핸들러를 여기로 옮겼다 —
# 경로를 같이 바꾸면 `lib/api.ts` 와 컴포넌트를 동시에 고치는 breaking rename 이라
# 화면 철거와 분리했다.
legacy_router = APIRouter(prefix="/api/v1/stock-monitor", tags=["ai-key-data"])


@legacy_router.get("/compute-index")
async def get_compute_index(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[컴퓨팅 지수 모니터링] — GPU 렌탈 지수 3분할(H100 · B200 · B200/H100 배수).

    원천은 AI Key Data의 GPU임대지수_주가_통합.xlsx (블룸버그 내보내기).
    지수 목록의 정본은 collector compute_index.INDICES.
    """
    return await _proxy_collector("/compute-index", if_none_match)


@legacy_router.get("/policy-rate")
async def get_policy_rate(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[정책금리] — FOMC 금리 결정(수준 %) 시계열.

    원천은 AI Key Data의 macro_releases.csv 중 event=RATE 행. 회의와 회의
    사이엔 금리가 유지되므로 화면은 계단으로 그린다(payload 는 결정 시점만 담는다).
    """
    return await _proxy_collector("/policy-rate", if_none_match)


@legacy_router.get("/rate-topics")
async def get_rate_topics(
    if_none_match: str | None = Header(default=None),
) -> Response:
    """[금리 5주제] — 하이퍼스케일러 채권발행 · 인플레지표 · WTI · ADP · FOMC 내재확률.

    원천은 AI Key Data 의 `input/raw/금리/금리_2.xlsx` 한 장(신상품팀 공모손차 데이터
    사본). 다섯 카드가 같은 파일을 보므로 엔드포인트도 하나로 둔다 — 주제별로 나누면
    같은 1.6MB 워크북을 다섯 번 연다.
    """
    return await _proxy_collector("/rate-topics", if_none_match)
