"""把券商財報頁「最近 8 季」的合約負債與資本支出存進歷史檔（不另外抓任何資料）。

為什麼：券商頁只留最近 8 季。季別一滾出 8 季窗格，以前得再向公開資訊觀測站查一次；
其實那一季當初券商頁就有了。每次建站／回補前先把券商頁的數字存進
`data/market/contract_liab.csv`（期末餘額）與 `data/market/capex_hist.csv`（年初累計），
回補程式看到「已經有了」就不會再查——同一份數字只抓一次。

- 合約負債：期末餘額直接存（券商頁的值優先，不覆蓋觀測站已讀到的數字）。
- 資本支出：歷史檔存「年初累計」，由同一年 Q1..Qn 的單季加總而來；那一年缺任何一季就不存（不猜）。
"""
from __future__ import annotations

from pathlib import Path

from . import cl_history as CL
from . import cx_history as CX


def archive(data_dir: Path, codes: list[str] | None = None, *, cl_out: Path | None = None,
            cx_out: Path | None = None) -> dict[str, int]:
    from ..chipflow.load import _sheet, _sheet_rows  # noqa: PLC0415 - 籌碼雷達同一套讀表

    root = Path(data_dir) / "sheets"
    if not root.is_dir():
        return {"cl": 0, "capex": 0}
    cl_path = Path(cl_out) if cl_out else Path(data_dir) / CL.FILE
    cx_path = Path(cx_out) if cx_out else Path(data_dir) / CX.FILE
    cl_data, cx_data = CL.read(cl_path), CX.read(cx_path)
    n_cl = n_cx = 0
    for d in sorted(root.iterdir()):
        if not d.is_dir() or (codes is not None and d.name not in codes):
            continue
        bs = _sheet_rows(_sheet(d / "BSQ.json.gz"), {"cl": ("合約負債－流動", "合約負債－非流動")})
        cf = _sheet_rows(_sheet(d / "CFQ.json.gz"), {"capex": (CX.SHEET_ROW,)}, sign=-1.0)
        mine = cl_data.setdefault(d.name, {})
        for lb, v in bs.items():
            if "cl" not in v:
                continue
            q = f"{lb[:4]}Q{lb[5]}"
            if q not in mine or mine[q] is None:
                mine[q] = round(v["cl"], 3)
                n_cl += 1
        singles = {f"{lb[:4]}Q{lb[5]}": v["capex"] for lb, v in cf.items() if "capex" in v}
        hist = cx_data.setdefault(d.name, {})
        known_single = {**CX.single(hist), **singles}
        for q in sorted(singles):
            if q in hist:
                continue
            y, k = q[:4], int(q[-1])
            parts = [known_single.get(f"{y}Q{i}") for i in range(1, k + 1)]
            if all(p is not None for p in parts):
                hist[q] = round(sum(parts), 3)
                n_cx += 1
        if not mine:
            cl_data.pop(d.name, None)
        if not hist:
            cx_data.pop(d.name, None)
    if n_cl:
        CL.write(cl_path, cl_data)
    if n_cx:
        CX.write(cx_path, cx_data)
    return {"cl": n_cl, "capex": n_cx}
