"""Every network call in the project goes through `request()`.

Reliability lives here, in one place:
  * a timeout on every call (a hung server can't freeze the run)
  * retries with exponential backoff + jitter for temporary failures
  * honours `Retry-After`, but refuses to sleep for long: if a rate limit
    resets in 10 minutes we fail fast and let the run continue without
    that source, because a fast partial report beats a slow complete one.
"""

import logging
import random
import time

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "ai-pulse/0.1 (personal AI-engineering learning project; RSS reader)"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_WAIT_SECONDS = 20


class RateLimited(Exception):
    """The server told us to come back later than we are willing to wait."""


class HTTPError(Exception):
    """A non-retryable 4xx. Keeps the status and a bit of the body for debugging."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {' '.join(body.split())[:200]}")
        self.status = status


def _seconds_to_wait(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        if "retry-after" in response.headers:
            try:
                return float(response.headers["retry-after"])
            except ValueError:
                pass
        # GitHub style: remaining=0 plus a unix timestamp for the reset.
        if response.headers.get("x-ratelimit-remaining") == "0":
            reset = float(response.headers.get("x-ratelimit-reset", 0))
            return max(reset - time.time(), 1)
    return 2**attempt + random.uniform(0, 1)   # 1s, 2s, 4s ... plus jitter


def _is_rate_limited(response: httpx.Response) -> bool:
    # GitHub signals rate limits with 403 rather than 429.
    return response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"


def request(method: str, url: str, *, timeout: float = 15, retries: int = 2,
            headers: dict | None = None, **kwargs) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(retries + 1):
        response = None
        try:
            response = httpx.request(method, url, headers=headers, timeout=timeout,
                                     follow_redirects=True, **kwargs)
            temporary = response.status_code in RETRY_STATUSES or _is_rate_limited(response)
            if not temporary:
                if response.status_code >= 400:   # 4xx = our mistake, retrying won't help
                    raise HTTPError(response.status_code, response.text)
                return response
            problem = f"HTTP {response.status_code}"
        except httpx.TransportError as exc:   # timeouts, DNS, connection resets
            problem = type(exc).__name__

        wait = _seconds_to_wait(response, attempt)
        if wait > MAX_WAIT_SECONDS:
            raise RateLimited(f"{problem}: rate limited for ~{wait / 60:.0f} more min")
        if attempt == retries:
            raise RuntimeError(f"{problem} after {retries + 1} attempts")
        log.debug("%s %s -> %s, retrying in %.1fs", method, url, problem, wait)
        time.sleep(wait)
    raise AssertionError("unreachable")


def get_json(url: str, **kwargs):
    return request("GET", url, **kwargs).json()


def get_text(url: str, **kwargs) -> str:
    return request("GET", url, **kwargs).text
