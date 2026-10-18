
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from twsix.serve import Jobs, make_handler, valid_code


def _site(tmp: Path) -> Path:
    root = tmp / "site"
    (root / "stock").mkdir(parents=True)
    (root / "index.html").write_text("<h1>首頁</h1>", encoding="utf-8")
    (root / "search.json").write_text('[["1101","台泥","水泥工業","1.00",0]]', "utf-8")
    return root


def _tmp() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="twsix-serve-"))


class _Server:

    def __init__(self, root: Path, run) -> None:
        self.jobs = Jobs()
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(root, self.jobs, run)
        )
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.url(path), timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def post(self, path: str):
        req = urllib.request.Request(self.url(path), method="POST", data=b"")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def test_only_a_stock_code_ever_reaches_the_pipeline():
    assert valid_code("2330") and valid_code("910322")
    for bad in ("", "abc", "23", "1234567", "../etc", "23 30", "2330;ls"):
        assert not valid_code(bad), bad


def test_the_page_can_tell_whether_a_machine_is_behind_it():
    tmp = _tmp()
    s = _Server(_site(tmp), lambda code: 0)
    try:
        status, body = s.get("/api/ping")
        assert status == 200
        assert body["service"] == "twsix"
    finally:
        s.stop()


def test_a_bad_code_is_refused_before_anything_runs():
    calls: list[str] = []
    tmp = _tmp()
    s = _Server(_site(tmp), lambda code: calls.append(code) or 0)
    try:
        status, body = s.post("/api/fetch/../../etc/passwd")
        assert status in (400, 404)
        assert "error" in body
        assert calls == [], "驗證失敗的代號不該進到管線裡"
    finally:
        s.stop()


def test_a_fetch_runs_in_the_background_and_reports_its_own_output():
    tmp = _tmp()

    def run(code: str) -> int:
        print(f"[1/4] 抓取 {code} 的報表…")
        time.sleep(0.2)
        print("  FRQ       100 列")
        return 0

    s = _Server(_site(tmp), run)
    try:
        status, body = s.post("/api/fetch/2330")
        assert status == 202
        assert body["done"] is False

        for _ in range(50):
            _, state = s.get("/api/job/2330")
            if state["done"]:
                break
            time.sleep(0.1)
        assert state["done"] and state["ok"]
        assert any("抓取 2330" in line for line in state["lines"])
        assert any("FRQ" in line for line in state["lines"])
    finally:
        s.stop()


def test_pressing_the_button_twice_does_not_start_two_fetches():
    tmp = _tmp()
    started: list[str] = []

    def run(code: str) -> int:
        started.append(code)
        time.sleep(0.5)
        return 0

    s = _Server(_site(tmp), run)
    try:
        s.post("/api/fetch/2330")
        s.post("/api/fetch/2330")
        s.post("/api/fetch/2330")
        time.sleep(0.9)
        assert started == ["2330"]
    finally:
        s.stop()


def test_a_failing_pipeline_is_reported_rather_than_hanging():
    tmp = _tmp()

    def run(code: str) -> int:
        raise RuntimeError("八個站台都拒絕")

    s = _Server(_site(tmp), run)
    try:
        s.post("/api/fetch/2330")
        for _ in range(50):
            _, state = s.get("/api/job/2330")
            if state["done"]:
                break
            time.sleep(0.1)
        assert state["done"] is True
        assert state["ok"] is False
        assert any("八個站台都拒絕" in line for line in state["lines"])
    finally:
        s.stop()


def test_an_unknown_job_is_a_404_not_an_empty_success():
    tmp = _tmp()
    s = _Server(_site(tmp), lambda code: 0)
    try:
        status, body = s.get("/api/job/9999")
        assert status == 404
        assert "error" in body
    finally:
        s.stop()


def test_the_static_site_is_still_served():
    tmp = _tmp()
    s = _Server(_site(tmp), lambda code: 0)
    try:
        with urllib.request.urlopen(s.url("/index.html"), timeout=5) as r:
            assert r.status == 200
            assert "首頁" in r.read().decode("utf-8")
            assert r.headers.get("Cache-Control") == "no-store"
    finally:
        s.stop()


def test_the_button_passes_everything_report_actually_reads():
    import argparse
    import inspect
    import re

    from twsix import cli, serve

    needs = set(re.findall(r"args\.([a-z_]+)", inspect.getsource(cli.cmd_report)))
    call = inspect.getsource(serve.run_report)
    body = call.split("argparse.Namespace(", 1)[1]
    gives = set(re.findall(r"(\w+)\s*=", body))
    missing = sorted(needs - gives)
    assert not missing, f"serve 沒有傳給 report 的欄位：{missing}"

    ns = argparse.Namespace(
        config=None, stock="2330", data=None, out=None, as_of=None,
        host=None, save_html=None, retries=1, rebuild=True,
        no_backfill=False, cached=False,
    )
    for name in sorted(needs):
        getattr(ns, name)
