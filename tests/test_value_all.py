
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import shutil
import tempfile
from pathlib import Path

from twsix.cli import cmd_value_all
from twsix.store.snapshots import VALUATION_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VALUATIONS = DATA / "valuations.csv"

SAMPLE = ("5439", "2330", "1101")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None




def test_全市場估值真的跑得動():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sheets").mkdir(parents=True)
        for code in SAMPLE:
            shutil.copytree(DATA / "sheets" / code, root / "sheets" / code)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code_out = cmd_value_all(argparse.Namespace(
                config=None, data=str(root), as_of=None, all=True))
        assert code_out == 0, buf.getvalue()
        rows = _rows(root / "valuations.csv")
        assert {r["stock_id"] for r in rows} == set(SAMPLE), (
            f"應該每一檔都有一列，實際上是 {[r['stock_id'] for r in rows]}"
        )
        assert list(rows[0]) == list(VALUATION_COLUMNS), "欄位順序和 schema 不一樣"


def test_一檔算不出來不會停下整批():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sheets").mkdir(parents=True)
        for code in SAMPLE:
            shutil.copytree(DATA / "sheets" / code, root / "sheets" / code)
        (root / "sheets" / "9999").mkdir()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code_out = cmd_value_all(argparse.Namespace(
                config=None, data=str(root), as_of=None, all=True))
        assert code_out == 0
        assert len(_rows(root / "valuations.csv")) == len(SAMPLE)




def test_預估EPS為負就沒有本益比估價():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sheets").mkdir(parents=True)
        shutil.copytree(DATA / "sheets" / "1101", root / "sheets" / "1101")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cmd_value_all(argparse.Namespace(
                config=None, data=str(root), as_of=None, all=True))
        row = _rows(root / "valuations.csv")[0]
    eps = _f(row["forecast_eps"])
    assert eps is not None and eps <= 0, (
        f"1101 的預估 EPS 變成 {eps} 了——這條測試挑它就是因為它是負的，"
        "換一檔還是負的來測"
    )
    assert not row["target_price"], (
        f"預估 EPS 是 {eps}，目標價卻是 {row['target_price']}"
        "——本益比 × 負的 EPS 是一個負的股價"
    )
    assert not row["reward_risk"], (
        f"預估 EPS 是 {eps} 卻算出了報酬風險比 {row['reward_risk']}。"
        "兩個負號被 abs() 約掉了，結果是一個看起來很漂亮的買進訊號"
    )
    assert row["risk_free"] == "0", "沒有估價就不是「無風險」，那是另一件事"


def test_存下來的那一份沒有一檔踩到這個():
    bad = [
        r for r in _rows(VALUATIONS)
        if (_f(r["forecast_eps"]) or 0) <= 0 and _f(r["reward_risk"]) is not None
    ]
    assert not bad, (
        f"{len(bad)} 檔的預估 EPS ≤ 0 卻有報酬風險比，例如 "
        + "、".join(f"{r['stock_id']} {r['name']}（{r['reward_risk'][:6]}）"
                    for r in bad[:5])
    )




def test_無風險和算不出來分得開():
    rows = _rows(VALUATIONS)
    free = [r for r in rows if r["risk_free"] == "1"]
    assert free, "一檔『股價已低於下檔價』都沒有？全市場實測是 492 檔"
    for r in free:
        assert not r["reward_risk"], (
            f"{r['stock_id']} 同時是無風險又有報酬風險比 {r['reward_risk']}"
        )
        assert r["target_price"], (
            f"{r['stock_id']} 標成無風險，卻連目標價都沒有"
            "——那是『算不出來』，不是『沒有下檔風險』"
        )
        price, floor = _f(r["market_price"]), _f(r["downside_price"])
        assert price is not None and floor is not None and price <= floor, (
            f"{r['stock_id']} 標成無風險，但股價 {price} 沒有低於下檔價 {floor}"
        )
    unknown = [r for r in rows if not r["reward_risk"] and r["risk_free"] != "1"]
    for r in unknown:
        assert not r["target_price"] or (_f(r["forecast_eps"]) or 0) <= 0, (
            f"{r['stock_id']} 有目標價、不是無風險、卻沒有報酬風險比"
        )


def test_發布出去的那一份蓋住整個市場():
    have = {r["stock_id"] for r in _rows(VALUATIONS)}
    want = {p.name for p in (DATA / "sheets").iterdir() if p.is_dir()}
    covered = len(have & want) / len(want)
    assert covered > 0.95, (
        f"只有 {len(have)} 檔有估值，而 {len(want)} 檔有格線（{covered:.0%}）。"
        "是不是 `twsix value --all` 沒有跑？"
    )


def test_股價高過目標價就沒有報酬可分():
    rows = _rows(VALUATIONS)
    bad = [
        r for r in rows
        if (_f(r["reward_risk"]) or 0) > 0 and (_f(r["expected_return"]) or 0) <= 0
    ]
    assert not bad, (
        f"{len(bad)} 檔的預期報酬 ≤ 0 卻有正的報酬風險比，例如 "
        + "、".join(
            f"{r['stock_id']} {r['name']}（RR {r['reward_risk'][:6]}、"
            f"報酬 {float(r['expected_return']) * 100:.0f}%）"
            for r in bad[:4]
        )
    )


def test_沒有上檔和算不出來不是同一件事():
    rows = _rows(VALUATIONS)
    zero = [r for r in rows if r["reward_risk"] == "0"]
    assert zero, "一檔『股價高過目標價』都沒有？全市場實測是 309 檔"
    for r in zero[:50]:
        assert r["target_price"], f"{r['stock_id']} 報酬風險比 0 卻連目標價都沒有"
        assert r["risk_free"] == "0", f"{r['stock_id']} 不可能同時零報酬又無風險"




def test_接收端用今天的收盤重算得到同一個判斷():
    flipped: list[str] = []
    worst = 0.0
    checked = 0
    over: list[str] = []
    for r in _rows(VALUATIONS):
        target, floor = _f(r["target_price"]), _f(r["downside_price"])
        price, stored = _f(r["market_price"]), _f(r["reward_risk"])
        if None in (target, floor, price) or price <= 0:
            continue
        if price <= floor:
            assert r["risk_free"] == "1", f"{r['stock_id']} 應該標成無風險"
            continue
        assert stored is not None, f"{r['stock_id']} 少了報酬風險比"
        ret = round(target, 4) / price - 1
        calc = 0.0 if ret <= 0 else abs(ret / (round(floor, 4) / price - 1))
        checked += 1
        worst = max(worst, abs(calc - stored) / max(stored, 1e-9))
        gap_up, gap_dn = target - price, price - floor
        if stored > 0 and gap_up > 0:
            tol = 1.5 * 5e-5 * (1 / gap_up + 1 / gap_dn) + 1e-6
            if abs(calc - stored) / stored > tol:
                over.append(f"{r['stock_id']}（{stored} vs {calc}，容許 {tol:.1e}）")
        for edge in (1.0, 2.0, 3.0):
            if (calc > edge) != (stored > edge):
                flipped.append(f"{r['stock_id']}（{stored} vs {calc}，門檻 {edge}）")
    assert checked > 500, f"只對到 {checked} 檔，這條測試沒有驗到東西"
    assert not flipped, "四捨五入讓這幾檔換了邊：" + "、".join(flipped[:5])
    assert not over, "差距超過捨入所能解釋的範圍：" + "、".join(over[:5])
