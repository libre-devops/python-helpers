"""What Planner needs from a Graph token: the Azure CLI's Group.ReadWrite.All reads group
plans, and a personal plan's tasks are made with Tasks.ReadWrite."""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "planner plans and tasks",
        "graph",
        (("Tasks.Read", "Tasks.ReadWrite", "Group.Read.All", "Group.ReadWrite.All"),),
    ),
    Requirement("planner tasks created", "graph", (("Tasks.ReadWrite", "Group.ReadWrite.All"),)),
)
