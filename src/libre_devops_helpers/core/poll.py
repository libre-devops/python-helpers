"""Run a check repeatedly until it is complete or a limit is reached.

The clock and the sleep are injected, so a poll of hours runs in microseconds in tests.
The poller never sleeps past the timeout: the last wait is cut short so one final pass
runs at the deadline.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from libre_devops_helpers.core.errors import InputError

T = TypeVar("T")

Reason = Literal["complete", "timeout", "max-passes"]


@dataclass(frozen=True)
class PollLimits:
    """How often to check, and when to give up. ``None`` means no limit of that kind."""

    interval: float
    timeout: float | None = None
    max_passes: int | None = None

    def __post_init__(self) -> None:
        if self.interval <= 0:
            raise InputError("the poll interval must be more than zero seconds")
        if self.timeout is not None and self.timeout <= 0:
            raise InputError("the poll timeout must be more than zero seconds")
        if self.max_passes is not None and self.max_passes < 1:
            raise InputError("the poll needs at least one pass")


@dataclass(frozen=True)
class PollOutcome(Generic[T]):
    """What the poll ended with: the last pass's result and why it stopped."""

    result: T
    passes: int
    elapsed: float
    reason: Reason

    @property
    def complete(self) -> bool:
        """Whether polling stopped because the condition was met, not at a limit."""
        return self.reason == "complete"


def poll(
    run_pass: Callable[[int], T],
    is_complete: Callable[[T], bool],
    limits: PollLimits,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_pass: Callable[[int, T], None] | None = None,
    on_wait: Callable[[float], None] | None = None,
) -> PollOutcome[T]:
    """Call ``run_pass(n)`` for n = 1, 2, ... until ``is_complete`` or a limit stops it.

    ``on_pass`` sees each result; ``on_wait`` is told how long the next wait is.
    Exceptions from ``run_pass`` propagate: the caller decides which ones a pass may
    absorb (a throttled request) and which end the poll (a rejected token).
    """
    started = clock()
    passes = 0
    while True:
        passes += 1
        result = run_pass(passes)
        if on_pass is not None:
            on_pass(passes, result)
        elapsed = clock() - started
        if is_complete(result):
            return PollOutcome(result, passes, elapsed, "complete")
        if limits.max_passes is not None and passes >= limits.max_passes:
            return PollOutcome(result, passes, elapsed, "max-passes")
        if limits.timeout is not None and elapsed >= limits.timeout:
            return PollOutcome(result, passes, elapsed, "timeout")
        wait = limits.interval
        if limits.timeout is not None:
            wait = min(wait, limits.timeout - elapsed)
        if on_wait is not None:
            on_wait(wait)
        sleep(wait)
