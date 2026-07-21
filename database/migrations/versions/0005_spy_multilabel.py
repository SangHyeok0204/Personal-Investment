"""sd_author_labels: (source,author) → (source,author,label) 유니크로 교체.

원본 SQLite author_labels 는 UNIQUE(author,source,label) — 한 작성자가 복수
발행사 스파이 라벨을 동시에 가질 수 있다(실측 72행 중 7행이 복수 라벨).
(source,author) 단일 유니크는 인제스트 dict 키잉과 함께 라벨을 유실시키므로
원본 semantics 로 교정한다. 프론트는 원본 UI 처럼 (source,author) 로 그룹핑한다.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_sd_author_labels_source_author", "sd_author_labels", type_="unique"
    )
    op.create_unique_constraint(
        "uq_sd_author_labels_source_author_label",
        "sd_author_labels",
        ["source", "author", "label"],
    )


def downgrade() -> None:
    # 복수 라벨 행이 존재하면 (source,author) 유니크 재생성이 실패한다 —
    # 다운그레이드 전 수동 dedup 필요.
    op.drop_constraint(
        "uq_sd_author_labels_source_author_label", "sd_author_labels", type_="unique"
    )
    op.create_unique_constraint(
        "uq_sd_author_labels_source_author",
        "sd_author_labels",
        ["source", "author"],
    )
