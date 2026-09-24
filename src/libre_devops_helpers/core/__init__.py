"""Vendor-neutral building blocks. Depends on nothing else in the package.

Everything more than one vendor or feature needs lives here: errors, the config file,
the token cache, the HTTP client, the command runner, polling, input parsing, tabular
results and logging. Vendor layers (``microsoft``, ...) build on core; nothing here knows
any vendor.

Public API::

    from libre_devops_helpers.core import ApiClient, PollLimits, poll, read_names
"""

from libre_devops_helpers.core.auth import (
    AccessToken,
    CachingTokenProvider,
    TokenProvider,
    token_source,
)
from libre_devops_helpers.core.config import (
    CONFIG_HEADER,
    ConfigFile,
    default_config_path,
    load_config_file,
    parse_config_file,
)
from libre_devops_helpers.core.errors import (
    AmbiguousError,
    ApiError,
    AuthError,
    CommandError,
    ConfigError,
    ConfigNotFoundError,
    InputError,
    LdoError,
    NotFoundError,
    TokenError,
)
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.inputs import read_names
from libre_devops_helpers.core.log import LOG_FORMATS, configure_logging
from libre_devops_helpers.core.poll import PollLimits, PollOutcome, poll
from libre_devops_helpers.core.process import CommandRunner
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import (
    candidate_names,
    format_duration,
    is_guid,
    odata_datetime,
    odata_string,
    parse_datetime,
    parse_duration,
    short_name,
    split_names,
)

__all__ = [
    "CONFIG_HEADER",
    "LOG_FORMATS",
    "AccessToken",
    "AmbiguousError",
    "ApiClient",
    "ApiError",
    "AuthError",
    "CachingTokenProvider",
    "CommandError",
    "CommandRunner",
    "ConfigError",
    "ConfigFile",
    "ConfigNotFoundError",
    "InputError",
    "LdoError",
    "NotFoundError",
    "PollLimits",
    "PollOutcome",
    "QueryResult",
    "TokenError",
    "TokenProvider",
    "candidate_names",
    "configure_logging",
    "default_config_path",
    "format_duration",
    "is_guid",
    "load_config_file",
    "odata_datetime",
    "odata_string",
    "parse_config_file",
    "parse_datetime",
    "parse_duration",
    "poll",
    "read_names",
    "short_name",
    "split_names",
    "token_source",
]
