"""Client side pacing for the protocols.io request quota."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """
    Sliding window limiter that blocks until a request slot is free.

    One instance can be shared between threads and clients that use the same account.

    Args:
        max_requests: Requests allowed inside one window.
        period: Window length in seconds.
        clock: Monotonic time source, replaceable in tests.
        sleep: Sleep function, replaceable in tests.
    """

    def __init__(
        self,
        max_requests: int = 90,
        period: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """Validate the window and start with no recorded requests."""
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")
        self.max_requests = max_requests
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """
        Wait for a free slot and record a request.

        Returns:
            Seconds spent waiting.
        """
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                while self._sent and now - self._sent[0] >= self.period:
                    self._sent.popleft()
                if len(self._sent) < self.max_requests:
                    self._sent.append(now)
                    return waited
                delay = self.period - (now - self._sent[0])
            self._sleep(delay)
            waited += delay
