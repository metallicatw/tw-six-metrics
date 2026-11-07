"""
SQLite Database Storage Engine for LobTurtle (龍蝦/海龜模組)
============================================================

Manages the 9 canonical SQLite databases used by the LobTurtle system:
1. `TWSE_INFO.db`      - Taiwan Weighted Index (`DATE`, `POINT`, `CHANGE`)
2. `LOBSTER.db`        - Daily Lobster Indicator (`DATE`, `LOBSTER`, `LOBSTER_SUM`)
3. `TWSE_FOREIGEN.db`  - Foreign Investor Spot Net Buy/Sell in 100M TWD (`DATE`, `SPOT_NET_BUY`)
4. `TXF_FOREIGEN.db`   - Foreign Investor TXF Futures Net Trade & Open Interest (`DATE`, `FUT_TRADE_NET`, `FUT_OI_NET`)
5. `MXF_LOSER.db`      - Mini-TXF Retail Long/Short Ratio % (`DATE`, `RETAIL_RATIO`)
6. `TMF_LOSER.db`      - Micro-TXF Retail Long/Short Ratio % (`DATE`, `RETAIL_RATIO`)
7. `TW50_TURTLE_V1.db` - Turtle Long-Term Signals V1 (`DATE`, `A`, `B`, `C`, `D`)
8. `TW50_TURTLE_V2.db` - Turtle Medium-Term Signals V2 (`DATE`, `S5`, `S4_5`, `S4`)
9. `TW50_TURTLE_V3.db` - Turtle Filtered Signals V3 (`DATE`, `S5`, `S4_5`, `S4`)
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

DB_FILES = (
    "TWSE_INFO.db",
    "LOBSTER.db",
    "TWSE_FOREIGEN.db",
    "TXF_FOREIGEN.db",
    "MXF_LOSER.db",
    "TMF_LOSER.db",
    "TW50_TURTLE_V1.db",
    "TW50_TURTLE_V2.db",
    "TW50_TURTLE_V3.db",
)

DB_SCHEMA_COLUMNS: dict[str, tuple[str, ...]] = {
    "TWSE_INFO.db": ("DATE", "POINT", "CHANGE"),
    "LOBSTER.db": ("DATE", "LOBSTER", "LOBSTER_SUM"),
    "TWSE_FOREIGEN.db": ("DATE", "SPOT_NET_BUY"),
    "TXF_FOREIGEN.db": ("DATE", "FUT_TRADE_NET", "FUT_OI_NET"),
    "MXF_LOSER.db": ("DATE", "RETAIL_RATIO"),
    "TMF_LOSER.db": ("DATE", "RETAIL_RATIO"),
    "TW50_TURTLE_V1.db": ("DATE", "A", "B", "C", "D"),
    "TW50_TURTLE_V2.db": ("DATE", "S5", "S4_5", "S4"),
    "TW50_TURTLE_V3.db": ("DATE", "S5", "S4_5", "S4"),
}


class LobTurtleDBManager:
    """Manages connection, schema initialization, queries, and upserts across all 9 LobTurtle SQLite databases."""

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.init_all_schemas()

    def db_path(self, db_name: str) -> Path:
        return self.data_dir / db_name

    @contextlib.contextmanager
    def _connect(self, db_name: str) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path(db_name)))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_all_schemas(self) -> None:
        """Create tables in all 9 SQLite databases if they do not exist."""
        schemas: dict[str, str] = {
            "TWSE_INFO.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    POINT REAL NOT NULL,
                    CHANGE REAL DEFAULT 0.0
                );
            """,
            "LOBSTER.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    LOBSTER INTEGER NOT NULL,
                    LOBSTER_SUM INTEGER NOT NULL
                );
            """,
            "TWSE_FOREIGEN.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    SPOT_NET_BUY REAL NOT NULL
                );
            """,
            "TXF_FOREIGEN.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    FUT_TRADE_NET REAL NOT NULL,
                    FUT_OI_NET REAL NOT NULL
                );
            """,
            "MXF_LOSER.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    RETAIL_RATIO REAL NOT NULL
                );
            """,
            "TMF_LOSER.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    RETAIL_RATIO REAL NOT NULL
                );
            """,
            "TW50_TURTLE_V1.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    A INTEGER NOT NULL,
                    B INTEGER NOT NULL,
                    C INTEGER NOT NULL,
                    D INTEGER NOT NULL
                );
            """,
            "TW50_TURTLE_V2.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    S5 INTEGER NOT NULL,
                    S4_5 INTEGER NOT NULL,
                    S4 INTEGER NOT NULL
                );
            """,
            "TW50_TURTLE_V3.db": """
                CREATE TABLE IF NOT EXISTS DATA (
                    DATE TEXT PRIMARY KEY,
                    S5 INTEGER NOT NULL,
                    S4_5 INTEGER NOT NULL,
                    S4 INTEGER NOT NULL
                );
            """,
        }
        for db_name, ddl in schemas.items():
            with self._connect(db_name) as conn:
                conn.executescript(ddl)
                conn.commit()

    def upsert_many(self, db_name: str, columns: Sequence[str], rows: Sequence[tuple[Any, ...]]) -> int:
        """Upsert multiple rows into the `DATA` table of the specified SQLite database."""
        if not rows:
            return 0
        cols_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT OR REPLACE INTO DATA ({cols_sql}) VALUES ({placeholders})"
        with self._connect(db_name) as conn:
            conn.executemany(sql, rows)
            conn.commit()
            return len(rows)

    def insert_ignore_many(self, db_name: str, columns: Sequence[str], rows: Sequence[tuple[Any, ...]]) -> int:
        """
        Insert rows using `INSERT OR IGNORE` so all existing historical records in `DATA`
        are strictly preserved and never overwritten. Returns count of newly inserted rows.
        """
        if not rows:
            return 0
        cols_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT OR IGNORE INTO DATA ({cols_sql}) VALUES ({placeholders})"
        with self._connect(db_name) as conn:
            before = conn.total_changes
            conn.executemany(sql, rows)
            conn.commit()
            return conn.total_changes - before

    def insert_new_one_by_one(self, db_name: str, columns: Sequence[str], rows: Sequence[tuple[Any, ...]]) -> list[str]:
        """
        Incrementally write new trading-day records into `DATA` one by one (`一一寫回資料庫中`)
        in chronological order without modifying any existing historical row.
        Returns the list of newly written `DATE` strings.
        """
        if not rows:
            return []
        cols_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT OR IGNORE INTO DATA ({cols_sql}) VALUES ({placeholders})"
        inserted_dates: list[str] = []
        with self._connect(db_name) as conn:
            for row in sorted(rows, key=lambda r: str(r[0])):
                before = conn.total_changes
                conn.execute(sql, row)
                if conn.total_changes > before:
                    inserted_dates.append(str(row[0]))
            conn.commit()
        return inserted_dates

    def fetch_all(self, db_name: str, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        """Fetch rows ordered by `DATE ASC` with optional date range filtering."""
        clauses: list[str] = []
        params: list[Any] = []
        if start_date:
            clauses.append("DATE >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("DATE <= ?")
            params.append(end_date)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM DATA {where_sql} ORDER BY DATE ASC"
        with self._connect(db_name) as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def get_status_summary(self) -> list[dict[str, Any]]:
        """Return status summary of all 9 SQLite databases (`name`, `firstDate`, `lastDate`, `rowCount`)."""
        summary: list[dict[str, Any]] = []
        for db_name in DB_FILES:
            p = self.db_path(db_name)
            if not p.exists():
                summary.append({"name": db_name, "firstDate": None, "lastDate": None, "rowCount": 0})
                continue
            with self._connect(db_name) as conn:
                row = conn.execute(
                    "SELECT MIN(DATE) AS first_date, MAX(DATE) AS last_date, COUNT(*) AS cnt FROM DATA"
                ).fetchone()
                summary.append({
                    "name": db_name,
                    "firstDate": row["first_date"] if row else None,
                    "lastDate": row["last_date"] if row else None,
                    "rowCount": int(row["cnt"]) if row else 0,
                })
        return summary

    def export_snapshot(self, since_date: str | None = None) -> dict[str, Any]:
        """
        Export compact row arrays across all 9 SQLite databases (optionally filtered to `DATE >= since_date`)
        for lossless bidirectional union-merge synchronization between Local PC and Synology NAS.
        """
        dbs_payload: dict[str, Any] = {}
        total_rows = 0
        for db_name, cols in DB_SCHEMA_COLUMNS.items():
            rows_dict = self.fetch_all(db_name, start_date=since_date)
            compact_rows = [[r.get(c) for c in cols] for r in rows_dict]
            dbs_payload[db_name] = {
                "columns": list(cols),
                "rows": compact_rows,
            }
            total_rows += len(compact_rows)
        summary = self.get_status_summary()
        latest_date = max((s["lastDate"] or "" for s in summary), default="")
        return {
            "ok": True,
            "latestDate": latest_date,
            "totalExportedRows": total_rows,
            "databases": dbs_payload,
        }

    def merge_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Merge an exported 9-DB snapshot into this `LobTurtleDBManager` using `INSERT OR IGNORE`.
        100% of existing historical records are strictly preserved; only missing trading dates are inserted.
        """
        dbs_payload = snapshot.get("databases") or {}
        per_db_inserted: dict[str, int] = {}
        total_inserted = 0
        for db_name, cols in DB_SCHEMA_COLUMNS.items():
            entry = dbs_payload.get(db_name)
            if not entry:
                per_db_inserted[db_name] = 0
                continue
            incoming_cols = tuple(entry.get("columns") or cols)
            if incoming_cols != cols:
                continue
            raw_rows = entry.get("rows") or []
            tuples = [tuple(r) for r in raw_rows if isinstance(r, (list, tuple)) and len(r) == len(cols)]
            added = self.insert_ignore_many(db_name, cols, tuples)
            per_db_inserted[db_name] = added
            total_inserted += added
        summary = self.get_status_summary()
        latest_date = max((s["lastDate"] or "" for s in summary), default="")
        return {
            "ok": True,
            "totalInsertedRows": total_inserted,
            "perDbInserted": per_db_inserted,
            "latestDate": latest_date,
        }

    def merge_from_directory(self, other_data_dir: str | Path) -> dict[str, Any]:
        """Union-merge all 9 SQLite `.db` files from another directory into this manager (`INSERT OR IGNORE`)."""
        other_mgr = LobTurtleDBManager(data_dir=other_data_dir)
        snap = other_mgr.export_snapshot()
        return self.merge_snapshot(snap)

    def get_lobster_chart_payload(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Build payload for `GET /api/charts/lobster/data`."""
        twse_rows = {r["DATE"]: r for r in self.fetch_all("TWSE_INFO.db", start_date, end_date)}
        lob_rows = self.fetch_all("LOBSTER.db", start_date, end_date)
        labels: list[str] = []
        point: list[float | None] = []
        change: list[float | None] = []
        lobster: list[int] = []
        lobster_sum: list[int] = []
        for r in lob_rows:
            dt = r["DATE"]
            labels.append(dt)
            if dt in twse_rows:
                point.append(round(float(twse_rows[dt]["POINT"]), 2))
                change.append(round(float(twse_rows[dt].get("CHANGE", 0.0) or 0.0), 2))
            else:
                point.append(None)
                change.append(None)
            lobster.append(int(r["LOBSTER"]))
            lobster_sum.append(int(r["LOBSTER_SUM"]))
        return {
            "dataDate": labels[-1] if labels else "",
            "labels": labels,
            "point": point,
            "change": change,
            "lobster": lobster,
            "lobster_sum": lobster_sum,
        }

    def get_foreign_chart_payload(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Build payload for `GET /api/charts/lobster/foreign`."""
        twse_rows = {r["DATE"]: r["POINT"] for r in self.fetch_all("TWSE_INFO.db", start_date, end_date)}
        spot_rows = {r["DATE"]: r["SPOT_NET_BUY"] for r in self.fetch_all("TWSE_FOREIGEN.db", start_date, end_date)}
        fut_rows = {r["DATE"]: r for r in self.fetch_all("TXF_FOREIGEN.db", start_date, end_date)}
        labels = sorted(set(twse_rows.keys()) | set(spot_rows.keys()) | set(fut_rows.keys()))
        point = [round(float(twse_rows[d]), 2) if d in twse_rows else None for d in labels]
        spot_vals = [round(float(spot_rows[d]), 2) if d in spot_rows else None for d in labels]
        fut_tr_vals = [round(float(fut_rows[d]["FUT_TRADE_NET"]), 1) if d in fut_rows else None for d in labels]
        fut_oi_vals = [round(float(fut_rows[d]["FUT_OI_NET"]), 1) if d in fut_rows else None for d in labels]
        return {
            "dataDate": labels[-1] if labels else "",
            "labels": labels,
            "point": point,
            "series": [
                {"name": "外資現貨買賣超(億)", "values": spot_vals, "invert": False},
                {"name": "外資期貨買賣超(口)", "values": fut_tr_vals, "invert": False},
                {"name": "外資期貨未平倉(口)", "values": fut_oi_vals, "invert": False},
            ],
        }

    def get_retail_chart_payload(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Build payload for `GET /api/charts/lobster/retail`."""
        twse_rows = {r["DATE"]: r["POINT"] for r in self.fetch_all("TWSE_INFO.db", start_date, end_date)}
        mxf_rows = {r["DATE"]: r["RETAIL_RATIO"] for r in self.fetch_all("MXF_LOSER.db", start_date, end_date)}
        tmf_rows = {r["DATE"]: r["RETAIL_RATIO"] for r in self.fetch_all("TMF_LOSER.db", start_date, end_date)}
        labels = sorted(set(twse_rows.keys()) | set(mxf_rows.keys()) | set(tmf_rows.keys()))
        point = [round(float(twse_rows[d]), 2) if d in twse_rows else None for d in labels]
        mxf_vals = [round(float(mxf_rows[d]), 2) if d in mxf_rows else None for d in labels]
        tmf_vals = [round(float(tmf_rows[d]), 2) if d in tmf_rows else None for d in labels]
        return {
            "dataDate": labels[-1] if labels else "",
            "labels": labels,
            "point": point,
            "series": [
                {"name": "小台散戶未平倉(%)", "values": mxf_vals, "invert": True},
                {"name": "微台散戶未平倉(%)", "values": tmf_vals, "invert": True},
            ],
        }

    def get_backtest_payload(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Build payload for `GET /api/charts/lobster/backtest`."""
        twse_rows = {r["DATE"]: r["POINT"] for r in self.fetch_all("TWSE_INFO.db", start_date, end_date)}
        lob_rows = {r["DATE"]: r for r in self.fetch_all("LOBSTER.db", start_date, end_date)}
        mxf_rows = {r["DATE"]: r["RETAIL_RATIO"] for r in self.fetch_all("MXF_LOSER.db", start_date, end_date)}
        tmf_rows = {r["DATE"]: r["RETAIL_RATIO"] for r in self.fetch_all("TMF_LOSER.db", start_date, end_date)}
        labels = sorted(lob_rows.keys())
        return {
            "dataDate": labels[-1] if labels else "",
            "labels": labels,
            "point": [round(float(twse_rows[d]), 2) if d in twse_rows else None for d in labels],
            "lobster": [int(lob_rows[d]["LOBSTER"]) for d in labels],
            "lobster_sum": [int(lob_rows[d]["LOBSTER_SUM"]) for d in labels],
            "mxf": [round(float(mxf_rows[d]), 2) if d in mxf_rows else None for d in labels],
            "tmf": [round(float(tmf_rows[d]), 2) if d in tmf_rows else None for d in labels],
        }

    def get_turtle_chart_payload(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Build payload for `GET /api/charts/turtle/data`."""
        twse_rows = {r["DATE"]: r["POINT"] for r in self.fetch_all("TWSE_INFO.db", start_date, end_date)}
        v1_rows = {r["DATE"]: r for r in self.fetch_all("TW50_TURTLE_V1.db", start_date, end_date)}
        v2_rows = {r["DATE"]: r for r in self.fetch_all("TW50_TURTLE_V2.db", start_date, end_date)}
        v3_rows = {r["DATE"]: r for r in self.fetch_all("TW50_TURTLE_V3.db", start_date, end_date)}
        labels = sorted(set(v1_rows.keys()) | set(v2_rows.keys()) | set(v3_rows.keys()))
        return {
            "dataDate": labels[-1] if labels else "",
            "labels": labels,
            "point": [round(float(twse_rows[d]), 2) if d in twse_rows else None for d in labels],
            "v1": [
                {"name": "A", "values": [int(v1_rows[d]["A"]) if d in v1_rows else 0 for d in labels]},
                {"name": "B", "values": [int(v1_rows[d]["B"]) if d in v1_rows else 0 for d in labels]},
                {"name": "C", "values": [int(v1_rows[d]["C"]) if d in v1_rows else 0 for d in labels]},
                {"name": "D", "values": [int(v1_rows[d]["D"]) if d in v1_rows else 0 for d in labels]},
            ],
            "v2": [
                {"name": "5", "values": [int(v2_rows[d]["S5"]) if d in v2_rows else 0 for d in labels]},
                {"name": "4.5", "values": [int(v2_rows[d]["S4_5"]) if d in v2_rows else 0 for d in labels]},
                {"name": "4", "values": [int(v2_rows[d]["S4"]) if d in v2_rows else 0 for d in labels]},
            ],
            "v3": [
                {"name": "5", "values": [int(v3_rows[d]["S5"]) if d in v3_rows else 0 for d in labels]},
                {"name": "4.5", "values": [int(v3_rows[d]["S4_5"]) if d in v3_rows else 0 for d in labels]},
                {"name": "4", "values": [int(v3_rows[d]["S4"]) if d in v3_rows else 0 for d in labels]},
            ],
        }
