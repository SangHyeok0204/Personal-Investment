from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning


STOCK_FUTURE_MASTER_URL = (
    "https://new.real.download.dws.co.kr/common/master/fo_stk_code_mts.mst.zip"
)

STOCK_FUTURE_COLUMNS = [
    "product_type",
    "short_code",
    "standard_code",
    "name",
    "atm_type",
    "strike",
    "contract_month_code",
    "underlying_code",
    "underlying_name",
]


@dataclass
class DomesticFutureOption:
    standard_code: str
    short_code: str
    name: str
    market_div_code: str
    currency: str = "KRW"


class DomesticFutureOptionMaster:
    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout: int = 30,
        verify_ssl: bool = False,
    ):
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir
            else Path(__file__).resolve().parents[4] / "data" / "ETF_iNAV모니터" / "cache" / "master"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            urllib3.disable_warnings(InsecureRequestWarning)
        self._stock_futures: pd.DataFrame | None = None
        self._stock_future_index: dict[str, DomesticFutureOption] | None = None

    def _stock_future_cache_path(self) -> Path:
        return self.cache_dir / f"fo_stk_code_mts_{datetime.now().strftime('%Y%m%d')}.parquet"

    def load_stock_futures(self, force_refresh: bool = False) -> pd.DataFrame:
        if self._stock_futures is not None and not force_refresh:
            return self._stock_futures

        cache_path = self._stock_future_cache_path()
        if cache_path.exists() and not force_refresh:
            df = pd.read_parquet(cache_path)
        else:
            response = requests.get(
                STOCK_FUTURE_MASTER_URL,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                names = [name for name in zf.namelist() if name.lower().endswith(".mst")]
                if not names:
                    raise RuntimeError(f"No .mst file in {STOCK_FUTURE_MASTER_URL}")
                raw = zf.read(names[0])
            df = pd.read_table(
                io.BytesIO(raw),
                sep="|",
                encoding="cp949",
                header=None,
                dtype=str,
            )
            df = df.iloc[:, : len(STOCK_FUTURE_COLUMNS)].copy()
            df.columns = STOCK_FUTURE_COLUMNS[: len(df.columns)]
            df = df.fillna("")
            try:
                df.to_parquet(cache_path, index=False)
            except Exception:
                pass

        self._stock_futures = df
        return df

    def _build_stock_future_index(self) -> dict[str, DomesticFutureOption]:
        if self._stock_future_index is not None:
            return self._stock_future_index

        index: dict[str, DomesticFutureOption] = {}
        for row in self.load_stock_futures().itertuples(index=False):
            standard_code = str(getattr(row, "standard_code", "")).strip().upper()
            short_code = str(getattr(row, "short_code", "")).strip().upper()
            if not standard_code or not short_code:
                continue
            index[standard_code] = DomesticFutureOption(
                standard_code=standard_code,
                short_code=short_code,
                name=str(getattr(row, "name", "")).strip(),
                market_div_code="JF",
            )
        self._stock_future_index = index
        return index

    def lookup_stock_future(self, standard_code: str) -> DomesticFutureOption | None:
        return self._build_stock_future_index().get((standard_code or "").strip().upper())

