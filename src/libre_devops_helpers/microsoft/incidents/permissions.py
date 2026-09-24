"""What the incidents feature needs from a Graph token.

The Azure CLI's Graph token never carries these, so incidents need an interactive or
device-code profile whose app registration has been granted them.
"""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "xdr incidents",
        "graph",
        (("SecurityIncident.Read.All", "SecurityIncident.ReadWrite.All"),),
    ),
)
