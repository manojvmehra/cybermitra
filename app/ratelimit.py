"""In-memory rate limits: per-IP sessions/hour and a global daily session cap."""

import time
from collections import defaultdict, deque

from app.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._ip_sessions: dict[str, deque[float]] = defaultdict(deque)
        self._day = time.strftime("%Y-%m-%d")
        self._day_count = 0

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def allow_session(self, ip: str, now: float | None = None) -> tuple[bool, str]:
        s = get_settings()
        now = now or time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if today != self._day:
            self._day, self._day_count = today, 0
        if self._day_count >= s.DAILY_SESSION_CAP:
            return False, "daily_cap"
        q = self._ip_sessions[ip]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= s.PER_IP_SESSIONS_PER_HOUR:
            return False, "ip_hourly"
        q.append(now)
        self._day_count += 1
        return True, ""


limiter = RateLimiter()
