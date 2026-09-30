"""SEC 공시 — 13F 거장 보유 · Form 4 내부자 · 13D/G 대량보유 · CUSIP 매핑 · 거장 명단 (계획 A1)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-26

★원본 `13F기관내부자/db/filings.db`(SQLite)의 표를 옮긴다 — 이름과 열은 가능한 한 그대로 두어
  이관(A2)·파서 이식(A3b)이 열 이름을 번역하지 않게 한다. 바꾼 것:
  - 날짜 문자열 → date / timestamptz, `summary_json` 문자열 → JSONB.
  - `sec_filings.amendment_type`: 13F-HR/A 가 **RESTATEMENT(대체)** 인지 **NEW HOLDINGS(추가분, 합산)**
    인지. ⚠️원본은 이걸 안 보고 "가장 늦은 공시 하나"만 남겨 버크셔 2023Q3 이 1종목·100% 가 됐다(계획 §A).
  - `form4_transactions.superseded_by`: Form 4/A 가 원 공시 거래를 대체하면 원 행에 정정 접수번호를 적는다
    (원본은 이중 집계했다).
  - `cusip_map.confidence` 에 'openfigi' 추가(A4).
  - `guru_roster`: 원본은 `watchlist.json` 파일이었다 — 거장을 화면에서 더하려면(사용자 결정 1) 표여야 한다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guru_roster",
        sa.Column("cik", sa.String(10), primary_key=True),              # 0 채운 10자리
        sa.Column("guru_name", sa.String(), nullable=True),             # 'Warren Buffett' (index 는 없음)
        sa.Column("firm", sa.String(), nullable=False),
        sa.Column("filer_name", sa.String(), nullable=False),           # SEC 제출자명
        sa.Column("kind", sa.String(), nullable=False),                 # 'guru' | 'index'
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # 'pending' | 'running' | 'done' | 'failed' | 'skip'
        sa.Column("backfill_status", sa.String(), nullable=False, server_default="pending"),
        # 그 전 13F 는 XML 이 아닌 텍스트 서식이라 파서가 못 읽는다(계획 A7)
        sa.Column("backfill_from", sa.Date(), nullable=False, server_default=sa.text("'2013-04-01'")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("note", sa.Text(), nullable=True),
    )

    op.create_table(
        "sec_filings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("form_type", sa.String(), nullable=False),
        sa.Column("accession_number", sa.String(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("period_of_report", sa.Date(), nullable=True),
        sa.Column("issuer_name", sa.String(), nullable=True),
        sa.Column("issuer_cik", sa.String(10), nullable=True),
        sa.Column("filer_name", sa.String(), nullable=True),
        sa.Column("filer_cik", sa.String(10), nullable=True),
        sa.Column("watch_cik", sa.String(10), nullable=True),
        sa.Column("watch_name", sa.String(), nullable=True),
        sa.Column("amendment_type", sa.String(), nullable=True),     # 13F: RESTATEMENT | NEW HOLDINGS
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("accession_number", "form_type", name="uq_sec_filings_acc_form"),
    )
    op.create_index("ix_sec_filings_watch_form_period", "sec_filings", ["watch_cik", "form_type", "period_of_report"])
    op.create_index("ix_sec_filings_issuer_form_date", "sec_filings", ["issuer_cik", "form_type", "filing_date"])

    op.create_table(
        "holdings_13f",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name_of_issuer", sa.String(), nullable=True),
        sa.Column("title_of_class", sa.String(), nullable=True),
        sa.Column("cusip", sa.String(9), nullable=True),
        sa.Column("value", sa.Numeric(20, 2), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("shr_type", sa.String(), nullable=True),            # SH | PRN(채권 — 비중에서 뺀다)
        sa.Column("put_call", sa.String(), nullable=True),            # Put | Call(옵션 — 비중에서 뺀다)
        sa.Column("investment_discretion", sa.String(), nullable=True),
        sa.Column("vote_sole", sa.Numeric(24, 4), nullable=True),
        sa.Column("vote_shared", sa.Numeric(24, 4), nullable=True),
        sa.Column("vote_none", sa.Numeric(24, 4), nullable=True),
    )
    op.create_index("ix_holdings_13f_acc", "holdings_13f", ["accession_number"])
    op.create_index("ix_holdings_13f_cusip", "holdings_13f", ["cusip"])

    op.create_table(
        "form4_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issuer_name", sa.String(), nullable=True),
        sa.Column("issuer_cik", sa.String(10), nullable=True),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("insider_name", sa.String(), nullable=True),
        sa.Column("insider_cik", sa.String(10), nullable=True),
        sa.Column("insider_role", sa.String(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("transaction_code", sa.String(4), nullable=True),   # P S A M F G …
        sa.Column("transaction_description", sa.String(), nullable=True),
        sa.Column("buy_sell", sa.String(), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("price", sa.Numeric(20, 6), nullable=True),
        sa.Column("transaction_value", sa.Numeric(24, 2), nullable=True),
        sa.Column("shares_owned_after", sa.Numeric(24, 4), nullable=True),
        sa.Column("ownership_type", sa.String(), nullable=True),
        sa.Column("acquired_disposed", sa.String(1), nullable=True),
        sa.Column("is_derivative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_open_market", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_option_exercise", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # 10b5-1 계획매매 — 장내 매도의 73%(실측). 순매수에서 뺀다(계획 §A-2)
        sa.Column("is_planned_trade", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("superseded_by", sa.String(), nullable=True),       # Form 4/A 접수번호
    )
    op.create_index("ix_form4_acc", "form4_transactions", ["accession_number"])
    op.create_index("ix_form4_issuer_date", "form4_transactions", ["issuer_cik", "transaction_date"])

    op.create_table(
        "ownership_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_name", sa.String(), nullable=True),
        sa.Column("subject_cik", sa.String(10), nullable=True),
        sa.Column("cusip", sa.String(9), nullable=True),
        sa.Column("filer_name", sa.String(), nullable=True),
        sa.Column("percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("is_amendment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_activist", sa.Boolean(), nullable=False, server_default=sa.text("false")),  # 13D
    )
    op.create_index("ix_ownership_events_acc", "ownership_events", ["accession_number"])

    op.create_table(
        "cusip_map",
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=True),
        # 'manual' | 'exact' | 'openfigi' | 'none'
        sa.Column("confidence", sa.String(), nullable=False, server_default="none"),
        sa.Column("figi", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    for t in ("cusip_map", "ownership_events", "form4_transactions", "holdings_13f", "sec_filings", "guru_roster"):
        op.drop_table(t)
