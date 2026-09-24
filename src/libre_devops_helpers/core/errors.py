"""Exception types raised by this package.

Library code raises these and never exits the process. Only the ``cli`` subpackage
turns them into messages and exit codes, so importing code keeps control of its flow.
"""

from __future__ import annotations


class LdoError(Exception):
    """Base class for every error this package raises.

    ``hint`` is an optional next step for the person running the command.
    """

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ConfigError(LdoError):
    """The config file is invalid, or a profile cannot be used."""


class ConfigNotFoundError(ConfigError):
    """The config file does not exist."""


class InputError(LdoError):
    """A list of names, a file of names, or a duration could not be read."""


class CommandError(LdoError):
    """An external command line tool is missing, or a command it ran failed."""


class AuthError(LdoError):
    """A credential could not produce an access token."""


class TokenError(LdoError):
    """A token could not be decoded."""


class NotFoundError(LdoError):
    """A named object does not exist."""


class AmbiguousError(LdoError):
    """A name matched more than one object where exactly one was needed."""


class ApiError(LdoError):
    """An HTTP API call failed."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.status = status
        self.code = code
        self.request_id = request_id
