from fakes.planner import task
from libre_devops_helpers.microsoft.planner import Bucket, Plan, Task


def test_the_records_read_their_fields_and_tolerate_missing_ones():
    done = Task.from_json(task("T1AAAAAAAAAAAAAAAAAAAAAAAAAA", "x", percent=100))
    assert done.done
    assert done.completed is not None
    bare = Task.from_json({"id": "t"})
    assert (bare.percent_complete, bare.done, bare.due) == (0, False, None)
    assert Plan.from_json({"id": "p", "title": "Ops"}).created is None
    assert Bucket.from_json({"id": "b", "name": "To do", "planId": "p"}).name == "To do"
