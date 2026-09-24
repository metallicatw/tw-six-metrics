"""LLM 介面：Google Gemini（免費版）。沒有金鑰就什麼都不做，其他部分照跑。

## 金鑰

只從環境變數 `GEMINI_API_KEY` 讀——在 GitHub 上是 repo secret，排程那一步用
`env:` 帶進來。**它不會被寫進任何檔案、任何頁面、任何 log**：送出去時放在
`x-goog-api-key` 標頭（不放網址，網址會出現在錯誤訊息裡），錯誤訊息只留狀態碼與
Google 回的那段說明，不留請求本身。`tests/test_aipick_llm.py` 檢查這件事。

## 模型

預設依序試 `gemini-flash-lite-latest`、`gemini-flash-latest`（Google 維護的「最新
穩定版」別名，型號改版時不用改程式）；`GEMINI_MODEL` 可以指定。某個型號回 404
（不存在或已下架）就換下一個。

## 額度

免費版有每分鐘與每日的請求上限。這裡的做法：

* 每一趟最多 `max_calls` 次（預設 40，`AIPICK_LLM_MAX` 可改）
* 兩次之間至少隔 `min_interval` 秒（預設 4.5 秒 ≈ 每分鐘 13 次）
* 一收到 429（額度用完）就**停止這一趟**所有呼叫——剩下的明天再做

呼叫的結果都寫進快取檔（見 :mod:`.talks`），同一份文件永遠只問一次。

## 隱私

依 Google 條款，免費版送出的內容可能被用來改進產品。這裡送的只有公開資料
（公開資訊觀測站的法說簡報、公司名稱），沒有任何個人或帳戶資訊。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest")


class QuotaExhausted(Exception):
    pass


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.status, resp.read()


def parse_json_text(text: str):
    """模型回的文字 → JSON。容忍 ```json 圍欄與前後的說明文字。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        a, b = t.find(open_), t.rfind(close)
        if a >= 0 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                continue
    return None


class Gemini:
    """最小的 Gemini 用戶端。`post` 可以換掉（測試用假的）。"""

    def __init__(self, key: str | None = None, *, models=None, max_calls: int | None = None,
                 min_interval: float = 4.5, timeout: float = 60.0, post=None, sleep=None):
        self._key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")
        env_model = os.environ.get("GEMINI_MODEL", "").strip()
        self.models = list(models or ((env_model,) if env_model else DEFAULT_MODELS))
        env_max = os.environ.get("AIPICK_LLM_MAX", "").strip()
        self.max_calls = max_calls if max_calls is not None else (int(env_max) if env_max.isdigit() else 40)
        self.min_interval = min_interval
        self.timeout = timeout
        self._post = post or _post
        self._sleep = sleep or time.sleep
        self.calls = 0
        self.errors: list[str] = []
        self.stopped = ""
        self._last = 0.0
        self.model_used = ""

    @property
    def enabled(self) -> bool:
        return bool(self._key) and not self.stopped and self.calls < self.max_calls

    def status(self) -> dict:
        """給頁面與 log 用的狀態——**不含金鑰**。"""
        return {"enabled": bool(self._key), "calls": self.calls, "max_calls": self.max_calls,
                "model": self.model_used, "stopped": self.stopped, "errors": self.errors[-5:]}

    def ask_json(self, prompt: str, *, max_output_tokens: int = 1024):
        """送出一個提示，回傳解析好的 JSON（失敗回 None）。額度用完丟 QuotaExhausted。"""
        if not self._key:
            return None
        if self.stopped or self.calls >= self.max_calls:
            raise QuotaExhausted(self.stopped or "這一趟的呼叫次數用完了")
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                 "maxOutputTokens": max_output_tokens},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        while self.models:
            model = self.models[0]
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0 and self._last:
                self._sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            try:
                status, raw = self._post(ENDPOINT.format(model=model), body, headers, self.timeout)
            except urllib.error.HTTPError as exc:
                detail = self._detail(exc)
                if exc.code == 404:
                    self.errors.append(f"{model}：404（型號不存在），換下一個")
                    self.models.pop(0)
                    continue
                if exc.code == 429:
                    self.stopped = f"額度用完（429）：{detail}"
                    raise QuotaExhausted(self.stopped) from None
                if exc.code in (401, 403):
                    self.stopped = f"金鑰被拒（{exc.code}）：{detail}"
                    raise QuotaExhausted(self.stopped) from None
                self.errors.append(f"{model}：HTTP {exc.code} {detail}")
                return None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.errors.append(f"{model}：連線失敗 {type(exc).__name__}")
                return None
            if status != 200:
                self.errors.append(f"{model}：HTTP {status}")
                return None
            self.model_used = model
            try:
                data = json.loads(raw.decode("utf-8"))
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts)
            except (ValueError, KeyError, IndexError, TypeError):
                self.errors.append(f"{model}：回應格式看不懂")
                return None
            return parse_json_text(text)
        self.stopped = "沒有可用的型號"
        raise QuotaExhausted(self.stopped)

    def _detail(self, exc: urllib.error.HTTPError) -> str:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            msg = ""
        msg = (msg or "")[:160]
        return msg.replace(self._key, "***") if self._key else msg
