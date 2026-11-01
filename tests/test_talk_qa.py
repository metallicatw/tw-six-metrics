from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from twsix.aipick import talk_qa as TQ
from twsix.aipick import talks as TK
from twsix.report import talks_page as TP

FUGLE_PAGE = """<html><body><h2>發布團隊</h2><p>x</p>
<article><h2><span>1. 台光電營運摘要</span></h2><p>營收 608 億元，季增 28.8%。</p>
<h2>6. 台光電展望與指引</h2><ul><li>第四季展望：公司預期 2026Q4 營收將季增 15% 至 20%，毛利率 38% 至 39.5%</li></ul>
<h2><span><strong>7. 台光電 Q&amp;A 重點</strong></span></h2>
<p><strong>Q1: 資本支出多少？</strong></p><p>A1: 預計每年約 <strong>530 億元</strong>。設備交期拉長。</p>
<p><strong>Q2: ASIC 載板進度？</strong></p><p>A2: 2026 年底認證，2027 年出貨。</p>
<h3>免責聲明</h3><p>請查閱<a href="https://mopsov.twse.com.tw/nas/STR/238320261028M001.pdf">簡報</a></p>
</article><h2>你可能會有興趣</h2><p>Q: 不要 A: 讀到</p></body></html>"""

BIGGO_PAGE = """<h2>摘要</h2><p>營運創新高</p><h2>公司正式指引</h2><p>第四季營收預估季增15%至20%</p>
<h2>QA 重點</h2><div><p><strong>Q: 漲價原因？</strong> A: 主要反映原物料上漲。</p>
<p><strong>Q: M10 進度？</strong> A: 預計年底認證。</p></div><h2>逐字稿</h2><p>Q: 不要 A: 逐字稿</p>"""


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _index(root: Path, rows: list[tuple]) -> None:
    d = root / "aipick" / "talks"
    d.mkdir(parents=True, exist_ok=True)
    lines = [",".join(TK.INDEX_FIELDS)]
    for code, day, summ, f in rows:
        lines.append(f"{code},名{code},{day},14:00,{summ},{f},,{day}")
    (d / "index.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


class Net:
    """假的網路：網址 → (狀態, 內容)；記錄每一次請求。"""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        return self.pages.get(url, (404, ""))


def _polite(pages) -> tuple[TQ.Polite, Net]:
    net = Net({"https://blog.fugle.tw/robots.txt": (200, "User-Agent: *\nAllow: /\nDisallow: /api/"),
               "https://finance.biggo.com.tw/robots.txt": (200, "User-Agent: *\nDisallow: /agent/"),
               **pages})
    return TQ.Polite(get=net, sleep=lambda s: None, clock=lambda: 0.0), net


SITEMAP = ('<sitemapindex><sitemap><loc>https://blog.fugle.tw/sitemap-post-1.xml</loc></sitemap>'
           '<sitemap><loc>https://blog.fugle.tw/sitemap-page.xml</loc></sitemap></sitemapindex>')
POSTS = ('<urlset><url><loc>https://blog.fugle.tw/post/earnings-call-2383-2026-10-29</loc></url>'
         '<url><loc>https://blog.fugle.tw/post/earnings-call-2383-2026-08-27</loc></url>'
         '<url><loc>https://blog.fugle.tw/post/other-article</loc></url></urlset>')


class LLM:
    enabled = True
    model_used = "gemini-test"

    def __init__(self, reply=None, quota=False):
        self.reply, self.quota, self.prompts = reply, quota, []

    def ask_json(self, prompt, **kw):
        self.prompts.append(prompt)
        if self.quota:
            from twsix.aipick.llm import QuotaExhausted
            raise QuotaExhausted("x")
        return self.reply


def test_切段_挑出QA與展望_略過逐字稿與推薦文():
    for page in (FUGLE_PAGE, BIGGO_PAGE):
        qa, guide = TQ.pick(TQ.sections(page))
        pairs = TQ.parse_qa(qa)
        assert len(pairs) == 2, pairs
        assert all("不要" not in q for q, _ in pairs)
        assert "15%" in guide
    q, a = TQ.parse_qa(TQ.pick(TQ.sections(FUGLE_PAGE))[0])[0]
    assert q == "資本支出多少？" and a.startswith("預計每年約 530 億元")
    assert TQ.mops_file(FUGLE_PAGE) == "238320261028M001.pdf"


def test_ASIC這種字不會被當成回答():
    pairs = TQ.parse_qa("Q: ASIC 載板？ A: 首個 ASIC: 專案年底認證。\nQ: 其他？ A: 沒有。")
    assert pairs == [("ASIC 載板？", "首個 ASIC: 專案年底認證。"), ("其他？", "沒有。")]


def test_沒有金鑰只留每則第一句_指引只留帶數字的預估句():
    r = TQ.rules("Q1: 問題一很長很長？\nA1: 第一句回答很重要。第二句不要。",
                 "【展望】\n公司預期明年營收成長 15%。\n我們很努力")
    assert r["qa"] == [{"q": "問題一很長很長？", "a": "第一句回答很重要。"}]
    assert r["guidance"] == ["公司預期明年營收成長 15%"]


def test_robots不允許就不連_被擋就整趟停用那個網站():
    net = Net({"https://blog.fugle.tw/robots.txt": (200, "User-Agent: *\nDisallow: /post/")})
    p = TQ.Polite(get=net, sleep=lambda s: None)
    assert p.get("https://blog.fugle.tw/post/earnings-call-2383-2026-10-29") == (-1, "")
    assert net.calls == ["https://blog.fugle.tw/robots.txt"]
    p2, net2 = _polite({"https://finance.biggo.com.tw/a": (429, "")})
    assert p2.get("https://finance.biggo.com.tw/a")[0] == -1
    assert p2.get("https://finance.biggo.com.tw/b")[0] == -1
    assert "https://finance.biggo.com.tw/b" not in net2.calls
    p3, _ = _polite({"https://blog.fugle.tw/x": (200, "<title>Just a moment...</title>")})
    assert p3.get("https://blog.fugle.tw/x")[0] == -1 and "blog.fugle.tw" in next(iter(p3.blocked))


def test_同一個網站兩次請求之間會等():
    waits, now = [], [100.0]
    net = Net({"https://blog.fugle.tw/robots.txt": (200, ""), "https://blog.fugle.tw/a": (200, "ok"),
               "https://blog.fugle.tw/b": (200, "ok")})
    p = TQ.Polite(get=net, sleep=waits.append, clock=lambda: now[0])
    p.get("https://blog.fugle.tw/a")
    p.get("https://blog.fugle.tw/b")
    assert waits and all(abs(w - TQ.GAP) < 1e-9 for w in waits)


def test_富果場次清單從sitemap來_半天內不重抓():
    root = _tmp()
    p, net = _polite({TQ.FUGLE_SITEMAP: (200, SITEMAP), "https://blog.fugle.tw/sitemap-post-1.xml": (200, POSTS)})
    idx = TQ.fugle_index(root, p, now=1000.0)
    assert idx == {"2383": ["2026-08-27", "2026-10-29"]}
    n = len(net.calls)
    assert TQ.fugle_index(root, p, now=1000.0 + 3600) == idx
    assert len(net.calls) == n


def _pages_2383():
    return {TQ.FUGLE_SITEMAP: (200, SITEMAP), "https://blog.fugle.tw/sitemap-post-1.xml": (200, POSTS),
            TQ.FUGLE_POST.format(code="2383", date="2026-10-29"): (200, FUGLE_PAGE),
            TQ.BIGGO_POST.format(code="2383", date="2026-10-29"): (200, BIGGO_PAGE)}


REPLY = {"qa": [{"q": "資本支出？", "a": "2027、2028 每年約 530 億元（來源說法不一）"}],
         "guidance": ["4Q26 營收季增 15%～20%"], "points": ["第四季全產品線漲價 5%～20%"],
         "revenue_outlook": 2, "margin_outlook": 1, "tone": 2, "capex": 1}


def test_整套流程_兩個來源合併給Gemini_結果寫進特徵檔但簡報特徵讀不到它():
    root = _tmp()
    _index(root, [("2383", "2026-10-29", "受邀參加高盛線上座談會", "238320261028M001.pdf")])
    p, net = _polite(_pages_2383())
    llm = LLM(REPLY)
    r = TQ.fetch(root, llm, today=date(2026, 11, 1), net=p,
                 targets=TQ.targets_for(TK.read_index(root), ["2383"], date(2026, 11, 1), recent_days=30))
    assert r["found"] == 1 and r["llm"] == 1
    assert "富果研究" in llm.prompts[0] and "BigGo" in llm.prompts[0] and "530 億元" in llm.prompts[0]
    qa = TQ.read_qa(root)
    rec = qa["qa:2383:2026-10-29"]
    assert rec["talk_file"] == "238320261028M001.pdf"
    assert [s["site"] for s in rec["sources"]] == [TQ.FUGLE, TQ.BIGGO]
    assert rec["llm"]["qa"][0]["q"] == "資本支出？" and rec["llm"]["v"] == TQ.QA_V
    assert TK.read_features(root) == {}
    # 再跑一次：已經有 Gemini 版，不再連網
    n = len(net.calls)
    TQ.fetch(root, llm, today=date(2026, 11, 2), net=p, targets=TQ.targets_for(TK.read_index(root), ["2383"],
                                                                                date(2026, 11, 2), recent_days=30))
    assert len(net.calls) == n


def test_額度用完不會用規則版蓋掉之前的Gemini版():
    root = _tmp()
    _index(root, [("2383", "2026-10-29", "x", "f.pdf")])
    TK._append_features(root, [{"file": "qa:2383:2026-10-29", "kind": "qa", "code": "2383", "date": "2026-10-29",
                                "processed": "2026-10-30", "source": "qa", "sources": [],
                                "llm": None, "rules": {"qa": [], "guidance": ["舊"]}}])
    p, _ = _polite(_pages_2383())
    TQ.fetch(root, LLM(REPLY), today=date(2026, 11, 1), net=p,
             targets=TQ.targets_for(TK.read_index(root), ["2383"], date(2026, 11, 1), recent_days=30))
    assert TQ.read_qa(root)["qa:2383:2026-10-29"]["llm"]
    p2, _ = _polite(_pages_2383())
    TQ.fetch(root, LLM(quota=True), today=date(2026, 11, 3), net=p2,
             targets=TQ.targets_for(TK.read_index(root), ["2383"], date(2026, 11, 3), recent_days=30))
    assert TQ.read_qa(root)["qa:2383:2026-10-29"]["llm"]


def test_較早又沒有富果文章的場次_不連網也不留記錄_最近的找不到會留下並隔天再找():
    root = _tmp()
    _index(root, [("1101", "2025-03-01", "受邀參加券商論壇", "a.pdf"), ("1101", "2026-10-30", "受邀參加論壇", "b.pdf")])
    p, net = _polite({TQ.FUGLE_SITEMAP: (200, SITEMAP), "https://blog.fugle.tw/sitemap-post-1.xml": (200, POSTS)})
    today = date(2026, 11, 1)
    TQ.fetch(root, None, today=today, net=p,
             targets=TQ.targets_for(TK.read_index(root), ["1101"], today, recent_days=30))
    qa = TQ.read_qa(root)
    assert list(qa) == ["qa:1101:2026-10-30"] and qa["qa:1101:2026-10-30"]["miss"]
    assert not any("2025-03-01" in u for u in net.calls)
    assert TQ._due(qa["qa:1101:2026-10-30"], "2026-10-30", date(2026, 11, 2), None)
    assert not TQ._due(qa["qa:1101:2026-10-30"], "2026-10-30", date(2026, 11, 20), None)


def test_較早的季別只猜公司自己辦的那一場_一季一次():
    root = _tmp()
    _index(root, [("1101", "2025-05-02", "說明本公司財務業務", "a.pdf"), ("1101", "2025-05-20", "說明營運概況", "a.pdf"),
                  ("1101", "2025-05-10", "受邀參加券商論壇", "a.pdf")])
    p, net = _polite({TQ.FUGLE_SITEMAP: (200, SITEMAP), "https://blog.fugle.tw/sitemap-post-1.xml": (200, POSTS)})
    TQ.fetch(root, None, today=date(2026, 11, 1), net=p,
             targets=TQ.targets_for(TK.read_index(root), ["1101"], date(2026, 11, 1)))
    guesses = [u for u in net.calls if "biggo" in u and "robots" not in u]
    assert guesses == [TQ.BIGGO_POST.format(code="1101", date="2025-05-02")]


def test_同一季其他場次也會找_富果文章對到日期相同的那一場():
    rows = [{"code": "2383", "name": "台光電", "date": d, "summary": "受邀", "file": "238320260729M001.pdf"}
            for d in ("2026-08-05", "2026-08-26", "2026-08-27")]
    t = TQ.targets_for(rows, ["2383"], date(2026, 11, 1))
    assert {r["date"] for r in t} == {"2026-08-05", "2026-08-26", "2026-08-27"}
    root = _tmp()
    _index(root, [(r["code"], r["date"], r["summary"], r["file"]) for r in rows])
    p, net = _polite({**_pages_2383(),
                      TQ.FUGLE_POST.format(code="2383", date="2026-08-27"): (200, FUGLE_PAGE)})
    TQ.fetch(root, None, today=date(2026, 11, 1), net=p, targets=t)
    qa = TQ.read_qa(root)
    assert "qa:2383:2026-08-27" in qa and "qa:2383:2026-08-26" not in qa
    assert net.calls.count(TQ.FUGLE_POST.format(code="2383", date="2026-08-27")) == 1


def _feat(day: str, file: str, llm=None) -> dict:
    return {"code": "2383", "name": "台光電", "date": day, "file": file, "processed": day, "source": "pdf",
            "rules": {"pos": 1, "neg": 0, "tone": 0.2}, "llm": llm}


def _qa_rec(day: str, talk_file: str, **x) -> dict:
    return {"file": TQ.key("2383", day), "kind": "qa", "code": "2383", "date": day, "talk_file": talk_file,
            "source": "qa", "sources": [{"site": TQ.FUGLE, "url": TQ.FUGLE_POST.format(code="2383", date=day)}],
            "llm": {**REPLY, **x, "v": 1}, "rules": {"qa": [], "guidance": []}}


def test_簡報沒有解讀時_法說轉折用QA的展望判斷():
    feats = {"a.pdf": _feat("2026-07-29", "a.pdf"), "b.pdf": _feat("2026-10-29", "b.pdf")}
    qa = {TQ.key("2383", "2026-07-30"): _qa_rec("2026-07-30", "a.pdf", revenue_outlook=0, margin_outlook=0, tone=0),
          TQ.key("2383", "2026-10-29"): _qa_rec("2026-10-29", "b.pdf")}
    t = TK.TalkBook(feats, qa=qa).latest("2383", "2026-11-01")
    assert t.method == "llm" and t.kind == "正轉折" and t.score == 5.0
    assert "公司指引：4Q26 營收季增 15%～20%" in t.why
    assert TK.TalkBook(feats).latest("2383", "2026-11-01").method == "rules"


def test_簡報解讀沒有指引時補上口頭指引():
    slide = {"revenue_outlook": 1, "margin_outlook": 0, "tone": 1, "capex": 0, "utilization": None,
             "new_business": False, "hedging": 0, "highlights": ["h"], "guidance": [], "risks": [], "summary": "s"}
    rec = TK.with_qa(_feat("2026-10-29", "b.pdf", slide), {"k": _qa_rec("2026-10-29", "b.pdf")})
    assert rec["llm"]["guidance"] == ["4Q26 營收季增 15%～20%"] and rec["llm"]["revenue_outlook"] == 1


def test_個股頁法說會資料附上QA_同一季別場的也算():
    rows = [{"code": "2383", "name": "台光電", "date": "2026-08-05", "time": "", "summary": "受邀", "file": "a.pdf"},
            {"code": "2383", "name": "台光電", "date": "2026-08-27", "time": "", "summary": "受邀", "file": "a.pdf"}]
    qa = {TQ.key("2383", "2026-08-27"): _qa_rec("2026-08-27", "x.pdf")}
    doc = TP.stock_doc("2383", rows, {}, {}, qa=qa)
    q = doc["quarters"][0]
    assert q["date"] == "2026-08-05" and q["qa"]["date"] == "2026-08-27"
    assert q["qa"]["qa"][0]["q"] == "資本支出？" and q["qa"]["outlook"]["revenue_outlook"] == 2
    assert q["qa"]["sources"][0]["url"].startswith("https://blog.fugle.tw/")


def test_建站寫出的json帶有QA():
    root, out = _tmp(), _tmp()
    _index(root, [("2383", "2026-10-29", "x", "b.pdf")])
    TK._append_features(root, [_qa_rec("2026-10-29", "b.pdf")])
    TP.write_talks_json(root, out, today=date(2026, 11, 1))
    doc = json.loads((out / "talks" / "2383.json").read_text("utf-8"))
    assert doc["quarters"][0]["qa"]["guidance"] == ["4Q26 營收季增 15%～20%"]


def test_個股頁畫得出QA區塊():
    js = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "法人 Q&amp;A（" in js and "qaBlock(a, q, idx === 0)" in js
    assert r"blog\.fugle\.tw|finance\.biggo\.com\.tw" in js
