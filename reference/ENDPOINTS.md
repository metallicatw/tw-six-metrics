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

## 六、單檔查詢目前的完整度（2026/08）

九張券商鏡像分頁全部解析成功，並在 `tests/test_derive.py` 與活頁簿的
估值逐項對照。抓回來的頁面只有 MoneyDJ 印出來的東西，活頁簿的工作表還多了
一整批 Excel 公式欄，`twsix.ingest.derive` 把它們補回原本的儲存格：

| 補回的欄位 | 來源 | 驗證 |
|---|---|---|
| 〔營收〕AD/AE 年增率(1-2合計&去1) | A/B/D 三欄，1、2 月合併計算 | 與活頁簿逐列相符 |
| 〔六大財務指標評等〕B3:G3 稅後淨利率 | 〔FRQ〕稅後淨利率 列（依標籤找，不依列號） | 完全相符 |
| 〔評價簡表〕B1/C1 代號與名稱 | 任一頁的標題 | — |
| 〔BASIC2〕最高／最低本益比 | 年度最高低價 ÷ 年度EPS | 相差 0.3%，原因見下 |

**〔年度交易資訊(上市櫃合併)〕** 不在鏡像站上，走證交所 `FMNPTK` 與櫃買
`yearlyStock`。櫃買那半邊已對照真實回應
（`tests/pages/5439/5439_yearly_tpex.json`），並立刻證明「依欄位名稱對應」
是對的決定：

| | 證交所 | 櫃買 |
|---|---|---|
| 第 5 欄 | 最高價 | **加權平均價(B/A)** |
| 高低價欄名 | 最高價／最低價 | **盤中最高價／盤中最低價** |
| 表格數 | 1 | **2**（第 2 張是「近年最高價／最低價」，欄名也會誤中） |

依位置讀會把 115 年的最高價讀成 331.33（加權平均價）而不是 463.50——
數字合理、契約檢查抓不到。

證交所那半邊也已對照真實回應（`tests/pages/2330/`）。兩個交易所在**三件事**
上不一致，任何只照著其中一邊寫的解析器都會在另一邊出錯：

| | 證交所 | 櫃買 |
|---|---|---|
| 高低價欄名 | 最高價／最低價 | 盤中最高價／盤中最低價 |
| 第 5 欄 | 最高價 | 加權平均價(B/A) |
| 年度排序 | **最舊在前**（83→114） | **最新在前**（115→89） |
| 當年度 | **沒有**（115 年只到 114） | 有 |

最後一項最危險：證交所的年度表不含當年度，所以上市股的序列會整條往上位移
一年——「當年度本益比」實際讀到去年，五年區間變成 113–109 而不是 114–110，
畫面上完全看不出來。`yearly_prices(reader, anchor)` 因此改為以資料本身的
當年度（〔營收〕最新月份、〔EPQ〕最新季度）錨定 index 0，缺的年度補空白列。

**Python 3.13 的 TLS 陷阱：** 3.13 讓 `ssl.create_default_context()` 預設開啟
`VERIFY_X509_STRICT`，而證交所憑證鏈有一張中介憑證缺 Subject Key Identifier，
於是每個 TWSE 請求都會死在

```
[SSL: CERTIFICATE_VERIFY_FAILED] Missing Subject Key Identifier
```

同一個網址在瀏覽器與 Python 3.12 都正常。`ingest.base.tls_context()` 把該旗標
關掉——憑證鏈仍然驗證、主機名稱仍然檢查，放棄的只是一項我們無權修改的
憑證格式符合性檢查。

**已知的 0.3% 差距：** 〔BASIC2〕的年度EPS 是 MoneyDJ 自己的年度數字，
單檔查詢是把〔EPQ〕四季 EPS 相加——每季已經四捨五入到小數兩位，所以
113 年加起來是 3.52，活頁簿是 3.51。要收斂就得多抓
〔MoneyDJ年財務比率〕(`/z/zc/zcr/zcr0.djhtm?b=Y&a={代號}`)。

## 七、十二頁面的完成度（2026/08）

| 頁面 | 狀態 | 說明 |
|---|---|---|
| 評價簡表 | ✅ | 九期 × 六指標矩陣、綜合評分、具投資價值旗標、資料來源狀態 |
| 六大財務指標評等 | ✅ | 各指標數列與評分理由；**54/54 對照活頁簿** |
| EPS預估與估價 | ✅ | 含四條報酬風險比判斷準則與兩條警語 |
| 殖利率估價 | ✅ | 含證明股利遞延一年的歷年對照列 |
| 財報圖表 | ✅ | 評分所依據的四條季度數列 |
| 河流圖 | ⚠️ | **改用年度收盤平均價**，見下 |
| 營收季節性 | ✅ | 各月占全年比重（完整年度平均）＋ 月×年格線 |
| 獲利季節性 | ✅ | 各季 EPS 占全年比重；虧損年度不計入 |
| 財務指標評等預估 | ⚠️ | 四種情境的適用時機已呈現；輸入預估值需靠 CLI |
| 外資投信 | ✅ | 〔三大法人〕近 20 日買賣超、估計持股與持股比重 |
| 個股新聞 | ❌ | MoneyLink／Yahoo，未取得過真實回應 |
| 大戶持股 / 董監持股 | ❌ | Goodinfo，需帶 referer，擋機房 IP 最嚴 |

### 河流圖為什麼不一樣

活頁簿用**週線**收盤價（鉅亨網），並在年底之間內插 BPS 與 EPS，河流才會平滑
彎曲。本專案沒有週線序列，改用交易所公布的**年度收盤平均價**——同樣的
2.5%～97.5% 信任區間、同樣六個分區，一年一點而不是一週一點。

代價與收穫都很明確：平滑曲線畫不出來，但「現在落在哪一區」這個真正驅動決策
的判斷仍然成立——5439 兩種算法都落在**合理區**（見
`tests/test_sections.py::test_the_river_puts_the_stock_in_the_workbooks_zone`）。

要升級成週線版，需要抓 `https://www.cnyes.com/twstock/ps_historyprice.aspx?code={代號}`
並存下一份真實回應。

### 〔三大法人〕加進 ORDER 了

它不在〔評價簡表〕Worksheet_Change 的九張裡（活頁簿是為了自己的分頁另外抓
的），但來源是同一批券商鏡像，多一次請求就換到一整頁，所以 `fetch-stock`
現在一併抓。

它的頁面也抓出一個**會殺死整份文件**的解析器 bug：〔三大法人〕的日期表單有
兩個 `<input type='hidden'>`。`input` 原本被列在「跳過內容直到結束標籤」的集合
裡，但它是 void 元素、永遠不會有結束標籤——於是跳過狀態再也沒有解除，整頁只
解析出四列（全是頁面裝飾）。現在 void 優先於 skip。任何帶隱藏欄位的頁面都會
踩到這個。

### 那三張還沒做的頁面

沒有寫解析器，不是忘了，是**沒看過真實回應**。要補上，先各抓一次並把回應給我。
Goodinfo 與 MoneyLink 是另外的站，擋得比券商鏡像兇，要先確認抓得到。

