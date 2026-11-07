"""龍蝦／海龜整合：靜態輸出、回補防重複（券商頁季別先存）、市場監控資料共用。"""
import gzip
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lobturtle_static_export():
    with tempfile.TemporaryDirectory() as td:
        _test_lobturtle_static_export(Path(td))


def _test_lobturtle_static_export(tmp_path):
    try:
        import numpy  # noqa: F401
    except ImportError:
        from twsix.report.build import MissingOptional
        raise MissingOptional("這一條需要 numpy") from None
    from twsix.lobturtle.export import export

    got = export(ROOT / "data", tmp_path)
    assert got and got["latest"]
    api = tmp_path / "lobturtle" / "api"
    bt = json.loads((api / "charts/lobster/backtest.json").read_text(encoding="utf-8"))
    assert len(bt["labels"]) == len(bt["point"]) == len(bt["lobster"]) > 1000
    html = (tmp_path / "lobturtle" / "index.html").read_text(encoding="utf-8")
    assert 'src="shim.js' in html and 'href="/' not in html and 'src="/' not in html


def test_regime_gap_fixed():
    src = (ROOT / "src/twsix/lobturtle/knowledge_base.py").read_text(encoding="utf-8")
    assert "RANGE_TURNING_UP" in src and "CERT_NONE" not in src


def _grid(rows):
    return gzip.compress(json.dumps(rows, ensure_ascii=False).encode("utf-8"))


def test_archive_sheet_quarters_into_history():
    with tempfile.TemporaryDirectory() as td:
        _test_archive_sheet_quarters_into_history(Path(td))


def _test_archive_sheet_quarters_into_history(tmp_path):
    from twsix.ingest import cl_history as CL
    from twsix.ingest import cx_history as CX
    from twsix.ingest.sheet_archive import archive

    d = tmp_path / "sheets" / "9999"
    d.mkdir(parents=True)
    head = ["期別", "2026.2Q", "2026.1Q", "2025.4Q", "2025.3Q", "2025.2Q", "2025.1Q"]
    (d / "BSQ.json.gz").write_bytes(_grid([head, ["合約負債－流動", "60", "50", "40", "30", "20", "10"]]))
    (d / "CFQ.json.gz").write_bytes(_grid([head, [CX.SHEET_ROW, "-6", "-5", "-4", "-3", "-2", "-1"]]))
    got = archive(tmp_path, ["9999"])
    assert got == {"cl": 6, "capex": 6}
    cl = CL.read(tmp_path / CL.FILE)["9999"]
    assert cl["2025Q1"] == 10 and cl["2026Q2"] == 60
    cx = CX.read(tmp_path / CX.FILE)["9999"]
    assert cx["2025Q4"] == 10 and cx["2026Q2"] == 11         # 年初累計
    assert CX.single(cx)["2025Q3"] == 3
    assert archive(tmp_path, ["9999"]) == {"cl": 0, "capex": 0}   # 第二次什麼都不用寫
