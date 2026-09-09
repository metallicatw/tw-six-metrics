# 這套系統是怎麼跑起來的

三個 repo，一個網站。這份文件回答兩件事：**每天自動發生什麼**，以及
**我想手動更新某一塊的時候要按哪個按鈕**。

排程改了請一起改這裡——不然它會變成一份看起來很像真的、但其實在說謊的文件。

---

## 三個 repo 怎麼串起來

```
market-monitor    ──→ index.html                    ┐
                                                     ├─ clone + cp ─→ 主站建站 ─→ GitHub Pages
tw-trend-filter   ──→ index.html（report 分支）     ┘
                                    ↑
                        tw-six-metrics 的 .github/actions/build-site
```

| repo | 產出 | 在網站上是哪一頁 |
| --- | --- | --- |
| `metallicatw/tw-six-metrics` | 整個網站（個股頁、評等清單、統計） | 全部 |
| `metallicatw/market-monitor` | 一整份自足的 HTML | 〔全球市場監控＋日股觀察〕`monitor.html` |
| `metallicatw/tw-trend-filter` | 一整份自足的 HTML（`report` 分支） | 〔台股趨勢選股〕`trend.html` |

兩份外來報告是**用 iframe 嵌進來**的，一個位元組都沒有被改過。它們每天重新產生，
改它遲早會壞；而嵌進來讀者還留在這個網站上，頁首、導覽、搜尋框都在。

### 最重要的一件事

**衛星 repo 跑完 ≠ 網站更新。**

那兩份報告是主站**建站的時候**才去 clone 的。所以更新它們一定是兩步：
先讓它自己產生新報告，再讓主站建一次站。只做第一步，網站上看到的還是舊的。

（clone 失敗只是 `::warning::`，不會讓整個網站發不出去——那一頁不見，
不該連累其他 1,700 多頁。）

---

## 每天的時序（台北時間）

| 時間 | 排程 | repo | 做什麼 | 發布網站？ |
| --- | --- | --- | --- | --- |
| 02:10 | 評等補課 | tw-six-metrics | `twsix refresh --limit 100` | ✅ 有變動才 |
| **06:30**（一–五） | 每日更新報告 | **market-monitor** | 抓資料＋產生 `index.html` | ❌ 只 commit 自己 |
| **07:10**（一–五） | pages | tw-six-metrics | 全站重建，順手抓兩個衛星 | ✅ |
| 08:10 | 評等補課 | tw-six-metrics | 同上 | ✅ 有變動才 |
| 09:20（每天） | 全市場官方資料 | tw-six-metrics | `twsix fetch --all` | ❌ **只存資料** |
| 09:30（一、四） | 股權資料 | tw-six-metrics | `twsix fetch-ownership` ＋補齊歷史 | ✅ 一定建 |
| 14:10 | 評等補課 | tw-six-metrics | 同上 | ✅ 有變動才 |
| **15:10**（一–五） | 每日篩選 | **tw-trend-filter** | 掃全市場約 1,900 檔 → `report` 分支 | ❌ 只推自己 |
| **16:00**（一–五） | pages | tw-six-metrics | 全站重建，順手抓兩個衛星 | ✅ |
| 17:30（一–五） | 每日全市場 | tw-six-metrics | `twsix fetch-daily` | ✅ 有變動才 |
| 20:10 | 評等補課 | tw-six-metrics | 同上 | ✅ 有變動才 |
| 23:30（一–五） | 每日全市場（第二次） | tw-six-metrics | 同上 | ✅ 有變動才 |

排程順序是刻意排的：**衛星先產、pages 後收**。market-monitor 06:30 產完，
07:10 的 pages 接走；tw-trend-filter 15:10 產完，16:00 的 pages 接走。

除了排程，**推任何東西到 `main` 也會觸發 pages**（`**.md` 與 `reference/**` 除外）。

> cron 寫的是 UTC，上面已經換算成台北時間。改排程的時候記得台北 = UTC+8，
> 換算跨午夜的話星期幾也要跟著移。

---

## 只有 pages 會跑測試

這個差別在出事的時候最重要：

| 建站路徑 | 跑 `scripts/run_tests.py`？ |
| --- | --- |
| **pages**（07:10／16:00／push／手動） | ✅ 全部跑完才建 |
| 每日全市場、股權資料、評等補課、加一檔個股 | ❌ `test: "false"` |

所以測試紅的時候，**網站不會完全停住**——那幾條排程照樣默默建站發布，
只有 pages 這條路被擋。症狀會是「網站有些地方在動，但推上去的改動一直沒生效」。
看到這種情形，先去 Actions 看 pages 是不是紅的。

---

## 手動更新：按哪個按鈕

操作都一樣：進該 repo →**Actions**→左邊點那個 workflow →右上 **Run workflow**
→送出。手機用 GitHub App 也可以。

**`pages` 是萬用鍵**：任何時候想讓網站反映「repo 裡現在的資料」，跑它就對了。

| 想更新的 | 第一步 | 在哪個 repo | 第二步 |
| --- | --- | --- | --- |
| 〔台股趨勢選股〕 | 「每日篩選」 | **tw-trend-filter** | **要**跑 tw-six-metrics 的「pages」 |
| 〔全球市場監控＋日股觀察〕 | 「每日更新報告」 | **market-monitor** | **要**跑 tw-six-metrics 的「pages」 |
| 〔每日全市場（收盤行情／三大法人）〕 | 同名 workflow | tw-six-metrics | 不用，自己會建站發布 |
| 〔全市場官方資料（月營收／季財報）〕 | 同名 workflow | tw-six-metrics | **要**跑「pages」（這條只存資料） |
| 〔股權資料（大戶／董監）〕 | 同名 workflow | tw-six-metrics | 不用，自己會建站發布 |

幾個各自的眉角：

**〔全球市場監控〕** 也可以走 market-monitor 的「管理追蹤名單」→動作選
「只更新報告」，效果一樣，那是給手機用的介面。

**〔每日全市場〕** 只有在這次真的有新資料時才建站（`changed == 'yes'`）。
非交易日、或當天已經抓過再跑一次，它會直接結束不建站——這時想更新網頁
還是得跑 pages。

**〔全市場官方資料〕** 不建站是刻意的：它目前只負責把月營收與季財報存下來
累積歷史，還沒接進評等引擎，所以網頁上本來就沒有東西會因為它而改變。
接進去之後這一列要改。

**〔股權資料〕** 就算沒有新資料（董監是月報，週週跑有四分之三次是空的）
也一定會建站發布，所以它可以當成另一個「順便更新網站」的按鈕。

---

## 出事的時候先看這裡

**網站沒有更新到我剛推的東西** → Actions 看 pages 是不是紅的。它是唯一會跑
測試的路徑，也是唯一會因為測試而停掉的。

**某一頁停在舊的，其他頁是新的** → 那一頁很可能是嵌進來的兩份報告之一。
先確認衛星 repo 自己那條排程有沒有成功，再確認之後有沒有跑過一次主站建站。
build-site 的 log 裡會有「〔市場監控〕N 位元組」「〔趨勢選股〕取自 report 分支」
這兩行，沒有那兩行就是沒抓到。

**收盤行情少了一整個交易所** → 看
`tests/test_daily_market.py::test_the_committed_price_files_carry_both_exchanges`。
規則是：最新那一天允許還在途（只發 `::warning::`），它之前的每一天都必須兩市俱全。
修法是手動跑一次「每日全市場」讓它 merge 補上，或
`twsix backfill-prices --days 2`（它會認出「有檔案但只有半個市場」並補另一半）。

**抓取失敗但沒有整個爆掉** → 這是設計。單一來源失敗會記進 `problems`、
變成 `::warning::`，其餘來源照樣存檔，寫入一律是 merge 不是覆蓋——一次打嗝
不該把已經累積好的歷史洗掉。所以要養成看 Actions 摘要上黃色警告的習慣，
不要只看紅綠燈。
