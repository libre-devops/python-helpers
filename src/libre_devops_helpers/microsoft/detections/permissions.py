"""What the detections feature needs from a Graph token.

The Azure CLI's Graph token carries it only when an admin has consented it for the Azure
CLI's app; otherwise use an interactive or device-code profile whose app has it.
"""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "xdr detections",
        "graph",
        (("CustomDetection.Read.All", "CustomDetection.ReadWrite.All"),),
    ),
)
