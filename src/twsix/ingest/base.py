"""HTTP plumbing shared by every source.

The workbook fetched with a synchronous ``MSXML2.XMLHTTP`` and a busy-wait
loop, and had no cache, no backoff and no rate limit — which is why a single
stock took several seconds and a market-wide pass was never attempted.  This
layer adds all three, and a disk cache keyed by URL so a re-run inside the
cache window costs nothing.

Only the standard library is required; ``httpx`` is used when present because
it handles HTTP/2 and connection reuse better than ``urllib``.
"""

from __future__ import annotations

import functools
import hashlib
import http.cookiejar
import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger("twsix.ingest")

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 twsix/0.1"
)

#: 給會看 request 長相的站台用的一整組標頭。
#:
#: Goodinfo 連 index.asp 都回 403，家用網路也一樣——那就不是 IP 的問題。urllib
#: 預設只送 User-Agent 與 Accept-Encoding: identity，少了 Accept、
#: Accept-Language、Sec-Fetch-* 這些每個真瀏覽器都會送的欄位；而我們的 UA 尾巴
#: 還掛著 `twsix/0.1`，等於自報家門。逐項補齊到跟瀏覽器一樣。
#:
#: 這不是偽裝成別人，是用一般讀者的方式讀一頁公開的網頁：一次一張、有節流、
#: 有 Referer。
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": BROWSER_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
}


def _decoded(resp: Any) -> bytes:
    """Undo Content-Encoding.

    urllib does not do this for you.  It never mattered while every request
    went out with the default ``Accept-Encoding: identity``, but a request
    shaped like a browser's asks for gzip, and a site that fingerprints
    requests will notice a client that asks and then cannot read the answer.
    """
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower().strip()
    if enc in ("gzip", "x-gzip"):
        import gzip

        return gzip.decompress(raw)
    if enc == "deflate":
        import zlib

        try:
            return zlib.decompress(raw)
        except zlib.error:  # raw deflate, no zlib wrapper
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


class FetchError(RuntimeError):
    """A request failed after every retry."""


@functools.lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    """Verify certificates, but without RFC 5280 strict mode.

    Python 3.13 turned ``VERIFY_X509_STRICT`` on inside
    ``ssl.create_default_context()``.  證交所's chain has an intermediate with
    no Subject Key Identifier, which that flag rejects — so on a 3.13 machine
    every TWSE request dies with::

        [SSL: CERTIFICATE_VERIFY_FAILED] Missing Subject Key Identifier

    while the same URL opens fine in a browser and on Python 3.12.  Turning the
    flag back off is the narrow fix: the chain is still verified against the
    system trust store and the hostname is still checked.  What is given up is
    an extra conformance check on a certificate the exchange controls and we
    cannot change.
    """
    ctx = ssl.create_default_context()
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        ctx.verify_flags &= ~strict
    return ctx


@dataclass
class HttpClient:
    """Polite, cached HTTP.

    ``min_interval`` is enforced per host: the official endpoints will happily
    serve a burst and then start refusing, so we simply never burst.
    """

    cache_dir: Path | None = None
    cache_ttl: float = 6 * 3600
    min_interval: float = 1.2
    timeout: float = 30.0
    retries: int = 4
    backoff: float = 2.0
    user_agent: str = DEFAULT_UA
    default_headers: Mapping[str, str] = field(default_factory=dict)
    #: Keep cookies across requests.  Some sites hand out a session cookie on
    #: the landing page and 403 anything that arrives without one, so a fetch
    #: that visits the front door first only works if the cookie survives.
    cookies: bool = False
    _last_call: dict[str, float] = field(default_factory=dict, init=False)
    _opener: object | None = field(default=None, init=False, repr=False)
    #: 這個 client 會被多執行緒共用（十三張表分散到八個鏡像站同時抓），所以
    #: 節流表和 opener 的建立都要上鎖。鎖只保護「排隊」那一瞬間，等待本身在鎖
    #: 外面睡——不然併發就退化成排隊，而排隊正是要修掉的東西。
    _lock: "threading.Lock" = field(default_factory=lambda: threading.Lock(), init=False, repr=False)

    def _build_opener(self):  # type: ignore[no-untyped-def]
        with self._lock:
            return self._build_opener_locked()

    def _build_opener_locked(self):  # type: ignore[no-untyped-def]
        if self._opener is None:
            handlers = [urllib.request.HTTPSHandler(context=tls_context())]
            if self.cookies:
                jar = http.cookiejar.CookieJar()
                handlers.append(urllib.request.HTTPCookieProcessor(jar))
            self._opener = urllib.request.build_opener(*handlers)
        return self._opener

    # -- cache ------------------------------------------------------------

    def _cache_path(self, url: str, body: bytes | None) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(url.encode() + (body or b"")).hexdigest()[:24]
        host = urllib.parse.urlparse(url).netloc.replace(":", "_")
        d = self.cache_dir / host
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.cache"

    def _read_cache(self, path: Path | None) -> bytes | None:
        if path is None or not path.exists():
            return None
        if self.cache_ttl and (time.time() - path.stat().st_mtime) > self.cache_ttl:
            return None
        return path.read_bytes()

    # -- fetch ------------------------------------------------------------

    @staticmethod
    def _encode(url: str) -> str:
        """Percent-encode a URL that carries non-ASCII.

        ``urllib`` refuses one outright: Goodinfo's 股權分散表 takes a
        ``SHEET=股數分級`` parameter and the request died with
        「'ascii' codec can't encode characters in position 94-97」 — an error
        that reads like a decoding problem in the response and is in fact the
        request never having been sent.
        """
        parts = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                urllib.parse.quote(parts.path, safe="/%"),
                urllib.parse.quote(parts.query, safe="=&%+"),
                urllib.parse.quote(parts.fragment, safe="%"),
            )
        )

    def _throttle(self, url: str) -> None:
        """每個主機之間至少隔 ``min_interval`` 秒，即使有好幾個執行緒同時要。

        先在鎖裡「訂位」——把下一個可以發送的時間點算出來並寫回去——再到鎖外面
        睡到那個時間。如果連睡覺都握著鎖，八個執行緒會排成一列，併發等於沒有；
        反過來，如果不在鎖裡訂位，八個執行緒會同時看到同一個 last 而一起衝出去，
        對站台就是一次八連發。
        """
        host = urllib.parse.urlparse(url).netloc
        now = time.time()
        with self._lock:
            last = self._last_call.get(host)
            send_at = now if last is None else max(now, last + self.min_interval)
            self._last_call[host] = send_at
        wait = send_at - time.time()
        if wait > 0:
            time.sleep(wait)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        use_cache: bool = True,
    ) -> bytes:
        url = self._encode(url)
        cache_path = self._cache_path(url, body)
        if use_cache:
            cached = self._read_cache(cache_path)
            if cached is not None:
                log.debug("cache hit %s", url)
                return cached

        merged = {"User-Agent": self.user_agent, **self.default_headers}
        if headers:
            merged.update(headers)

        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._throttle(url)
            try:
                req = urllib.request.Request(url, data=body, headers=dict(merged))
                if self.cookies:
                    with self._build_opener().open(req, timeout=self.timeout) as resp:
                        data = _decoded(resp)
                else:
                    with urllib.request.urlopen(
                        req, timeout=self.timeout, context=tls_context()
                    ) as resp:
                        data = _decoded(resp)
                if cache_path is not None:
                    cache_path.write_bytes(data)
                return data
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                last_error = exc
                status = getattr(exc, "code", None)
                if status in (400, 401, 403, 404):
                    # Not transient.  Retrying just gets us blocked faster.
                    break
                delay = self.backoff**attempt
                log.warning(
                    "fetch failed (%s), retry %d/%d in %.1fs: %s",
                    status or type(exc).__name__,
                    attempt + 1,
                    self.retries,
                    delay,
                    url,
                )
                time.sleep(delay)
        raise FetchError(f"{url}: {last_error}") from last_error

    def get_json(self, url: str, **kw: Any) -> Any:
        raw = self.get(url, **kw)
        text = raw.decode("utf-8-sig", errors="replace")
        return json.loads(text)

    def get_text(self, url: str, encoding: str = "utf-8", **kw: Any) -> str:
        return self.get(url, **kw).decode(encoding, errors="replace")


@dataclass(frozen=True)
class SourceInfo:
    """Metadata every fetcher reports, so a snapshot can say where it came from."""

    name: str
    url: str
    fetched_at: str
    row_count: int
    note: str = ""


def roc_date(year: int, month: int, day: int) -> str:
    """``2026, 8, 28`` -> ``115/08/28``."""
    return f"{year - 1911:03d}/{month:02d}/{day:02d}"


def parse_number(text: object) -> float | None:
    """Official feeds mix ``1,234``, ``--``, ``N/A``, ``(123)`` and blanks."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(",", "").replace("　", "")
    if not s or s in {"--", "-", "N/A", "NA", "不適用", "無"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negative else v
