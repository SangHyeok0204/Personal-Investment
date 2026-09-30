"""실적 모니터 — 발표 일정 · 실적 · 가이던스 · 관전포인트 (계획 B1)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-27

원본 `어닝모니터`는 엑셀(`보유종목정리.xlsx`)이 정본이고 SQLite(`EARNINGS_MONITOR.db`)는 그 미러였다
(`earnings_store.mirror_master_to_db` — "DB 는 조회용 미러"). 사내 경로의 DB 는 이 맥에 없고
zip 에도 없다 → 정본인 엑셀에서 옮긴다(B1 이관 스크립트).

바꾼 것:
  - 시트 한 장(실적 22열)을 **발표(events) · 결과(results) · 가이던스(guidance) · 관전포인트(watchpoints)** 로 나눈다.
  - '108.86B' 같은 문자열 → 숫자(달러). 장전/장후는 'BMO' / 'AMC'.
  - ⚠️`quarter` 는 원본 규칙(`derive_fiscal_quarter`)대로 **발표일로 정한 달력 분기 라벨**이다 — 회사 회계분기가 아니다
    (예: NVDA 8월 발표 = '2026Q2', 회사 기준으로는 FY27 Q2). 한 종목의 발표를 구분하는 키로만 쓴다.
  - 매출 컨센은 원천이 따로(Investing.com 크롤, B3b) — 수집 실패를 '없음'과 구분해 `revenue_forecast_status` 에 둔다.
  - 펀드 열(보유펀드 · 종합 시트)은 버린다(회사 펀드 — 계획 B).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "earnings_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("quarter", sa.String(8), nullable=False),            # '2026Q2' — 발표일 기준 라벨(위 설명)
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("timing", sa.String(8), nullable=True),               # 'BMO' | 'AMC' | NULL(미정)
        sa.Column("eps_forecast", sa.Numeric(14, 4), nullable=True),
        sa.Column("n_estimates", sa.Integer(), nullable=True),
        sa.Column("revenue_forecast", sa.Numeric(20, 2), nullable=True),
        # 'ok' | 'failed'(크롤 실패 — 화면에 "수집 실패") | NULL(아직 안 모음)
        sa.Column("revenue_forecast_status", sa.String(), nullable=True),
        sa.Column("revenue_forecast_source", sa.String(), nullable=True),   # 'investing' | 'import'
        sa.Column("market_cap", sa.Numeric(20, 2), nullable=True),
        sa.Column("source", sa.String(), nullable=False),               # 'nasdaq' | 'import'
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("ticker", "quarter", name="uq_earnings_events_ticker_quarter"),
    )
    op.create_index("ix_earnings_events_date", "earnings_events", ["report_date"])

    op.create_table(
        "earnings_results",
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("earnings_events.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("eps_actual", sa.Numeric(14, 4), nullable=True),
        sa.Column("revenue_actual", sa.Numeric(20, 2), nullable=True),
        sa.Column("eps_surprise_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("revenue_surprise_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("verdict", sa.String(), nullable=True),               # '상회' | '부합' | '하회'
        sa.Column("filing_accession", sa.String(), nullable=True),      # 8-K / 6-K
        sa.Column("filing_url", sa.Text(), nullable=True),
        # 발표 후 반응(장후 16:00→17:30 ET · 장전은 전일 종가→09:30 등 — B4)
        sa.Column("reaction_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("reaction_window", sa.String(), nullable=True),
        sa.Column("reaction_note", sa.Text(), nullable=True),           # 원본 '기타시장반응'(LLM 요약)
        sa.Column("source", sa.String(), nullable=False),               # 'nasdaq' | 'sec' | 'import'
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "earnings_guidance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("earnings_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),               # 'revenue' | 'eps' | 'gross_margin' …
        sa.Column("period", sa.String(), nullable=True),                # 가이던스 대상 기간(원문)
        sa.Column("low", sa.Numeric(20, 4), nullable=True),
        sa.Column("high", sa.Numeric(20, 4), nullable=True),
        sa.Column("prior_low", sa.Numeric(20, 4), nullable=True),
        sa.Column("prior_high", sa.Numeric(20, 4), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),             # 'raise' | 'lower' | 'maintain' | 'new'
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.create_index("ix_earnings_guidance_event", "earnings_guidance", ["event_id"])

    op.create_table(
        "earnings_watchpoints",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("quarter", sa.String(8), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),            # 1~4
        sa.Column("point", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),               # 'import' | 'llm'
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("ticker", "quarter", "rank", name="uq_earnings_watchpoints"),
    )


def downgrade() -> None:
    for t in ("earnings_watchpoints", "earnings_guidance", "earnings_results", "earnings_events"):
        op.drop_table(t)
