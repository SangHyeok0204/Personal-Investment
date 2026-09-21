"""worker 의 `prices.history` 를 API 에서 쓰기 위한 통로.

⚠️같은 계약을 두 번 구현하지 않는다 — 시세 소스와 시계열 파싱은 worker 에 있고,
  API 는 그걸 읽어 쓰기만 한다.
"""

import sys
from pathlib import Path

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices.history import Series, fetch_series as fetch_history  # noqa: E402,F401
