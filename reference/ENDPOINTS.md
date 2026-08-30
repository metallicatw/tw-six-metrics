# 活頁簿實際使用的資料來源

由 `scripts/extract_vba.py` 從 `vbaProject.bin` 還原的 47 個模組整理而來
（原始碼在 `reference/vba/`）。

**這份文件推翻了 `DATASOURCES.md` 的假設。** 專案原本的 `ingest/` 是照
TWSE / TPEx / MOPS / TDCC 官方 API 文件寫的，從未實跑過。活頁簿實際上
**幾乎不用官方 API**——它打的是**券商的 MoneyDJ 鏡像站**（`.djhtm` 頁面），
只有年度交易資訊走證交所、櫃買中心。

## 一、券商鏡像（主力來源）

`Module1.GetHost()` 在下列 8 個 host 之間輪替，任一個掛掉就換下一個：

```
https://moneydj.emega.com.tw          兆豐證券
https://kgieworld.moneydj.com         凱基證券
https://fubon-ebrokerdj.fbs.com.tw    富邦證券
https://stocks.firstsec.com.tw        第一金證券
https://just2.entrust.com.tw          華南永昌證券
https://stockchannelnew.sinotrade.com.tw  永豐金證券
https://newjust.masterlink.com.tw     元富證券
https://djinfo.cathaysec.com.tw       國泰證券
```

（原始碼另註記 元大 `jdata.yuanta.com.tw`、群益 `stock.capital.com.tw`、
統一 `pscnetsecrwd.moneydj.com`、合庫 `tcfhcsec.moneydj.com`；日盛與國泰世華
已註記失效。）

所有頁面路徑共用同一套 MoneyDJ 代碼：

| 工作表 | 內容 | 路徑 |
|---|---|---|
| `FRQ` | 財務比率表 | `/z/zc/zcr/zcr_{代號}.djhtm` |
| `ISQ` | 綜合損益表 | `/z/zc/zcq/zcq_{代號}.djhtm` |
| `BSQ` | 資產負債表 | `/z/zc/zcp/zcpa/zcpa_{代號}.djhtm` |
| `CFQ` | 現金流量表 | `/z/zc/zc3/zc3_{代號}.djhtm` |
| `BASIC` | 基本資料 | `/z/zc/zca/zca_{代號}.djhtm` |
| `OPQ` | 經營績效 | `/z/zc/zce/zcd_{代號}.djhtm` |
| `EPQ` | 獲利能力 | `/z/zc/zce/zce_{代號}.djhtm` |
| `營收` | 月營收 | `/z/zc/zch/zch_{代號}.djhtm` |
| `股利` | 股利政策 | `/z/zc/zcc/zcc_{代號}.djhtm` |
| `三大法人` | 法人買賣超（近20日） | `/z/zc/zcl/zcl.djhtm?a={代號}&b=3` |
| `MoneyDJ年財務比率` | 年度財務比率 | `/z/zc/zcr/zcr0.djhtm?b=Y&a={代號}` |

## 二、官方站台

| 用途 | 網址 |
|---|---|
| 年度交易資訊（上市） | `https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK?response=html&stockNo={代號}` |
| 年度交易資訊（上櫃） | `https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock?code={代號}&id=&response=html` |
| 股東會年報 / 財報書 | `https://doc.twse.com.tw/server-java/t57sb01?...` （只是開啟網頁，不抓資料） |

上市與上櫃兩份年度交易資訊由 `Module1.MergeYTV_New` 合併成
〔年度交易資訊(上市櫃合併)〕，這正是估值用的歷年最高／最低／收盤平均價來源。

## 三、其他站台

| 工作表 | 來源 | 網址 |
|---|---|---|
| `股價(日)` | 鉅亨網 | `https://www.cnyes.com/twstock/ps_historyprice.aspx?code={代號}` |
| `Goodinfo年財務比率` | Goodinfo | `https://goodinfo.tw/StockInfo/StockFinDetail.asp?RPT_CAT=XX_M_QUAR_ACC&STOCK_ID={代號}` |
| `董監持股` | Goodinfo | `https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID={代號}` |
| `大戶持股` | Goodinfo | `https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STEP=DATA&STOCK_ID={代號}&CHT_CAT=WEEK&PRICE_ADJ=F&SHEET={類別}&START_DT={起}&END_DT={迄}` |
| `個股新聞` | MoneyLink | `https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId={代號}` |
| `個股新聞`（備援） | Yahoo | `https://tw.stock.yahoo.com/quote/{代號}/news` |

Goodinfo 的請求會帶 `referer`；`設定!G1` 可整組關掉 Goodinfo 年財務比率
（`操作說明` 建議預設 `N`，說是為了加速並避開 Excel 2019 的下載錯誤）。

## 四、移植時必須正視的三件事

1. **這些都不是公開 API，是網頁。** 版面一改就壞——`Module1` 裡光是網址變更
   的註記就有 6 處（112/03/24 證交所改版、113/11/05 櫃買改版、113/6/11
   Goodinfo 改網址…）。契約檢查（`CONTRACT_KEYS`）比原本更重要，不是加分項。

2. **券商鏡像會擋機房 IP。** 專案 `settings.toml` 原本就註明
   `enable_moneydj_fallback = false`，理由是「MoneyDJ 鏡像擋資料中心 IP，
   且其條款未涵蓋排程抓取」。GitHub Actions 跑在 Azure 機房，極可能被擋。
   Goodinfo 尤其嚴格。

3. **速度。** 活頁簿抓一檔要 1.5～3.5 秒（〔評價簡表〕M1 記錄查詢總秒數，
   5439 為 1.57 秒）。1,741 檔 × 8 個來源，就算完全平行也是以小時計，
   而且是對別人的站台。全市場每日更新在這個來源結構下並不現實。

## 五、版面實況（2026/08 抓回的 9 張真實頁面）

`tests/pages/5439/` 收了 5439 當天實際回傳的九張 HTML，並在
`tests/test_moneydj.py` 逐格對照活頁簿自己的工作表。以下是**看過真實頁面後**
才知道、單看 VBA 猜不到的事：

| 事實 | 影響 |
|---|---|
| 三個「版面世代」的差別只在標記，不在語意 | 不需要三套解析器，一套 HTML 表格排版器就夠 |
| `ISQ` 的 `<FORM>` 開在 `<table>` 之前、關在 `<td>` 之內 | 照著關會把 table 從堆疊上彈掉，整頁只剩 4 列 |
| `股利` 的資料列只有 `</tr>`，沒有 `<tr>` | 相信標記的解析器只讀到 6 列（實際 18 年） |
| `股利` 的「員工/配股率(%)」同時是 `rowspan=2` 和兩行 | 把第二行算進本列高度會插入空白列，整段股利往下位移一列 |
| 每頁的「單位：…」是標題儲存格內的 `<div class="t11">` | 它自己佔一列，本文因此比直覺低一列 |
| `BASIC` 的年度本益比是**巢狀** 9 欄表格，塞在 8 欄的父儲存格裡 | Excel 把區域的**第一欄**撐開，所以本文落在 A 與 C..I，B 空著；收盤價因此在 I5 |
| `BASIC`、`股利` 沒有 `#oMainTable` | 改用 `class="t01"` 選表，比 `.WebTables` 的序號穩 |
| 頁面上的百分比在工作表裡是分數（22.46% → 0.2246） | 去掉百分號而不除以 100，會差兩個數量級且不會報錯 |

原本的三套 `layout` 是照 VBA 的三個 helper 猜的，九張表錯六張。現在
`parse_page()` 一支函式處理全部，且對照活頁簿逐格相符。
