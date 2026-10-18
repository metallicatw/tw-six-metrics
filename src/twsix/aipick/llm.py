
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest")
TRANSIENT = frozenset({500, 502, 503, 504})
BUSY_STOP = 3
BUSY_WAIT = 8.0


class QuotaExhausted(Exception):
    pass


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.status, resp.read()


def parse_json_text(text: str):
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
        self.busy = 0
        self._busy_streak = 0

    @property
    def enabled(self) -> bool:
        return bool(self._key) and not self.stopped and self.calls < self.max_calls

    def status(self) -> dict:
        return {"enabled": bool(self._key), "calls": self.calls, "max_calls": self.max_calls,
                "model": self.model_used, "stopped": self.stopped, "busy": self.busy,
                "errors": self.errors[-5:]}

    def ask_json(self, prompt: str, *, max_output_tokens: int = 1024):
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
        tried: set[str] = set()
        while self.models:
            model = self.models[0]
            if model in tried:
                return self._gave_up_busy()
            if self.calls >= self.max_calls:
                return None
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
                if exc.code in TRANSIENT:
                    self._busy(model, f"HTTP {exc.code} {detail}", tried)
                    continue
                self.errors.append(f"{model}：HTTP {exc.code} {detail}")
                return None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._busy(model, f"連線失敗 {type(exc).__name__}", tried)
                continue
            if status != 200:
                self.errors.append(f"{model}：HTTP {status}")
                return None
            self.model_used = model
            self._busy_streak = 0
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

    def _busy(self, model: str, detail: str, tried: set[str]) -> None:
        self.busy += 1
        self.errors.append(f"{model}：{detail}")
        tried.add(model)
        if len(self.models) > 1:
            self.models.append(self.models.pop(0))
        if self.models[0] not in tried:
            self._sleep(BUSY_WAIT)

    def _gave_up_busy(self):
        self._busy_streak += 1
        if self._busy_streak >= BUSY_STOP:
            self.stopped = (f"Google 那邊忙（連續 {self._busy_streak} 個提示每個型號都回忙碌），"
                            "這一趟先停，剩下的下一趟再問")
        return None

    def _detail(self, exc: urllib.error.HTTPError) -> str:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            msg = ""
        msg = (msg or "")[:160]
        return msg.replace(self._key, "***") if self._key else msg
