"""``twsix serve`` — the local server that makes 「輸入代號就抓」 possible.

The feature the whole tool is for — type a code, get a full report — cannot
work on GitHub Pages, and it is worth being precise about why so nobody
tries again: MoneyDJ's mirrors send no CORS header, so a ``fetch()`` from a
page on ``github.io`` is refused by the browser before the request leaves the
machine, and the rating engine is Python besides.

So the fetch happens on a machine and this is the smallest web front end for
one.  These tests use a fake pipeline rather than the real one: whether the
mirrors answer today is not what this file is about.
"""

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
    """A real HTTP server on a free port, for the length of one test."""

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
        # urlopen raises on 4xx, and a 404 is a result here rather than an
        # accident — the page asks for jobs that may not exist.
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
    """The code becomes a URL and a directory name downstream.

    Checked once, at the door, rather than trusted by every module that later
    interpolates it.
    """
    assert valid_code("2330") and valid_code("910322")
    for bad in ("", "abc", "23", "1234567", "../etc", "23 30", "2330;ls"):
        assert not valid_code(bad), bad


def test_the_page_can_tell_whether_a_machine_is_behind_it():
    """``/api/ping`` is how one built file behaves two ways.

    The same HTML is served from GitHub Pages, where this endpoint does not
    exist and the fetch button never appears.  No build flag, nothing to
    forget to set.
    """
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
    """Twenty seconds is too long to hold a request open with a blank page.

    The lines the page shows are the ones ``twsix report`` prints, so the
    progress display costs nothing to keep in step with the pipeline.
    """
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
        assert body["done"] is False  # returned immediately, still working

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
    """Two fetches of one stock race for the mirrors and write the same files."""
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
    """Blocked mirrors must end the job, not leave the page polling forever."""
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
    """It is the same site — the API is bolted on, not a replacement."""
    tmp = _tmp()
    s = _Server(_site(tmp), lambda code: 0)
    try:
        with urllib.request.urlopen(s.url("/index.html"), timeout=5) as r:
            assert r.status == 200
            assert "首頁" in r.read().decode("utf-8")
            # Pages are rewritten in place while the server runs; a cached
            # copy would hand back the thin page after a successful fetch.
            assert r.headers.get("Cache-Control") == "no-store"
    finally:
        s.stop()
