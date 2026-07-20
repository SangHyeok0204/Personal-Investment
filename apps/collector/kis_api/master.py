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


MASTER_URL_TEMPLATE = "https://new.real.download.dws.co.kr/common/master/{exchange}mst.cod.zip"

MASTER_COLUMNS = [
    "National code",
    "Exchange id",
    "Exchange code",
    "Exchange name",
    "Symbol",
    "realtime symbol",
    "Korea name",
    "English name",
    "Security type",
    "currency",
    "float position",
    "data type",
    "base price",
    "Bid order size",
    "Ask order size",
    "market start time",
    "market end time",
    "DR yn",
    "DR country code",
    "industry code",
    "index member yn",
    "tick size type",
    "etp type",
]

US_EXCHANGES = ("nas", "nys", "ams")
ALL_EXCHANGES = US_EXCHANGES + ("hks", "shs", "szs", "tse", "hnx", "hsx")

# A rough exchange hint (e.g. "NAS" from OpenFIGI) only tells us the region;
# the master files are authoritative for the exact listing venue, so a hint
# expands to every exchange in its region and we scan them in order.
EXCHANGE_REGIONS = {
    "nas": US_EXCHANGES,
    "nys": US_EXCHANGES,
    "ams": US_EXCHANGES,
    "shs": ("shs", "szs"),
    "szs": ("shs", "szs"),
    "hks": ("hks",),
    "tse": ("tse",),
    "hnx": ("hnx", "hsx"),
    "hsx": ("hnx", "hsx"),
}

EXCHANGE_ALIASES = {
    "NAS": "nas",
    "NYS": "nys",
    "AMS": "ams",
    "NASDAQ": "nas",
    "NYSE": "nys",
    "AMEX": "ams",
    "HKS": "hks",
    "HKSE": "hks",
    "SHS": "shs",
    "SZS": "szs",
    "TSE": "tse",
    "HNX": "hnx",
    "HSX": "hsx",
}


@dataclass
class OverseasExchange:
    code: str
    symbol: str
    realtime_symbol: str
    english_name: str
    korea_name: str
    security_type: str
    currency: str


class KisMaster:
    """Download and cache KIS overseas stock master files.

    Master files are refreshed roughly daily. We cache the parsed DataFrame
    per (exchange, YYYYMMDD) under ``cache_dir`` so repeated runs in one
    trading day do not redownload.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout: int = 30,
        verify_ssl: bool = False,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(__file__).resolve().parents[4] / "data" / "ETF_iNAV모니터" / "cache" / "master"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            urllib3.disable_warnings(InsecureRequestWarning)
        self._dataframes: dict[str, pd.DataFrame] = {}
        self._symbol_index: dict[str, dict[str, OverseasExchange]] = {}

    def _cache_path(self, exchange: str) -> Path:
        return self.cache_dir / f"{exchange}mst_{datetime.now().strftime('%Y%m%d')}.parquet"

    def load(self, exchange: str, force_refresh: bool = False) -> pd.DataFrame:
        exch = self._normalize(exchange)
        if not force_refresh and exch in self._dataframes:
            return self._dataframes[exch]

        cache_path = self._cache_path(exch)
        if not force_refresh and cache_path.exists():
            df = pd.read_parquet(cache_path)
        else:
            df = self._download_and_parse(exch)
            try:
                df.to_parquet(cache_path, index=False)
            except Exception:
                pass

        self._dataframes[exch] = df
        return df

    def _download_and_parse(self, exch: str) -> pd.DataFrame:
        url = MASTER_URL_TEMPLATE.format(exchange=exch)
        response = requests.get(url, timeout=self.timeout, verify=self.verify_ssl)
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith(".cod")]
            if not names:
                raise RuntimeError(f"No .cod file in {url}")
            with zf.open(names[0]) as fh:
                raw = fh.read()

        df = pd.read_csv(
            io.BytesIO(raw),
            sep="\t",
            encoding="cp949",
            header=None,
            dtype=str,
            on_bad_lines="skip",
        )
        column_count = min(len(df.columns), len(MASTER_COLUMNS))
        df = df.iloc[:, :column_count].copy()
        df.columns = MASTER_COLUMNS[:column_count]
        return df.fillna("")

    def _build_index(self, exch: str) -> dict[str, OverseasExchange]:
        if exch in self._symbol_index:
            return self._symbol_index[exch]
        df = self.load(exch)
        index: dict[str, OverseasExchange] = {}
        for row in df.itertuples(index=False):
            symbol = str(getattr(row, "Symbol", "")).strip().upper()
            if not symbol:
                continue
            index[symbol] = OverseasExchange(
                # The master filename (nasmst/nysmst/...) is the reliable KIS
                # exchange code; the file's own column is inconsistent.
                code=exch.upper(),
                symbol=symbol,
                realtime_symbol=str(getattr(row, "realtime symbol", "")).strip().upper(),
                english_name=str(getattr(row, "English name", "")).strip(),
                korea_name=str(getattr(row, "Korea name", "")).strip(),
                security_type=str(getattr(row, "Security type", "")).strip(),
                currency=str(getattr(row, "currency", "")).strip().upper(),
            )
        self._symbol_index[exch] = index
        return index

    def lookup(self, ticker: str, exchange_hint: str | None = None) -> OverseasExchange | None:
        ticker_upper = (ticker or "").strip().upper()
        if not ticker_upper:
            return None

        candidates: tuple[str, ...]
        if exchange_hint:
            normalized = self._normalize(exchange_hint, allow_none=True)
            candidates = EXCHANGE_REGIONS.get(normalized, US_EXCHANGES) if normalized else US_EXCHANGES
        else:
            candidates = US_EXCHANGES

        for exch in candidates:
            index = self._build_index(exch)
            for symbol in self._symbol_candidates(ticker_upper, exch):
                hit = index.get(symbol)
                if hit:
                    return hit
        return None

    @staticmethod
    def _normalize(exchange: str, allow_none: bool = False) -> str:
        if not exchange:
            if allow_none:
                return ""
            raise ValueError("exchange is required")
        text = exchange.strip().upper()
        normalized = EXCHANGE_ALIASES.get(text, text.lower())
        if normalized not in ALL_EXCHANGES:
            if allow_none:
                return ""
            raise ValueError(f"Unsupported exchange: {exchange}")
        return normalized

    @staticmethod
    def _symbol_candidates(ticker: str, exchange: str) -> tuple[str, ...]:
        if exchange == "hks" and ticker.isdigit():
            padded = ticker.zfill(5)
            return (ticker, padded) if ticker != padded else (ticker,)
        return (ticker,)
