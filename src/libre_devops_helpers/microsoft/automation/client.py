"""Azure Automation through ARM: accounts, the jobs their runbooks ran, and the jobs' logs.

A job is one run of a runbook. It writes streams, as the portal's job page shows them:
output, warnings, errors, and verbose, progress and debug records when the runbook turns
those on. Jobs are kept for 30 days. Everything here reads: nothing starts, stops or
changes a runbook.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from urllib.parse import quote

from libre_devops_helpers.core.errors import AmbiguousError, ApiError, InputError, NotFoundError
from libre_devops_helpers.core.util import require_guid
from libre_devops_helpers.microsoft.api_clients import ArmServiceClient
from libre_devops_helpers.microsoft.automation.models import AutomationAccount, Job, JobStream
from libre_devops_helpers.microsoft.resource_ids import looks_like_resource_id, parse_resource_id

API_VERSION = "2023-11-01"
PROVIDER = "Microsoft.Automation/automationAccounts"
# What each part of a path may hold, so nothing typed can reach another resource.
_ACCOUNT = re.compile(r"[A-Za-z0-9-]{1,50}")
_GROUP = re.compile(r"[A-Za-z0-9._()-]{1,90}")
# A job started by hand is a GUID; one a schedule started is SCH_, the schedule and runbook
# GUIDs and a timestamp, joined by underscores (96 characters).
_JOB = re.compile(r"[A-Za-z0-9_-]{1,128}")
_STREAM = re.compile(r"[A-Za-z0-9:._-]{1,128}")


class AutomationClient(ArmServiceClient):
    """Reads Automation accounts and their jobs through ARM. Close it when done."""

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
        if looks_like_resource_id(ref):
            try:
                return AutomationAccount.from_json(
                    self.api.get(_path(ref), params={"api-version": API_VERSION})
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
        if not _STREAM.fullmatch(stream_id):
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
    return _path(account.id)


def _path(resource_id: str) -> str:
    """An Automation account's ARM path, from its resource id, with each part checked."""
    found = parse_resource_id(resource_id)
    if not found.is_type(PROVIDER) or not found.resource_group or found.parent is not None:
        raise InputError(
            f"{resource_id!r} is not an Automation account's resource id",
            hint=f"it is the resource id of a {found.type or 'tenant'}",
        )
    return (
        f"/subscriptions/{found.subscription}/resourceGroups/{_group(found.resource_group)}"
        f"/providers/{PROVIDER}/{_account(found.name)}"
    )


def _guid(value: str) -> str:
    return require_guid(value, "a subscription id")


def _group(value: str) -> str:
    if not _GROUP.fullmatch(value):
        raise InputError(f"{value!r} is not a resource group name")
    return value


def _account(value: str) -> str:
    if not _ACCOUNT.fullmatch(value):
        raise InputError(f"{value!r} is not an Automation account name")
    return value


def _job(value: str) -> str:
    if not _JOB.fullmatch(value.strip()):
        raise InputError(f"{value!r} is not a job id")
    return value.strip()
