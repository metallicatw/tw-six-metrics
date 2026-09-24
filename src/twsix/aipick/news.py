"""重大訊息：每天存一份，從裡面挑出財報品質（方案 E）看不到的警訊。

## 來源

* 上市：證交所 openapi `opendata/t187ap04_L`（上市公司每日重大訊息）
* 上櫃：櫃買 openapi `mopsfin_t187ap04_O`

兩支都只給**前一個交易日**的訊息，沒有歷史——所以要每天存。存在
`data/aipick/news/<發言日期>.json.gz`，一天一個檔（同一天跑兩次就合併、去重）。
說明欄只留前 600 字：要的是「發生了什麼」，不是全文。

## 警訊（進方案 E 的紅旗）

| 旗 | 從哪裡看 | 算幾面 | 有效多久 |
|---|---|---|---|
| auditor | 更換簽證會計師，**但不是**事務所內部輪調 | 1 | 180 天 |
| cfo | 財務主管或會計主管異動 | 1 | 180 天 |
| distress | 退票、跳票、重整、破產、繼續經營有疑慮、無法表示意見 | 2 | 365 天 |
| incident | 停工、停產、火災、重大災害 | 1 | 90 天 |

台灣的會計師更換大多是事務所內部輪調（每 7 年強制），那是例行公事，不算。
這些旗子只從**開始存的那一天**起才有——回測期間沒有這份資料，所以它們不影響
回測，只影響今天之後的影子帳戶。
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"
KEEP_CHARS = 600

FLAG_RULES = {
    "auditor": {"weight": 1, "days": 180, "text": "非例行更換簽證會計師"},
    "cfo": {"weight": 1, "days": 180, "text": "財務／會計主管異動"},
    "distress": {"weight": 2, "days": 365, "text": "退票、重整或繼續經營疑慮"},
    "incident": {"weight": 1, "days": 90, "text": "停工、火災或重大災害"},
}


def roc_to_iso(text: str) -> str:
    t = (text or "").strip().replace("/", "")
    if len(t) < 7 or not t.isdigit():
        return ""
    try:
        return date(int(t[:-4]) + 1911, int(t[-4:-2]), int(t[-2:])).isoformat()
    except ValueError:
        return ""


def normalize(raw: dict, market: str) -> dict | None:
    """兩個交易所的欄位名稱不一樣（上市的「主旨」後面還多一個空白）。"""
    code = (raw.get("公司代號") or raw.get("SecuritiesCompanyCode") or "").strip()
    name = (raw.get("公司名稱") or raw.get("CompanyName") or "").strip()
    subject = (raw.get("主旨 ") or raw.get("主旨") or "").strip()
    day = roc_to_iso(raw.get("發言日期") or "")
    if not code or not day or not subject:
        return None
    return {
        "date": day,
        "time": (raw.get("發言時間") or "").strip(),
        "code": code,
        "name": name,
        "market": market,
        "clause": (raw.get("符合條款") or "").strip(),
        "subject": " ".join(subject.split()),
        "body": (raw.get("說明") or "").replace("\r\n", "\n").strip()[:KEEP_CHARS],
    }


def _get_json(url: str, timeout: float = 40.0):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tw-six-metrics)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return json.loads(resp.read().decode("utf-8"))


def news_dir(data_dir: Path) -> Path:
    return data_dir / "aipick" / "news"


def store(data_dir: Path, items: list[dict]) -> int:
    """依發言日期分檔存；同一天的舊檔合併去重。回傳新增幾則。"""
    by_day: dict[str, list[dict]] = {}
    for it in items:
        by_day.setdefault(it["date"], []).append(it)
    added = 0
    folder = news_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for day, new in by_day.items():
        path = folder / f"{day}.json.gz"
        old = load_day(path)
        keys = {(x["code"], x["time"], x["subject"]) for x in old}
        merged = list(old)
        for x in new:
            k = (x["code"], x["time"], x["subject"])
            if k not in keys:
                keys.add(k)
                merged.append(x)
                added += 1
        if len(merged) != len(old):
            merged.sort(key=lambda x: (x["code"], x["time"], x["subject"]))
            raw = json.dumps(merged, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            path.write_bytes(gzip.compress(raw, mtime=0))
    return added


def load_day(path: Path) -> list[dict]:
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return []


def fetch(data_dir: Path, get=None) -> dict:
    """抓兩個交易所今天的重大訊息並存檔。任一邊失敗不影響另一邊。"""
    get = get or _get_json
    items, errors = [], []
    for url, market in ((TWSE_URL, "上市"), (TPEX_URL, "上櫃")):
        try:
            data = get(url)
            if not isinstance(data, list):
                raise ValueError("回應不是清單")
            items += [x for x in (normalize(r, market) for r in data) if x]
        except Exception as exc:  # noqa: BLE001 - 一邊壞掉不能拖垮另一邊
            errors.append(f"{market}：{type(exc).__name__}")
    return {"added": store(data_dir, items), "seen": len(items), "errors": errors}


def load_all(data_dir: Path, since: str = "") -> list[dict]:
    folder = news_dir(data_dir)
    if not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.glob("*.json.gz")):
        if since and f.name[:10] < since:
            continue
        out += load_day(f)
    return out


# ---------------------------------------------------------------------------
# 警訊


def classify(item: dict) -> str:
    """一則重大訊息屬於哪一種警訊（沒有就回空字串）。"""
    s = item.get("subject", "")
    b = item.get("body", "")
    text = s + "\n" + b
    if any(k in text for k in ("退票", "跳票", "存款不足", "聲請重整", "重整裁定", "破產",
                               "繼續經營之能力", "繼續經營能力", "無法表示意見")):
        return "distress"
    if "會計師" in s and any(k in s for k in ("更換", "變更", "異動")):
        routine = ("內部輪調", "內部調整", "內部組織", "輪調", "內部工作調整", "組織調整", "內部職務")
        return "" if any(k in text for k in routine) else "auditor"
    if any(k in s for k in ("財務主管", "會計主管", "財會主管")) and any(
            k in s for k in ("異動", "變動", "更換", "辭任", "解任", "change")):
        return "cfo"
    if any(k in s for k in ("停工", "停產", "火災", "火警", "爆炸", "重大災害", "天然災害")):
        return "incident"
    return ""


class NewsBook:
    """每一檔在某一天「有效中」的重訊警訊。"""

    def __init__(self, items: list[dict]):
        self.events: dict[str, list[tuple[str, str, str]]] = {}
        for it in items:
            flag = classify(it)
            if flag:
                self.events.setdefault(it["code"], []).append((it["date"], flag, it["subject"]))
        for v in self.events.values():
            v.sort()

    def flags(self, code: str, day: str) -> list[tuple[str, str, str]]:
        """(旗, 發言日期, 主旨)，只算 day 以前、還在有效期內的；同一種旗只留最新一則。"""
        out: dict[str, tuple[str, str, str]] = {}
        d0 = date.fromisoformat(day)
        for d, flag, subject in self.events.get(code, []):
            if d > day:
                break
            if date.fromisoformat(d) + timedelta(days=FLAG_RULES[flag]["days"]) < d0:
                continue
            out[flag] = (flag, d, subject)
        return list(out.values())

    def weight(self, code: str, day: str) -> int:
        return sum(FLAG_RULES[f]["weight"] for f, _, _ in self.flags(code, day))
