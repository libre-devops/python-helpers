"""Microsoft Planner: plans, buckets and tasks, and creating or updating a task, as the
signed-in user.

Through Graph's ``planner`` API, which covers basic plans (not premium ones). Reading takes
Tasks.Read or Group.Read.All; creating or updating a task, Tasks.ReadWrite or
Group.ReadWrite.All.
Depends only on ``core`` and the shared Microsoft layer. Public API::

    from libre_devops_helpers.microsoft.planner import PlannerClient, keyed

    with PlannerClient.create(tokens, tenant_id) as planner:
        plan = planner.plan("Operations")
        done = keyed(planner.tasks(plan.id), re.compile(r"^MC[0-9]+"))
"""

from libre_devops_helpers.microsoft.planner.client import TITLE_LIMIT, PlannerClient, keyed
from libre_devops_helpers.microsoft.planner.models import Bucket, Plan, Task
from libre_devops_helpers.microsoft.planner.permissions import REQUIREMENTS

__all__ = ["REQUIREMENTS", "TITLE_LIMIT", "Bucket", "Plan", "PlannerClient", "Task", "keyed"]
