
from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Candidate:

    name: str
    url: str
    expect: str
    group: str = "daily"
    headers: dict[str, str] = field(default_factory=dict)
    form: dict[str, str] = field(default_factory=dict)
    sample_pending: str = ""


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        name="twse_daily_all",
        url="https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        expect="已驗證：全上市當日 OHLC，欄位 Date/Code/Name/OpeningPrice/…，日期是民國 1150831",
    ),
    Candidate(
        name="twse_mi_index",
        url="https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999&response=json",
        expect=(
            "未驗證：證交所網站自己用的每日收盤行情。存它的理由是 openapi 那份實測會"
            "落後一個交易日——台北時間 16:30 還停在前一天，而這一份 00:36 已經是當天的"
        ),
    ),
    Candidate(
        name="tpex_daily_openapi",
        url="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        expect="未驗證：猜是上櫃當日收盤行情",
    ),
    Candidate(
        name="tpex_daily_rwd",
        url="https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?type=EW&response=json",
        expect="未驗證：櫃買改版後的盤後行情路徑",
    ),
    Candidate(
        name="twse_t86_openapi",
        url="https://openapi.twse.com.tw/v1/fund/T86",
        expect="未驗證：猜是上市三大法人買賣超（開放資料版）",
    ),
    Candidate(
        name="twse_t86_rwd",
        url="https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALL&response=json",
        expect="未驗證：證交所網站自己的 T86，沒帶 date 就是最新一日",
    ),
    Candidate(
        name="tpex_insti_openapi",
        url="https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
        expect="未驗證：猜是上櫃三大法人買賣超",
    ),
    Candidate(
        name="cnyes_category_tw_stock",
        url="https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=30",
        expect="已驗證：全市場台股新聞列表，645 篇 22 頁；每篇的 market[].code 是股票代號",
        group="news",
        headers={
            "Origin": "https://www.cnyes.com",
            "Referer": "https://www.cnyes.com/",
        },
    ),
    Candidate(
        name="mops_balance_summary",
        url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb05",
        expect="已驗證：全市場資產負債表彙總（七張表，一般業 1,049 家）。**沒有存貨**",
        group="statements",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
              "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"},
    ),
    Candidate(
        name="mops_cashflow_summary",
        url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb20",
        expect="已驗證：全市場現金流量表彙總（六張表，欄位一致）。上櫃 890 家，"
               "比損益表那張多 8 家。自由現金流量就是靠這一張",
        group="statements",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
              "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"},
    ),
    Candidate(
        name="mops_income_summary",
        url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb04",
        expect="已驗證：全市場綜合損益表彙總。同樣是彙總層級",
        group="statements",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        form={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
              "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"},
    ),
)


def groups() -> list[str]:
    return sorted({c.group for c in CANDIDATES})


def save(out_dir: Path, name: str, body: bytes, meta: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(body)
    from ..store.snapshots import atomic_write  # noqa: PLC0415

    target = atomic_write(out_dir / f"{name}.raw.gz", buf.getvalue())
    atomic_write(
        out_dir / f"{name}.meta.json",
        (json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return target


def load(out_dir: Path, name: str) -> bytes:
    return gzip.decompress((out_dir / f"{name}.raw.gz").read_bytes())


def head(body: bytes, limit: int = 400) -> str:
    text = body[:limit].decode("utf-8", errors="replace")
    return " ".join(text.split())


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
