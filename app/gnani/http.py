"""Shared Gnani HTTP layer: one AsyncClient, global semaphore, retry with backoff + jitter, error parsing."""

import asyncio
import logging
import random
import time
from collections import defaultdict
from typing import Any, Literal

import httpx

from app.config import get_settings

logger = logging.getLogger("gnani.http")

RETRY_STATUS = {429, 500, 503, 504}
MAX_ATTEMPTS = 4


class GnaniError(Exception):
    def __init__(self, status: int, code: str, message: str, request_id: str | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id


class Metrics:
    def __init__(self) -> None:
        self.calls_by_endpoint: dict[str, int] = defaultdict(int)
        self.errors_by_code: dict[str, int] = defaultdict(int)
        self.cache_hits = 0
        self.cache_misses = 0
        self.latency_ms: list[int] = []

    def snapshot(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms)

        def pct(p: float) -> int | None:
            if not lat:
                return None
            return lat[min(len(lat) - 1, int(round(p * (len(lat) - 1))))]

        total = self.cache_hits + self.cache_misses
        return {
            "calls_by_endpoint": dict(self.calls_by_endpoint),
            "errors_by_code": dict(self.errors_by_code),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.cache_hits / total, 3) if total else None,
            "latency_p50_ms": pct(0.5),
            "latency_p95_ms": pct(0.95),
            "n_latency": len(lat),
        }


metrics = Metrics()

_client: httpx.AsyncClient | None = None
_sem: asyncio.Semaphore | None = None
_sem_loop: asyncio.AbstractEventLoop | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        s = get_settings()
        _client = httpx.AsyncClient(base_url=s.GNANI_BASE_URL, timeout=s.GNANI_TIMEOUT_S)
    return _client


def _semaphore() -> asyncio.Semaphore:
    # Re-create per event loop (pytest runs each test in a fresh loop).
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(get_settings().GNANI_MAX_CONCURRENCY)
        _sem_loop = loop
    return _sem


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def parse_error(resp: httpx.Response) -> tuple[str, str]:
    """Normalise the Gnani error shapes into (code, message)."""
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP_{resp.status_code}", resp.text[:200]
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):  # gateway: auth / credit / rate limit
            return str(detail.get("error_code") or f"HTTP_{resp.status_code}"), str(detail.get("message", ""))
        if isinstance(detail, list):  # 422 validation
            msgs = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
            return "VALIDATION_ERROR", msgs
        err = body.get("error")
        if isinstance(err, dict):  # STT endpoint envelope
            return str(err.get("type") or f"HTTP_{resp.status_code}"), str(err.get("message", ""))
        if "code" in body:  # v3.0 504 UPSTREAM_TIMEOUT
            return str(body["code"]), str(body.get("message") or body.get("error") or "")
        if body.get("success") is False and "message" in body:  # TTS flat shape
            return f"HTTP_{resp.status_code}", str(body["message"])
    return f"HTTP_{resp.status_code}", str(body)[:200]


def _backoff(attempt: int) -> float:
    return 0.5 * 2**attempt + random.uniform(0, 0.3)


async def call(
    method: str,
    path: str,
    *,
    files: Any = None,
    data: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    expect: Literal["json", "bytes"] = "json",
    request_id: str | None = None,
    endpoint: str | None = None,
) -> tuple[Any, int]:
    """Returns (parsed body or bytes, latency_ms). Raises GnaniError."""
    s = get_settings()
    headers = {"X-API-Key-ID": s.GNANI_API_KEY}
    if request_id:
        headers["X-API-Request-ID"] = request_id
    name = endpoint or path
    last_err: GnaniError | None = None
    for attempt in range(MAX_ATTEMPTS):
        async with _semaphore():
            t0 = time.perf_counter()
            try:
                resp = await get_client().request(method, path, files=files, data=data, json=json, headers=headers)
            except httpx.TransportError as e:
                last_err = GnaniError(0, "TRANSPORT_ERROR", type(e).__name__, request_id)
                resp = None
            latency = int((time.perf_counter() - t0) * 1000)
        metrics.calls_by_endpoint[name] += 1
        if resp is not None:
            if resp.status_code == 200:
                metrics.latency_ms.append(latency)
                return (resp.json() if expect == "json" else resp.content), latency
            code, msg = parse_error(resp)
            last_err = GnaniError(resp.status_code, code, msg, request_id)
            metrics.errors_by_code[code] += 1
            if resp.status_code not in RETRY_STATUS:
                raise last_err
        logger.warning("gnani retry", extra={"extra_fields": {"endpoint": name, "attempt": attempt + 1,
                                                                  "code": last_err.code if last_err else ""}})
        if attempt < MAX_ATTEMPTS - 1:
            await asyncio.sleep(_backoff(attempt))
    assert last_err is not None
    raise last_err
