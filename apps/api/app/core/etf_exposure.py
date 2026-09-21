"""`database/seeds/etf_exposure.py` 를 읽어 오는 얇은 통로.

⚠️매핑의 정본은 `database/seeds/` 다. 여기에 복제하지 않는다 — 같은 표가 두 군데
  있으면 한쪽만 고쳐 놓고 왜 화면이 안 바뀌는지 찾게 된다(이 저장소에서 섹터
  시드로 이미 겪었다). worker 의 `repositories/sectors.py` 도 같은 방식으로 읽는다.
"""

import importlib.util
import sys
from pathlib import Path

_SEED_PATH = (
    Path(__file__).resolve().parents[4] / "database" / "seeds" / "etf_exposure.py"
)


def _load() -> dict[str, tuple[str, str]]:
    if not _SEED_PATH.exists():
        # 시드가 없으면 ETF 치환 없이 tech_l1 그대로 동작한다 — 화면이 죽지는 않는다.
        return {}
    spec = importlib.util.spec_from_file_location("_etf_exposure_seed", _SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_etf_exposure_seed"] = module
    spec.loader.exec_module(module)
    return module.ETF_EXPOSURE


ETF_EXPOSURE: dict[str, tuple[str, str]] = _load()
