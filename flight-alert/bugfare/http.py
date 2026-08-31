"""標準ライブラリだけの薄い HTTP クライアント。

外部依存を増やさないため requests は使わない。
GitHub Actions の素の python でそのまま動く。
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional

log = logging.getLogger(__name__)

USER_AGENT = "bugfare-alert/1.0 (+https://github.com/)"


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


def request_json(
    url: str,
    *,
    method: str = "GET",
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    json_body: Any = None,
    form_body: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
    retries: int = 3,
) -> Any:
    """JSON を返す API を叩く。5xx と 429 は指数バックオフで再試行する。"""

    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)

    body: Optional[bytes] = None
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        all_headers["Content-Type"] = "application/json"
    elif form_body is not None:
        body = urllib.parse.urlencode(form_body).encode("utf-8")
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    if headers:
        all_headers.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                last_error = HttpError(exc.code, detail, url)
                _sleep_backoff(attempt, exc.headers.get("Retry-After"))
                continue
            raise HttpError(exc.code, detail, url) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                _sleep_backoff(attempt, None)
                continue
            raise

    assert last_error is not None
    raise last_error


def _sleep_backoff(attempt: int, retry_after: Optional[str]) -> None:
    if retry_after:
        try:
            time.sleep(min(float(retry_after), 60.0))
            return
        except ValueError:
            pass
    delay = min(2 ** attempt, 16) + random.uniform(0, 0.5)
    log.debug("retrying in %.1fs", delay)
    time.sleep(delay)
