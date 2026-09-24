import pytest

from fakes.clock import FakeClock
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.poll import PollLimits, poll


def counting(done_at: int | None):
    """A pass that returns its number, complete once it reaches ``done_at``."""
    return (lambda number: number), (lambda result: done_at is not None and result >= done_at)


def test_stops_as_soon_as_a_pass_is_complete():
    clock = FakeClock()
    run, done = counting(3)
    outcome = poll(run, done, PollLimits(interval=60), clock=clock, sleep=clock.sleep)
    assert (outcome.reason, outcome.passes, outcome.result) == ("complete", 3, 3)
    assert outcome.complete
    assert clock.sleeps == [60, 60]


def test_max_passes_stops_without_a_final_sleep():
    clock = FakeClock()
    run, done = counting(None)
    outcome = poll(run, done, PollLimits(interval=60, max_passes=4), clock=clock, sleep=clock.sleep)
    assert (outcome.reason, outcome.passes) == ("max-passes", 4)
    assert not outcome.complete
    assert clock.sleeps == [60, 60, 60]


def test_the_last_wait_is_cut_short_so_a_final_pass_runs_at_the_deadline():
    clock = FakeClock()
    run, done = counting(None)
    outcome = poll(run, done, PollLimits(interval=300, timeout=700), clock=clock, sleep=clock.sleep)
    assert outcome.reason == "timeout"
    assert clock.sleeps == [300, 300, 100]
    assert outcome.passes == 4
    assert outcome.elapsed == 700


def test_hooks_see_each_pass_and_each_wait():
    clock = FakeClock()
    run, done = counting(2)
    passes: list[tuple[int, int]] = []
    waits: list[float] = []
    poll(
        run,
        done,
        PollLimits(interval=5),
        clock=clock,
        sleep=clock.sleep,
        on_pass=lambda number, result: passes.append((number, result)),
        on_wait=waits.append,
    )
    assert passes == [(1, 1), (2, 2)]
    assert waits == [5]


def test_an_exception_from_a_pass_ends_the_poll():
    def run(number: int) -> int:
        raise RuntimeError("token rejected")

    clock = FakeClock()
    with pytest.raises(RuntimeError, match="token rejected"):
        poll(run, lambda result: False, PollLimits(interval=5), clock=clock, sleep=clock.sleep)


@pytest.mark.parametrize(
    "limits",
    [{"interval": 0}, {"interval": 5, "timeout": 0}, {"interval": 5, "max_passes": 0}],
)
def test_limits_are_validated(limits):
    with pytest.raises(InputError):
        PollLimits(**limits)
