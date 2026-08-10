"""Immutable CLI-only models and closed catalogs."""

from dataclasses import dataclass
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


CLI_ISSUE_CATALOG = MappingProxyType({
    "KAM-CLI-E100": ("error", "dispatch", 5),
    "KAM-CLI-E101": ("error", "template", 5),
    "KAM-CLI-E102": ("error", "template-write", 5),
    "KAM-CLI-E110": ("error", "override-syntax", 3),
    "KAM-CLI-E111": ("error", "override-field", 3),
    "KAM-CLI-E112": ("error", "override-value", 3),
    "KAM-CLI-E200": ("error", "presentation", 5),
    "KAM-CLI-E201": ("error", "gui-launch", 5),
    "KAM-CLI-W100": ("warning", "legacy-invocation", None),
})
OUTPUT_MODES = frozenset({"text", "json"})
AVAILABILITY_STATES = frozenset({
    "available", "unavailable", "configuration-required",
})
VERBOSITY_LEVELS = frozenset({0, 1, 2})
TEMPLATE_PROFILES = frozenset({"minimal", "full"})
APPLICATION_EXIT_CODES = frozenset({0, 2, 3, 4, 5, 6, 130})


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("{0} must be a non-empty string without NUL".format(label))
    return value


def _scalar(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    return type(value) is float and math.isfinite(value)


@dataclass(frozen=True)
class CliIssue:
    code: str
    level: str
    field: str
    message: str
    hint: Optional[str] = None

    def __post_init__(self) -> None:
        policy = CLI_ISSUE_CATALOG.get(self.code)
        if policy is None:
            raise ValueError("unknown CLI issue code: {0}".format(self.code))
        if self.level != policy[0]:
            raise ValueError("CLI issue severity must be catalog-owned")
        _text(self.field, "CLI issue field")
        _text(self.message, "CLI issue message")
        if self.hint is not None:
            _text(self.hint, "CLI issue hint")

    @property
    def application_code(self) -> Optional[int]:
        return CLI_ISSUE_CATALOG[self.code][2]


def cli_issue(
    code: str,
    field: str,
    message: str,
    hint: Optional[str] = None,
) -> CliIssue:
    policy = CLI_ISSUE_CATALOG.get(code)
    if policy is None:
        raise ValueError("unknown CLI issue code: {0}".format(code))
    return CliIssue(code, policy[0], field, message, hint)


@dataclass(frozen=True)
class PresentationPolicy:
    quiet: bool
    verbosity: int
    color: bool
    output_mode: str

    def __post_init__(self) -> None:
        if type(self.quiet) is not bool or type(self.color) is not bool:
            raise TypeError("quiet and color must be exact booleans")
        if type(self.verbosity) is not int or self.verbosity not in VERBOSITY_LEVELS:
            raise ValueError("verbosity must be 0, 1, or 2")
        if self.quiet and self.verbosity:
            raise ValueError("quiet and verbosity are mutually exclusive")
        if self.output_mode not in OUTPUT_MODES:
            raise ValueError("unknown output mode")
        if self.output_mode == "json" and self.color:
            raise ValueError("JSON presentation cannot use color")


@dataclass(frozen=True)
class ConfigAssignment:
    field: str
    raw_value: str
    parsed_value: Any

    def __post_init__(self) -> None:
        _text(self.field, "override field")
        if self.field.count(".") != 1:
            raise ValueError("override field must be one canonical dotted name")
        if not isinstance(self.raw_value, str) or "\x00" in self.raw_value:
            raise ValueError("override raw value must be a string without NUL")
        if not _scalar(self.parsed_value):
            raise TypeError("override value must be a finite JSON scalar or string")


@dataclass(frozen=True)
class PreparedPlanView:
    plan: Any
    overrides: Tuple[ConfigAssignment, ...]
    stages: Tuple[Any, ...]

    def __post_init__(self) -> None:
        overrides = tuple(self.overrides)
        stages = tuple(self.stages)
        if any(not isinstance(item, ConfigAssignment) for item in overrides):
            raise TypeError("prepared plan overrides must be ConfigAssignment values")
        fields = tuple(item.field for item in overrides)
        if len(fields) != len(set(fields)):
            raise ValueError("prepared plan overrides must be unique")
        planned = tuple(getattr(self.plan, "stages", ()))
        if len(planned) != len(stages):
            raise ValueError("prepared stages must cover the exact plan")
        for planned_stage, prepared_stage in zip(planned, stages):
            if getattr(prepared_stage, "planned_stage", None) != planned_stage:
                raise ValueError("prepared stage must retain the exact planned stage")
            invocation = getattr(prepared_stage, "invocation", None)
            if getattr(invocation, "stage", None) != getattr(planned_stage.spec, "name", None):
                raise ValueError("prepared stage identity must match plan order")
        object.__setattr__(self, "overrides", overrides)
        object.__setattr__(self, "stages", stages)


def scalar_to_primitive(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if not _scalar(value):
        raise TypeError("value is not a supported primitive scalar")
    return value


__all__ = [
    "APPLICATION_EXIT_CODES",
    "AVAILABILITY_STATES",
    "CLI_ISSUE_CATALOG",
    "CliIssue",
    "ConfigAssignment",
    "OUTPUT_MODES",
    "PreparedPlanView",
    "PresentationPolicy",
    "TEMPLATE_PROFILES",
    "VERBOSITY_LEVELS",
    "cli_issue",
    "scalar_to_primitive",
]
