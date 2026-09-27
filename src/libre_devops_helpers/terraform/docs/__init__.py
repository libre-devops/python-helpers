"""A module's README: its hand-written top (``HEADER.md``) above the section terraform-docs
writes between its markers, and terraform-docs run to write that section. terraform-docs
is not part of this package: it is found on PATH. Depends only on ``core`` and the
terraform layer. Public API::

    from libre_devops_helpers.terraform.docs import document
    from libre_devops_helpers.terraform.tools import terraform_docs

    print(document(Path("."), tool=terraform_docs(), check=False).state)
"""

from libre_devops_helpers.terraform.docs.readme import (
    BEGIN,
    END,
    HEADER,
    README,
    Readme,
    document,
    folders,
    with_header,
)

# Local files only: nothing to sign in to.
REQUIREMENTS: tuple[str, ...] = ()

__all__ = [
    "BEGIN",
    "END",
    "HEADER",
    "README",
    "REQUIREMENTS",
    "Readme",
    "document",
    "folders",
    "with_header",
]
