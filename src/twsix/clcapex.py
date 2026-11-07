"""合約負債 × 資本支出：企業擴張的正向循環（四象限判讀，全站共用一套規則）。

合約負債（資產負債表，流動負債）＝客戶先付的訂金＝「未來的營收」，隨交貨約 2 季內轉成營收；
資本支出（現金流量表，投資活動）＝公司買廠房設備＝「未來的產能」，建廠調機約 2 年以上才貢獻營收。

| 組合 | 條件 | 解讀 |
|---|---|---|
| 最強組合 | 合約負債 ↑、資本支出 ↑ | 現在有訂單、未來有產能；擴產有真實需求（訂金）撐腰 |
| 風險組合 A | 合約負債 ─／↓、資本支出 ↑ | 大舉建廠卻沒有對應的預收訂單；需求不如預期時，折舊侵蝕毛利與淨利 |
| 風險組合 B | 合約負債 ↑、資本支出 ─／↓ | 訂單多但產能受限；不擴產的話營收成長終將遇到天花板（輕資產、外包生產的公司除外） |
| 平淡 | 兩者都沒有明顯增加 | 沒有擴張訊號，看其他指標 |

門檻：合約負債「↑」＝年增 ≥ 20%；資本支出「↑」＝近四季合計比前四季多 ≥ 20%（×1.2）、「↓／─」＝ ≤ ×1.0。
"""
from __future__ import annotations

CL_UP = 20.0       # 合約負債年增 %（≥）
CL_FLAT = 10.0     # 合約負債年增 < 10% 視為持平或下降
CX_UP = 1.2        # 近四季資本支出 ÷ 前四季（≥）
CX_FLAT = 1.0


def quadrant(cl_yoy: float | None, capex_ratio: float | None) -> dict[str, str] | None:
    """cl_yoy：合約負債年增率（%）；capex_ratio：近四季資本支出 ÷ 前四季。回傳 {key, level, title, text}。"""
    if cl_yoy is None or capex_ratio is None:
        return None
    cl_up, cl_flat = cl_yoy >= CL_UP, cl_yoy < CL_FLAT
    cx_up, cx_flat = capex_ratio >= CX_UP, capex_ratio <= CX_FLAT
    pct = int(abs(cl_yoy) + 0.5) * (1 if cl_yoy >= 0 else -1)   # 四捨五入（與網頁 JS 一致，不用銀行家捨入）
    tail = f"（合約負債年增 {'+' if cl_yoy >= 0 else '-'}{abs(pct)}%、資本支出為前四季的 {capex_ratio:.2f} 倍）"
    if cl_up and cx_up:
        return {"key": "best", "level": "good", "title": "最強組合：合約負債 ↑ ＋ 資本支出 ↑",
                "text": "現在有訂單、未來有產能，擴產有真實需求撐腰，營收與獲利爆發的確定性高" + tail}
    if cl_flat and cx_up:
        return {"key": "risk_a", "level": "warn", "title": "風險組合 A：合約負債 ─ ＋ 資本支出 ↑",
                "text": "大舉建廠但沒有對應的預收訂單；需求不如預期時，新產能的折舊會侵蝕毛利與淨利" + tail}
    if cl_up and cx_flat:
        return {"key": "risk_b", "level": "info", "title": "風險組合 B：合約負債 ↑ ＋ 資本支出 ─",
                "text": "訂單多但沒有擴產，受限於既有產能，營收成長終將遇到天花板（輕資產、外包生產的公司除外）" + tail}
    if not cl_up and not cx_up:
        return {"key": "flat", "level": "info", "title": "平淡：兩者都沒有明顯增加", "text": "沒有擴張訊號" + tail}
    return {"key": "mid", "level": "info", "title": "過渡：其中一項溫和增加", "text": "擴張訊號還不明確，追蹤下一季" + tail}
