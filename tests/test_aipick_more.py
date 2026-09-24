"""〔AI 選股〕第二輪：A 營收驚喜、B 供應鏈連動、C 法說轉折、E 的重訊警訊、LLM、
合併帳戶、個股頁與清單的 AI 標示。

守的是這幾件事：

* 不偷看：SUE 只用那個月以前的誤差；營收在次月 10 日以後才看得到；連動圖只用
  重建那天以前的股價；法說與重訊依「讀進來的那一天」才算數。
* 只往後加：營收第一次看到的日子、法說一覽、法說特徵、LLM 註解、重大訊息。
* 失敗不擴散：LLM 沒金鑰就不呼叫、額度用完就停、金鑰不會出現在任何輸出；
  一個來源壞掉不拖垮其他來源。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import tempfile
import urllib.error
from datetime import date, timedelta
from pathlib import Path

from twsix.aipick import combo as CB
from twsix.aipick import data as D
from twsix.aipick import links as LK
from twsix.aipick import llm as LL
from twsix.aipick import news as NW
from twsix.aipick import quality as Q
from twsix.aipick import relate as RL
from twsix.aipick import revenue as RV
from twsix.aipick import talks as TK

ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# A 營收驚喜


def _series(start_y: int, start_m: int, values: list[float]) -> dict[int, float]:
    k0 = RV.month_key(start_y, start_m)
    return {k0 + n: v for n, v in enumerate(values)}


def test_營收模型是去年同月乘上最近的成長():
    # 每個月都是去年同月 × 1.10：模型應該完全猜中，驚喜是 0
    base = [100 + 10 * (m % 12) for m in range(12)]
    vals = []
    for y in range(4):
        vals += [b * 1.10 ** y for b in base]
    u = RV.surprises(_series(2021, 1, vals))
    assert u, "應該有評分"
    assert all(abs(x) < 1e-9 for x in u.values()), u


def test_一月不單獨評分_二月用一加二月合計():
    vals = [100.0] * 48
    s = _series(2021, 1, vals)
    # 春節從二月搬到一月：一月大、二月小，但合計不變 → 二月的驚喜是 0
    s[RV.month_key(2024, 1)] = 150.0
    s[RV.month_key(2024, 2)] = 50.0
    u = RV.surprises(s)
    assert RV.month_key(2024, 1) not in u
    assert abs(u[RV.month_key(2024, 2)]) < 1e-9


def test_SUE只用那個月以前的誤差():
    vals = [100.0 * (1 + 0.02 * ((m * 7) % 5 - 2)) for m in range(48)]
    s = _series(2021, 1, vals)
    target = RV.month_key(2023, 6)
    before = RV.sue_series(s)[target]
    # 把目標月份**之後**的營收全部改掉：目標月份的 SUE 不能變
    for k in list(s):
        if k > target:
            s[k] *= 3.0
    assert RV.sue_series(s)[target] == before, "SUE 偷看了未來的營收"


def test_營收在次月十日以後才看得到():
    days = []
    d = date(2026, 8, 3)
    while d <= date(2026, 9, 30):
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    p = D.Panel(days, {}, {}, {}, {}, {}, {}, len(days) - 1)
    i = RV.signal_day_index(p, RV.month_key(2026, 8))
    assert days[i] == "2026-09-10", "8 月營收：9/10（週四）晚上才算數"
    # 10 日落在週六 → 下一個交易日
    days2 = [x for x in days if x != "2026-09-10"]
    p2 = D.Panel(days2, {}, {}, {}, {}, {}, {}, len(days2) - 1)
    assert days2[RV.signal_day_index(p2, RV.month_key(2026, 8))] == "2026-09-11"
    # 還沒到的月份
    assert RV.signal_day_index(p, RV.month_key(2026, 9)) == -1


def _write_revenue_sheet(root: Path, code: str, rows: list[tuple[str, int, int | None]]):
    d = root / "sheets" / code
    d.mkdir(parents=True, exist_ok=True)
    grid = [[f"x({code})", "", "", "", "", "", "", ""],
            ["年/月", "營收", "月增率", "去年同期", "年增率", "累計營收", "年增率", ""]]
    for label, v, prior in rows:
        grid.append([label, f"{v:,}", "", "" if prior is None else f"{prior:,}", "", "", "", ""])
    (d / "營收.json.gz").write_bytes(gzip.compress(json.dumps(grid).encode()))


def test_營收分頁讀進來_去年同期往前補一年():
    root = _tmp()
    _write_revenue_sheet(root, "1234", [("115/08", 200, 100), ("115/07", 190, None)])
    s = RV.load_revenue(root)["1234"]
    assert s[RV.month_key(2026, 8)] == 200
    assert s[RV.month_key(2025, 8)] == 100
    assert RV.month_key(2025, 7) not in s


def _write_market_revenue(root: Path, rows: list[tuple[str, str]]):
    folder = root / "market" / "twse_revenue"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "11508.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["公司代號", "資料年月", "營業收入-當月營收", "營業收入-去年當月營收"])
        for code, ym in rows:
            w.writerow([code, ym, "100", "90"])


def test_第一次看到的日子_第一次跑記空白_之後只往後加():
    root = _tmp()
    _write_market_revenue(root, [("1111", "11508")])
    assert RV.record_first_seen(root, "2026-09-05") == 1
    _write_market_revenue(root, [("1111", "11508"), ("2222", "11508")])
    assert RV.record_first_seen(root, "2026-09-08") == 1
    assert RV.record_first_seen(root, "2026-09-09") == 0
    rows = list(csv.DictReader((root / "aipick" / "rev_seen.csv").open(encoding="utf-8")))
    assert rows == [{"code": "1111", "month": "2026-08", "first_seen": ""},
                    {"code": "2222", "month": "2026-08", "first_seen": "2026-09-08"}], (
        "開始記錄以前就公布的，日子是不詳（空白），不是第一次跑的那一天")


# ---------------------------------------------------------------------------
# B 供應鏈連動


def _panel_from_returns(rets: dict[str, list[float]]) -> D.Panel:
    n = len(next(iter(rets.values())))
    d0 = date(2024, 1, 1)
    days = [(d0 + timedelta(days=k)).isoformat() for k in range(n)]
    from array import array

    ret = {c: array("d", r) for c, r in rets.items()}
    close = {}
    for c, r in rets.items():
        px, arr = 100.0, array("d")
        for x in r:
            px *= 1 + (0 if x != x else x)
            arr.append(px)
        close[c] = arr
    return D.Panel(days, close, close, close, {c: array("d", [1e6] * n) for c in rets},
                   ret, {c: "上市" for c in rets}, n - 1)


def _noise(seed: int, n: int) -> list[float]:
    x, out = seed, []
    for _ in range(n):
        x = (1103515245 * x + 12345) % 2**31
        out.append((x / 2**31 - 0.5) * 0.04)
    return out


def test_連動圖找得到一起動的那一對_ETF不當鄰居():
    n = 5 * 60 + 1
    common = _noise(7, n)
    rets = {
        "1111": [c + e * 0.3 for c, e in zip(common, _noise(1, n), strict=False)],
        "2222": [c + e * 0.3 for c, e in zip(common, _noise(2, n), strict=False)],
        "3333": _noise(3, n),
        "4444": _noise(4, n),
    }
    p = _panel_from_returns(rets)
    vecs = LK.weekly_residuals(p, [c for c in rets if not LK.is_fund(c)], p.asof_index)
    g = LK.build_graph(vecs, min_corr=0.3)
    assert g["1111"][0][0] == "2222" and g["1111"][0][1] > 0.5, g
    assert "3333" not in g or all(b != "4444" or r < 0.5 for b, r in g.get("3333", []))
    assert LK.is_fund("0050") and not LK.is_fund("2330")


def test_連動圖只用重建那天以前的股價():
    n = 5 * 70 + 1
    rets = {c: _noise(k + 1, n) for k, c in enumerate(("1111", "2222", "3333"))}
    p = _panel_from_returns(rets)
    end = 5 * 60
    a = LK.weekly_residuals(p, list(rets), end)
    for c in rets:
        for k in range(end + 1, n):
            p.ret[c][k] = 0.5
    b = LK.weekly_residuals(p, list(rets), end)
    assert a == b, "重建那天之後的股價改了，圖卻跟著變——偷看"


# ---------------------------------------------------------------------------
# E 的重訊警訊


def test_兩個交易所的欄位名稱都認得():
    twse = {"出表日期": "1150924", "發言日期": "1150923", "發言時間": "63117", "公司代號": "1101",
            "公司名稱": "台泥", "主旨 ": "公告本公司董事會決議", "符合條款": "第11款",
            "事實發生日": "1150922", "說明": "1.說明\r\n2.內容"}
    tpex = {"Date": "1150923", "發言日期": "1150922", "發言時間": "70003",
            "SecuritiesCompanyCode": "4530", "CompanyName": "天意能創", "主旨": "公告更名",
            "符合條款": "第53款", "事實發生日": "1150708", "說明": "x"}
    a, b = NW.normalize(twse, "上市"), NW.normalize(tpex, "上櫃")
    assert a["code"] == "1101" and a["date"] == "2026-09-23" and a["subject"].startswith("公告本公司")
    assert "\r" not in a["body"]
    assert b["code"] == "4530" and b["name"] == "天意能創" and b["date"] == "2026-09-22"


def test_例行的會計師輪調不算警訊():
    item = {"subject": "公告本公司更換簽證會計師", "body": "變更原因：會計師事務所內部輪調"}
    assert NW.classify(item) == ""
    assert NW.classify({"subject": "公告本公司更換簽證會計師", "body": "原因：業務需要"}) == "auditor"
    assert NW.classify({"subject": "本公司財務主管異動", "body": ""}) == "cfo"
    assert NW.classify({"subject": "澄清媒體報導", "body": "本公司發生存款不足退票"}) == "distress"
    assert NW.classify({"subject": "本公司廠區火災", "body": ""}) == "incident"
    assert NW.classify({"subject": "本公司受邀參加法人說明會", "body": ""}) == ""


def test_重訊一天一檔_同一天跑兩次不會重複():
    root = _tmp()
    it = {"date": "2026-09-23", "time": "1", "code": "1101", "name": "台泥", "market": "上市",
          "clause": "", "subject": "甲", "body": ""}
    assert NW.store(root, [it]) == 1
    assert NW.store(root, [it, {**it, "subject": "乙"}]) == 1
    assert sorted(x["subject"] for x in NW.load_all(root)) == sorted(["甲", "乙"])


def test_重訊一邊壞掉不影響另一邊():
    root = _tmp()

    def get(url):
        if "tpex" in url:
            raise OSError("boom")
        return [{"發言日期": "1150923", "發言時間": "1", "公司代號": "1101", "公司名稱": "台泥",
                 "主旨 ": "甲", "符合條款": "", "說明": ""}]

    st = NW.fetch(root, get=get)
    assert st["added"] == 1 and st["errors"] == ["上櫃：OSError"]


def test_重訊警訊有有效期_退票算兩面_進E的否決():
    items = [{"date": "2026-01-10", "code": "9999", "subject": "本公司發生退票", "body": ""},
             {"date": "2026-09-01", "code": "9999", "subject": "本公司廠區火災", "body": ""}]
    nb = NW.NewsBook(items)
    assert nb.weight("9999", "2026-09-20") == 3
    assert nb.weight("9999", "2025-12-31") == 0, "還沒發生的重訊不能算"
    assert nb.weight("9999", "2027-02-01") == 0, "過了有效期"
    # 財報一面紅旗（本業虧損）＋退票兩面 → 三面 → 否決
    stmts = {"9999": {(115, 1): {"revenue": 100.0, "op_income": -5.0, "pretax": 1.0,
                                  "net_income": 1.0, "non_op": 6.0, "assets": 1000.0,
                                  "liabilities": 100.0, "cfo": 10.0}}}
    qb = Q.QualityBook(stmts, {}, NW.NewsBook(items[:1]))
    v = qb.verdict("9999", "2026-06-01")
    assert "news_distress" in v.flags
    assert v.score == len(v.flags) + 1
    qb0 = Q.QualityBook(stmts, {})
    assert qb.verdict("9999", "2026-06-01").score == qb0.verdict("9999", "2026-06-01").score + 2


# ---------------------------------------------------------------------------
# C 法說


LIST_HTML = """<table id='myTable' class='hasBorder'><thead><tr><th>公司代號</th></tr></thead>
<tr class='even' data-type='body' >
<td style='text-align:left !important;'>1101</td><td>台泥</td>
<td align='center'>115/08/31</td>
<td align='center'>14:00</td>
<td style='text-align:left !important;'>富邦金融大樓</td>
<td style='text-align:left !important;'>本公司受邀參加富邦證券舉辦之法人座談會，
會中說明本公司營運簡介</td>
<td style='text-align:left !important;'><a href='#' onclick='document.fm_fileDownload.fileName.value="110120260829M002.pdf";document.fm_fileDownload.submit();'><font color='blue'><u>110120260829M002.pdf</u></font></a></td>
<td style='text-align:left !important;'><a href='#' onclick='x'><font color='blue'><u>110120260829E002.pdf</u></font></a></td>
<td>網站</td><td>影音</td><td>無</td><td align='center'><input type='button'></td>
</tr>
<tr class='odd' data-type='body' >
<td>1102</td><td>亞泥</td><td align='center'>115/08/17</td><td>14:00</td><td>線上</td>
<td>亞洲水泥舉辦2026年第二季線上法說會</td><td></td><td></td><td></td><td></td><td></td><td></td>
</tr></table>"""


def test_法說一覽表解析():
    rows = TK.parse_list(LIST_HTML)
    assert rows[0]["code"] == "1101" and rows[0]["date"] == "2026-08-31"
    assert rows[0]["file"] == "110120260829M002.pdf" and rows[0]["file_en"] == "110120260829E002.pdf"
    assert "營運簡介" in rows[0]["summary"]
    assert rows[1]["code"] == "1102" and rows[1]["file"] == ""


def test_法說一覽只往後加_未來的場次不收():
    root = _tmp()
    future = LIST_HTML.replace("115/08/17", "115/12/17")
    assert TK.fetch_list(root, date(2026, 9, 24), post=lambda url, form: future)["new"] == 1
    assert TK.fetch_list(root, date(2026, 9, 24), post=lambda url, form: LIST_HTML)["new"] == 1
    assert TK.fetch_list(root, date(2026, 9, 25), post=lambda url, form: LIST_HTML)["new"] == 0
    assert [r["code"] for r in TK.read_index(root)] == ["1101", "1102"]


def test_簡報取重點頁_跳過免責聲明():
    pages = ["免責聲明 本簡報含前瞻性敘述 審慎", "營收 100", "未來展望：下半年成長、產能滿載"]
    t = TK.focus_text(pages)
    assert "免責" not in t and t.startswith("未來展望")
    f = TK.rule_features("成長 成長 滿載 衰退")
    assert f["pos"] == 3 and f["neg"] == 1 and f["tone"] > 0


def test_LLM回的欄位被夾在合理範圍():
    x = TK.clean_llm({"revenue_outlook": 9, "margin_outlook": "-5", "capex": 3, "utilization": 400,
                      "tone": "abc", "hedging": 7, "highlights": ["a" * 99, "b", "c", "d"]})
    assert x["revenue_outlook"] == 2 and x["margin_outlook"] == -2 and x["capex"] == 1
    assert x["utilization"] == 150 and x["tone"] == 0 and x["hedging"] == 1
    assert len(x["highlights"]) == 3 and len(x["highlights"][0]) == 40
    assert TK.clean_llm("不是物件") is None


def _feat(code, day, file, tone=None, llm=None, processed=None):
    return {"code": code, "date": day, "file": file, "processed": processed or day,
            "rules": {"tone": tone or 0.0}, "llm": llm}


def _llm(r, m, t):
    return {"revenue_outlook": r, "margin_outlook": m, "tone": t, "summary": "s",
            "highlights": [], "risks": []}


def test_轉折只拿同一種讀法比_讀進來那天才算():
    feats = {
        "a": _feat("1111", "2026-05-01", "a", llm=_llm(1, 1, 1)),
        "b": _feat("1111", "2026-06-01", "b", tone=0.9),                 # 只有規則
        "c": _feat("1111", "2026-08-01", "c", llm=_llm(-1, 0, -1), processed="2026-08-05"),
    }
    tb = TK.TalkBook(feats)
    assert tb.latest("1111", "2026-08-03").file == "b", "8/5 才讀進來的簡報，8/3 看不到"
    t = tb.latest("1111", "2026-08-06")
    assert t.method == "llm" and t.prev_date == "2026-05-01", "LLM 只和上一次 LLM 比"
    assert t.score == (-1 + 0 - 1) - (1 + 1 + 1) and t.kind == "負轉折"
    assert tb.negative("1111", "2026-09-01") is not None
    assert tb.negative("1111", "2027-01-01") is None, "負轉折 120 天後失效"


# ---------------------------------------------------------------------------
# LLM


class _Resp:
    def __init__(self, obj):
        self.raw = json.dumps(obj).encode()


def _ok(text):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()


def _http_error(code, msg=""):
    return urllib.error.HTTPError("https://x", code, "err", {},
                                  io.BytesIO(json.dumps({"error": {"message": msg}}).encode()))


def test_沒有金鑰就不呼叫():
    calls = []
    g = LL.Gemini("", post=lambda *a: calls.append(a))
    assert not g.enabled and g.ask_json("hi") is None and calls == []


def test_金鑰放在標頭_不放網址_不出現在任何輸出():
    key = "AIzaFAKEKEY_for_test_1234567890"
    seen = []

    def post(url, body, headers, timeout):
        seen.append((url, headers))
        raise _http_error(400, f"API key {key} is bad")

    g = LL.Gemini(key, post=post, sleep=lambda s: None)
    assert g.ask_json("hi") is None
    url, headers = seen[0]
    assert key not in url and headers["x-goog-api-key"] == key
    assert key not in json.dumps(g.status(), ensure_ascii=False), "金鑰跑進狀態裡了"
    assert "***" in g.errors[-1]


def test_型號不存在就換下一個_額度用完就整趟停():
    urls = []

    def post(url, body, headers, timeout):
        urls.append(url)
        if "first" in url:
            raise _http_error(404)
        return _ok('```json\n{"a": 1}\n```')

    g = LL.Gemini("k", models=["first", "second"], post=post, sleep=lambda s: None)
    assert g.ask_json("hi") == {"a": 1} and g.model_used == "second"

    def post429(url, body, headers, timeout):
        raise _http_error(429, "quota")

    g2 = LL.Gemini("k", models=["m"], post=post429, sleep=lambda s: None)
    try:
        g2.ask_json("hi")
        raise AssertionError("429 應該丟 QuotaExhausted")
    except LL.QuotaExhausted:
        pass
    assert not g2.enabled, "額度用完之後這一趟不再呼叫"


def test_每一趟有呼叫次數上限():
    g = LL.Gemini("k", models=["m"], max_calls=2, post=lambda *a: _ok("{}"), sleep=lambda s: None)
    g.ask_json("1")
    g.ask_json("2")
    assert not g.enabled
    try:
        g.ask_json("3")
        raise AssertionError("超過上限應該停")
    except LL.QuotaExhausted:
        pass


def test_LLM註解每一對只問一次():
    root = _tmp()
    asked = []

    def post(url, body, headers, timeout):
        asked.append(body)
        return _ok('{"relation": "供應商", "confidence": 0.8, "note": "PCB"}')

    g = LL.Gemini("k", models=["m"], post=post, sleep=lambda s: None)
    names = {"1111": "甲", "2222": "乙"}
    assert RL.label_pairs(root, g, [("1111", "2222")], names, date(2026, 9, 24))["labelled"] == 1
    assert RL.label_pairs(root, g, [("1111", "2222")], names, date(2026, 9, 25))["labelled"] == 0
    assert len(asked) == 1
    rec = RL.load(root)["1111>2222"]
    assert rec["relation"] == "供應商" and rec["confidence"] == 0.8
    assert RL.clean({"relation": "亂寫"})["relation"] == "無明確關係"


def test_抓取那一趟_每一段各自失敗_狀態不含金鑰():
    from twsix.aipick import fetch as FT

    root = _tmp()
    key = "AIzaSECRET_should_never_be_written"

    def bad(*a, **k):
        raise OSError("offline")

    g = LL.Gemini(key, models=["m"], post=bad, sleep=lambda s: None)
    st = FT.fetch_all(root, today=date(2026, 9, 24), llm=g, news_get=bad, list_post=bad,
                      pdf_get=bad)
    assert st["news"]["errors"] and st["talks_list"]["errors"]
    saved = (root / "aipick" / "fetch_status.json").read_text(encoding="utf-8")
    assert key not in saved
    for f in root.rglob("*"):
        if f.is_file():
            assert key.encode() not in f.read_bytes(), f"{f} 裡有金鑰"


def test_程式裡沒有寫死任何金鑰():
    import re

    pat = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-ant-[0-9A-Za-z_\-]{10,}")
    for f in (ROOT / "src").rglob("*.py"):
        assert not pat.search(f.read_text(encoding="utf-8")), f
    for f in (ROOT / ".github").rglob("*.yml"):
        assert not pat.search(f.read_text(encoding="utf-8")), f


# ---------------------------------------------------------------------------
# 合併帳戶


class _Pick:
    def __init__(self, code, strategy, score=0.9):
        self.code, self.name, self.industry, self.score = code, code, "x", score
        self.close, self.reasons, self.strategy = 10.0, ["r"], strategy

    @property
    def note(self):
        return "n"


class _M:
    def __init__(self, name, days, picks, p=None):
        self.name, self.signal_days, self._picks = name, days, picks
        self.new_per_signal = 5
        self.p = p
        self.exits = []

    def signal(self, day):
        class S:
            pass

        s = S()
        s.candidates = self._picks.get(day, [])
        return s

    def entry_stop(self, code, i, price, strategy=""):
        return price - 1

    def exit_check(self, code, i, entry_i, stop, regime, strategy=""):
        self.exits.append(code)
        return "", "", stop


def test_合併帳戶輪流挑_三套同時看好的排最前面():
    import dataclasses

    @dataclasses.dataclass
    class P:
        code: str
        strategy: str
        reasons: list
        name: str = ""
        industry: str = ""
        score: float = 0.9
        close: float = 10.0

    a = _M("A", ["d1"], {"d1": [P("1", "A", ["a"]), P("2", "A", ["a"]), P("9", "A", ["a"])]})
    b = _M("B", ["d1"], {"d1": [P("3", "B", ["b"]), P("9", "B", ["b"])]})
    d = _M("D", ["d1", "d2"], {"d1": [P("4", "D", ["d"])]})
    c = CB.Combined([a, b, d])
    got = c.signal("d1").candidates
    assert got[0].code == "9" and got[0].reasons[0].startswith("同時符合 A、B")
    assert [x.code for x in got[1:]] == ["1", "4", "3", "2"], "A → D → B 輪流"
    assert c.signal_days == ["d1", "d2"]
    assert a.signal("d1").candidates[2].reasons == ["a"], "不能改到原本那一套的候選"


def test_法說負轉折_不買也提早出場():
    class Talks:
        def negative(self, code, day):
            if code == "1" and day >= "d1":
                return TK.Turn("1", "d1", "d0", "llm", -3.0, -2, "", [], [], "f")
            return None

    class Pn:
        dates = ["d0", "d1", "d2"]

    a = _M("A", ["d1"], {"d1": [_Pick("1", "A"), _Pick("2", "A")]}, p=Pn())
    c = CB.Combined([a], talks=Talks())
    assert [x.code for x in c.signal("d1").candidates] == ["2"]
    when, why, _ = c.exit_check("1", 2, 0, 5.0, None, strategy="A")
    assert when == "next" and "法說負轉折" in why
    assert c.exit_check("2", 2, 0, 5.0, None, strategy="A")[0] == ""


# ---------------------------------------------------------------------------
# 個股頁與清單


def test_個股摘要拆成一檔一個檔_清單標籤():
    from twsix.report.ai_page import write_stock_json

    root = _tmp()
    (root / "aipick").mkdir(parents=True)
    data = {"asof": "2026-09-23", "strategy_text": {"A": "A 營收驚喜"}, "feature_text": {},
            "stocks": {"1111": {"name": "甲", "candidate": ["A", "B"]},
                       "2222": {"name": "乙", "held": {"strategy": "D"}},
                       "3333": {"name": "丙", "e": {"veto": True}},
                       "4444": {"name": "丁"},
                       "../x": {"name": "壞"}}}
    (root / "aipick" / "stocks.json.gz").write_bytes(gzip.compress(json.dumps(data).encode()))
    out = _tmp()
    assert write_stock_json(root, out) == 4
    one = json.loads((out / "ai" / "stock" / "1111.json").read_text(encoding="utf-8"))
    assert one["code"] == "1111" and one["asof"] == "2026-09-23"
    marks = json.loads((out / "ai" / "marks.json").read_text(encoding="utf-8"))["marks"]
    assert marks == {"1111": "AI 候選・AB", "2222": "AI 持有・D", "3333": "財報否決"}
    assert not (out / "ai" / "x.json").exists()
    assert write_stock_json(_tmp(), _tmp()) == 0, "沒有資料就什麼都不寫"


def test_個股頁有AI分頁_內容是點開才抓():
    tpl = (ROOT / "src/twsix/report/templates/stockpage.html.j2").read_text("utf-8")
    assert 'id="tab-ai"' in tpl and 'id="panel-ai"' in tpl
    assert 'data-src="{{ rel }}ai/stock/{{ p.stock_id }}.json"' in tpl
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    block = js[js.index("var panel = document.getElementById('panel-ai');"):]
    block = block[:block.index("})();")]
    assert "innerHTML" in block and "esc(" in block
    # 每一段資料字串都要經過 esc()——重訊與 LLM 的摘要不能直接當 HTML
    for field in ("t.summary", "n.note", "n.name", "x)"):
        assert f"esc({field}" in block or field == "x)", field


def test_清單的AI標籤不改變排序與搜尋():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    block = js[js.index("fetch(rel + 'ai/marks.json'"):]
    block = block[:block.index("})();")]
    assert "setAttribute('data-ai'" in block
    assert "textContent" not in block and "innerHTML" not in block, \
        "標籤要畫在 ::after，不能塞進格子的文字裡"
    css = (ROOT / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert "#t td[data-ai]::after{content:attr(data-ai)" in css


# ---------------------------------------------------------------------------
# 排程


def test_排程_抓取與計算分兩步_金鑰只給抓取那一步():
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert 'pip install -e ".[report,ai]"' in wf
    steps = wf.split("\n      - ")
    fetch = next(s for s in steps if s.startswith("name: AI 選股：重大訊息"))
    calc = next(s for s in steps if s.startswith("name: AI 選股\n"))
    for s in (fetch, calc):
        assert "continue-on-error: true" in s and "timeout-minutes:" in s and '|| echo "::error::' in s
    assert "GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}" in fetch
    assert wf.count("secrets.GEMINI_API_KEY") == 1, "金鑰只能交給抓取那一步"
    assert sum("secrets.GEMINI_API_KEY" in s for s in steps if s.startswith("name:")) == 1
    assert wf.index("AI 選股：重大訊息") < wf.index("- name: AI 選股\n") < wf.index("- name: Commit")
    toml = (ROOT / "pyproject.toml").read_text("utf-8")
    assert 'ai = ["pypdf' in toml


def test_沒有pypdf也能跑():
    assert TK.pdf_pages(b"not a pdf") == []
    assert math.isfinite(TK.rule_features("")["tone"])


def _stats(total):
    return {"start": "2025-01-02", "end": "2026-09-23", "total": total, "cagr": total / 2,
            "mdd": -0.1, "sharpe": 0.5, "trades": 10, "win_rate": 0.5, "avg_ret": 0.01,
            "profit_factor": 1.2, "avg_days": 20.0}


def _block(total):
    return {"stats": _stats(total), "curve": {"dates": ["2025-01-02", "2026-09-23"],
                                              "values": [1.0, 1 + total]},
            "by_strategy": {"A": {"trades": 3, "avg_ret": 0.02, "win_rate": 0.6}}}


def test_AI頁面用新格式的資料畫得出來_讀法沒有寫死數字():
    from test_aipick import _env_and_base
    from twsix.report.build import _write_ai_page

    data = _tmp()
    (data / "aipick").mkdir()
    pick_a = {"code": "1111", "name": "甲<script>", "industry": "x", "score": 0.95, "close": 10,
              "reasons": ["r"], "strategy": "A", "six": None, "flags": [],
              "turn": {"date": "2026-09-01", "prev_date": "", "method": "rules", "score": -2.4,
                       "kind": "負轉折", "level": 0, "summary": "", "highlights": [], "risks": [],
                       "file": "f"},
              "extra": {"sue": 2.1, "prev_sue": 1.0, "yoy": 0.3, "month": "2026-08"}}
    pick_b = {**pick_a, "code": "2222", "strategy": "B", "turn": None,
              "extra": {"nm": 0.1, "own": -0.02, "gap": 0.12},
              "neighbors": [{"code": "3333", "name": "丙", "corr": 0.5, "relation": "客戶",
                             "confidence": 0.7, "note": "n"}]}
    today = {"asof": "2026-09-23", "generated_at": "x", "regime_now": None, "regime_in_force": None,
             "candidates": [], "weights": {}, "universe": 0, "feature_text": {}, "flag_text": {},
             "strategy_text": {"A": "A 營收驚喜", "B": "B 供應鏈連動", "D": "D 籌碼共振"},
             "a": {"day": "2026-09-10", "month": "2026-08", "universe": 1900, "candidates": [pick_a]},
             "b": {"day": "2026-09-19", "graph_day": "2026-07-03", "universe": 1800,
                   "candidates": [pick_b]},
             "vetoes": [], "veto_count": 0, "rated": 0, "news_flags": [], "turns": [],
             "breadth": {}, "fetch": {"llm": {"enabled": False}}}
    bt = {"A": {"horizon": _block(0.123), "plan": _block(-0.05), "bench": _block(0.9),
                "bench_f": _block(0.5), "bench_ew": _block(0.4),
                "signal": {"mean_excess": 0.0071, "hit": 12, "periods": 23}},
          "B": {"horizon": _block(0.065), "bench": _block(0.9), "bench_f": _block(0.5),
                "bench_ew": _block(0.4), "signal": {"mean_excess": 0.01, "hit": 60, "periods": 100}},
          "D": {"horizon": _block(0.04), "plan": _block(0.003), "bench": _block(0.9),
                "bench_f": _block(0.5), "bench_ew": _block(0.4),
                "signal": {"mean_excess": 0.0167, "hit": 20, "weeks": 40, "ic": {}, "ic_weeks": {}}},
          "ALL": {"since_d": {**_block(0.111), "bench": _block(0.902), "bench_f": _block(0.48),
                              "bench_ew": _block(0.525)},
                  "full": {**_block(-0.045), "bench": _block(1.7), "bench_f": _block(0.8),
                           "bench_ew": _block(0.5)}},
          "F": {"timed": _block(1.18), "bench": _block(2.6), "state_days": {"中性": 10}},
          "E": {"rows": [], "horizon": 60}}
    port = {"live_start": "2026-09-24", "rules": "合併帳戶", "equity0": 1e6, "dates": [],
            "equity": [], "bench": [], "positions": [], "trades": [], "by_strategy": {}}
    for name, obj in (("today.json", today), ("backtest.json", bt), ("portfolio.json", port)):
        (data / "aipick" / name).write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    out = _tmp() / "site"
    env, base = _env_and_base(out)
    assert _write_ai_page(env, base, out, data) == 1
    html = (out / "ai.html").read_text("utf-8")
    assert "暫時無法顯示" not in html
    assert "+11.1%" in html and "+90.2%" in html, "讀法的數字要來自 backtest.json"
    assert "甲&lt;script&gt;" in html and "甲<script>" not in html
    assert "負轉折" in html and "客戶" in html
    for cid in ("ai-all-chart", "ai-a-chart", "ai-b-chart", "ai-d-chart", "ai-f-chart"):
        assert f'id="{cid}"' in html, cid
