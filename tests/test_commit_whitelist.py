
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

GUARD = "這些檔案被改到了但沒有被 commit"


def _writing_workflows(*, scheduled_only: bool = False) -> list[Path]:
    out = []
    for p in sorted(WORKFLOWS.glob("*.yml")):
        text = p.read_text("utf-8")
        if not (re.search(r"^\s*git add ", text, re.M) and "git commit" in text):
            continue
        if scheduled_only and not re.search(r"^\s*schedule:", text, re.M):
            continue
        out.append(p)
    return out


def test_找得到會寫資料的排程():
    names = [p.name for p in _writing_workflows()]
    assert len(names) >= 4, f"只找到 {names}，正規表示式是不是失效了？"


def test_每一條會寫的排程都要有守門():
    missing = [p.name for p in _writing_workflows(scheduled_only=True)
               if GUARD not in p.read_text("utf-8")]
    assert not missing, (
        f"這幾條會 commit 卻沒有守門：{missing}。"
        "白名單漏掉一個檔案的時候，它們不會紅，只會讓那個檔案永遠不進版控——"
        "而那要等到有人發現『網站上這個數字好幾個月沒動』才看得出來。"
    )


def test_月營收那一條要記得帶上評等清單():
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    fold = cli.split("def _fold_revenue")[1].split("\ndef ")[0]
    assert "rerate(" in fold, (
        "`_fold_revenue` 不再重算評等了？那這條測試要跟著改——"
        "但先確認 market.yml 的白名單還需不需要 ratings.csv。"
    )
    market = (WORKFLOWS / "market.yml").read_text("utf-8")
    add = market.split("git add", 1)[1].split("\n          if", 1)[0]
    assert "data/ratings.csv" in add, (
        "market.yml 的 git add 少了 data/ratings.csv，而 twsix fetch 會寫它"
        "（_fold_revenue → rerate）。整趟會被守門擋下來。"
    )


def test_每日那一條要記得帶上全市場估值():
    daily = (WORKFLOWS / "daily.yml").read_text("utf-8")
    assert "twsix value --all" in daily, (
        "daily.yml 不跑全市場估值了？那 data/valuations.csv 會停在某一天的價格，"
        "而〔台股評等清單〕與〔趨勢∩六大∩報酬〕都讀它。"
    )
    add = daily.split("git add", 1)[1].split("\n          if", 1)[0]
    assert "data/valuations.csv" in add, (
        "daily.yml 的 git add 少了 data/valuations.csv，而 `twsix value --all` "
        "每天都會寫它。守門會擋下整趟。"
    )


def test_守門要在提早exit的上面():
    bad = []
    for p in _writing_workflows(scheduled_only=True):
        text = "\n".join(ln for ln in p.read_text("utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
        if GUARD not in text:
            continue
        guard_at = text.index(GUARD)
        for m in re.finditer(r'changed=no', text):
            exit_at = text.find('exit 0', m.end())
            if 0 <= exit_at < guard_at:
                bad.append(f"{p.name}（守門在 exit 0 之後）")
                break
    assert not bad, (
        "這幾條的守門排在提早 exit 的下面，白名單裡的檔案都沒變的那一天就跑不到："
        + "、".join(bad)
    )
