#!/usr/bin/env python3
"""Run the suite without pytest.

pytest is the normal way in (``uv run pytest``), but the whole engine is
standard-library only and the tests are plain functions, so a bare Python is
enough to check the work — useful on a machine with nothing installed, and in
a CI job that has not restored its cache yet.
"""

from __future__ import annotations

import importlib.util
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def load(path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    files = sorted((REPO / "tests").glob("test_*.py"))
    if not files:
        print("no tests found")
        return 1

    passed = failed = 0
    failures: list[tuple[str, str]] = []
    started = time.time()

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
            try:
                fn()
            except Exception:
                failed += 1
                failures.append((f"{path.name}::{name}", traceback.format_exc()))
                print(f"  {RED}FAIL{RESET} {name}")
            else:
                passed += 1
                print(f"  {GREEN}ok{RESET}   {name}")

    elapsed = time.time() - started
    print()
    for name, tb in failures:
        print(f"{RED}=== {name} ==={RESET}")
        print(tb)
    colour = RED if failed else GREEN
    print(f"{colour}{passed} passed, {failed} failed{RESET} in {elapsed:.2f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
