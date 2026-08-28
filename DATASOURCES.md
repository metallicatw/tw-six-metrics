# 資料來源盤點與遷移對照

> 逆向來源：`5439_六大財務指標評等v6.62pub_20250913.xlsm` → `Module1`（2,232 行，36 個程序）

## 1. 原檔實際使用的所有端點

### MoneyDJ 標準化財報系統（8 家券商鏡像，Big5 編碼）

`GetHost()` 回傳的鏡像清單，使用者可在各表的 `F1` / `Z3` 儲存格選擇：

```
https://moneydj.emega.com.tw            兆豐證券
https://kgieworld.moneydj.com           凱基證券
https://fubon-ebrokerdj.fbs.com.tw      富邦證券
https://stocks.firstsec.com.tw          第一金證券
https://just2.entrust.com.tw            華南永昌證券
https://stockchannelnew.sinotrade.com.tw 永豐金證券
https://newjust.masterlink.com.tw       元富證券
https://djinfo.cathaysec.com.tw         國泰證券
```
（註解中另列元大 jdata.yuanta.com.tw、群益 stock.capital.com.tw、統一 pscnetsecrwd.moneydj.com、合庫 tcfhcsec.moneydj.com，未納入陣列）

| 工作表 | 路徑 | 內容 |
|---|---|---|
| FRQ | `/z/zc/zcr/zcr_{code}.djhtm` | 財務比率表（季） |
| CFQ | `/z/zc/zc3/zc3_{code}.djhtm` | 現金流量表（季） |
| ISQ | `/z/zc/zcq/zcq_{code}.djhtm` | 綜合損益表（季） |
| BSQ | `/z/zc/zcp/zcpa/zcpa_{code}.djhtm` | 資產負債表（季） |
| BASIC | `/z/zc/zca/zca_{code}.djhtm` | 基本資料 |
| OPQ | `/z/zc/zce/zcd_{code}.djhtm` | 經營績效 |
| EPQ | `/z/zc/zce/zce_{code}.djhtm` | 獲利能力 |
| 營收 | `/z/zc/zch/zch_{code}.djhtm` | 月營收 |
| 股利 | `/z/zc/zcc/zcc_{code}.djhtm` | 股利政策 |
| MoneyDJ年財務比率 | `/z/zc/zcr/zcr0.djhtm?b=Y&a={code}` | 年度財務比率 |
| 三大法人 | `fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a={code}&b=3` | 近 20 日買賣超（寫死富邦） |
| K 線 | `/Z/ZC/ZCW/CZKC1_{code}_{D|W|M|A}_1440.djbcd` | 最多 1440 根 K 棒，空白分段的 CSV |

解析方式：`MSXML2.XMLHTTP.6.0` GET → `convertraw(responseBody, "Big5")` →
`HTMLFile` → `getElementById("oMainTable")` → 逐 `div.table-row` 取其 `span` 為欄位。

`.djbcd` 格式：以空白切成欄位群，每群以逗號分隔。
`Result(0)` = 日期、`(1)` 開、`(2)` 高、`(3)` 低、`(4)` 收、`(5)` 量。
日期可能是西元 `YYYY/MM/DD` 或民國 `1140110` / `981023`。

### Goodinfo（需規避保護機制）

| 工作表 | URL | 特殊處理 |
|---|---|---|
| Goodinfo年財務比率 | `https://goodinfo.tw/StockInfo/StockFinDetail.asp?RPT_CAT=XX_M_QUAR_ACC&STOCK_ID={code}` | 用 `InternetExplorer.Application` 自動化，選 `RPT_CAT.selectedIndex = 2`（合併-年度）後 `FireEvent("onchange")`，等 3 秒 |
| 董監持股 | `https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID={code}` | `WinHttp.WinHttpRequest.5.1`、Cookie `SCREEN_SIZE=WIDTH=1139&HEIGHT=640`、`Option(4)=13056`、可選 proxy |
| 大戶持股 | `https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STEP=DATA&STOCK_ID={code}&CHT_CAT=WEEK&PRICE_ADJ=F&SHEET={type}&START_DT={-2y}&END_DT={today}` | POST、referer、行動版 UA（Nexus 5 / Chrome 90）、同上 Cookie 與 proxy |

proxy 開關位於〔大戶持股〕`M2`（Y/N）與 `M3`（位址）。

### 官方端點（原檔已在使用）

| 用途 | URL |
|---|---|
| 上市年度交易資訊 | `https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK?response=html&stockNo={code}` |
| 上櫃年度交易資訊 | `https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock?code={code}&id=&response=html` |
| 股東會年報 | `https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id={code}&year={roc}&mtype=F&` |
| 財務報告書 | 同上 `&seamon=&mtype=A&` |

### 其他

| 用途 | URL |
|---|---|
| 日股價（備選） | `https://www.cnyes.com/twstock/ps_historyprice.aspx?code={code}`（POST，含寫死的 `__EVENTVALIDATION`） |
| 個股新聞 | `https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId={code}` |
| 個股新聞（備選） | `https://tw.stock.yahoo.com/quote/{code}/news` |

---

## 2. 遷移對照表

| 資料 | 原來源 | 建議來源 | 判定 |
|---|---|---|---|
| 綜合損益表 ISQ | MoneyDJ `zcq_` | MOPS XBRL／TWSE OpenAPI 綜合損益表 | 改官方 |
| 資產負債表 BSQ | MoneyDJ `zcpa_` | MOPS XBRL／TWSE OpenAPI 資產負債表 | 改官方 |
| 現金流量表 CFQ | MoneyDJ `zc3_` | MOPS XBRL 現金流量表 | 改官方 |
| 財務比率 FRQ | MoneyDJ `zcr_` | **不抓，由三表自算** | 自算更好 |
| 月營收 | MoneyDJ `zch_` | MOPS 月營收／TWSE OpenAPI `t187ap05_L` | 改官方 |
| 基本資料 | MoneyDJ `zca_` | TWSE／TPEx 公司基本資料 OpenAPI | 改官方 |
| 股利 | MoneyDJ `zcc_` | TWSE OpenAPI 股利分派／MOPS | 改官方 |
| 日／週 K 線 | MoneyDJ `.djbcd` | TWSE `STOCK_DAY` + TPEx 日成交，自行聚合週線 | 改官方 |
| 年度交易資訊（上市） | TWSE FMNPTK | 維持，改吃 JSON | 保留 |
| 年度交易資訊（上櫃） | TPEx yearlyStock | 維持，改吃 `response=json` | 保留 |
| 三大法人 | MoneyDJ `zcl` | TWSE `T86`／TPEx 對應端點 | 改官方 |
| 大戶持股（週） | Goodinfo | 集保結算所 TDCC 股權分散表開放資料 | 改官方 |
| 董監持股 | Goodinfo | MOPS 董監事持股餘額明細 | 改官方 |
| 年財務比率（8 年） | MoneyDJ + Goodinfo 取大者 | 由季報累加自算 | 自算更好 |
| 個股新聞 | money-link / Yahoo | RSS 或整段移除 | 可選 |

---

## 3. GitHub Actions 環境注意事項

- Actions runner IP 屬 Azure 資料中心網段，Goodinfo 與部分券商站極可能直接封鎖。
  原檔的 `SetProxy` 開關正是為此存在。
- 建議：**官方 API 走 Actions；任何仍需爬蟲的來源改本機排程 + 推 CSV 進 repo**，
  雲端流程只讀 repo 內的資料快照。
- 合規：Goodinfo 服務條款禁止自動化抓取，原檔以偽造 Cookie 與行動版 UA 規避保護機制。
  公開發布的專案不宜內含這類程式碼。
