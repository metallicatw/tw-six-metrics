
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DOC_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_CELL_RE = re.compile(r"([A-Z]+)(\d+)")


def col_to_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


@dataclass(frozen=True)
class SheetRef:
    name: str
    path: str
    sheet_id: str
    state: str


class Workbook:

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path)
        self._sst: list[str] | None = None
        self.sheets = self._read_sheet_index()


    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Workbook:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def shared_strings(self) -> list[str]:
        if self._sst is None:
            try:
                raw = self._zip.read("xl/sharedStrings.xml")
            except KeyError:
                self._sst = []
                return self._sst
            root = ET.fromstring(raw)
            self._sst = [
                "".join(t.text or "" for t in si.iter(NS + "t")) for si in root
            ]
        return self._sst

    def _read_sheet_index(self) -> list[SheetRef]:
        rels_raw = self._zip.read("xl/_rels/workbook.xml.rels")
        rid_to_target: dict[str, str] = {}
        for rel in ET.fromstring(rels_raw):
            rid_to_target[rel.get("Id", "")] = rel.get("Target", "")

        wb_raw = self._zip.read("xl/workbook.xml")
        out: list[SheetRef] = []
        for sheet in ET.fromstring(wb_raw).iter(NS + "sheet"):
            rid = sheet.get(DOC_REL_NS + "id", "")
            target = rid_to_target.get(rid, "")
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            out.append(
                SheetRef(
                    name=sheet.get("name", ""),
                    path=path,
                    sheet_id=sheet.get("sheetId", ""),
                    state=sheet.get("state", "visible"),
                )
            )
        return out

    def sheet(self, name: str) -> SheetRef:
        for s in self.sheets:
            if s.name == name:
                return s
        raise KeyError(f"no such sheet: {name!r} (have {[s.name for s in self.sheets]})")


    def cached_values(
        self,
        sheet_name: str,
        min_row: int = 1,
        max_row: int | None = None,
    ) -> dict[tuple[int, int], object]:
        ref = self.sheet(sheet_name)
        sst = self.shared_strings
        out: dict[tuple[int, int], object] = {}

        with self._zip.open(ref.path) as fh:
            for _event, el in ET.iterparse(fh, events=("end",)):
                if el.tag != NS + "row":
                    continue
                row = int(el.get("r", "0"))
                if row < min_row:
                    el.clear()
                    continue
                if max_row is not None and row > max_row:
                    el.clear()
                    break
                for c in el.iter(NS + "c"):
                    m = _CELL_RE.match(c.get("r", ""))
                    if not m:
                        continue
                    col = col_to_index(m.group(1))
                    ctype = c.get("t")
                    if ctype == "inlineStr":
                        is_el = c.find(NS + "is")
                        if is_el is None:
                            continue
                        out[(row, col)] = "".join(
                            t.text or "" for t in is_el.iter(NS + "t")
                        )
                        continue
                    v = c.find(NS + "v")
                    if v is None or v.text is None:
                        continue
                    raw = v.text
                    if ctype == "s":
                        try:
                            out[(row, col)] = sst[int(raw)]
                        except (ValueError, IndexError):
                            out[(row, col)] = raw
                    elif ctype == "str" or ctype == "e":
                        out[(row, col)] = raw
                    elif ctype == "b":
                        out[(row, col)] = raw == "1"
                    else:
                        try:
                            out[(row, col)] = float(raw)
                        except ValueError:
                            out[(row, col)] = raw
                el.clear()
        return out
