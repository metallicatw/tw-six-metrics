# 部署到 GitHub

## 一、推上去

repo 已經初始化並完成第一個 commit，只差一個遠端。

```bash
cd tw-six-metrics

# 建立空的 GitHub repo（用 gh CLI，或到網頁上開一個，先不要加 README）
gh repo create tw-six-metrics --private --source=. --remote=origin --push

# 或者手動指定
git remote add origin https://github.com/<你的帳號>/tw-six-metrics.git
git push -u origin main
```

如果是從 `tw-six-metrics.bundle` 還原：

```bash
git clone tw-six-metrics.bundle tw-six-metrics
cd tw-six-metrics
git remote remove origin          # bundle 會被記成 origin
git remote add origin https://github.com/<你的帳號>/tw-six-metrics.git
git push -u origin main
```

## 二、開啟 Pages

Settings → Pages → **Source: GitHub Actions**（不要選 Deploy from a branch，
工作流程用的是 `actions/deploy-pages`）。

第一次部署後網址是 `https://<你的帳號>.github.io/tw-six-metrics/`。

私有 repo 要發布 Pages 需要 GitHub Pro 或以上；若是免費方案，把 repo 設為
public，或把 `site/` 產出改成別的靜態託管。

## 三、開啟 Actions 的寫入權限

排程工作流程會把資料快照 commit 回 repo，需要：

Settings → Actions → General → Workflow permissions →
**Read and write permissions**。

（工作流程本身已經宣告了 `permissions: contents: write`，但 repo 層級的
預設值必須先放行。）

## 四、確認排程

只剩兩個工作流程：`ci.yml`（每次 push 跑測試）與 `pages.yml`
（push 到 main 時測試 → 對帳 → 建站 → 發布）。兩者都不抓資料。

先前的 `daily` / `monthly` / `quarterly` 全市場排程已移除，原因見 README
的〈排程〉一節——簡短版：官方 OpenAPI 只給最新一期快照、沒有現金流量表，
而 `twsix rate` 在沒有活頁簿的 CI 裡必定失敗。

因為不再有排程 commit 資料，repo 也就不需要 Actions 的寫入權限；
第三節那個設定可以留著，但已非必要。


## 五、第一次抓取會遇到的事

`ingest/` 的官方端點是照各站文件寫的，但**尚未在有網路的環境實跑過**。
第一次 `twsix fetch` 很可能會有欄位名稱對不上的狀況——那是預期內的，
每個模組的 `CONTRACT_KEYS` 就是為此存在：

```bash
twsix fetch --companies          # 先試最小的一個
twsix fetch --revenue
twsix fetch --statements
```

失敗時錯誤訊息會指出是哪個端點。修正 `ENDPOINTS` 或 `CONTRACT_KEYS`
後重跑即可；`.cache/http` 會保留已成功的回應，不會重複打站台。

在那之前，網站已經有 `twsix import-list` 匯入的 1,741 檔基準快照可以看。

## 六、把工作流程調成你要的節奏

所有時間設定都在 `.github/workflows/*.yml` 的 `on.schedule`；
所有演算法門檻在 `config/rating_rules.toml`；
所有預估與估價選項在 `config/settings.toml`。

改了門檻之後務必重跑對帳：

```bash
twsix verify        # 應該仍是 54/54，除非你是故意要改變評等口徑
python scripts/run_tests.py
```
