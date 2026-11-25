# SPDX-License-Identifier: Apache-2.0
"""Commands shown in menus carry validated operations, never ambiguous edit flags."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field

from mutations import JsonObject, Mutation, OnlineCommand, Operation, parse_mutation


@dataclass
class Action:
    label: str
    args: list[str]
    confirm: bool = False
    viewer: bool = False
    context: InitVar[JsonObject | Mutation | None] = None
    operation: Operation | None = field(init=False, default=None)

    def __post_init__(self, context: JsonObject | Mutation | None) -> None:
        if context is not None:
            payload = context.to_payload() if isinstance(context, Mutation) else dict(context)
            payload["args"] = self.args
            self.operation = parse_mutation(payload)
        elif not self.viewer and self.args:
            self.operation = OnlineCommand(args=tuple(self.args))
