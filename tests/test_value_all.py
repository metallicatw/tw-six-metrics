"""全市場估值：`twsix value --all`，以及它逼出來的一個符號錯誤。

## 為什麼要有這支指令

`twsix value` 一次算一檔。於是 `data/valuations.csv` 長期**只有一列**（5439）
——不是算不出來，是沒有人一檔一檔去跑。而券商鏡像的格線早就在了：
`data/sheets/` 底下 1,957 檔都有 BSQ／OPQ／CFQ／EPQ／股利／年度交易資訊，
全市場的估值一個請求都不用發，13 秒就算完。

## 它逼出來的那個錯誤

一檔一檔看的時候，預估 EPS 是負的不會出事——畫面上同一行就寫著「預估EPS
−1957」，沒有人會把那一列的目標價當真。

全市場一起算就會出事。本益比估價是「本益比 × 每股盈餘」，EPS 是負的時候那個
乘積是一個**負的股價**，而後面每一步都照算不誤：

    潤隆 1808   預估EPS −1957.17   目標價 −68,720   下檔價 −31,046
                報酬 −2.4          風險 −2.2
                報酬風險比 = |(−2.4) / (−2.2)| = 2.21   ← 看起來是買進訊號

實測 1,958 檔裡有 166 檔 EPS 是負的卻拿到了報酬風險比，其中 12 檔大於 2。而
〔趨勢∩六大∩報酬〕那一頁正是拿 > 2 去篩的——那 12 檔會直接變成推薦名單，而
名單上不會有任何一個字說它們正在虧錢。

## 「無風險」和「算不出來」不是同一件事

股價已經跌到下檔價之下的時候，`PriceView` 的 `expected_risk` 與 `reward_risk`
都是 None——因為沒有下檔風險，不是因為缺資料。全市場 1,958 檔裡有 492 檔是
這一類，而它們在 CSV 裡和「缺年度交易資訊」長得一模一樣（兩欄都空）。意思卻
正好相反：一個是判斷準則裡最好的那一種，一個是資料不足。所以多存一欄
`risk_free`。
"""

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

#: 三檔拿來真的跑一次的樣本。挑這三檔是因為它們各自代表一種結果：
#: 5439 有完整的報酬風險比（也是整個 repo 的對帳基準），2330 是最大的一檔，
#: 1101 的預估 EPS 是負的——也就是上面那個符號錯誤會出現的地方。
SAMPLE = ("5439", "2330", "1101")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# ── 真的跑一次 ──────────────────────────────────────────────────────────


def test_全市場估值真的跑得動():
    """把三檔的格線複製到 tmp，跑一次指令，看它寫出什麼。

    不是 grep 原始碼：這裡要驗的是「一個迴圈跑完 N 檔之後 CSV 長什麼樣」，
    而那件事只有真的跑過才知道。
    """
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
    """多一個空資料夾（沒有任何格線），其餘三檔還是要寫出來。

    全市場一定會有幾檔是壞的——新上市的、下市的、格線抓到一半的。一檔擋住
    整批的話，這支指令會在最需要它的那天什麼都不寫。
    """
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


# ── 符號錯誤 ────────────────────────────────────────────────────────────


def test_預估EPS為負就沒有本益比估價():
    """1101 台泥的預估 EPS 是負的。修好之前它的報酬風險比是 1.12。

    直接拿 repo 裡真實的格線跑，因為這個錯誤的形狀就是「真實資料才有」——
    造一個假的負 EPS 也測得到，但測不到「這件事在這份資料上真的發生過」。
    """
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
    """上面那條只看 1101。這一條掃過 repo 裡真正發布出去的那一份。"""
    bad = [
        r for r in _rows(VALUATIONS)
        if (_f(r["forecast_eps"]) or 0) <= 0 and _f(r["reward_risk"]) is not None
    ]
    assert not bad, (
        f"{len(bad)} 檔的預估 EPS ≤ 0 卻有報酬風險比，例如 "
        + "、".join(f"{r['stock_id']} {r['name']}（{r['reward_risk'][:6]}）"
                    for r in bad[:5])
    )


# ── 無風險 vs 算不出來 ──────────────────────────────────────────────────


def test_無風險和算不出來分得開():
    """兩種情況的 `reward_risk` 都是空的，意思卻正好相反。

    〔趨勢∩六大∩報酬〕拿 `> 2` 去篩。少了 `risk_free`，最好的那 492 檔會和
    缺資料的一起被丟掉——而丟掉的方式是「它們不在名單上」，沒有任何徵兆。
    """
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
    """這支指令存在的理由就是這一條。

    修好之前 `data/valuations.csv` 只有 1 列，而網站、評等清單、新分頁全都讀
    它。一列和一千九百列在程式裡長得一樣——都是一個能讀的 CSV。
    """
    have = {r["stock_id"] for r in _rows(VALUATIONS)}
    want = {p.name for p in (DATA / "sheets").iterdir() if p.is_dir()}
    covered = len(have & want) / len(want)
    assert covered > 0.95, (
        f"只有 {len(have)} 檔有估值，而 {len(want)} 檔有格線（{covered:.0%}）。"
        "是不是 `twsix value --all` 沒有跑？"
    )


def test_股價高過目標價就沒有報酬可分():
    """`abs(ret / risk)` 的另一個受害者——和負 EPS 同一家族。

    股價已經高過目標價的時候 `ret` 是負的、`risk` 也是負的，abs() 把兩個負號
    約掉，而 |ret| 大、|risk| 小的時候商還特別大：

        6584 南俊國際   報酬風險比 582.26   預期報酬 −100.0%
        3447 展達       報酬風險比   4.21   預期報酬  −61.7%

    四個判斷準則從頭到尾預設報酬是正的（「報酬風險 > 2 才有買進的意義」講的是
    還剩多少上檔），所以這種情況的報酬風險比是 0，不是一個大數。
    """
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
    """零報酬給 0.00，不是空白。

    空白的意思是「算不出來」——清單上顯示 —，排序沉到底。而「股價已經超過目標
    價」是**算得出來的一個答案**，答案是不要買。兩者混在一起，讀者會以為這一檔
    只是缺資料。
    """
    rows = _rows(VALUATIONS)
    zero = [r for r in rows if r["reward_risk"] == "0"]
    assert zero, "一檔『股價高過目標價』都沒有？全市場實測是 309 檔"
    for r in zero[:50]:
        assert r["target_price"], f"{r['stock_id']} 報酬風險比 0 卻連目標價都沒有"
        assert r["risk_free"] == "0", f"{r['stock_id']} 不可能同時零報酬又無風險"


# ── cross.json：發布給 tw-trend-filter 的那一份 ────────────────────────


def test_接收端用今天的收盤重算得到同一個判斷():
    """`cross.json` 只發目標價與下檔價，報酬風險比由 tw-trend-filter 自己算。

    這條測試就是兩個 repo 之間的那個約定：拿 `cross.json` 發出去的兩個數字
    （四捨五入到小數第四位）加上同一個股價，要重算出和 `valuations.csv` 一樣
    的**判斷**。對不起來的話，同一檔在〔台股評等清單〕和〔趨勢∩六大∩報酬〕
    上會是兩個報酬風險比，而使用者無從判斷哪一個是對的。

    驗的是**門檻的哪一邊**，不是小數第幾位。位數本來就會差一點：CSV 存十位
    有效數字、`cross.json` 存四位，而股價貼近下檔價的時候分母很小，會把那點
    捨入放大（實測最大相對差 5.2e-4）。真正要緊的是沒有任何一檔因此換邊——
    換邊才會讓一檔股票進或不進那份名單。
    """
    flipped: list[str] = []
    worst = 0.0
    checked = 0
    for r in _rows(VALUATIONS):
        target, floor = _f(r["target_price"]), _f(r["downside_price"])
        price, stored = _f(r["market_price"]), _f(r["reward_risk"])
        if None in (target, floor, price) or price <= 0:
            continue
        if price <= floor:
            assert r["risk_free"] == "1", f"{r['stock_id']} 應該標成無風險"
            continue
        assert stored is not None, f"{r['stock_id']} 少了報酬風險比"
        # 這兩行就是接收端會做的事——發出去的是四位。
        ret = round(target, 4) / price - 1
        calc = 0.0 if ret <= 0 else abs(ret / (round(floor, 4) / price - 1))
        checked += 1
        worst = max(worst, abs(calc - stored) / max(stored, 1e-9))
        for edge in (1.0, 2.0, 3.0):
            if (calc > edge) != (stored > edge):
                flipped.append(f"{r['stock_id']}（{stored} vs {calc}，門檻 {edge}）")
    assert checked > 500, f"只對到 {checked} 檔，這條測試沒有驗到東西"
    assert not flipped, "四捨五入讓這幾檔換了邊：" + "、".join(flipped[:5])
    assert worst < 1e-3, f"最大相對差 {worst:.2e}，比預期大——是不是少存了幾位？"
