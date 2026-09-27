"""A made-up Terraform module on disk, and stand-ins for the tools run on it: terraform fmt
and terraform-docs, found on a fake PATH only when a test says they are there."""

import subprocess
from pathlib import Path

VARIABLES = """\
# The region, as Azure names it.
variable "location" {
  type        = string
  description = <<-EOT
  Where it goes.
}
  EOT
}

variable "name" {
  type = string
}

variable "Environment" {
  type    = string
  default = "${upper("dev")}"
}
"""

OUTPUTS = """\
output "id" {
  value = azurerm_resource_group.this.id
}

output "fqdn" {
  value = { for name, host in var.hosts : name => "${host}.example.test" }
}
"""

HEADER = "# A module\n\nWhat it makes.\n"
README = "# Old title\n\n<!-- BEGIN_TF_DOCS -->\nold tables\n<!-- END_TF_DOCS -->\n"
GENERATED = "<!-- BEGIN_TF_DOCS -->\n## Inputs\n<!-- END_TF_DOCS -->\n"


def write_module(folder: Path) -> Path:
    """A module in ``folder``, its variables and outputs out of order, with an example."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "variables.tf").write_text(VARIABLES, encoding="utf-8")
    (folder / "outputs.tf").write_text(OUTPUTS, encoding="utf-8")
    (folder / "HEADER.md").write_text(HEADER, encoding="utf-8")
    (folder / "README.md").write_text(README, encoding="utf-8")
    example = folder / "examples" / "minimal"
    example.mkdir(parents=True)
    (example / "variables.tf").write_text('variable "b" {}\nvariable "a" {}\n', encoding="utf-8")
    (example / "HEADER.md").write_text("# The minimal example\n", encoding="utf-8")
    hidden = folder / ".terraform" / "modules" / "other"
    hidden.mkdir(parents=True)
    (hidden / "variables.tf").write_text('variable "z" {}\nvariable "y" {}\n', encoding="utf-8")
    return folder


class FakeTools:
    """``find`` stands in for shutil.which and ``run`` for subprocess.run: terraform fmt
    formats nothing, and terraform-docs writes GENERATED between a README's markers, or
    with --output-check fails as the real one does when the README differs."""

    def __init__(self, *present: str) -> None:
        self.present = set(present)
        self.calls: list[list[str]] = []
        self.formatted: list[str] = []

    def find(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.present else None

    def run(self, cmd: list[str], **_) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        tool, *args = cmd
        if tool.endswith("terraform-docs"):
            return self._docs(cmd, args)
        return subprocess.CompletedProcess(cmd, 0, "".join(f"{f}\n" for f in self.formatted), "")

    def _docs(self, cmd: list[str], args: list[str]) -> subprocess.CompletedProcess[str]:
        folder = Path(args[-1])
        name = args[args.index("--output-file") + 1] if "--output-file" in args else "README.md"
        readme = folder / name
        text = readme.read_text(encoding="utf-8")
        start = text.index("<!-- BEGIN_TF_DOCS -->")
        wanted = text[:start] + GENERATED
        if "--output-check" in args:
            if text != wanted:
                return subprocess.CompletedProcess(cmd, 1, "", f"Error: {readme} is out of date\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        readme.write_text(wanted, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, f"{readme} updated successfully\n", "")
