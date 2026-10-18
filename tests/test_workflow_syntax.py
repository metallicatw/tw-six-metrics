
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

_STARTS_OK = re.compile(r"[A-Za-z_(!'0-9-]")
_RUN = re.compile(r"(\s*)(?:- )?run:\s*(.*)$")
_INPUT = ("${{ inputs.", "${{ github.event.inputs.")


def _texts():
    return {
        p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))
    }


def _expression_problems(text: str) -> list[tuple[int, str]]:
    bad = []
    for no, line in enumerate(text.splitlines(), 1):
        i = 0
        while (i := line.find("${{", i)) >= 0:
            j = line.find("}}", i + 3)
            if j < 0:
                bad.append((no, "沒有收尾的 }}"))
                break
            inner = line[i + 3 : j].strip()
            if not inner:
                bad.append((no, "空的 ${{ }}"))
            elif not _STARTS_OK.match(inner):
                bad.append((no, f"不像表達式：{inner!r}"))
            i = j + 2
    return bad


def _inputs_in_run(text: str) -> list[int]:
    hits, run_indent = [], None
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if run_indent is not None:
            if stripped and indent <= run_indent:
                run_indent = None
            else:
                if any(k in line for k in _INPUT):
                    hits.append(no)
                continue
        m = _RUN.match(line)
        if m:
            if m.group(2).startswith(("|", ">")):
                run_indent = len(m.group(1))
            elif any(k in m.group(2) for k in _INPUT):
                hits.append(no)
    return hits


def test_workflow_裡沒有空的表達式():
    problems = {n: p for n, t in _texts().items() if (p := _expression_problems(t))}
    assert not problems, f"GitHub 會拒收這些 workflow：{problems}"


def test_掃描器抓得到空表達式():
    sample = (
        "        run: |\n          # 沒有 eval，${{ }} 已經走 env\n          echo ok\n"
    )
    assert _expression_problems(sample) == [(2, "空的 ${{ }}")]
    assert _expression_problems("x: ${{ inputs.code") == [(1, "沒有收尾的 }}")]
    assert _expression_problems("x: ${{ … }}") == [(1, "不像表達式：'…'")]
    assert _expression_problems("x: ${{ inputs.a || 100 }} ${{ secrets.K }}") == []


def test_使用者輸入不直接內插進_run():
    offenders = {n: h for n, t in _texts().items() if (h := _inputs_in_run(t))}
    assert not offenders, f"這些 run: 直接內插了使用者輸入，改走 env：{offenders}"


def test_掃描器分得出_env_和_run():
    ok = (
        "      - name: a\n"
        "        env:\n"
        "          IN_NAME: ${{ inputs.name }}\n"
        "        run: |\n"
        '          twsix probe --name "$IN_NAME"\n'
        "      - name: b\n"
        "        with:\n"
        "          x: ${{ inputs.name }}\n"
    )
    assert _inputs_in_run(ok) == []
    bad_block = (
        "        run: |\n          echo hi\n          twsix --name ${{ inputs.name }}\n"
    )
    assert _inputs_in_run(bad_block) == [3]
    bad_inline = '        run: twsix refresh --limit "${{ inputs.limit || 100 }}"\n'
    assert _inputs_in_run(bad_inline) == [1]


def _runner():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_run_tests", ROOT / "scripts" / "run_tests.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_測試夾具的_error_不會變成_GitHub_的紅字():
    import contextlib
    import io
    import os

    runner = _runner()
    old = os.environ.get("GITHUB_ACTIONS")
    out = io.StringIO()
    try:
        os.environ["GITHUB_ACTIONS"] = "true"
        with contextlib.redirect_stdout(out):
            token = runner._mute_annotations()
            print("::error::每日收盤：最新的一天是 2026-09-04（夾具）")
            runner._unmute(token, [("test_x.py::test_y", "tb")], 0)
    finally:
        if old is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = old

    lines = out.getvalue().splitlines()
    assert token and lines[0] == f"::stop-commands::{token}", "沒有先關掉指令解析"
    resume = lines.index(f"::{token}::")
    assert resume > lines.index("::error::每日收盤：最新的一天是 2026-09-04（夾具）"), (
        "夾具的 ::error:: 印在關掉解析之前"
    )
    assert lines[resume + 1] == "::error title=測試失敗::test_x.py::test_y", (
        "恢復之後沒有替真正的失敗留註記"
    )


def test_本機不印那些指令():
    import os

    runner = _runner()
    old = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        assert runner._mute_annotations() is None
    finally:
        if old is not None:
            os.environ["GITHUB_ACTIONS"] = old
