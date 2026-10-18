import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

_spec = importlib.util.spec_from_file_location("site_slim", ROOT / "scripts" / "site_slim.py")
slim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slim)


def _site():
    import test_build_site as t

    tmp = t._tmp()
    out = tmp / "site"
    t.build_site(t._records(), out, sheets_dir=t._sheets(tmp))
    return out


def test_lazy_panels_round_trip_exactly():
    out = _site()
    page = out / "stock" / "5439.html"
    html = page.read_text("utf-8")
    res = slim.lazify(html)
    assert res, "沒有可以延後載入的分頁"
    new, parts = res
    assert slim.restore(new, parts) == html
    assert len(new) < len(html)
    assert 'id="panel-summary"' in new and "data-lazy" not in new.split('id="panel-summary"')[1][:200]
    for pid in parts:
        assert f'id="{pid}"' in new


def test_slim_rewrites_the_site_and_is_idempotent():
    out = _site()
    before = (out / "stock" / "5439.html").read_text("utf-8")
    assert slim.main([str(out), "--lazy"]) == 0
    page = (out / "stock" / "5439.html").read_text("utf-8")
    assert "assets/lazy.js" in page and 'data-p="5439.p.json"' in page and "assets/site.js" in page
    parts = json.loads(gzip.decompress((out / "stock" / "5439.p.json.gz").read_bytes()))
    assert parts and all(k.startswith("panel-") for k in parts)
    assert not list((out / "stock").glob("*.r.json")) and not list((out / "stock").glob("*.i.json"))
    assert (out / "assets" / "lazy.js").exists()
    assert len(page) < len(before)
    snapshot = page
    assert slim.main([str(out), "--lazy"]) == 0
    assert (out / "stock" / "5439.html").read_text("utf-8") == snapshot


def test_size_limit_stops_publishing(tmp_path=None):
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "big.bin").write_bytes(b"x" * 2_000_000)
    assert slim.main([str(d), "--max-mb", "1"]) == 1
    assert slim.main([str(d), "--max-mb", "100"]) == 0
    shutil.rmtree(d)


def test_site_js_reads_compressed_files_with_a_fallback():
    from twsix.report.build import asset_text

    js = asset_text("site.js")
    assert js.startswith("(function(){\n  if (window.TWSIXgz) return;")
    assert "TWSIXgz(code + '.r.json'" in js
    assert "TWSIXgz(stat.getAttribute('data-src')" in js
    radar = (ROOT / "src/twsix/report/templates/radar.html.j2").read_text("utf-8")
    assert '{% include "gz.js" %}' in radar and "window.TWSIXgz(" in radar


def test_the_inflate_fallback_matches_zlib():
    node = shutil.which("node")
    if not node:
        return
    js = r"""
const fs=require('fs'),zlib=require('zlib'),vm=require('vm');
const win={TWSIX_NO_DS:true};
const ctx={window:win,Response,Blob,TextDecoder,Uint8Array,Uint16Array,Promise,JSON,Error,Math,String,decodeURIComponent,escape};
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
(async()=>{let bad=0;
 for(let i=0;i<60;i++){const n=(i*7919)%150000;const b=Buffer.alloc(n);for(let j=0;j<n;j++)b[j]=(j*31+i)%(i%3?256:7);
  for(const l of [0,1,9]){const o=await win.TWSIXgunzip(zlib.gzipSync(b,{level:l}));if(Buffer.compare(Buffer.from(o),b))bad++;}}
 console.log(bad);})();
"""
    r = subprocess.run([node, "-e", js, str(ROOT / "src/twsix/report/templates/gz.js")],
                       capture_output=True, text=True, timeout=120)
    assert r.stdout.strip() == "0", r.stdout + r.stderr


def test_default_only_compresses_data_and_keeps_pages():
    out = _site()
    before = (out / "stock" / "5439.html").read_text("utf-8")
    raws = sorted((out / "stock").glob("*.r.json"))
    assert raws
    keep = {f.name: f.read_bytes() for f in raws}
    assert slim.main([str(out), "--live", "http://127.0.0.1:9/"]) == 0
    for name, data in keep.items():
        assert (out / "stock" / name).read_bytes() == data
        assert gzip.decompress((out / "stock" / (name + ".gz")).read_bytes()) == data
    assert slim.main([str(out)]) == 0
    assert not list((out / "stock").glob("*.r.json"))
    for name, data in keep.items():
        assert gzip.decompress((out / "stock" / (name + ".gz")).read_bytes()) == data
    assert (out / "stock" / "5439.html").read_text("utf-8") == before
    assert not (out / "assets" / "lazy.js").exists()


def test_dropping_a_data_file_also_drops_its_compressed_copy():
    from twsix.report import build

    d = Path(__import__("tempfile").mkdtemp())
    f = d / "1234.r.json"
    f.write_text("{}")
    (d / "1234.r.json.gz").write_bytes(b"x")
    build._drop(f)
    assert not f.exists() and not (d / "1234.r.json.gz").exists()
    shutil.rmtree(d)
