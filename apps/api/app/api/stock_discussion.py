"""종토방(stock discussion) 읽기 서빙 + push-ingest 라우터.

개발 PC 파이프라인이 정본(SQLite)을 소유하고, 여기에 60s 주기로 push 한다.
대시보드 Postgres 는 멱등 upsert 로 저장하는 읽기 서빙 사본(read-replica).
계약 D1–D11 은 계획 §1.4 참조.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.internal import require_internal_api_key
from app.db.session import get_db
from app.models import SdAuthorLabel, SdEtfMeta, SdPost, SdSyncState
from app.schemas_stock_discussion import (
    EtfOut,
    IngestApplied,
    IngestPayload,
    IngestResponse,
    PostOut,
    RecentOut,
    SpyOut,
)

router = APIRouter(prefix="/api/v1/stock-discussion", tags=["stock-discussion"])

# 원본 파이프라인은 KST 로컬시각을 기록한다 (한국은 DST 없음 → 고정 +09:00).
# zoneinfo 대신 고정 오프셋을 써서 slim 이미지의 tzdata 유무에 의존하지 않는다.
KST = timezone(timedelta(hours=9))


def _parse_ts(raw: str | None) -> datetime | None:
    """naive 'YYYY-MM-DD HH:MM[:SS]' (KST 가정) 또는 offset ISO → tz-aware datetime.

    파싱 불가/빈 값 → None. naive 값엔 +09:00 을 부여한다 (계약 C2/D1).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


# ── 인제스트 (개발 PC → 대시보드, 인증) ───────────────────────────────────


@router.post(
    "/ingest",
    response_model=IngestResponse,
    dependencies=[Depends(require_internal_api_key)],
)
def ingest(payload: IngestPayload, db: Session = Depends(get_db)) -> IngestResponse:
    now = datetime.now(timezone.utc)

    # 1) etfs upsert (code PK). 한글 값→영문 컬럼, C7 소멸.
    if payload.etfs:
        etf_rows = {
            e.code: {
                "code": e.code,
                "name": e.name,
                "issuer": e.issuer,
                "category": e.category,
                "updated_at": now,
            }
            for e in payload.etfs
        }
        stmt = pg_insert(SdEtfMeta).values(list(etf_rows.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": stmt.excluded.name,
                "issuer": stmt.excluded.issuer,
                "category": stmt.excluded.category,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        db.execute(stmt)

    # 2) posts upsert ON CONFLICT(source,post_id,etf_code) — 배치 내 충돌키 중복은
    #    마지막 것으로 dedup (Postgres "cannot affect row a second time" 회피).
    post_rows: dict[tuple, dict] = {}
    for p in payload.posts:
        post_date = _parse_ts(p.post_date)
        post_date_raw = p.post_date_raw
        if post_date is None and p.post_date and p.post_date.strip():
            # 파싱 불가 post_date → NULL + 원문 보존 (C2).
            post_date_raw = post_date_raw or p.post_date
        crawled_at = _parse_ts(p.crawled_at) or now
        post_rows[(p.source, p.post_id, p.etf_code)] = {
            "src_id": p.src_id,
            "source": p.source,
            "post_id": p.post_id,
            "etf_code": p.etf_code,
            "etf_name": p.etf_name,
            "title": p.title,
            "content": p.content,
            "post_date": post_date,
            "post_date_raw": post_date_raw,
            "author": p.author,
            "likes": p.likes,
            "dislikes": p.dislikes,
            "comments": p.comments,
            "crawled_at": crawled_at,
            "sentiment": p.sentiment,
            "sentiment_confidence": p.sentiment_confidence,
            "sentiment_model": p.sentiment_model,
            "sentiment_at": _parse_ts(p.sentiment_at),
        }

    posts_upserted = 0
    if post_rows:
        rows = list(post_rows.values())
        stmt = pg_insert(SdPost).values(rows)
        # 충돌 시 변동 가능한 값만 갱신 (참여수·감성·src_id). 정체성/본문은 불변.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_sd_posts_source_postid_etfcode",
            set_={
                "src_id": stmt.excluded.src_id,
                "likes": stmt.excluded.likes,
                "dislikes": stmt.excluded.dislikes,
                "comments": stmt.excluded.comments,
                "sentiment": stmt.excluded.sentiment,
                "sentiment_confidence": stmt.excluded.sentiment_confidence,
                "sentiment_model": stmt.excluded.sentiment_model,
                "sentiment_at": stmt.excluded.sentiment_at,
            },
        )
        db.execute(stmt)
        posts_upserted = len(rows)

    # 3) sentiment_updates: 존재 행만 UPDATE. 부재(미매칭)는 행 생성 없이 카운트만
    #    (D2: 배치캡 불변식이 지켜지면 sentiment_unmatched 는 상시 0 이어야 함).
    sentiment_upserted = 0
    sentiment_unmatched = 0
    for s in payload.sentiment_updates:
        conds = [SdPost.source == s.source, SdPost.post_id == s.post_id]
        if s.etf_code is None:
            conds.append(SdPost.etf_code.is_(None))
        else:
            conds.append(SdPost.etf_code == s.etf_code)
        result = db.execute(
            update(SdPost)
            .where(*conds)
            .values(
                sentiment=s.sentiment,
                sentiment_confidence=s.sentiment_confidence,
                sentiment_model=s.sentiment_model,
                sentiment_at=_parse_ts(s.sentiment_at),
            )
        )
        if result.rowcount:
            sentiment_upserted += result.rowcount
        else:
            sentiment_unmatched += 1

    # 4) spy_labels_full: 빈 셋이면 스킵 (D4 — 재기동 직후 전건 소거 방지),
    #    아니면 테이블 전체 full-replace (delete-missing + upsert).
    spies_replaced = 0
    spies_skipped = 0
    if payload.spy_labels_full:
        # 원본 UNIQUE(author,source,label) — 한 작성자 복수 라벨 보존.
        spy_rows = {
            (sp.source, sp.author, sp.label): {
                "source": sp.source,
                "author": sp.author,
                "label": sp.label,
                "reason": sp.reason,
                "stats": sp.stats,
                "updated_at": _parse_ts(sp.updated_at) or now,
            }
            for sp in payload.spy_labels_full
        }
        keys = list(spy_rows.keys())
        db.execute(
            delete(SdAuthorLabel).where(
                tuple_(
                    SdAuthorLabel.source, SdAuthorLabel.author, SdAuthorLabel.label
                ).notin_(keys)
            )
        )
        stmt = pg_insert(SdAuthorLabel).values(list(spy_rows.values()))
        stmt = stmt.on_conflict_do_update(
            constraint="uq_sd_author_labels_source_author_label",
            set_={
                "label": stmt.excluded.label,
                "reason": stmt.excluded.reason,
                "stats": stmt.excluded.stats,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        db.execute(stmt)
        spies_replaced = len(spy_rows)
    else:
        spies_skipped = 1

    # 5) health → sd_sync_state 싱글턴 (id=1). last_ingest_at 은 forward-only
    #    GREATEST(existing, now()) — 서버측 now (D5).
    #    빈 health(백필·push_once 의 {})는 기존 헬스 값을 NULL 로 덮지 않는다:
    #    전 필드 None 이면 헬스 컬럼을 upsert 대상에서 제외한다.
    h = payload.health
    health_values = {
        "naver_last_ok": _parse_ts(h.naver_last_ok) if h else None,
        "naver_last_error": h.naver_last_error if h else None,
        "naver_consec_errors": h.naver_consec_errors if h else None,
        "toss_last_ok": _parse_ts(h.toss_last_ok) if h else None,
        "toss_last_error": h.toss_last_error if h else None,
        "toss_consec_errors": h.toss_consec_errors if h else None,
        "sentiment_labeled_total": h.sentiment_labeled_total if h else None,
        "sentiment_cost_usd_total": h.sentiment_cost_usd_total if h else None,
        "spy_labels_total": h.spy_labels_total if h else None,
    }
    has_health = any(v is not None for v in health_values.values())

    insert_values = {
        "id": 1,
        "last_ingest_at": func.now(),
        "last_batch_id": payload.batch_id,
        "updated_at": func.now(),
        **health_values,
    }
    stmt = pg_insert(SdSyncState).values(**insert_values)
    set_ = {
        "last_batch_id": stmt.excluded.last_batch_id,
        "last_ingest_at": func.greatest(SdSyncState.last_ingest_at, func.now()),
        "updated_at": func.now(),
    }
    if has_health:
        set_.update(
            {
                "naver_last_ok": stmt.excluded.naver_last_ok,
                "naver_last_error": stmt.excluded.naver_last_error,
                "naver_consec_errors": stmt.excluded.naver_consec_errors,
                "toss_last_ok": stmt.excluded.toss_last_ok,
                "toss_last_error": stmt.excluded.toss_last_error,
                "toss_consec_errors": stmt.excluded.toss_consec_errors,
                "sentiment_labeled_total": stmt.excluded.sentiment_labeled_total,
                "sentiment_cost_usd_total": stmt.excluded.sentiment_cost_usd_total,
                "spy_labels_total": stmt.excluded.spy_labels_total,
            }
        )
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=set_)
    db.execute(stmt)

    db.commit()

    return IngestResponse(
        ok=True,
        applied=IngestApplied(
            posts_upserted=posts_upserted,
            sentiment_upserted=sentiment_upserted,
            sentiment_unmatched=sentiment_unmatched,
            spies_replaced=spies_replaced,
            spies_skipped=spies_skipped,
        ),
        server_time=now.isoformat(),
    )


# ── 읽기 (프론트 → 대시보드, 로컬 Postgres) ────────────────────────────────


@router.get("/recent", response_model=RecentOut)
def recent(
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    etf_code: str | None = None,
    etf_codes: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> RecentOut:
    limit = min(limit, 500)  # 렌더 상한 (SD_KEYWORD_RENDER_MAX 정책과 일치).

    conds = []
    if etf_code:
        conds.append(SdPost.etf_code == etf_code)
    if etf_codes:
        codes = [c.strip() for c in etf_codes.split(",") if c.strip()]
        if codes:
            conds.append(SdPost.etf_code.in_(codes))
    if source:
        conds.append(SdPost.source == source)
    if keyword and keyword.strip():
        # LIKE 와일드카드를 리터럴로 처리 (사용자 keyword 는 부분일치 검색).
        esc = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{esc}%"
        conds.append(
            or_(
                SdPost.title.ilike(pat, escape="\\"),
                SdPost.content.ilike(pat, escape="\\"),
                SdPost.author.ilike(pat, escape="\\"),
            )
        )

    total = db.execute(
        select(func.count()).select_from(SdPost).where(*conds)
    ).scalar_one()

    rows = (
        db.execute(
            select(SdPost)
            .where(*conds)
            .order_by(
                func.coalesce(SdPost.post_date, SdPost.crawled_at).desc().nulls_last(),
                SdPost.src_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    return RecentOut(
        items=[PostOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    # 일 경계 = crawled_at 의 KST 날짜 (D8, 원본=수집시각 semantics). 피드 정렬만 COALESCE.
    today_where = (
        "(crawled_at AT TIME ZONE 'Asia/Seoul')::date "
        "= (now() AT TIME ZONE 'Asia/Seoul')::date"
    )

    total = db.execute(text("SELECT count(*) FROM sd_posts")).scalar_one()
    today = db.execute(
        text(f"SELECT count(*) FROM sd_posts WHERE {today_where}")
    ).scalar_one()
    last_hour = db.execute(
        text("SELECT count(*) FROM sd_posts WHERE crawled_at >= now() - interval '1 hour'")
    ).scalar_one()

    by_etf_source = [
        {"etf_code": r.etf_code, "etf_name": r.etf_name, "source": r.source, "n": r.n}
        for r in db.execute(
            text(
                "SELECT etf_code, max(etf_name) AS etf_name, source, count(*) AS n "
                "FROM sd_posts GROUP BY etf_code, source ORDER BY n DESC"
            )
        )
    ]
    today_by_etf = [
        {"etf_code": r.etf_code, "n": r.n}
        for r in db.execute(
            text(
                f"SELECT etf_code, count(*) AS n FROM sd_posts WHERE {today_where} "
                "GROUP BY etf_code ORDER BY n DESC"
            )
        )
    ]

    srow = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE sentiment IS NOT NULL) AS labeled, "
            "count(*) FILTER (WHERE sentiment = '긍정') AS pos, "
            "count(*) FILTER (WHERE sentiment = '부정') AS neg, "
            "count(*) FILTER (WHERE sentiment = '중립') AS neu FROM sd_posts"
        )
    ).one()

    st = db.execute(
        select(SdSyncState).where(SdSyncState.id == 1)
    ).scalar_one_or_none()

    health = {
        "naver": {
            "last_ok": _iso(st.naver_last_ok) if st else None,
            "last_error": st.naver_last_error if st else None,
            "consecutive_errors": st.naver_consec_errors if st else None,
        },
        "toss": {
            "last_ok": _iso(st.toss_last_ok) if st else None,
            "last_error": st.toss_last_error if st else None,
            "consecutive_errors": st.toss_consec_errors if st else None,
        },
        "sentiment": {
            "labeled_total": st.sentiment_labeled_total if st else None,
            "cost_usd_total": st.sentiment_cost_usd_total if st else None,
        },
        "spy": {"labels_total": st.spy_labels_total if st else None},
    }

    return {
        "total": total,
        "today": today,
        "last_hour": last_hour,
        "by_etf_source": by_etf_source,
        "today_by_etf": today_by_etf,
        "sentiment": {
            "labeled": srow.labeled,
            "긍정": srow.pos,
            "부정": srow.neg,
            "중립": srow.neu,
        },
        "health": health,
        "last_ingest_at": _iso(st.last_ingest_at) if st else None,
    }


@router.get("/spies", response_model=list[SpyOut])
def spies(label: str | None = None, db: Session = Depends(get_db)) -> list[SdAuthorLabel]:
    stmt = select(SdAuthorLabel)
    if label:
        stmt = stmt.where(SdAuthorLabel.label == label)
    stmt = stmt.order_by(SdAuthorLabel.updated_at.desc().nulls_last())
    return list(db.execute(stmt).scalars().all())


@router.get("/etfs", response_model=list[EtfOut])
def etfs(db: Session = Depends(get_db)) -> list[SdEtfMeta]:
    return list(db.execute(select(SdEtfMeta).order_by(SdEtfMeta.code)).scalars().all())
