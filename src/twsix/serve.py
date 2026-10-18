
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
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool = False
    started: float = field(default_factory=time.time)

    def write(self, text: str) -> int:
        for part in text.splitlines():
            if part.strip():
                self.lines.append(part.rstrip())
        return len(text)

    def flush(self) -> None:  # pragma: no cover - file-like protocol
        pass

    def state(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "lines": self.lines[-40:],
            "done": self.done,
            "ok": self.ok,
            "seconds": round(time.time() - self.started, 1),
        }


class Jobs:

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, code: str) -> Job | None:
        with self._lock:
            return self._jobs.get(code)

    def start(self, code: str, run: Any) -> Job:
        with self._lock:
            existing = self._jobs.get(code)
            if existing is not None and not existing.done:
                return existing
            job = Job(code)
            self._jobs[code] = job

        def work() -> None:
            import contextlib  # noqa: PLC0415

            try:
                with contextlib.redirect_stdout(job), contextlib.redirect_stderr(job):
                    job.ok = run(code) == 0
            except Exception as exc:  # noqa: BLE001 - report, never crash the server
                job.lines.append(f"失敗：{exc}")
                job.ok = False
            finally:
                job.done = True

        threading.Thread(target=work, daemon=True).start()
        return job


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
                return self._json({"ok": True, "service": "twsix"})
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

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/fetch/"):
                return self._json({"error": "不支援"}, 404)
            code = path[len("/api/fetch/") :]
            if not valid_code(code):
                return self._json({"error": f"「{code}」不是股票代號"}, 400)
            job = jobs.start(code, run)
            return self._json(job.state(), 202)

    return Handler


def run_report(code: str) -> int:
    import argparse  # noqa: PLC0415

    from .cli import cmd_report  # noqa: PLC0415

    return cmd_report(
        argparse.Namespace(
            config=None, stock=code, data=None, out=None, as_of=None,
            host=None, save_html=None, retries=1, rebuild=True,
            no_backfill=False,
            cached=False,
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
    print("　搜尋框輸入股票代號，沒有完整報告的會出現「立即抓取」。")
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
