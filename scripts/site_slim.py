from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GZ_JS = ROOT / "src" / "twsix" / "report" / "templates" / "gz.js"

LOADER = r"""
(function(){
  var me = document.currentScript, p = me.getAttribute("data-p"), s = me.getAttribute("data-s");
  function go(){ var x = document.createElement("script"); x.src = s; document.body.appendChild(x); }
  function fail(){
    [].forEach.call(document.querySelectorAll("[data-lazy]"), function(el){
      if (!el.firstChild) el.innerHTML = '<p class="stale">這一段內容載入失敗，請重新整理頁面。</p>';
    });
  }
  function run(o){
    var t = (o.getAttribute("type") || "").toLowerCase();
    if (t && t !== "text/javascript" && t !== "application/javascript" && t !== "module") return;
    var n = document.createElement("script");
    for (var i = 0; i < o.attributes.length; i++) n.setAttribute(o.attributes[i].name, o.attributes[i].value);
    n.text = o.text;
    o.parentNode.replaceChild(n, o);
  }
  var v = (window.TWSIX && window.TWSIX.built) ? "?v=" + window.TWSIX.built : "";
  window.TWSIXgz(p + v).then(function(d){
    for (var id in d){
      var el = document.getElementById(id);
      if (!el) continue;
      el.innerHTML = d[id];
      el.removeAttribute("data-lazy");
      [].forEach.call(el.querySelectorAll("script"), run);
    }
  }).catch(fail).then(go, go);
})();
"""

SITE_TAG = re.compile(r'<script src="(\.\./assets/site\.js\?v=[^"]*)" defer></script>')
PANEL_OPEN = re.compile(r'<section class="panel" id="(panel-[\w-]+)"[^>]*>')
SEC = re.compile(r"<section\b|</section\s*>", re.I)


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9, mtime=0)


def gzip_files(paths: list[Path], keep: bool = False) -> tuple[int, int]:
    n = saved = 0
    for f in paths:
        raw = f.read_bytes()
        out = f.with_name(f.name + ".gz")
        _write(out, _gz(raw))
        if not keep:
            f.unlink()
            saved += len(raw)
        saved -= out.stat().st_size
        n += 1
    return n, saved


def live_reads_gz(url: str | None) -> bool:
    if not url:
        return True
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/assets/site.js", timeout=20) as r:
            return b"TWSIXgz" in r.read()
    except Exception as e:  # noqa: BLE001
        print(f"live check failed ({e}); keeping uncompressed copies this time")
        return False


def _size_mb(site: Path) -> float:
    return sum(f.stat().st_size for f in site.rglob("*") if f.is_file()) / 1048576


def _panel_end(html: str, start: int) -> int:
    depth = 0
    for m in SEC.finditer(html, start):
        if m.group(0).lower().startswith("<section"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start()
    return -1


def lazify(html: str) -> tuple[str, dict[str, str]] | None:
    tag = SITE_TAG.search(html)
    if not tag or "data-lazy" in html:
        return None
    parts: dict[str, str] = {}
    out = []
    pos = 0
    for m in PANEL_OPEN.finditer(html):
        if m.start() < pos:
            continue
        open_tag = m.group(0)
        if " hidden" not in open_tag or "data-src=" in open_tag:
            continue
        end = _panel_end(html, m.start())
        if end < 0:
            return None
        inner = html[m.end():end]
        if len(inner) < 2000:
            continue
        parts[m.group(1)] = inner
        out.append(html[pos:m.start()])
        out.append(open_tag[:-1] + " data-lazy>")
        pos = end
    if not parts:
        return None
    out.append(html[pos:])
    return "".join(out), parts


def restore(new: str, parts: dict[str, str]) -> str:
    for pid, inner in parts.items():
        m = re.search(r'<section class="panel" id="' + re.escape(pid) + r'"[^>]*? data-lazy>', new)
        if not m:
            raise ValueError(pid)
        tag = m.group(0).replace(" data-lazy>", ">")
        new = new[:m.start()] + tag + inner + new[m.end():]
    return new


def slim_page(path: Path) -> int:
    html = path.read_text("utf-8")
    res = lazify(html)
    if not res:
        return 0
    new, parts = res
    if restore(new, parts) != html:
        print(f"::warning::{path.name}: reassembly mismatch, left as is")
        return 0
    tag = SITE_TAG.search(new)
    name = path.stem + ".p.json"
    loader = (f'<script src="../assets/lazy.js?v={tag.group(1).split("?v=")[1]}" data-p="{name}" '
              f'data-s="{tag.group(1)}" defer></script>')
    new = new[:tag.start()] + loader + new[tag.end():]
    built = re.search(r'built:"([^"]*)"', new)
    v = f"?v={built.group(1)}" if built else ""
    pre = (f'<link rel="preload" href="{name}.gz{v}" as="fetch" crossorigin>'
           f'<link rel="preload" href="{tag.group(1)}" as="script">')
    at = new.find(loader)
    new = new[:at] + pre + new[at:]
    _write(path.parent / (name + ".gz"),
           _gz(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
    _write(path, new.encode("utf-8"))
    return len(html.encode()) - len(new.encode())


def _data_files(site: Path) -> list[Path]:
    stock = site / "stock"
    cf = site / "chipflow" / "stock"
    out = sorted(stock.glob("*.r.json")) + sorted(stock.glob("*.i.json")) if stock.is_dir() else []
    return out + (sorted(cf.glob("*.json")) if cf.is_dir() else [])


def main(argv: list[str]) -> int:
    site = Path(argv[0])
    max_mb = float(argv[argv.index("--max-mb") + 1]) if "--max-mb" in argv else None
    live = argv[argv.index("--live") + 1] if "--live" in argv else None
    keep = not live_reads_gz(live)
    files = _data_files(site)
    n, s = gzip_files(files, keep=keep)
    if keep:
        print(f"gzip data: {n} files, +{-s / 1048576:.0f} MB（這次保留原檔，下一次建站再刪）")
    else:
        print(f"gzip data: {n} files, -{s / 1048576:.0f} MB")
    if keep and max_mb is not None and _size_mb(site) > max_mb:
        for f in files:
            f.unlink(missing_ok=True)
        print("::warning::too big to keep the uncompressed copies; removed them")
    stock = site / "stock"
    if "--lazy" in argv and stock.is_dir():
        assets = site / "assets"
        assets.mkdir(exist_ok=True)
        _write(assets / "lazy.js", (GZ_JS.read_text("utf-8") + LOADER).encode("utf-8"))
        pages = saved = 0
        for f in sorted(stock.glob("*.html")):
            d = slim_page(f)
            if d:
                pages += 1
                saved += d
        print(f"lazy panels: {pages} pages, html -{saved / 1048576:.0f} MB")
    mb = _size_mb(site)
    print(f"site: {mb:.0f} MB, {sum(1 for f in site.rglob('*') if f.is_file())} files")
    if max_mb is not None:
        if mb > max_mb:
            print(f"::error::site is {mb:.0f} MB (> {max_mb:.0f} MB); not publishing")
            return 1
        if mb > max_mb * 0.9:
            print(f"::warning::site is {mb:.0f} MB, close to the {max_mb:.0f} MB limit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
