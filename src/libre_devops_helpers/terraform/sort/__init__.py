"""A module's variables and outputs in name order: the blocks of one kind moved into order
where they stand, the comments just above each moving with it, and all else left as it was.
Depends only on ``core`` and the terraform layer. Public API::

    from libre_devops_helpers.terraform.sort import sort_file, sort_text, targets

    text, count, in_order = sort_text(source, "variable")
    for path, kinds in targets([Path(".")], KINDS, recursive=True):
        print(sort_file(path, kinds, write=False))
"""

from libre_devops_helpers.terraform.sort.blocks import (
    FILES,
    KINDS,
    Sorting,
    order_key,
    sort_file,
    sort_text,
    targets,
)

# Local files only: nothing to sign in to.
REQUIREMENTS: tuple[str, ...] = ()

__all__ = [
    "FILES",
    "KINDS",
    "REQUIREMENTS",
    "Sorting",
    "order_key",
    "sort_file",
    "sort_text",
    "targets",
]
