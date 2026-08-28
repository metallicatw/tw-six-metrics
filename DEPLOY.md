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

| 工作流程 | cron (UTC) | 台北時間 |
|---|---|---|
| `daily.yml` | `0 8 * * 1-5` | 週一至週五 16:00 |
| `monthly.yml` | `0 4 10-16 * *` | 每月 10–16 日 12:00 |
| `quarterly.yml` | `0 5 29-31 3 *` 等四組 | 財報申報期前後 13:00 |

排程工作流程只在**預設分支**上執行，而且 repo 連續 60 天沒有活動時
GitHub 會自動停用排程——資料快照的 commit 本身就會維持活躍。

先手動跑一次確認：Actions → 選 workflow → **Run workflow**。

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
