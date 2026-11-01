from __future__ import annotations

import tempfile
from pathlib import Path

from twsix import refresh as R


def _ctx(**kw):
    root = Path(tempfile.mkdtemp(prefix="twsix-refresh-"))
    return R.Ctx(code="2330", config=None, root=root, site=root / "site", **kw)


def _stages(calls):
    def ok(c):
        calls.append("ok")
        return "ok", "好了"

    def boom(c):
        calls.append("boom")
        raise RuntimeError("來源壞了")

    def home(c):
        calls.append("home")
        return "ok", "家裡才抓得到"

    return (R.Stage("a", "第一項", ok, quick=True), R.Stage("b", "會壞的一項", boom),
            R.Stage("c", "觀測站", home, home=True), R.Stage("d", "最後一項", ok, quick=True))


def test_一項失敗不擋後面_雲端略過要在家跑的項目(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(R, "STAGES", _stages(calls))
    counts = R.run(_ctx(cloud=True))
    out = capsys.readouterr().out.splitlines()
    assert calls == ["ok", "boom", "ok"]
    assert counts == {"ok": 2, "warn": 1, "cloud": 1}
    st = R.parse_stages(out)
    assert [(s["i"], s["n"], s["state"]) for s in st] == [(1, 4, "ok"), (2, 4, "warn"), (3, 4, "cloud"), (4, 4, "ok")]
    assert "來源壞了" in st[1]["note"]
    assert out[-1].startswith("一鍵更新完成：")


def test_快速範圍只跑標了_quick_的項目(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(R, "STAGES", _stages(calls))
    R.run(_ctx(), scope="quick")
    st = R.parse_stages(capsys.readouterr().out.splitlines())
    assert [s["title"] for s in st] == ["第一項", "最後一項"] and st[0]["n"] == 2


def test_進行中的那一行會被結果蓋掉():
    st = R.parse_stages(["【1/3】甲｜⏳ 進行中", "    子程式的輸出【2/3】不算", "【1/3】甲｜⏭️ 還很新 · 2 秒"])
    assert len(st) == 1 and st[0]["state"] == "skip" and st[0]["note"] == "還很新 · 2 秒"


def test_全市場共用的小檔三十分鐘內不重抓_force_照抓():
    c = _ctx()
    assert not c.recent("news")
    c.touch("news")
    assert c.recent("news")
    c.force = True
    assert not c.recent("news")


def test_登錄表涵蓋網站上的每一類資料():
    keys = [s.key for s in R.STAGES]
    for k in ("sheets", "yearly", "holders", "directors", "levels", "daily", "revenue", "cl", "news",
              "talks", "page", "chipflow", "aipick", "trend", "build"):
        assert k in keys, k
    assert keys[0] == "sheets" and keys[-1] == "build"
    home = {s.key for s in R.STAGES if s.home}
    assert home == {"cl", "talks"}
    assert len(keys) == len(set(keys))


def test_沒有報表就不重畫個股頁():
    c = _ctx()
    c.state["sheets"] = False
    assert R.st_page(c)[0] == "fail"
    assert R.st_build(c)[0] == "skip"


def test_子程式的輸出縮排而且不會被當成階段行(capsys):
    def noisy():
        print("【9/9】假的｜✅ 不該算")
        print("第二行")
        return 7

    assert R._quiet(noisy) == 7
    out = capsys.readouterr().out.splitlines()
    assert all(x.startswith("    ") for x in out)
    assert R.parse_stages(out) == []
