
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

CODE_MIN, CODE_MAX = 4, 6


@dataclass
class Job:

    code: str
    scope: str = "full"
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool = False
    queued: bool = False
    started: float = field(default_factory=time.time)

    def write(self, text: str) -> int:
        for part in text.splitlines():
            if part.strip():
                self.lines.append(part.rstrip())
        return len(text)

    def flush(self) -> None:  # pragma: no cover - file-like protocol
        pass

    def state(self) -> dict[str, Any]:
        from .refresh import parse_stages  # noqa: PLC0415

        return {
            "code": self.code,
            "scope": self.scope,
            "lines": self.lines[-40:],
            "stages": parse_stages(self.lines),
            "done": self.done,
            "ok": self.ok,
            "queued": self.queued,
            "seconds": round(time.time() - self.started, 1),
        }


class Jobs:
    """一次只跑一檔（資料來源的禮貌，也避免兩檔同時改寫網站）；其他的排隊。"""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: list[tuple[Job, Any]] = []
        self._busy = False
        self.batch: list[str] = []

    def get(self, code: str) -> Job | None:
        with self._lock:
            return self._jobs.get(code)

    def start(self, code: str, run: Any, scope: str = "full") -> Job:
        with self._lock:
            existing = self._jobs.get(code)
            if existing is not None and not existing.done:
                return existing
            job = Job(code, scope=scope, queued=True)
            job.lines.append("排隊中…")
            self._jobs[code] = job
            self._queue.append((job, run))
            if self._busy:
                return job
            self._busy = True
        threading.Thread(target=self._drain, daemon=True).start()
        return job

    def start_batch(self, codes: list[str], run: Any, scope: str = "full") -> list[Job]:
        with self._lock:
            self.batch = list(codes)
        return [self.start(c, run, scope) for c in codes]

    def batch_state(self) -> dict[str, Any]:
        with self._lock:
            jobs = [(c, self._jobs.get(c)) for c in self.batch]
        rows = []
        for c, j in jobs:
            if j is None:
                continue
            st = j.state()
            rows.append({"code": c, "done": j.done, "ok": j.ok, "queued": j.queued,
                         "stages": st["stages"], "last": (j.lines[-1] if j.lines else "")})
        return {"codes": [r["code"] for r in rows], "rows": rows,
                "done": all(r["done"] for r in rows) if rows else True}

    def cancel(self) -> int:
        with self._lock:
            left = [j for j, _ in self._queue]
            self._queue.clear()
        for j in left:
            j.lines.append("已取消")
            j.queued, j.done, j.ok = False, True, False
        return len(left)

    def _drain(self) -> None:
        import contextlib  # noqa: PLC0415

        while True:
            with self._lock:
                if not self._queue:
                    self._busy = False
                    return
                job, run = self._queue.pop(0)
            job.queued = False
            job.started = time.time()
            job.lines = []
            try:
                with contextlib.redirect_stdout(job), contextlib.redirect_stderr(job):
                    job.ok = _call(run, job.code, job.scope) == 0
            except Exception as exc:  # noqa: BLE001 - report, never crash the server
                job.lines.append(f"失敗：{exc}")
                job.ok = False
            finally:
                job.done = True


def _call(run: Any, code: str, scope: str) -> int:
    import inspect  # noqa: PLC0415

    try:
        n = len(inspect.signature(run).parameters)
    except (TypeError, ValueError):
        n = 2
    return run(code, scope) if n >= 2 else run(code)


def valid_code(code: str) -> bool:
    return code.isdigit() and CODE_MIN <= len(code) <= CODE_MAX


def make_handler(root: Path, jobs: Jobs, run: Any) -> type[SimpleHTTPRequestHandler]:

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/ping":
                return self._json({"ok": True, "service": "twsix", "refresh": 2})
            if path == "/api/batch":
                return self._json(jobs.batch_state())
            if path.startswith("/api/job/"):
                code = path[len("/api/job/") :]
                job = jobs.get(code)
                if job is None:
                    return self._json({"error": "沒有這個工作"}, 404)
                return self._json(job.state())
            if path.endswith(".html") or path == "/":
                self.send_header_no_cache = True
            return super().do_GET()

        def end_headers(self) -> None:
            if getattr(self, "send_header_no_cache", False):
                self.send_header("Cache-Control", "no-store")
                self.send_header_no_cache = False
            super().end_headers()

        def _body(self) -> dict[str, Any]:
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 65536)
                return json.loads(self.rfile.read(n) or b"{}") if n else {}
            except (ValueError, OSError):
                return {}

        def do_POST(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path == "/api/batch/cancel":
                return self._json({"cancelled": jobs.cancel()})
            if path == "/api/fetch-batch":
                body = self._body()
                codes = [str(c).strip() for c in (body.get("codes") or []) if valid_code(str(c).strip())]
                if not codes:
                    return self._json({"error": "沒有可以更新的代號"}, 400)
                scope = "quick" if body.get("scope") == "quick" else "full"
                jobs.start_batch(list(dict.fromkeys(codes))[:100], run, scope)
                return self._json(jobs.batch_state(), 202)
            if not path.startswith("/api/fetch/"):
                return self._json({"error": "不支援"}, 404)
            code = path[len("/api/fetch/") :]
            if not valid_code(code):
                return self._json({"error": f"「{code}」不是股票代號"}, 400)
            scope = "quick" if (q.get("scope") or self._body().get("scope")) == "quick" else "full"
            job = jobs.start(code, run, scope)
            return self._json(job.state(), 202)

    return Handler


def run_report(code: str, scope: str = "full") -> int:
    import argparse  # noqa: PLC0415

    from .cli import cmd_refresh_stock  # noqa: PLC0415

    return cmd_refresh_stock(
        argparse.Namespace(
            config=None, stock=code, scope=scope, force=False, only=None, cloud=False,
            data=None, out=None, cl_out=None, trend_report=None, trend_data=None, trend_repo=None,
        )
    )


def serve(
    root: Path,
    port: int = DEFAULT_PORT,
    *,
    run: Any = None,
    open_browser: bool = True,
) -> None:
    jobs = Jobs()
    handler = make_handler(root, jobs, run or run_report)
    httpd = ThreadingHTTPServer((HOST, port), handler)
    url = f"http://{HOST}:{port}/"
    print(f"網站在 {url}")
    print("　個股頁標題列的〔一鍵更新〕會在這台電腦上更新那一檔的所有資料。")
    print("　Ctrl-C 結束。")
    if open_browser:
        try:
            import webbrowser  # noqa: PLC0415

            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless box has no browser
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n結束。")
    finally:
        httpd.server_close()
