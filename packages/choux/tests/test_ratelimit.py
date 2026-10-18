import pytest
from choux.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        """Start the clock at zero with no recorded sleeps."""
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_allows_requests_up_to_the_limit_without_waiting():
    """Allows requests up to the limit without waiting."""
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock, sleep=clock.sleep)
    assert [limiter.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert clock.sleeps == []


def test_waits_until_the_oldest_request_leaves_the_window():
    """Waits until the oldest request leaves the window."""
    clock = FakeClock()
    limiter = RateLimiter(2, 60, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    clock.now = 10.0
    limiter.acquire()
    clock.now = 20.0
    assert limiter.acquire() == pytest.approx(40.0)
    assert clock.now == pytest.approx(60.0)


def test_slots_free_up_after_the_period():
    """Slots free up after the period."""
    clock = FakeClock()
    limiter = RateLimiter(1, 5, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    clock.now = 5.0
    assert limiter.acquire() == 0.0


@pytest.mark.parametrize("max_requests, period", [(0, 60), (1, 0)])
def test_rejects_invalid_settings(max_requests, period):
    """Rejects invalid settings."""
    with pytest.raises(ValueError):
        RateLimiter(max_requests, period)
