"""
Data Seeding & Live TWSE / TAIFEX / FinMind One-Click Updater for LobTurtle (龍蝦/海龜模組)
===========================================================================================

Core Data Persistence Rule (`所有的歷史資料庫皆保留，往後新的數據再一一寫回資料庫中`):
1. `seed_databases(db_manager, force=False)`:
   - Loads bundled 6-year official historical baseline (`seed_data.json`: `2020/11/05 ~ 2026/11/06`,
     1,458 trading days; `TMF_LOSER.db`: `2024/07/29 ~ 2026/11/06`, 553 trading days).
   - By default (`force=False`), uses `INSERT OR IGNORE` (`insert_ignore_many`) so **all existing
     historical records AND all future appended records in `data/*.db` are 100% preserved and never overwritten**.
2. `TWSETAIFEXFetcher`:
   - Dual-source official crawler fetching post-market Taiwan stock & futures data:
     * Taiwan Weighted Index (`POINT`, `CHANGE`): Official TWSE `FMTQIK` + FinMind `TaiwanStockPrice (TAIEX)`
     * Foreign Spot Net Buy/Sell (`億`): FinMind `TaiwanStockTotalInstitutionalInvestors` + TWSE `BFI82U` fallback
     * Foreign TXF Futures Net Trade & Open Interest (`口`): Official TAIFEX `futContractsDateDown` + FinMind `TaiwanFuturesInstitutionalInvestors (TX)`
     * Mini-TXF (`小台 MTX/MXF`) & Micro-TXF (`微台 TMF`) Retail Open Interest Long/Short Ratio (`%`):
       `Retail_Ratio(%) = - (Three_Major_Institutional_Net_OI / Regular_Session_Single_Contract_Total_Market_OI) * 100`
       via Official TAIFEX (`futContractsDateDown` + `futDataDown` in `<=25`-day windows) + FinMind fallback.
3. `update_all_to_latest(db_manager)`:
   - Queries official live endpoints for dates after each database's `MAX(DATE)` up to `today`,
     and **incrementally writes each new trading day one by one (`insert_new_one_by_one`)** back into
     all 9 SQLite databases (`data/*.db`) without modifying any historical row.
"""

from __future__ import annotations

import datetime
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .db import LobTurtleDBManager
from .indicators import LobsterIndicator, TurtleIndicator

SEED_JSON_PATH = Path(__file__).resolve().parent / "seed_data.json"


def _ssl_ctx() -> ssl.SSLContext:
    """驗證憑證（原版關閉驗證，等於任何人都能冒充證交所／期交所回假資料）。"""
    try:
        import certifi  # noqa: PLC0415

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def seed_databases(db_manager: LobTurtleDBManager, force: bool = False) -> dict[str, int]:
    """
    Ensure all 9 SQLite databases contain the 6-year (`2020/11/05 ~ 2026/11/06`) historical baseline.
    - When `force=False` (default): strictly preserves all existing rows (`INSERT OR IGNORE`), only inserting
      missing historical dates if a database is newly created or incomplete.
    - When `force=True`: overwrites baseline dates via `INSERT OR REPLACE` (still keeping any post-seed future dates).
    """
    if not SEED_JSON_PATH.exists():
        raise FileNotFoundError(f"Bundled seed data not found at {SEED_JSON_PATH}")

    with open(SEED_JSON_PATH, encoding="utf-8") as f:
        payload = json.load(f)

    daily_6y: list[dict[str, Any]] = payload.get("daily_6y", [])
    if not daily_6y:
        raise ValueError("seed_data.json missing 'daily_6y' records")

    expected_full = len(daily_6y)
    expected_tmf = sum(1 for r in daily_6y if r.get("tmf_retail") is not None)
    seed_first_date = daily_6y[0]["date"]
    seed_last_date = daily_6y[-1]["date"]

    status = {s["name"]: s for s in db_manager.get_status_summary()}
    if not force:
        all_ready = True
        for name, st in status.items():
            target_cnt = expected_tmf if name == "TMF_LOSER.db" else expected_full
            target_first = "2024/07/29" if name == "TMF_LOSER.db" else seed_first_date
            if (
                st["rowCount"] < target_cnt
                or (st["firstDate"] or "9999/99/99") > target_first
                or (st["lastDate"] or "") < seed_last_date
            ):
                all_ready = False
                break
        if all_ready:
            return {k: v["rowCount"] for k, v in status.items()}

    twse_rows: list[tuple[str, float, float]] = []
    lob_rows: list[tuple[str, int, int]] = []
    spot_rows: list[tuple[str, float]] = []
    fut_rows: list[tuple[str, float, float]] = []
    mxf_rows: list[tuple[str, float]] = []
    tmf_rows: list[tuple[str, float]] = []
    v1_rows: list[tuple[str, int, int, int, int]] = []
    v2_rows: list[tuple[str, int, int, int]] = []
    v3_rows: list[tuple[str, int, int, int]] = []

    for r in daily_6y:
        dt = str(r["date"])
        twse_rows.append((dt, float(r["point"]), float(r.get("change") or 0.0)))
        lob_rows.append((dt, int(r["lobster"]), int(r["lobster_sum"])))
        if r.get("spot") is not None:
            spot_rows.append((dt, float(r["spot"])))
        if r.get("fut_tr") is not None and r.get("fut_oi") is not None:
            fut_rows.append((dt, float(r["fut_tr"]), float(r["fut_oi"])))
        if r.get("mxf_retail") is not None:
            mxf_rows.append((dt, float(r["mxf_retail"])))
        if r.get("tmf_retail") is not None:
            tmf_rows.append((dt, float(r["tmf_retail"])))
        v1 = r["v1"]
        v2 = r["v2"]
        v3 = r["v3"]
        v1_rows.append((dt, int(v1[0]), int(v1[1]), int(v1[2]), int(v1[3])))
        v2_rows.append((dt, int(v2[0]), int(v2[1]), int(v2[2])))
        v3_rows.append((dt, int(v3[0]), int(v3[1]), int(v3[2])))

    writer = db_manager.upsert_many if force else db_manager.insert_ignore_many
    writer("TWSE_INFO.db", ["DATE", "POINT", "CHANGE"], twse_rows)
    writer("LOBSTER.db", ["DATE", "LOBSTER", "LOBSTER_SUM"], lob_rows)
    writer("TWSE_FOREIGEN.db", ["DATE", "SPOT_NET_BUY"], spot_rows)
    writer("TXF_FOREIGEN.db", ["DATE", "FUT_TRADE_NET", "FUT_OI_NET"], fut_rows)
    writer("MXF_LOSER.db", ["DATE", "RETAIL_RATIO"], mxf_rows)
    writer("TMF_LOSER.db", ["DATE", "RETAIL_RATIO"], tmf_rows)
    writer("TW50_TURTLE_V1.db", ["DATE", "A", "B", "C", "D"], v1_rows)
    writer("TW50_TURTLE_V2.db", ["DATE", "S5", "S4_5", "S4"], v2_rows)
    writer("TW50_TURTLE_V3.db", ["DATE", "S5", "S4_5", "S4"], v3_rows)

    return {s["name"]: s["rowCount"] for s in db_manager.get_status_summary()}


class TWSETAIFEXFetcher:
    """
    Official TWSE, TAIFEX & FinMind Dual-Source Post-Market Data Crawler
    --------------------------------------------------------------------
    Fetches daily Taiwan Weighted Index (`POINT`, `CHANGE`), Foreign Spot Net Buy/Sell (`億`),
    Foreign TXF Futures Net Trade & Open Interest (`口`), and Mini/Micro-TXF Retail Ratio (`%`).
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    @staticmethod
    def roc_to_gregorian(roc_date: str) -> str:
        """Convert ROC date string `'115/11/06'` to `'2026/11/06'`."""
        parts = roc_date.strip().split("/")
        if len(parts) == 3 and len(parts[0]) <= 3:
            year = int(parts[0]) + 1911
            return f"{year:04d}/{int(parts[1]):02d}/{int(parts[2]):02d}"
        return roc_date.strip().replace("-", "/")

    @staticmethod
    def compute_retail_long_short_ratio(inst_net_oi: float, total_market_oi: float) -> float:
        """
        Compute Mini-TXF (`小台`) or Micro-TXF (`微台`) Retail Open Interest Long/Short Ratio (%):
        `Retail_Net_OI = - Inst_Net_OI`
        `Retail_Ratio(%) = (Retail_Net_OI / Total_Market_OI) * 100.0`
        """
        if total_market_oi <= 0:
            return 0.0
        retail_net_oi = -float(inst_net_oi)
        return round((retail_net_oi / float(total_market_oi)) * 100.0, 2)

    def _finmind_get(
        self, dataset: str, data_id: str | None, start_date_iso: str, end_date_iso: str
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "dataset": dataset,
            "start_date": start_date_iso,
            "end_date": end_date_iso,
        }
        if data_id:
            params["data_id"] = data_id
        url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", [])

    def fetch_taiex_range(self, start_date_iso: str, end_date_iso: str) -> list[tuple[str, float, float]]:
        """Fetch TAIEX (`DATE`, `POINT`, `CHANGE`) from FinMind + Official TWSE `FMTQIK`."""
        rows: dict[str, tuple[str, float, float]] = {}
        try:
            for item in self._finmind_get("TaiwanStockPrice", "TAIEX", start_date_iso, end_date_iso):
                dt = str(item["date"]).replace("-", "/")
                rows[dt] = (
                    dt,
                    round(float(item["close"]), 2),
                    round(float(item.get("spread", 0.0)), 2),
                )
        except Exception:
            pass

        # Also query official TWSE FMTQIK month-by-month for immediate same-day 13:35 post-market freshness
        try:
            s_dt = datetime.datetime.strptime(start_date_iso, "%Y-%m-%d").date().replace(day=1)
            e_dt = datetime.datetime.strptime(end_date_iso, "%Y-%m-%d").date().replace(day=1)
            cur = s_dt
            while cur <= e_dt:
                ym = cur.strftime("%Y%m01")
                try:
                    for r in self.fetch_twse_index_month(ym):
                        if start_date_iso.replace("-", "/") <= r[0] <= end_date_iso.replace("-", "/"):
                            rows[r[0]] = r
                except Exception:
                    pass
                if cur.month == 12:
                    cur = datetime.date(cur.year + 1, 1, 1)
                else:
                    cur = datetime.date(cur.year, cur.month + 1, 1)
        except Exception:
            pass

        return [rows[k] for k in sorted(rows.keys())]

    def fetch_twse_index_month(self, date_yyyymmdd: str) -> list[tuple[str, float, float]]:
        """Fetch daily Taiwan Weighted Index (`POINT`, `CHANGE`) for a given month from TWSE `FMTQIK`."""
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={date_yyyymmdd}&response=json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.USER_AGENT, "Referer": "https://www.twse.com.tw/"},
        )
        with urllib.request.urlopen(req, timeout=8, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows: list[tuple[str, float, float]] = []
        for item in data.get("data", []):
            dt = self.roc_to_gregorian(item[0])
            pt = round(float(str(item[4]).replace(",", "")), 2)
            chg = round(float(str(item[5]).replace(",", "")), 2)
            rows.append((dt, pt, chg))
        return rows

    def fetch_foreign_spot_range(self, start_date_iso: str, end_date_iso: str) -> dict[str, float]:
        """Fetch Foreign Investor spot net buy/sell in 100M TWD (`億`) for `[start_date_iso, end_date_iso]`."""
        spot_map: dict[str, float] = {}
        try:
            for item in self._finmind_get(
                "TaiwanStockTotalInstitutionalInvestors", None, start_date_iso, end_date_iso
            ):
                if item.get("name") == "Foreign_Investor":
                    dt = str(item["date"]).replace("-", "/")
                    spot_map[dt] = round((float(item["buy"]) - float(item["sell"])) / 1e8, 2)
        except Exception:
            pass
        return spot_map

    def fetch_taifex_institutional_range(
        self, start_date_slash: str, end_date_slash: str
    ) -> tuple[dict[str, tuple[float, float]], dict[str, float], dict[str, float]]:
        """
        Fetch TAIFEX `futContractsDateDown` for `TXF`, `MXF`, `TMF` over `[start_date_slash, end_date_slash]`,
        with FinMind `TaiwanFuturesInstitutionalInvestors` fallback/complement.
        Returns `(txf_map, mxf_inst_oi_map, tmf_inst_oi_map)`.
        """
        headers_form = {
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        txf_map: dict[str, tuple[float, float]] = {}
        mxf_inst_oi: dict[str, float] = {}
        tmf_inst_oi: dict[str, float] = {}

        # 1. Primary: Official TAIFEX futContractsDateDown
        for cid in ("TXF", "MXF", "TMF"):
            try:
                body = urllib.parse.urlencode({
                    "queryStartDate": start_date_slash,
                    "queryEndDate": end_date_slash,
                    "commodityId": cid,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://www.taifex.com.tw/cht/3/futContractsDateDown",
                    data=body,
                    headers=headers_form,
                )
                with urllib.request.urlopen(req, timeout=12, context=_ssl_ctx()) as resp:
                    raw = resp.read().decode("cp950", errors="replace")
                for ln in raw.splitlines()[1:]:
                    cols = [c.strip() for c in ln.split(",")]
                    if len(cols) >= 14 and cols[0].startswith("20"):
                        dt = cols[0]
                        role = cols[2]
                        tr_net = float(cols[7])
                        oi_net = float(cols[13])
                        if cid == "TXF" and "外資" in role:
                            txf_map[dt] = (tr_net, oi_net)
                        elif cid == "MXF":
                            mxf_inst_oi[dt] = mxf_inst_oi.get(dt, 0.0) + oi_net
                        elif cid == "TMF":
                            tmf_inst_oi[dt] = tmf_inst_oi.get(dt, 0.0) + oi_net
            except Exception:
                pass

        # 2. Complement / Fallback: FinMind TaiwanFuturesInstitutionalInvestors
        s_iso = start_date_slash.replace("/", "-")
        e_iso = end_date_slash.replace("/", "-")
        try:
            for r in self._finmind_get("TaiwanFuturesInstitutionalInvestors", "TX", s_iso, e_iso):
                if "外資" in str(r.get("institutional_investors", "")):
                    dt = str(r["date"]).replace("-", "/")
                    if dt not in txf_map:
                        tr_net = float(r["long_deal_volume"]) - float(r["short_deal_volume"])
                        oi_net = float(r["long_open_interest_balance_volume"]) - float(
                            r["short_open_interest_balance_volume"]
                        )
                        txf_map[dt] = (tr_net, oi_net)
        except Exception:
            pass

        for fm_cid, target in (("MTX", mxf_inst_oi), ("TMF", tmf_inst_oi)):
            try:
                acc: dict[str, float] = {}
                for r in self._finmind_get("TaiwanFuturesInstitutionalInvestors", fm_cid, s_iso, e_iso):
                    dt = str(r["date"]).replace("-", "/")
                    oi_net = float(r["long_open_interest_balance_volume"]) - float(
                        r["short_open_interest_balance_volume"]
                    )
                    acc[dt] = acc.get(dt, 0.0) + oi_net
                for dt, val in acc.items():
                    if dt not in target:
                        target[dt] = val
            except Exception:
                pass

        return txf_map, mxf_inst_oi, tmf_inst_oi

    def fetch_taifex_total_oi_range(
        self, start_date: datetime.date, end_date: datetime.date
    ) -> tuple[dict[str, int], dict[str, int]]:
        """
        Fetch TAIFEX `futDataDown` in `<=25`-day windows for `MTX` (`小台`) and `TMF` (`微台`)
        to obtain daily regular-session single-contract Total Market Open Interest (`全市場未平倉口數`),
        with FinMind `TaiwanFuturesDaily` fallback/complement.
        """
        headers_form = {
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        mtx_tot: dict[str, int] = {}
        tmf_tot: dict[str, int] = {}

        windows: list[tuple[str, str]] = []
        cur = start_date
        while cur <= end_date:
            nxt = min(end_date, cur + datetime.timedelta(days=25))
            windows.append((cur.strftime("%Y/%m/%d"), nxt.strftime("%Y/%m/%d")))
            cur = nxt + datetime.timedelta(days=1)

        # 1. Primary: Official TAIFEX futDataDown
        for cid, target in (("MTX", mtx_tot), ("TMF", tmf_tot)):
            for s_str, e_str in windows:
                try:
                    body = urllib.parse.urlencode({
                        "down_type": "1",
                        "commodity_id": cid,
                        "commodity_id2": "",
                        "queryStartDate": s_str,
                        "queryEndDate": e_str,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        "https://www.taifex.com.tw/cht/3/futDataDown",
                        data=body,
                        headers=headers_form,
                    )
                    with urllib.request.urlopen(req, timeout=12, context=_ssl_ctx()) as resp:
                        raw = resp.read().decode("cp950", errors="replace")
                    for ln in raw.splitlines()[1:]:
                        cols = [c.strip() for c in ln.split(",")]
                        if (len(cols) >= 18 and cols[0].startswith("20") and cols[17] == "一般"
                                and "/" not in cols[2] and cols[11].isdigit()):
                            target[cols[0]] = target.get(cols[0], 0) + int(cols[11])
                except Exception:
                    pass

        # 2. Complement / Fallback: FinMind TaiwanFuturesDaily
        s_iso = start_date.strftime("%Y-%m-%d")
        e_iso = end_date.strftime("%Y-%m-%d")
        for cid, target in (("MTX", mtx_tot), ("TMF", tmf_tot)):
            try:
                acc: dict[str, int] = {}
                for r in self._finmind_get("TaiwanFuturesDaily", cid, s_iso, e_iso):
                    if r.get("trading_session") == "position" and "/" not in str(r.get("contract_date", "")):
                        dt = str(r["date"]).replace("-", "/")
                        acc[dt] = acc.get(dt, 0) + int(r.get("open_interest") or 0)
                for dt, val in acc.items():
                    if dt not in target and val > 0:
                        target[dt] = val
            except Exception:
                pass

        return mtx_tot, tmf_tot


def update_all_to_latest(
    db_manager: LobTurtleDBManager,
    fetcher: TWSETAIFEXFetcher | None = None,
    target_end_date: datetime.date | None = None,
) -> dict[str, Any]:
    """
    One-Click Incremental Live Data Updater (`一鍵更新最新數據`)
    ------------------------------------------------------------
    1. Ensures all 9 historical SQLite databases (`2020/11/05 ~ 2026/11/06`) exist and are preserved.
    2. Queries official TWSE / TAIFEX / FinMind endpoints from each DB's `MAX(DATE)` up to `today`.
    3. Writes ONLY new trading days (`DATE > db_last_date`) one by one (`insert_new_one_by_one`)
       back into `data/*.db`, strictly preserving every historical record.
    4. Seamlessly computes `LOBSTER`, `LOBSTER_SUM`, and `TW50_TURTLE_V1..V3` for newly added
       trading days and writes them back one by one into `LOBSTER.db` and `TW50_TURTLE_V1..V3.db`.
    """
    seed_databases(db_manager, force=False)

    status_before = {s["name"]: (s["lastDate"] or "2020/11/05") for s in db_manager.get_status_summary()}
    previous_latest_date = max(status_before.values(), default="")
    min_last_str = min(status_before.values(), default="2026/11/06")

    try:
        min_last_dt = datetime.datetime.strptime(min_last_str, "%Y/%m/%d").date()
    except ValueError:
        min_last_dt = datetime.date(2026, 11, 6)

    end_dt = target_end_date or datetime.date.today()
    fetch_start = min_last_dt
    active_fetcher = fetcher or TWSETAIFEXFetcher()
    inserted_by_db: dict[str, list[str]] = {name: [] for name in status_before}

    if fetch_start <= end_dt:
        s_iso = fetch_start.strftime("%Y-%m-%d")
        e_iso = end_dt.strftime("%Y-%m-%d")
        s_slash = fetch_start.strftime("%Y/%m/%d")
        e_slash = end_dt.strftime("%Y/%m/%d")

        # 1. TAIEX -> TWSE_INFO.db (strictly dates > status_before["TWSE_INFO.db"])
        taiex_new = [
            r for r in active_fetcher.fetch_taiex_range(s_iso, e_iso)
            if r[0] > status_before["TWSE_INFO.db"]
        ]
        if taiex_new:
            inserted_by_db["TWSE_INFO.db"] = db_manager.insert_new_one_by_one(
                "TWSE_INFO.db", ["DATE", "POINT", "CHANGE"], taiex_new
            )

        # 2. Foreign Spot -> TWSE_FOREIGEN.db
        spot_map = active_fetcher.fetch_foreign_spot_range(s_iso, e_iso)
        spot_new = [
            (dt, val) for dt, val in sorted(spot_map.items())
            if dt > status_before["TWSE_FOREIGEN.db"]
        ]
        if spot_new:
            inserted_by_db["TWSE_FOREIGEN.db"] = db_manager.insert_new_one_by_one(
                "TWSE_FOREIGEN.db", ["DATE", "SPOT_NET_BUY"], spot_new
            )

        # 3. Foreign TXF & Mini/Micro-TXF Institutional + Total OI -> TXF_FOREIGEN.db, MXF_LOSER.db, TMF_LOSER.db
        txf_map, mxf_inst, tmf_inst = active_fetcher.fetch_taifex_institutional_range(s_slash, e_slash)
        txf_new = [
            (dt, vals[0], vals[1]) for dt, vals in sorted(txf_map.items())
            if dt > status_before["TXF_FOREIGEN.db"]
        ]
        if txf_new:
            inserted_by_db["TXF_FOREIGEN.db"] = db_manager.insert_new_one_by_one(
                "TXF_FOREIGEN.db", ["DATE", "FUT_TRADE_NET", "FUT_OI_NET"], txf_new
            )

        mtx_tot, tmf_tot = active_fetcher.fetch_taifex_total_oi_range(fetch_start, end_dt)

        mxf_new: list[tuple[str, float]] = []
        for dt, inst_oi in sorted(mxf_inst.items()):
            if dt > status_before["MXF_LOSER.db"] and dt in mtx_tot and mtx_tot[dt] > 0:
                mxf_new.append((dt, active_fetcher.compute_retail_long_short_ratio(inst_oi, mtx_tot[dt])))
        if mxf_new:
            inserted_by_db["MXF_LOSER.db"] = db_manager.insert_new_one_by_one(
                "MXF_LOSER.db", ["DATE", "RETAIL_RATIO"], mxf_new
            )

        tmf_new: list[tuple[str, float]] = []
        for dt, inst_oi in sorted(tmf_inst.items()):
            if dt >= "2024/07/29" and dt > status_before["TMF_LOSER.db"] and dt in tmf_tot and tmf_tot[dt] > 0:
                tmf_new.append((dt, active_fetcher.compute_retail_long_short_ratio(inst_oi, tmf_tot[dt])))
        if tmf_new:
            inserted_by_db["TMF_LOSER.db"] = db_manager.insert_new_one_by_one(
                "TMF_LOSER.db", ["DATE", "RETAIL_RATIO"], tmf_new
            )

    # 4. Incrementally compute & write back LOBSTER and TURTLE for any new dates in TWSE_INFO.db
    twse_all = db_manager.fetch_all("TWSE_INFO.db")
    if twse_all:
        dates = [r["DATE"] for r in twse_all]
        points = [float(r["POINT"]) for r in twse_all]

        lob_existing = {r["DATE"]: int(r["LOBSTER"]) for r in db_manager.fetch_all("LOBSTER.db")}
        missing_lob_dates = {d for d in dates if d not in lob_existing}
        if missing_lob_dates:
            preserved_seq: list[int | None] = [lob_existing.get(d) for d in dates]
            lob_ind = LobsterIndicator()
            calc_lob, calc_sum = lob_ind.compute_with_preserved_history(points, preserved_seq)
            lob_new_rows = [
                (d, int(calc_lob[i]), int(calc_sum[i]))
                for i, d in enumerate(dates)
                if d in missing_lob_dates
            ]
            if lob_new_rows:
                inserted_by_db["LOBSTER.db"] = db_manager.insert_new_one_by_one(
                    "LOBSTER.db", ["DATE", "LOBSTER", "LOBSTER_SUM"], lob_new_rows
                )

        v1_existing = {r["DATE"] for r in db_manager.fetch_all("TW50_TURTLE_V1.db")}
        v2_existing = {r["DATE"] for r in db_manager.fetch_all("TW50_TURTLE_V2.db")}
        v3_existing = {r["DATE"] for r in db_manager.fetch_all("TW50_TURTLE_V3.db")}
        if len(v1_existing) < len(dates) or len(v2_existing) < len(dates) or len(v3_existing) < len(dates):
            tur_ind = TurtleIndicator()
            tur_res = tur_ind.compute_all(points)
            v1_new, v2_new, v3_new = [], [], []
            for i, d in enumerate(dates):
                if d not in v1_existing:
                    v1_new.append((
                        d,
                        int(tur_res["v1"]["A"][i]),
                        int(tur_res["v1"]["B"][i]),
                        int(tur_res["v1"]["C"][i]),
                        int(tur_res["v1"]["D"][i]),
                    ))
                if d not in v2_existing:
                    v2_new.append((
                        d,
                        int(tur_res["v2"]["5"][i]),
                        int(tur_res["v2"]["4.5"][i]),
                        int(tur_res["v2"]["4"][i]),
                    ))
                if d not in v3_existing:
                    v3_new.append((
                        d,
                        int(tur_res["v3"]["5"][i]),
                        int(tur_res["v3"]["4.5"][i]),
                        int(tur_res["v3"]["4"][i]),
                    ))
            if v1_new:
                inserted_by_db["TW50_TURTLE_V1.db"] = db_manager.insert_new_one_by_one(
                    "TW50_TURTLE_V1.db", ["DATE", "A", "B", "C", "D"], v1_new
                )
            if v2_new:
                inserted_by_db["TW50_TURTLE_V2.db"] = db_manager.insert_new_one_by_one(
                    "TW50_TURTLE_V2.db", ["DATE", "S5", "S4_5", "S4"], v2_new
                )
            if v3_new:
                inserted_by_db["TW50_TURTLE_V3.db"] = db_manager.insert_new_one_by_one(
                    "TW50_TURTLE_V3.db", ["DATE", "S5", "S4_5", "S4"], v3_new
                )

    summary = db_manager.get_status_summary()
    latest_date = max((s["lastDate"] or "" for s in summary), default="")
    total_inserted = sum(len(v) for v in inserted_by_db.values())
    return {
        "ok": True,
        "previousDate": previous_latest_date,
        "latestDate": latest_date,
        "totalInsertedRows": total_inserted,
        "insertedByDb": {k: v for k, v in inserted_by_db.items() if v},
        "checkedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(summary),
        "summary": summary,
    }


recompute_indicators_for_new_dates = update_all_to_latest
