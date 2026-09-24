"""Azure Automation through ARM: accounts, the jobs their runbooks ran, and the jobs' logs.

A job is one run of a runbook. It writes streams, as the portal's job page shows them:
output, warnings, errors, and verbose, progress and debug records when the runbook turns
those on. Jobs are kept for 30 days. Everything here reads: nothing starts, stops or
changes a runbook.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Self
from urllib.parse import quote

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import AmbiguousError, ApiError, InputError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.util import is_guid
from libre_devops_helpers.microsoft.automation.models import AutomationAccount, Job, JobStream
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile

API_VERSION = "2023-11-01"
PROVIDER = "Microsoft.Automation/automationAccounts"
# What each part of a path may hold, so nothing typed can reach another resource.
_ACCOUNT = re.compile(r"^[A-Za-z0-9-]{1,50}$")
_GROUP = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")
_JOB = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_STREAM = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_ACCOUNT_ID = re.compile(
    r"^/subscriptions/(?P<subscription>[^/]+)/resourceGroups/(?P<group>[^/]+)"
    r"/providers/Microsoft\.Automation/automationAccounts/(?P<name>[^/]+)$",
    re.IGNORECASE,
)


class AutomationClient:
    """Reads Automation accounts and their jobs through ARM. Close it when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        arm_url: str = PUBLIC.arm_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        api = ApiClient(
            arm_url,
            token_source(tokens, arm_url.rstrip("/") + "/", tenant_id),
            name="Azure Resource Manager",
            verify=verify,
            session=session,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        return cls.create(
            tokens, profile.tenant_id, arm_url=profile.cloud.arm_url, verify=verify, session=session
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Accounts -----------------------------------------------------------------------

    def accounts(self, subscriptions: Iterable[str]) -> list[AutomationAccount]:
        """Every Automation account in the subscriptions, by name."""
        found: list[AutomationAccount] = []
        for subscription in subscriptions:
            path = f"/subscriptions/{_guid(subscription)}/providers/{PROVIDER}"
            found.extend(
                AutomationAccount.from_json(item)
                for item in self.api.get_all(
                    path, params={"api-version": API_VERSION}, next_link="nextLink"
                )
            )
        return sorted(found, key=lambda account: (account.name.casefold(), account.id))

    def find_account(
        self, ref: str, subscriptions: Sequence[str], *, resource_group: str | None = None
    ) -> AutomationAccount:
        """One account, by its resource id, or by name within ``subscriptions``.

        A name several accounts share is refused, with their ids to choose from.
        """
        ref = ref.strip()
        by_id = _ACCOUNT_ID.match(ref)
        if by_id:
            path = (
                f"/subscriptions/{_guid(by_id['subscription'])}/resourceGroups/"
                f"{_group(by_id['group'])}/providers/{PROVIDER}/{_account(by_id['name'])}"
            )
            try:
                return AutomationAccount.from_json(
                    self.api.get(path, params={"api-version": API_VERSION})
                )
            except ApiError as exc:
                if exc.status == 404:
                    raise NotFoundError(f"no Automation account {ref}") from None
                raise
        name = _account(ref)
        matches = [
            account
            for account in self.accounts(subscriptions)
            if account.name.casefold() == name.casefold()
            and (
                resource_group is None
                or account.resource_group.casefold() == resource_group.casefold()
            )
        ]
        if not matches:
            where = f" in resource group {resource_group}" if resource_group else ""
            raise NotFoundError(
                f"no Automation account is named {name!r}{where}",
                hint="check the subscription (-s), or list them: 'azure automation accounts'",
            )
        if len(matches) > 1:
            raise AmbiguousError(
                f"{len(matches)} Automation accounts are named {name!r}",
                hint="pass -g for its resource group, or its resource id: "
                + ", ".join(account.id for account in matches),
            )
        return matches[0]

    # Jobs ---------------------------------------------------------------------------

    def jobs(self, account: AutomationAccount) -> list[Job]:
        """Every job the account keeps (30 days of them), newest first."""
        found = [
            Job.from_json(item)
            for item in self.api.get_all(
                f"{_account_path(account)}/jobs",
                params={"api-version": API_VERSION},
                next_link="nextLink",
            )
        ]
        return sorted(found, key=_newest_first)

    def job(self, account: AutomationAccount, job_id: str) -> Job:
        """One job, with what only a single job's GET gives: who started it, and why it failed."""
        try:
            data = self.api.get(
                f"{_account_path(account)}/jobs/{_job(job_id)}", params={"api-version": API_VERSION}
            )
        except ApiError as exc:
            if exc.status == 404:
                raise NotFoundError(f"no job {job_id} in {account.name}") from None
            raise
        return Job.from_json(data)

    def streams(self, account: AutomationAccount, job_id: str) -> list[JobStream]:
        """Every record the job wrote, oldest first, each with its summary."""
        found = [
            JobStream.from_json(item)
            for item in self.api.get_all(
                f"{_account_path(account)}/jobs/{_job(job_id)}/streams",
                params={"api-version": API_VERSION},
                next_link="nextLink",
            )
        ]
        return sorted(found, key=lambda stream: (stream.time is None, stream.time))

    def stream(self, account: AutomationAccount, job_id: str, stream_id: str) -> JobStream:
        """One record in full: a listing carries only its summary."""
        if not _STREAM.match(stream_id):
            raise InputError(f"{stream_id!r} is not a job stream id")
        data = self.api.get(
            f"{_account_path(account)}/jobs/{_job(job_id)}/streams/{quote(stream_id, safe='')}",
            params={"api-version": API_VERSION},
        )
        return JobStream.from_json(data)

    def output(self, account: AutomationAccount, job_id: str) -> str:
        """The job's output stream as text, as the portal's Output tab shows it."""
        return self.api.get_text(
            f"{_account_path(account)}/jobs/{_job(job_id)}/output",
            params={"api-version": API_VERSION},
            headers={"Accept": "text/plain"},
        )


def _newest_first(job: Job) -> tuple[bool, float]:
    when = job.created or job.started
    return (when is None, -when.timestamp() if when else 0.0)


def _account_path(account: AutomationAccount) -> str:
    matched = _ACCOUNT_ID.match(account.id)
    if not matched:
        raise InputError(f"{account.id!r} is not an Automation account's resource id")
    return (
        f"/subscriptions/{_guid(matched['subscription'])}/resourceGroups/"
        f"{_group(matched['group'])}/providers/{PROVIDER}/{_account(matched['name'])}"
    )


def _guid(value: str) -> str:
    if not is_guid(value):
        raise InputError(f"{value!r} is not a subscription id")
    return value


def _group(value: str) -> str:
    if not _GROUP.match(value):
        raise InputError(f"{value!r} is not a resource group name")
    return value


def _account(value: str) -> str:
    if not _ACCOUNT.match(value):
        raise InputError(f"{value!r} is not an Automation account name")
    return value


def _job(value: str) -> str:
    if not _JOB.match(value.strip()):
        raise InputError(f"{value!r} is not a job id")
    return value.strip()
