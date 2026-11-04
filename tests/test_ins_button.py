"""名稱旁的〔概況〕：各頁一致，點了到〔籌碼雷達〕打開〈基本面與籌碼概況〉面板。"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"


def test_各頁名稱旁都有概況():
    macros = (TPL / "_macros.html.j2").read_text("utf-8")
    assert "macro ins(" in macros and "{{ ins(r.stock_id, rel) }}" in macros   # 評等清單、觀察清單
    assert 'radar.html#t1-{{ code }}-ins' in macros
    assert macros.count("ins-btn") == 1 and 'data-ins="{{ code }}"' in macros
    ai = (TPL / "ai.html.j2").read_text("utf-8")
    assert ai.count("{{ ins(") >= 8                                              # AI 選股各表
    for page in ("screener.html.j2", "cl.html.j2"):
        src = (TPL / page).read_text("utf-8")
        assert "ins-btn" in src and '-ins"' in src, page
    api = (TPL / "radar_bg" / "api.js").read_text("utf-8")
    assert "BG_INS_ICON + '</button>'" in api                                  # 籌碼雷達清單（小圖示）
    assert "a.ins-btn" in (TPL / "site.css").read_text("utf-8")


def test_籌碼雷達網址帶ins就打開概況面板():
    radar = (TPL / "radar.html.j2").read_text("utf-8")
    assert 'h[2] === "ins"' in radar and "CFI.show(h[1]" in radar


def test_其他頁的概況面板跟籌碼雷達同一份程式():
    from twsix.report.build import asset_text
    js = asset_text("ins.js")
    assert "var CFI = (function()" in js and "{% raw %}" not in js and "window.CFI = CFI" in js
    assert js.strip().startswith("/*") and js.rstrip().endswith("})();")      # 整包在一個函式裡，不蓋頁面的 $／open
    css = asset_text("ins.css")
    assert "#cf .cfi-drawer" in css and "html.cfi-on body > .wrap" in css
    site = (TPL / "site.js").read_text("utf-8")
    assert "window.TWSIXIns" in site and "assets/ins.js" in site


def test_個股頁名稱右邊也有概況():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    tpl = (root / "stockpage.html.j2").read_text("utf-8")
    assert "{{ p.name }}{{ m.ins(p.stock_id, rel) }}" in tpl
    css = (root / "site.css").read_text("utf-8")
    assert ".ident h2 a.ins-btn{" in css
    assert "html.cfi-on .ident .tabs{flex-wrap:wrap" in css
