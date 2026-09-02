"""把候選端點的**真實回應**原封不動存下來。這裡不解析任何東西。

這個專案有一條鐵律：**沒有真實回應就不寫解析器**。原本的 `ingest/` 是照官方
API 文件寫的、從未實跑過，結果九張表裡有六張欄位對錯位——那不是寫錯一行，是
整批資料看起來很正常但都是錯的。

所以流程被切成兩半，而這個模組是前半：

1. `twsix probe` 打一輪候選端點，把回應的位元組原樣存進 `reference/samples/`，
   連同「哪個網址、什麼狀態碼、什麼 Content-Type、多大」的一份 meta。
   **它不解析、不寫進任何資料表**，所以就算某個端點回的東西跟預期天差地遠，
   也不會弄壞任何既有的功能。
2. 有人（或我）真的把那些位元組讀過一遍之後，才寫解析器，而那份樣本同時變成
   測試的定樁。

候選網址全部標著「未驗證」不是客套：它們是**猜測**，probe 的用途正是把猜測換成
事實。哪一個回 200、哪一個回 404、哪一個回了一頁 HTML 說「因為安全性考量」，
存下來才知道。
"""

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
    """一個要去打打看的網址。"""

    name: str
    url: str
    #: 我們**猜**它會回什麼。只寫在這裡給人看，程式不依賴它。
    expect: str
    group: str = "daily"
    headers: dict[str, str] = field(default_factory=dict)


#: 階段二（每日全市場股價與三大法人）需要的端點。
#:
#: 上市的日收盤已經驗證過（`Twse.daily_all()` 用的就是它），仍然存一份樣本，
#: 因為測試需要一個定樁，而「我們相信它長這樣」和「檔案裡就是這樣」是兩件事。
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        name="twse_daily_all",
        url="https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        expect="已驗證：全上市當日 OHLC，欄位 Date/Code/Name/OpeningPrice/…，日期是民國 1150831",
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
    #: 階段一那兩個官方開放資料拿不到的指標（存貨、現金流量）要走公開資訊觀測站的
    #: 彙總報表。表單 POST 回 HTML，最需要先看真實回應的就是它。
    Candidate(
        name="mops_balance_summary",
        url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb05",
        expect="未驗證：猜是資產負債表彙總（含存貨）。POST 表單，可能要帶參數才有內容",
        group="statements",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ),
    Candidate(
        name="mops_cashflow_summary",
        url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb20",
        expect="未驗證：猜是現金流量表彙總。同上",
        group="statements",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ),
)


def groups() -> list[str]:
    return sorted({c.group for c in CANDIDATES})


def save(out_dir: Path, name: str, body: bytes, meta: dict[str, Any]) -> Path:
    """存成 `<name>.raw.gz` + `<name>.meta.json`，兩個都是決定性的。

    壓縮存是因為一份全市場的回應大約 1 MB，而樣本進版控是為了**被讀**，不是為了
    佔空間；gzip 固定 mtime=0，同樣的回應存兩次得到同一個檔案，重跑 probe 不會
    製造假差異。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(body)
    target = out_dir / f"{name}.raw.gz"
    target.write_bytes(buf.getvalue())
    (out_dir / f"{name}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load(out_dir: Path, name: str) -> bytes:
    """把存下來的回應讀回來（寫解析器與測試都從這裡拿）。"""
    return gzip.decompress((out_dir / f"{name}.raw.gz").read_bytes())


def head(body: bytes, limit: int = 400) -> str:
    """回應的開頭，給人在 log 裡一眼看出它到底是什麼。

    「回了 200 但內容是一頁寫著『因為安全性考量』的 HTML」這種事，看狀態碼看不
    出來，看開頭一眼就知道。
    """
    text = body[:limit].decode("utf-8", errors="replace")
    return " ".join(text.split())


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
