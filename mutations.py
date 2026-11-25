# SPDX-License-Identifier: Apache-2.0
"""Validated, typed durable operations with backward-compatible JSON encoding.

Only this boundary accepts untyped stored payloads. A distinct dataclass describes
what each edit may change; UI row projection and sync dispatch use these types.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import date
from enum import StrEnum
from typing import Any, ClassVar, Literal, cast

type JsonObject = dict[str, Any]


class MutationKind(StrEnum):
    STATE = "state"
    STATUS = "status"
    DATE = "date"
    MEMBERSHIP = "membership"
    PROJECT_REMOVE = "project_remove"
    ADD = "add"
    CREATE = "create"
    COMMENT = "comment"
    ONLINE = "online"


class JobStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    UNCERTAIN = "uncertain"
    CONFLICT = "conflict"
    DONE = "done"
    ARCHIVED = "archived"


@dataclass(frozen=True, kw_only=True)
class Mutation:
    args: tuple[str, ...]
    repo: str | None = None
    tab: int | None = None
    target: str | None = None
    hostname: str | None = None
    extra: JsonObject = field(default_factory=dict, repr=False)
    kind: ClassVar[MutationKind]

    def to_payload(self) -> JsonObject:
        values = asdict(self)
        extra = values.pop("extra")
        return {
            **extra,
            **{key: value for key, value in values.items() if value is not None},
            "args": list(self.args),
            "kind": self.kind.value,
        }


@dataclass(frozen=True, kw_only=True)
class StateChange(Mutation):
    identity: int | str
    base: str
    desired: str
    row: JsonObject = field(default_factory=dict)
    kind: ClassVar[MutationKind] = MutationKind.STATE


@dataclass(frozen=True, kw_only=True)
class StatusChange(Mutation):
    project: JsonObject
    identity: str
    base: str
    desired: str
    kind: ClassVar[MutationKind] = MutationKind.STATUS


@dataclass(frozen=True, kw_only=True)
class DateChange(Mutation):
    project: JsonObject
    identity: str
    field_id: str
    field_name: str
    base: str
    desired: str
    kind: ClassVar[MutationKind] = MutationKind.DATE


@dataclass(frozen=True, kw_only=True)
class MembershipChange(Mutation):
    identity: int | str
    field: Literal["labels", "assignees"]
    value: str
    base: bool
    desired: bool
    kind: ClassVar[MutationKind] = MutationKind.MEMBERSHIP


@dataclass(frozen=True, kw_only=True)
class ProjectRemove(Mutation):
    project: JsonObject
    url: str
    identity: int | str | None = None
    base: bool = True
    desired: bool = False
    kind: ClassVar[MutationKind] = MutationKind.PROJECT_REMOVE


@dataclass(frozen=True, kw_only=True)
class ProjectAdd(Mutation):
    project: JsonObject | None = None
    url: str | None = None
    project_owner: str | None = None
    parent: str | None = None
    title: str | None = None
    body: str | None = None
    kind: ClassVar[MutationKind] = MutationKind.ADD


@dataclass(frozen=True, kw_only=True)
class CreateIssue(Mutation):
    title: str
    body: str
    project: JsonObject | None = None
    project_owner: str | None = None
    marker: str | None = None
    result_url: str | None = None
    kind: ClassVar[MutationKind] = MutationKind.CREATE


@dataclass(frozen=True, kw_only=True)
class Comment(Mutation):
    identity: int | str
    body: str
    marker: str | None = None
    kind: ClassVar[MutationKind] = MutationKind.COMMENT


@dataclass(frozen=True, kw_only=True)
class OnlineCommand(Mutation):
    kind: ClassVar[MutationKind] = MutationKind.ONLINE


type FieldChange = StateChange | StatusChange | DateChange | MembershipChange | ProjectRemove
type Operation = FieldChange | ProjectAdd | CreateIssue | Comment | OnlineCommand

_TYPES: dict[MutationKind, type[Mutation]] = {
    MutationKind.STATE: StateChange,
    MutationKind.STATUS: StatusChange,
    MutationKind.DATE: DateChange,
    MutationKind.MEMBERSHIP: MembershipChange,
    MutationKind.PROJECT_REMOVE: ProjectRemove,
    MutationKind.ADD: ProjectAdd,
    MutationKind.CREATE: CreateIssue,
    MutationKind.COMMENT: Comment,
    MutationKind.ONLINE: OnlineCommand,
}


def parse_mutation(payload: JsonObject | Mutation) -> Operation:
    """Validate new/stored jobs without changing their existing JSON schema."""
    raw = deepcopy(payload.to_payload() if isinstance(payload, Mutation) else dict(payload))
    try:
        kind = MutationKind(raw.pop("kind"))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Unknown queued operation; original payload is retained.") from exc
    cls = _TYPES[kind]
    raw_args = raw.get("args")
    if not isinstance(raw_args, (list, tuple)) or not raw_args:
        raise ValueError("Queued operation needs a nonempty argument list.")
    if not all(isinstance(arg, (str, int)) and not isinstance(arg, bool) for arg in raw_args):
        raise ValueError("Command arguments must be strings or integer identifiers.")
    raw["args"] = tuple(str(arg) for arg in raw_args)
    known = {item.name for item in fields(cls)} - {"extra"}
    missing = [
        item.name
        for item in fields(cls)
        if item.name != "extra"
        and item.default is MISSING
        and item.default_factory is MISSING
        and item.name not in raw
    ]
    if missing:
        raise ValueError("Incomplete queued operation: " + ", ".join(missing))
    kwargs = {key: value for key, value in raw.items() if key in known}
    kwargs["extra"] = {key: value for key, value in raw.items() if key not in known}
    operation = cast(Operation, cls(**kwargs))
    if isinstance(operation, (StateChange, StatusChange, DateChange)):
        if not isinstance(operation.base, str) or not isinstance(operation.desired, str):
            raise ValueError("State/status/date values must be strings.")
    if isinstance(operation, (MembershipChange, ProjectRemove)):
        if type(operation.base) is not bool or type(operation.desired) is not bool:
            raise ValueError("Membership values must be booleans.")
    if isinstance(operation, MembershipChange):
        if (
            operation.field not in ("labels", "assignees")
            or not isinstance(operation.value, str)
            or not operation.value
        ):
            raise ValueError("Membership edits require a label or assignee value.")
    if isinstance(operation, (StatusChange, DateChange, ProjectRemove)):
        if not isinstance(operation.project, dict) or not isinstance(
            operation.project.get("id"), str
        ):
            raise ValueError("Project edit needs a Project ID.")
    if isinstance(operation, DateChange):
        if not operation.field_id or not operation.field_name:
            raise ValueError("Date edit needs a field ID and name.")
        for value in (operation.base, operation.desired):
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError("Date edits require YYYY-MM-DD values.")
    return operation
