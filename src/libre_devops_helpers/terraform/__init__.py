"""Terraform (and OpenTofu) modules, as files: their configuration read as far as sorting it
needs (``hcl``), and the command line tools run on them (``tools``): terraform or tofu to
format a module, and terraform-docs for its README. Nothing here signs in anywhere, plans or
applies. Depends only on ``core``."""

from libre_devops_helpers.terraform.hcl import Piece, split
from libre_devops_helpers.terraform.tools import (
    FORMATTERS,
    TERRAFORM_DOCS_HINT,
    format_code,
    formatter,
    terraform_docs,
)

__all__ = [
    "FORMATTERS",
    "TERRAFORM_DOCS_HINT",
    "Piece",
    "format_code",
    "formatter",
    "split",
    "terraform_docs",
]
