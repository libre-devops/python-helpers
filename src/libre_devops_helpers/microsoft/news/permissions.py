"""What Message Center needs from a Graph token. The Azure CLI's token does not have it."""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (Requirement("Message Center posts", "graph", (("ServiceMessage.Read.All",),)),)
