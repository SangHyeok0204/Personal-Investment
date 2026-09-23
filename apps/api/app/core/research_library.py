"""내가 가진 리서치 자료를 한곳에서 본다 — **파일을 옮기지 않고.**

★왜 이렇게 좁게 만드나: 화면이 "자료 인덱싱이 아직 연결되지 않았습니다"라고만
  적혀 있었다. 할 일 목록은 있는데 **무엇을 하면 켜지는지**가 없어서, 그런
  화면은 영영 안 채워진다. 켜는 방법을 화면이 말하게 하고, 켜면 실제로 동작하는
  가장 작은 것을 만든다.

⚠️**내용은 읽지 않는다.** 파일 이름 · 수정시각 · 크기 · 확장자뿐이다. 문서를
  열어 종목코드를 뽑는 것은 다음 단계다 — 지금 그걸 하면 "무엇을 읽었는지"를
  사용자가 모르는 채로 개인 문서를 해석하게 된다.

⚠️**지정한 폴더 밖으로 나가지 않는다.** 심볼릭 링크를 따라가다 홈 디렉터리를
  훑는 일이 없도록, 실경로가 뿌리 안인지 확인하고 아니면 버린다.

⚠️**파일을 옮기거나 고치지 않는다.** 경로만 들고 있다가 열어 줄 뿐이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: 읽을 확장자. 리서치 자료로 실제로 쓰이는 것만.
EXTENSIONS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".md", ".txt"}

#: 한 번에 훑는 상한. 폴더를 잘못 지정했을 때 몇 만 개를 세다 멈추지 않게 한다.
MAX_FILES = 2000

#: 내려갈 깊이. 연도/분기 폴더 두세 겹이면 충분하다.
MAX_DEPTH = 4

#: 건너뛸 폴더 이름. 동기화 찌꺼기와 숨김 폴더.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".obsidian", ".Trash"}


@dataclass(frozen=True)
class Document:
    """자료 한 건. **내용은 안 들어 있다.**"""

    name: str
    #: 뿌리 기준 상대 경로. 화면에 폴더 맥락을 보여 주는 데 쓴다.
    relative_path: str
    #: 절대 경로. 여는 데만 쓴다.
    path: str
    extension: str
    size_bytes: int
    modified_at: datetime
    #: 파일 이름에서 찾은 보유 종목. ⚠️이름만 보고 찾은 것이라 **놓칠 수 있다**.
    tickers: list[str]


@dataclass(frozen=True)
class Library:
    configured: bool
    root: str | None
    #: 뿌리가 설정됐는데 없거나 폴더가 아니면 여기에 이유를 적는다.
    problem: str | None
    documents: list[Document]
    #: 상한에 걸려 잘렸는지. ⚠️조용히 자르면 "자료가 이게 다"로 읽힌다.
    truncated: bool


def _match_tickers(name: str, holdings: dict[str, str]) -> list[str]:
    """파일 이름에 보유 종목이 있는지. 티커와 한글 이름을 둘 다 본다.

    ⚠️티커는 **낱말 경계**로 본다. 그냥 부분 문자열로 찾으면 "BE"(블룸 에너지)가
      "BETA", "ROBERT" 같은 이름에 죄다 걸린다 — 실측으로 겪기 전에 막는다.
    """
    upper = name.upper()
    found = []
    for ticker, display in holdings.items():
        if display and display in name:
            found.append(ticker)
            continue
        index = upper.find(ticker)
        while index != -1:
            before = upper[index - 1] if index > 0 else " "
            after_index = index + len(ticker)
            after = upper[after_index] if after_index < len(upper) else " "
            if not before.isalnum() and not after.isalnum():
                found.append(ticker)
                break
            index = upper.find(ticker, index + 1)
    return sorted(set(found))


def scan(root_path: str | None, holdings: dict[str, str] | None = None) -> Library:
    """폴더를 훑어 자료 목록을 만든다.

    holdings: 티커 → 화면에 쓰는 이름. 파일 이름과 맞춰 태그를 붙이는 데만 쓴다.
    """
    if not root_path:
        return Library(
            configured=False, root=None, problem=None, documents=[], truncated=False
        )

    root = Path(root_path).expanduser()
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return Library(
            configured=True, root=str(root),
            problem="그 경로를 찾을 수 없습니다.",
            documents=[], truncated=False,
        )
    if not resolved_root.is_dir():
        return Library(
            configured=True, root=str(resolved_root),
            problem="폴더가 아니라 파일입니다.",
            documents=[], truncated=False,
        )

    holdings = holdings or {}
    documents: list[Document] = []
    truncated = False

    for current, dirnames, filenames in os.walk(resolved_root):
        current_path = Path(current)
        depth = len(current_path.relative_to(resolved_root).parts)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = [
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
            ]

        for filename in filenames:
            if filename.startswith(".") or filename.startswith("~$"):
                continue  # 숨김 파일과 오피스 임시 파일.
            extension = Path(filename).suffix.lower()
            if extension not in EXTENSIONS:
                continue
            if len(documents) >= MAX_FILES:
                truncated = True
                break

            file_path = current_path / filename
            try:
                # ⚠️심볼릭 링크를 따라가 뿌리 밖으로 나가지 않는다.
                real = file_path.resolve(strict=True)
                real.relative_to(resolved_root)
                stat = real.stat()
            except (OSError, RuntimeError, ValueError):
                continue

            documents.append(
                Document(
                    name=filename,
                    relative_path=str(file_path.relative_to(resolved_root)),
                    path=str(real),
                    extension=extension.lstrip("."),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    tickers=_match_tickers(filename, holdings),
                )
            )
        if truncated:
            break

    # 최근 것이 위로 — 안 읽은 자료를 먼저 보게.
    documents.sort(key=lambda d: d.modified_at, reverse=True)
    return Library(
        configured=True, root=str(resolved_root), problem=None,
        documents=documents, truncated=truncated,
    )
