"""Extract VBA module source from an .xlsm without oletools.

Three formats stand between the file and the code:

1. The VBA project is an OLE2 compound file (``xl/vbaProject.bin``) — a FAT
   filesystem in a file, with a normal sector chain and a "mini" chain for
   streams under 4096 bytes.
2. Each stream holds MS-OVBA compressed data: a 0x01 signature byte then a
   series of chunks, each a 16-bit header giving chunk length and whether it
   is compressed, followed by flag-byte-driven literal/copy tokens.
3. A module stream begins with a performance cache; the source starts at the
   byte offset recorded for that module in the (itself compressed) ``dir``
   stream.  Scanning for the first plausible 0x01 works for small modules and
   silently truncates large ones, so the offsets are read properly here.

The sandbox has no network and therefore no oletools.  Read-only, which is
all that is needed to port the macros.
"""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC


class Ole:
    def __init__(self, data: bytes):
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("not an OLE2 compound file")
        self.data = data
        self.ssz = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mssz = 1 << struct.unpack_from("<H", data, 32)[0]
        self.n_fat = struct.unpack_from("<I", data, 44)[0]
        self.dir_start = struct.unpack_from("<I", data, 48)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        self.mini_fat_start = struct.unpack_from("<I", data, 60)[0]
        self.difat_start = struct.unpack_from("<I", data, 68)[0]
        self._read_difat()
        self._read_fat()
        self._read_dir()
        self._read_mini_fat()

    def _sector(self, i: int) -> bytes:
        off = 512 + i * self.ssz
        return self.data[off : off + self.ssz]

    def _read_difat(self) -> None:
        self.difat = list(struct.unpack_from("<109I", self.data, 76))
        nxt = self.difat_start
        per = self.ssz // 4 - 1
        while nxt not in (ENDOFCHAIN, FREESECT):
            sec = self._sector(nxt)
            vals = struct.unpack_from(f"<{self.ssz // 4}I", sec, 0)
            self.difat.extend(vals[:per])
            nxt = vals[per]
        self.difat = [d for d in self.difat if d != FREESECT][: self.n_fat]

    def _read_fat(self) -> None:
        self.fat: list[int] = []
        for s in self.difat:
            self.fat.extend(struct.unpack_from(f"<{self.ssz // 4}I", self._sector(s), 0))

    def _chain(self, start: int) -> list[int]:
        out: list[int] = []
        cur, seen = start, set()
        while cur not in (ENDOFCHAIN, FREESECT, FATSECT, DIFSECT) and cur < len(self.fat):
            if cur in seen:
                break
            seen.add(cur)
            out.append(cur)
            cur = self.fat[cur]
        return out

    def _read_dir(self) -> None:
        raw = b"".join(self._sector(s) for s in self._chain(self.dir_start))
        self.entries = []
        for i in range(0, len(raw), 128):
            e = raw[i : i + 128]
            if len(e) < 128:
                break
            nlen = struct.unpack_from("<H", e, 64)[0]
            self.entries.append(
                {
                    "name": e[: max(0, nlen - 2)].decode("utf-16-le", "replace"),
                    "type": e[66],
                    "start": struct.unpack_from("<I", e, 116)[0],
                    "size": struct.unpack_from("<Q", e, 120)[0],
                }
            )

    def _read_mini_fat(self) -> None:
        self.mini_fat: list[int] = []
        for s in self._chain(self.mini_fat_start):
            self.mini_fat.extend(
                struct.unpack_from(f"<{self.ssz // 4}I", self._sector(s), 0)
            )
        root = next((e for e in self.entries if e["type"] == 5), None)
        self.mini_stream = (
            b"".join(self._sector(s) for s in self._chain(root["start"]))
            if root
            else b""
        )

    def read(self, name: str) -> bytes:
        e = next((x for x in self.entries if x["name"] == name), None)
        if e is None:
            raise KeyError(name)
        if e["size"] < self.mini_cutoff:
            chain: list[int] = []
            cur = e["start"]
            while cur not in (ENDOFCHAIN, FREESECT) and cur < len(self.mini_fat):
                chain.append(cur)
                cur = self.mini_fat[cur]
            out = b"".join(
                self.mini_stream[i * self.mssz : (i + 1) * self.mssz] for i in chain
            )
        else:
            out = b"".join(self._sector(s) for s in self._chain(e["start"]))
        return out[: e["size"]]


def _copy_token_bits(difference: int) -> int:
    """MS-OVBA 2.4.1.3.19.1 — bit width grows with the *chunk's* output size."""
    bits = 4
    while (1 << bits) < difference:
        bits += 1
    return max(4, min(12, bits))


def decompress(data: bytes) -> bytes:
    """MS-OVBA 2.4.1.3.5 DecompressContainer."""
    if not data or data[0] != 0x01:
        return data
    out = bytearray()
    pos = 1
    while pos + 1 < len(data):
        header = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        size = (header & 0x0FFF) + 3
        compressed = bool(header & 0x8000)
        end = min(pos + size - 2, len(data))
        if not compressed:
            out.extend(data[pos:end])
            pos = end
            continue
        # Copy-token offsets are measured from the start of THIS chunk's
        # output, not from the start of the whole decompressed buffer.
        chunk_start = len(out)
        while pos < end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= end:
                    break
                if not (flags >> bit) & 1:
                    out.append(data[pos])
                    pos += 1
                    continue
                if pos + 1 >= len(data):
                    break
                token = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                bits = _copy_token_bits(len(out) - chunk_start)
                length = (token & ((1 << (16 - bits)) - 1)) + 3
                offset = (token >> (16 - bits)) + 1
                start = len(out) - offset
                if start < 0:
                    return bytes(out)
                for i in range(length):
                    out.append(out[start + i])
        pos = end
    return bytes(out)


# -- the dir stream --------------------------------------------------------

MODULE_NAME = 0x0019
MODULE_STREAMNAME = 0x001A
MODULE_OFFSET = 0x0031


PROJECT_VERSION = 0x0009


def module_offsets(dir_stream: bytes) -> dict[str, int]:
    """Map each module's stream name to the byte offset of its source.

    Every record is ``Id(2) Size(4) Payload(Size)`` — except PROJECTVERSION,
    whose "size" field is a reserved constant and whose payload is a fixed 6
    bytes.  Walking it by the generic rule desynchronises the whole stream,
    which is why an earlier attempt found no modules at all.
    """
    d = decompress(dir_stream)
    out: dict[str, int] = {}
    pos, current = 0, None
    while pos + 6 <= len(d):
        rec_id, size = struct.unpack_from("<HI", d, pos)
        if rec_id == PROJECT_VERSION:
            pos += 12
            continue
        pos += 6
        payload = d[pos : pos + size]
        if rec_id == MODULE_STREAMNAME:
            current = payload.decode("cp950", "replace")
        elif rec_id == MODULE_OFFSET and current and size == 4:
            out[current] = struct.unpack_from("<I", payload, 0)[0]
            current = None
        pos += size
    return out


def modules(vba_bin: bytes) -> dict[str, str]:
    ole = Ole(vba_bin)
    offsets = module_offsets(ole.read("dir"))
    out: dict[str, str] = {}
    for name, off in offsets.items():
        try:
            raw = ole.read(name)
        except KeyError:
            continue
        text = decompress(raw[off:]).decode("cp950", "replace")
        out[name] = text
    return out


if __name__ == "__main__":
    path = Path(sys.argv[1])
    with zipfile.ZipFile(path) as z:
        vba = z.read("xl/vbaProject.bin")
    mods = modules(vba)
    outdir = Path(sys.argv[2] if len(sys.argv) > 2 else "vba")
    outdir.mkdir(exist_ok=True)
    total = 0
    for name, text in sorted(mods.items(), key=lambda kv: -len(kv[1])):
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
        (outdir / f"{safe}.bas").write_text(text, encoding="utf-8")
        total += len(text)
        if len(text) > 700:
            print(f"{name:32} {len(text):9,} chars  {text.count(chr(10)):6,} lines")
    print(f"\n{len(mods)} modules, {total:,} chars -> {outdir}")
