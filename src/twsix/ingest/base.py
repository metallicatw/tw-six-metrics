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
import json
import logging
import ssl
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
    _last_call: dict[str, float] = field(default_factory=dict, init=False)

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

    def _throttle(self, url: str) -> None:
        host = urllib.parse.urlparse(url).netloc
        last = self._last_call.get(host)
        if last is not None:
            wait = self.min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_call[host] = time.time()

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        use_cache: bool = True,
    ) -> bytes:
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
                with urllib.request.urlopen(
                    req, timeout=self.timeout, context=tls_context()
                ) as resp:
                    data = resp.read()
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
