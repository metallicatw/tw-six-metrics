"""龍蝦／海龜系統 × 全球宏觀策略（整合進金股道）。

原專案 D:\\PROJECTS\\lobturtle（獨立網站＋SQLite）。這裡保留它的指標、資料庫與策略引擎，
資料放在 tw-six-metrics 的 `data/lobturtle/`，建站時輸出成靜態 JSON（`site/lobturtle/api/*.json`），
頁面用原本的介面（`static/`），由 `shim.js` 把 `/api/...` 換成靜態檔、回測改在瀏覽器裡算。
"""
DATA_SUBDIR = "lobturtle"
