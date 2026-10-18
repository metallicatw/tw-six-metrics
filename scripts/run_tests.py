#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

GREEN, RED, DIM, YELLOW, RESET = (
    "\033[32m", "\033[31m", "\033[2m", "\033[33m", "\033[0m"
)


def _missing_optional() -> tuple[type[BaseException], ...]:
    try:
        from twsix.report.build import MissingOptional
    except Exception:  # pragma: no cover - 套件本身壞掉時照舊報失敗
        return ()
    return (MissingOptional,)


def load(path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _mute_annotations() -> str | None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    token = uuid.uuid4().hex
    print(f"::stop-commands::{token}", flush=True)
    return token


def _unmute(token: str | None, failures: list[tuple[str, str]], lint: int) -> None:
    if token is None:
        return
    print(f"::{token}::", flush=True)
    for name, _ in failures:
        print(f"::error title=測試失敗::{name}")
    if lint:
        print("::error title=ruff::ruff check 沒過")


def main() -> int:
    files = sorted((REPO / "tests").glob("test_*.py"))
    if not files:
        print("no tests found")
        return 1

    token = _mute_annotations()

    passed = failed = skipped = 0
    failures: list[tuple[str, str]] = []
    started = time.time()
    optional = _missing_optional()

    for path in files:
        try:
            module = load(path)
        except Exception:
            failed += 1
            failures.append((path.name, traceback.format_exc()))
            print(f"{RED}!{RESET} {path.name} — import failed")
            continue

        names = [n for n in dir(module) if n.startswith("test_")]
        print(f"{DIM}{path.name}{RESET}")
        for name in names:
            fn = getattr(module, name)
            if not callable(fn):
                continue
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    fn()
            except optional as exc:  # type: ignore[misc]
                skipped += 1
                print(f"  {YELLOW}skip{RESET} {name} — {exc}")
            except Exception:
                failed += 1
                said = out.getvalue()
                tb = traceback.format_exc()
                if said.strip():
                    tb = "（測試印出的內容）\n" + said.rstrip() + "\n\n" + tb
                failures.append((f"{path.name}::{name}", tb))
                print(f"  {RED}FAIL{RESET} {name}")
            else:
                passed += 1
                print(f"  {GREEN}ok{RESET}   {name}")

    elapsed = time.time() - started
    print()
    for name, tb in failures:
        print(f"{RED}=== {name} ==={RESET}")
        print(tb)
    lint = _ruff()
    _unmute(token, failures, lint)
    colour = RED if (failed or lint) else GREEN
    tail = f"，{skipped} 跳過（少了選用相依）" if skipped else ""
    print(f"{colour}{passed} passed, {failed} failed{RESET}{tail} in {elapsed:.2f}s")
    return 1 if (failed or lint) else 0


def _ruff() -> int:
    import shutil
    import subprocess  # noqa: S404

    if not shutil.which("ruff"):
        print(f"{YELLOW}skip{RESET} ruff — 這台機器沒裝（CI 會跑）")
        return 0
    done = subprocess.run(  # noqa: S603
        ["ruff", "check", "src", "tests", "scripts"],  # noqa: S607
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    if done.returncode:
        print(f"{RED}=== ruff ==={RESET}")
        print(done.stdout or done.stderr)
    else:
        print(f"{GREEN}ok{RESET}   ruff")
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
