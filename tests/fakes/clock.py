"""A clock that only moves when something sleeps, for polling tests."""


class FakeClock:
    """A monotonic clock that only moves when ``sleep`` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
