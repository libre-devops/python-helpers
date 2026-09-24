"""Who this tool is, in one place.

Every name the running tool shows or reads comes from here: its command, the prefix of
its environment variables, its config directory, and how it introduces itself. To ship it
under another name, run ``just rebrand``. That rewrites these values together with the
names no module can hold, such as the Python package name in every import; see
``scripts/rebrand.py`` and ``brand.toml``.
"""

DISPLAY_NAME = "Libre DevOps Helpers"
COMMAND = "ldo"
# The name to install, from PyPI or a git URL.
DISTRIBUTION = "libre-devops-helpers"
ENV_PREFIX = "LDO"
CONFIG_DIR = "ldo"

# The welcome banner, drawn after the Libre DevOps unicorn. Plain ASCII, so it renders in
# any terminal and font. 'just rebrand --banner FILE' swaps it; --no-banner empties it.
# banner-start
BANNER = r"""
     `.
      `.`.
        `. `.           |`.
          `.  `.        |  `.
           `.   `.      |  /
             `.    `.   |   `.
              `.    .'        `.
                `..'        \    `.
               .'             \    `.
             .'   __           \     `.
            .'     /           /       `.
          .'                  /          `.
        .'                    /            `.
      .'  -                .-                `.
      `.              .--''
        `.       .--''    |
          `._.-''         |
                           |

 _    ___ ___ ___ ___   ___  _____   _____  ___  ___
| |  |_ _| _ ) _ \ __| |   \| __\ \ / / _ \| _ \/ __|
| |__ | || _ \   / _|  | |) | _| \ V / (_) |  _/\__ \
|____|___|___/_|_\___| |___/|___| \_/ \___/|_|  |___/
"""
# banner-end


def env_var(name: str) -> str:
    """The environment variable ``name`` under this tool's prefix, e.g. ``LDO_CONFIG``."""
    return f"{ENV_PREFIX}_{name}"


def command(text: str) -> str:
    """A command line to suggest to the person, e.g. ``'ldo config init'``, quoted."""
    return f"'{COMMAND} {text}'"


CONFIG_ENV = env_var("CONFIG")
PROFILE_ENV = env_var("PROFILE")
LOG_FORMAT_ENV = env_var("LOG_FORMAT")
LOG_LEVEL_ENV = env_var("LOG_LEVEL")
