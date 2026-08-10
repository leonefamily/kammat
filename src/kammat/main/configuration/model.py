"""Immutable presentation-neutral configuration models."""

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from kammat.main.stages import STAGE_NAMES


STAGE_ORDER = STAGE_NAMES

PROVENANCE_VALUES = frozenset(
    {"gui", "json", "legacy-neighbor", "default", "derived"}
)
VALUE_KINDS = frozenset({"bool", "int", "float", "str", "path"})
REQUIRED_POLICIES = frozenset({"always", "optional"})
PATH_ROLE_VALUES = frozenset({
    "existing_file",
    "existing_directory",
    "optional_existing_file",
    "optional_existing_directory",
    "generated_file",
    "generated_directory",
    "upstream_or_existing_file",
    "external_file",
    "external_directory_or_executable",
})

ISSUE_CATALOG = MappingProxyType({
    "KAM-CFG-E001": ("error", "source"),
    "KAM-CFG-E002": ("error", "root"),
    "KAM-CFG-E100": ("error", "schema-version"),
    "KAM-CFG-E101": ("error", "unknown-field"),
    "KAM-CFG-E102": ("error", "required-field"),
    "KAM-CFG-E200": ("error", "scalar-type"),
    "KAM-CFG-E201": ("error", "scalar-value"),
    "KAM-CFG-E300": ("error", "path-syntax"),
    "KAM-CFG-E301": ("error", "path-existence"),
    "KAM-CFG-E302": ("error", "path-kind"),
    "KAM-CFG-E400": ("error", "relationship"),
    "KAM-CFG-W100": ("warning", "legacy-source"),
    "KAM-CFG-W101": ("warning", "legacy-conversion"),
    "KAM-CFG-W102": ("warning", "legacy-unknown-field"),
    "KAM-CFG-W200": ("warning", "optional-metadata"),
})


def freeze(value: Any) -> Any:
    """Recursively freeze configuration values without retaining caller state."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a recursively copied mutable representation."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {thaw(item) for item in value}
    return value


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    level: str
    field: str
    message: str
    hint: Optional[str] = None

    def __post_init__(self) -> None:
        policy = ISSUE_CATALOG.get(self.code)
        if policy is None:
            raise ValueError("unknown configuration issue code: {0}".format(self.code))
        if self.level != policy[0]:
            raise ValueError(
                "issue level for {0} must be {1}".format(self.code, policy[0])
            )
        if not self.field or not self.message:
            raise ValueError("issue field and message must be non-empty")


@dataclass(frozen=True)
class RunConfig:
    schema_version: int
    config_path: Path
    workspace: Path
    stages: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("effective RunConfig schema_version must be 1")
        if tuple(self.stages) != STAGE_ORDER:
            raise ValueError("RunConfig must contain all stages in canonical order")
        config_path = Path(self.config_path)
        workspace = Path(self.workspace)
        if not config_path.is_absolute() or not workspace.is_absolute():
            raise ValueError("RunConfig paths must be absolute normalized paths")
        object.__setattr__(self, "config_path", config_path)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "stages", freeze(self.stages))


@dataclass(frozen=True)
class ConfigResult:
    config: Optional[RunConfig]
    issues: Tuple[ValidationIssue, ...]
    source_version: Optional[int]
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.config is None and not any(
            issue.level == "error" for issue in self.issues
        ):
            raise ValueError("ConfigResult without a config requires a root error")
        if any(not key for key in self.provenance):
            raise ValueError("configuration provenance keys must be non-empty")
        for source in self.provenance.values():
            if source not in PROVENANCE_VALUES:
                raise ValueError("unknown configuration provenance: {0}".format(source))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "provenance", freeze(self.provenance))


@dataclass(frozen=True)
class FieldSpec:
    name: str
    value_kind: str
    nullable: bool = False
    required_when: str = "optional"
    default: Any = None
    gui_key: Optional[str] = None
    legacy_keys: Tuple[str, ...] = ()
    path_role: Optional[str] = None
    allowed_values: Tuple[Any, ...] = ()
    validator_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or self.value_kind not in VALUE_KINDS:
            raise ValueError("FieldSpec requires a name and supported value kind")
        if self.required_when not in REQUIRED_POLICIES:
            raise ValueError("unknown FieldSpec required policy")
        if self.path_role is not None and self.path_role not in PATH_ROLE_VALUES:
            raise ValueError("unknown FieldSpec path role")
        if self.value_kind != "path" and self.path_role is not None:
            raise ValueError("only path fields may declare a path role")
        if self.gui_key is not None and not (
            self.gui_key.startswith("-") and self.gui_key.endswith("-")
        ):
            raise ValueError("FieldSpec GUI key must use the GUI token form")
        if len(self.validator_codes) != len(set(self.validator_codes)):
            raise ValueError("FieldSpec validator codes must be unique")
        if any(code not in ISSUE_CATALOG for code in self.validator_codes):
            raise ValueError("FieldSpec references an unknown validator code")


class ConfigurationError(RuntimeError):
    """Aggregate compatibility exception containing every validation issue."""

    def __init__(self, issues: Tuple[ValidationIssue, ...]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(
            "{0} {1}: {2}".format(issue.code, issue.field, issue.message)
            for issue in self.issues
        ))
