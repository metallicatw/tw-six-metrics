"""workflow 檔本身的兩種壞法，都是「CI 綠、按鈕紅」或「CI 綠、門開著」。

1. **空的或不像表達式的 `${{ }}`。** GitHub 解析 YAML 字串值裡每一個
   `${{ … }}`，包括 `run: |` 區塊裡 shell 的 `#` 註解——對 YAML 來說那只是
   字串的一部分。market-monitor 2026-09-22 就死在這裡：註解裡寫了一個空的
   `${{ }}`，manage.yml 整份變成 Invalid workflow file，而同一個 commit 的
   CI 仍然是綠的，因為 CI 不讀那份檔。

2. **使用者輸入直接內插進 `run:`。** `${{ inputs.x }}` 在 shell 看到之前就被
   展開，等於把使用者打的字貼成程式碼。probe.yml 的 `name` 是自由文字，填
   `x" ]; touch /tmp/pwned; [ "` 就會在握有 `contents: write` 的 runner 上執行
   （實測過）。一律走 `env:`，shell 看到的就只是變數的值。

純文字掃描，不引 yaml：要擋的正是 YAML 解析器看得懂、GitHub 卻不收的東西。
"""

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
