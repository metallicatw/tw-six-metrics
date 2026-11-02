"""名稱旁的〔概況〕：各頁一致，點了到〔籌碼雷達〕打開〈基本面與籌碼概況〉面板。"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"


def test_各頁名稱旁都有概況():
    macros = (TPL / "_macros.html.j2").read_text("utf-8")
    assert "macro ins(" in macros and "{{ ins(r.stock_id, rel) }}" in macros   # 評等清單、觀察清單
    assert 'radar.html#t1-{{ code }}-ins' in macros
    assert macros.count("ins-btn") == 1
    ai = (TPL / "ai.html.j2").read_text("utf-8")
    assert ai.count("{{ ins(") >= 8                                              # AI 選股各表
    for page in ("screener.html.j2", "cl.html.j2"):
        src = (TPL / page).read_text("utf-8")
        assert "ins-btn" in src and '-ins"' in src, page
    api = (TPL / "radar_bg" / "api.js").read_text("utf-8")
    assert '">概況</button>' in api                                              # 籌碼雷達清單
    assert "a.ins-btn" in (TPL / "site.css").read_text("utf-8")


def test_籌碼雷達網址帶ins就打開概況面板():
    radar = (TPL / "radar.html.j2").read_text("utf-8")
    assert 'h[2] === "ins"' in radar and "CFI.show(h[1]" in radar
