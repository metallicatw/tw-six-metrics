# tw-six-metrics

台股六大財務指標評等引擎，由 `5439_六大財務指標評等v6.62pub` Excel 活頁簿移植而來。

活頁簿有 44 張工作表、76,726 條公式、2,232 行 VBA，以及對八個券商鏡像站與
Goodinfo 的爬蟲依賴。這個專案把其中的**演算法**原封不動搬過來，把**資料層**
換成官方開放資料，把**手動按鈕**換成排程。

---

## 移植是否忠實？可以驗證

活頁簿把上一次重算的結果存在每個儲存格的 `<v>` 裡。那不是負債，是一組免費的
迴歸測試資料——而且涵蓋整個市場。測試分三層，全部是精確比對，沒有容差：

| 層 | 比對什麼 | 規模 | 結果 |
|---|---|---|---|
| 規則 | 把活頁簿自己的指標輸入餵進 `grade_*()` | 9 期 × 6 指標 | **54 / 54** |
| 管線 | 由 ISQ/BSQ/CFQ/EPQ/營收 重建輸入再評分 | 9 期 × 6 指標 + 9 綜合評分 | **54 / 54 · 9 / 9** |
| 市場 | 綜合評分與「具投資價值」邏輯 | 1,741 檔 × 9 期 | **15,619 / 15,620 · 13,892 / 13,892** |
| 行事曆 | 營收月份 → 財報季度 對應 | 15,669 組 | **15,669 / 15,669** |

管線層是關鍵：那一列證明的不只是規則寫對了，而是**我們自己從三大報表算出來的
數字，和 Excel 從券商財務比率表讀來的數字一樣**。

唯一一筆不符是活頁簿自身的資料異常：一檔個股的營收年增率評分是 `5`，超出
0–4 的量表——兩個互斥旗標同時觸發所致。引擎拒絕給它一個不可能的分數。
詳見 [CHANGELOG.md](CHANGELOG.md) 決議 #10。

```
$ python scripts/run_tests.py
45 passed, 0 failed in 0.60s
```

---

## 快速開始

不需要網路，不需要 API key——你手上那個 `.xlsm` 就夠了。

```bash
git clone <this repo> && cd tw-six-metrics

# 1. 把活頁簿凍結成測試樣本（一次就好）
python scripts/extract_golden.py /path/to/5439_六大財務指標評等v6.62pub.xlsm

# 2. 對帳：引擎 vs 活頁簿的既有答案
PYTHONPATH=src python -m twsix.cli verify
#   5439: 指標評分 54/54 相符

# 3. 評等單一個股
PYTHONPATH=src python -m twsix.cli rate --workbook /path/to/workbook.xlsm
#   期別  財報季度   營收月份    營收年增 營業利益 稅後淨利 每股盈餘 存貨周轉 自由現金 綜合    價值
#   1     2026.2Q  115/07     BB      AA      AA      AA      A       BB      3.17   ★

# 4. 匯入活頁簿的全市場快照，產生網站
PYTHONPATH=src python -m twsix.cli import-list /path/to/workbook.xlsm --out data
PYTHONPATH=src python -m twsix.cli build --data data --out site
python -m http.server -d site
```

安裝成命令列工具：

```bash
pip install -e ".[all]"      # 或 uv sync --extra all
twsix verify
twsix rate --workbook book.xlsm
```

---

## 這個專案怎麼組起來的

```
src/twsix/
├── models.py          Grade / Status / IndicatorResult / Snapshot
├── calendar_tw.py     台股財報行事曆、民國西元換算、季度算術
├── rating/
│   ├── indicators.py  六個純函式，零相依，可單獨測試
│   └── engine.py      組出九期快照、綜合評分、具投資價值
├── transform/
│   ├── statements.py  由三大報表自算比率（不抓券商的現成值）
│   └── revenue.py     月營收年增率、近12月累計、三種預估成長率
├── valuation/
│   ├── eps_forecast.py  EPS 預估 + 本益比估價 + PEG/總報酬
│   ├── pe_band.py       河流圖分位帶
│   └── yield_model.py   殖利率三價位
├── ingest/
│   ├── twse.py tpex.py mops.py tdcc.py   官方/開放資料
│   ├── moneydj.py                        券商鏡像備援（預設關閉）
│   └── workbook.py                       把 .xlsm 當資料源（離線可用）
├── store/snapshots.py CSV 快照 + manifest
├── report/build.py    Jinja2 → 靜態網站
├── xlsx/extract.py    自製 OOXML 讀取器（不需 openpyxl）
└── cli.py             twsix 命令列
```

### 兩個刻意的設計選擇

**評等引擎零相依。** `rating/` 只用標準函式庫。六個 `grade_*()` 是純函式：
輸入一組浮點數，輸出等第與命中理由。不碰 IO、不碰 DataFrame。這才有辦法直接
拿 Excel 算好的值對帳，也才能用邊界測試掃門檻。

**資料存成 CSV，不是 Parquet。** 欄式儲存查詢比較快，但這個 repo 的資料檔存在
的目的是被**閱讀**：當一次排程改動了 1,700 檔評等，那個 diff 就是稽核軌跡，而
看不懂的 diff 不算稽核軌跡。全市場評等表壓縮後不到 2 MB，速度從來不是瓶頸。

---

## 資料來源

活頁簿最脆弱的部分就是資料層：八家券商的 MoneyDJ 鏡像輪替、Big5 編碼、
Goodinfo 需要偽造 Cookie 與行動版 UA、還內建 proxy 開關。這些在 GitHub Actions
的 Azure IP 上幾乎必然被擋。

| 資料 | 原來源 | 現在 |
|---|---|---|
| 綜合損益表 / 資產負債表 | MoneyDJ `zcq_` / `zcpa_` | TWSE·TPEx OpenAPI |
| 現金流量表 | MoneyDJ `zc3_` | 公開資訊觀測站 |
| 月營收 | MoneyDJ `zch_` | TWSE `t187ap05_L` |
| **財務比率** | MoneyDJ `zcr_` | **不抓，由三表自算** |
| 日/週 K 線 | MoneyDJ `.djbcd` | TWSE `STOCK_DAY` |
| 三大法人 | MoneyDJ `zcl` | TWSE `T86` |
| 大戶持股 | Goodinfo（需規避保護機制） | 集保 TDCC 開放資料 |
| 董監持股 | Goodinfo | 公開資訊觀測站 |

完整對照見 [DATASOURCES.md](DATASOURCES.md)。

> **狀態說明**：`ingest/` 的官方端點已依各站文件實作，但尚未在有網路的環境
> 跑過一次真實抓取——本專案是在無外網的環境中完成的。每個模組都配了
> contract test（`CONTRACT_KEYS`），第一次 `twsix fetch` 若欄位對不上會
> fail fast 並指出是哪個端點。`rating/`、`transform/`、`valuation/` 與
> `report/` 則已用真實資料完整驗證。

Goodinfo 的服務條款禁止自動化抓取。`ingest/moneydj.py` 預設停用，
且刻意不實作 Goodinfo。

---

## 排程

| 工作流程 | 時機 | 做什麼 |
|---|---|---|
| `ci.yml` | 每次 push / PR | ruff + mypy + 全部測試（含黃金對帳） |
| `daily.yml` | 交易日收盤後 | 抓股價與三大法人、重算估價、重建站台 |
| `monthly.yml` | 每月 10–16 日 | 抓月營收、重算評等 |
| `quarterly.yml` | 3/31·5/15·8/14·11/14 前後 | 抓三大報表、全市場重評 |

資料快照會 commit 進 repo，形成天然的稽核軌跡；站台由 `actions/deploy-pages`
發布到 GitHub Pages。

---

## 文件

- [SPEC.md](SPEC.md) — 六大指標的完整演算法規格，逐條對應原始公式
- [DATASOURCES.md](DATASOURCES.md) — 每個端點的網址、參數與遷移對照
- [CHANGELOG.md](CHANGELOG.md) — 十項與 v6.62 的刻意差異及理由
- [DEPLOY.md](DEPLOY.md) — 推上 GitHub、開啟 Pages 與排程的步驟

---

## 資料再散布

`data/ratings.csv` 是用 `twsix import-list` 從活頁簿〔評等清單〕匯入的基準
快照（1,741 檔 × 9 期），讓網站在第一次抓取完成前就有內容。那是原始活頁簿
作者發布的計算結果。若你不打算連同它一起公開，刪掉該檔並把 `data/` 加入
`.gitignore` 即可——排程第一次跑完就會重新產生。

## 免責

由公開資料自動產生，僅供研究參考，不構成投資建議。
評等規則來自原始活頁簿作者，本專案只負責忠實移植與驗證。
