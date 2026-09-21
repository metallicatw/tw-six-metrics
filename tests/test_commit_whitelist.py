"""排程 commit 的白名單，要蓋住引擎真的會寫的每一個檔案。

## 這是什麼壞法

每一條會寫資料的排程都用**白名單式的 `git add`**（`git add data/market
data/sheets …`），不是 `git add -A`。那是對的：bot 不該把 runner 上任何
意外產生的東西一起提交。

代價是白名單會和程式脫節，而脫節的症狀有兩種，一種比一種糟：

1. 有守門的（market / refresh / daily / stock）→ 整趟紅掉，訊息寫出漏掉哪個檔。
   2026-09-19 就是這個：`_fold_revenue` 折完月營收會**接著重算評等**，寫了
   `data/ratings.csv`，而 market.yml 的白名單裡沒有它。

2. 沒有守門的 → 那個檔案永遠不會被提交，而 job 是綠的。這種要等到有人發現
   「網站上這個數字怎麼好幾個月沒動」才會冒出來。

所以這一支守兩件事：**每一條會寫的排程都要有守門**，以及**已知的耦合要在
白名單裡**。第一件比第二件重要——守門在，漏掉的下一個檔案會自己講出名字；
守門不在，就只能靠運氣。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

#: 這一行是守門。`git diff --quiet` 為假 → 有檔案被改到卻沒進 index。
GUARD = "這些檔案被改到了但沒有被 commit"


def _writing_workflows(*, scheduled_only: bool = False) -> list[Path]:
    """會 `git commit` 資料的那幾個 workflow。

    `scheduled_only` 把「有排程的」挑出來，而守門那一條只管這些。理由不是
    寬容，是**守門在防什麼**：它防的是「沒有人在看的時候，檔案安靜地沒有被
    提交」。`probe.yml` 只能手動觸發，按下去的人就坐在 log 前面——漏掉什麼
    他當場就看得到。排程不是，排程跑在半夜，而且 GitHub 連排程被丟掉都不會
    通知。
    """
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
    """這一條是另外兩條的前提——找不到的話它們會空跑而且全部通過。"""
    names = [p.name for p in _writing_workflows()]
    assert len(names) >= 4, f"只找到 {names}，正規表示式是不是失效了？"


def test_每一條會寫的排程都要有守門():
    """沒有守門的那一條，漏掉的檔案會安靜地留在 runner 上。

    只管**有排程的**：手動觸發的那幾個（probe.yml）按下去的人就在看 log，
    漏掉什麼當場就知道。排程跑在半夜，沒有人看。
    """
    missing = [p.name for p in _writing_workflows(scheduled_only=True)
               if GUARD not in p.read_text("utf-8")]
    assert not missing, (
        f"這幾條會 commit 卻沒有守門：{missing}。"
        "白名單漏掉一個檔案的時候，它們不會紅，只會讓那個檔案永遠不進版控——"
        "而那要等到有人發現『網站上這個數字好幾個月沒動』才看得出來。"
    )


def test_月營收那一條要記得帶上評等清單():
    """`market.yml` 跑的 `twsix fetch` 會連帶重算評等，所以它會寫 ratings.csv。

    這個耦合寫在 `cli._fold_revenue` 的 docstring 裡（「兩步，不是一步」），
    而它正是 2026-09-19 那次失敗的原因。程式那一側改了、白名單沒跟上。
    """
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
    """`daily.yml` 跑 `twsix value --all`，而它每天都會改到 data/valuations.csv。

    每天都會改，是因為估值的股價取自當天的收盤（`cmd_value_all` 的
    `latest_quotes`）。所以這個漏掉的話不是偶爾紅，是**每天**紅。
    """
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
    """有那一行不等於跑得到那一行。

    守門防的是「引擎寫了一個白名單沒列的檔案」。而它原本排在
    `changed=no → exit 0` 的**下面**：

        git add <白名單>
        if git diff --cached --quiet; then      # 白名單裡的都沒變
          echo "changed=no"; exit 0             # ← 直接走人
        fi
        ...
        if ! git diff --quiet; then             # ← 守門在這裡，跑不到
          echo "::error::這些檔案被改到了但沒有被 commit"

    於是只要白名單裡的檔案剛好都沒變——非交易日、期別沒換、補課 0 列，
    在穩定狀態下這是常態——那個漏掉的檔案就一聲不吭地留在 runner 上，
    job 綠燈。

    這道門在最需要它的那一天（引擎開始寫新檔案的第一天，而那天多半沒有
    別的變動）剛好是關著的。

    上一條測的是「字串在不在」，這一條測的是「跑不跑得到」——`test_commit_whitelist`
    自己的開頭就寫著那兩種壞法，而這是比較糟的那一種。
    """
    bad = []
    for p in _writing_workflows(scheduled_only=True):
        # 註解要先剝掉——這一段的說明文字裡就寫著 `changed=no → exit 0`，
        # 不剝的話測到的是自己的註解（第一版就這樣紅了）。
        text = "\n".join(ln for ln in p.read_text("utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
        if GUARD not in text:
            continue
        guard_at = text.index(GUARD)
        # 提早離開的那幾行：`changed=no` 之後的 `exit 0`。
        for m in re.finditer(r'changed=no', text):
            exit_at = text.find('exit 0', m.end())
            if 0 <= exit_at < guard_at:
                bad.append(f"{p.name}（守門在 exit 0 之後）")
                break
    assert not bad, (
        "這幾條的守門排在提早 exit 的下面，白名單裡的檔案都沒變的那一天就跑不到："
        + "、".join(bad)
    )
