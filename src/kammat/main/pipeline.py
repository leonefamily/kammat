"""Presentation-neutral deterministic pipeline planning."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from kammat.main.configuration import (
    ConfigurationError,
    FIELD_MAP,
    RunConfig,
    validate_configuration,
)
from kammat.main.stages import (
    ArtifactSpec,
    RegistryError,
    STAGES,
    STAGE_BY_NAME,
    STAGE_NAMES,
    StageSpec,
    stage_registry,
)


PLAN_ISSUE_CATALOG = MappingProxyType({
    "KAM-PLAN-E100": ("error", "unknown-stage"),
    "KAM-PLAN-E101": ("error", "selection-conflict"),
    "KAM-PLAN-E102": ("error", "invalid-range"),
    "KAM-PLAN-E200": ("error", "artifact-missing"),
    "KAM-PLAN-E201": ("error", "artifact-kind"),
    "KAM-PLAN-E202": ("error", "ambiguous-producer"),
    "KAM-PLAN-E203": ("error", "output-collision"),
    "KAM-PLAN-E204": ("error", "snapshot-incomplete"),
    "KAM-PLAN-E205": ("error", "inspection-failed"),
    "KAM-PLAN-W100": ("warning", "duplicate-selection"),
    "KAM-PLAN-W101": ("warning", "empty-plan"),
})

OBSERVATION_STATES = frozenset({
    "missing", "file", "directory", "symlink", "other", "planned"
})
SUPPLIER_MODES = frozenset({"selected-stage", "external"})
PLAN_REASONS = frozenset({"launch", "explicit", "range", "dependency"})
SELECTION_MODES = frozenset({"launch", "explicit", "range"})
REQUEST_SELECTION_MODES = frozenset({"auto", "explicit"})


@dataclass(frozen=True)
class PlanSelection:
    """Invocation selection independent of CLI and GUI presentation types."""

    explicit_stages: Tuple[str, ...] = ()
    from_stage: Optional[str] = None
    until_stage: Optional[str] = None
    include_dependencies: bool = True
    selection_mode: str = "auto"

    def __post_init__(self) -> None:
        explicit = tuple(self.explicit_stages)
        if any(not isinstance(name, str) or not name for name in explicit):
            raise TypeError("explicit stage names must be non-empty strings")
        if self.from_stage is not None and (
            not isinstance(self.from_stage, str) or not self.from_stage
        ):
            raise TypeError("from_stage must be a non-empty string or None")
        if self.until_stage is not None and (
            not isinstance(self.until_stage, str) or not self.until_stage
        ):
            raise TypeError("until_stage must be a non-empty string or None")
        if type(self.include_dependencies) is not bool:
            raise TypeError("include_dependencies must be an exact boolean")
        if type(self.selection_mode) is not str:
            raise TypeError("selection_mode must be an exact string")
        if self.selection_mode not in REQUEST_SELECTION_MODES:
            raise ValueError("unknown request selection mode")
        object.__setattr__(self, "explicit_stages", explicit)


@dataclass(frozen=True)
class PlanIssue:
    code: str
    level: str
    field: str
    message: str
    hint: Optional[str] = None

    def __post_init__(self) -> None:
        policy = PLAN_ISSUE_CATALOG.get(self.code)
        if policy is None:
            raise ValueError("unknown plan issue code: {0}".format(self.code))
        if self.level != policy[0]:
            raise ValueError(
                "plan issue level for {0} must be {1}".format(
                    self.code, policy[0]
                )
            )
        if not self.field or not self.message:
            raise ValueError("plan issue field and message must be non-empty")


@dataclass(frozen=True)
class ArtifactObservation:
    path: Path
    state: str
    target_kind: Optional[str] = None

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError("artifact observation path must be absolute")
        if self.state not in OBSERVATION_STATES.difference({"planned"}):
            raise ValueError("unknown artifact observation state")
        if self.target_kind is not None and self.target_kind not in {
            "file", "directory", "missing", "other"
        }:
            raise ValueError("unknown symlink target kind")
        if self.state != "symlink" and self.target_kind is not None:
            raise ValueError("only symlink observations may have a target kind")
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class ArtifactSnapshot:
    observations: Mapping[Path, ArtifactObservation]

    def __post_init__(self) -> None:
        copied: Dict[Path, ArtifactObservation] = {}
        for key, value in self.observations.items():
            path = Path(key)
            if not path.is_absolute() or path != value.path:
                raise ValueError("snapshot keys must equal absolute observation paths")
            copied[path] = value
        object.__setattr__(self, "observations", MappingProxyType(copied))


@dataclass(frozen=True)
class ArtifactResolution:
    identifier: str
    path: Path
    kind: str
    consumer: str
    supplier: str
    producer_stage: Optional[str]
    observed_state: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not self.identifier or not self.consumer or not path.is_absolute():
            raise ValueError("artifact resolution identity must be complete")
        if self.kind not in {"file", "directory"}:
            raise ValueError("artifact resolution kind is invalid")
        if self.supplier not in SUPPLIER_MODES:
            raise ValueError("artifact supplier mode is invalid")
        if self.supplier == "selected-stage" and self.producer_stage is None:
            raise ValueError("selected-stage artifact requires a producer")
        if self.supplier == "external" and self.producer_stage is not None:
            raise ValueError("external artifact may not name a producer")
        if self.observed_state not in OBSERVATION_STATES:
            raise ValueError("artifact resolution state is invalid")
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class PlannedStage:
    spec: StageSpec
    reason: str
    dependencies: Tuple[str, ...]
    inputs: Tuple[ArtifactResolution, ...]
    outputs: Tuple[ArtifactResolution, ...]

    def __post_init__(self) -> None:
        if self.reason not in PLAN_REASONS:
            raise ValueError("unknown planned-stage reason")
        dependencies = tuple(self.dependencies)
        inputs = tuple(self.inputs)
        outputs = tuple(self.outputs)
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("planned-stage dependencies must be unique")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "outputs", outputs)


@dataclass(frozen=True)
class ExecutionPlan:
    schema_version: int
    config: RunConfig
    selection: PlanSelection
    selection_mode: str
    root_stages: Tuple[str, ...]
    stages: Tuple[PlannedStage, ...]
    warnings: Tuple[PlanIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("ExecutionPlan schema version must be 1")
        if self.selection_mode not in SELECTION_MODES:
            raise ValueError("unknown plan selection mode")
        roots = tuple(self.root_stages)
        stages = tuple(self.stages)
        warnings = tuple(self.warnings)
        names = tuple(stage.spec.name for stage in stages)
        if names != tuple(name for name in STAGE_NAMES if name in names):
            raise ValueError("planned stages must use canonical registry order")
        if any(name not in names for name in roots):
            raise ValueError("plan roots must be planned stages")
        if any(issue.level != "warning" for issue in warnings):
            raise ValueError("ExecutionPlan may contain only warnings")
        object.__setattr__(self, "root_stages", roots)
        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True)
class PlanResult:
    plan: Optional[ExecutionPlan]
    issues: Tuple[PlanIssue, ...]

    def __post_init__(self) -> None:
        issues = tuple(self.issues)
        has_error = any(issue.level == "error" for issue in issues)
        if has_error and self.plan is not None:
            raise ValueError("PlanResult with errors may not contain a plan")
        if not has_error and self.plan is None:
            raise ValueError("PlanResult without errors requires a plan")
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True)
class _BoundArtifact:
    stage: str
    spec: ArtifactSpec
    path: Path


class _ArtifactInspectionError(OSError):
    """Retain the exact registry requirement whose metadata read failed."""

    def __init__(self, field: str, path: Path, cause: OSError) -> None:
        self.field = field
        self.path = path
        self.cause = cause
        super().__init__(str(cause))


def _plan_issue(code: str, field: str, message: str) -> PlanIssue:
    return PlanIssue(code, PLAN_ISSUE_CATALOG[code][0], field, message)


def _stage_index(name: str) -> int:
    return STAGE_BY_NAME[name].index if name in STAGE_BY_NAME else len(STAGES)


def _sort_issues(issues: Iterable[PlanIssue]) -> Tuple[PlanIssue, ...]:
    unique: Dict[Tuple[str, str, str], PlanIssue] = {}
    for issue in issues:
        unique.setdefault((issue.code, issue.field, issue.message), issue)

    def key(issue: PlanIssue) -> Tuple[int, int, str, str, str]:
        if issue.field.startswith("selection"):
            return (0, -1, issue.field, issue.code, issue.message)
        stage = issue.field.split(":", 1)[0]
        artifact = issue.field.split(":", 1)[1] if ":" in issue.field else ""
        return (1, _stage_index(stage), artifact, issue.code, issue.message)

    return tuple(sorted(unique.values(), key=key))


def _validate_bindings(stages: Tuple[StageSpec, ...] = STAGES) -> None:
    for stage in stages:
        for artifact in stage.requires + stage.provides:
            field_stage, field_name = artifact.binding.field.split(".", 1)
            if field_stage not in FIELD_MAP or field_name not in FIELD_MAP[field_stage]:
                raise RegistryError(
                    "unknown schema binding: {0}".format(artifact.binding.field)
                )
            field_spec = FIELD_MAP[field_stage][field_name]
            if field_spec.value_kind != "path":
                raise RegistryError(
                    "artifact binding must reference a path: {0}".format(
                        artifact.binding.field
                    )
                )


_validate_bindings()


def _bound_path(config: RunConfig, artifact: ArtifactSpec) -> Optional[Path]:
    stage, name = artifact.binding.field.split(".", 1)
    value = config.stages[stage].get(name)
    if value is None:
        return None
    if not isinstance(value, Path):
        raise RegistryError(
            "artifact binding is not a normalized Path: {0}".format(
                artifact.binding.field
            )
        )
    for part in artifact.binding.relative_parts:
        value = value / part
    if not value.is_absolute():
        raise RegistryError("bound artifact paths must be absolute")
    return value


def _bound_requires(config: RunConfig, stage: StageSpec) -> Tuple[_BoundArtifact, ...]:
    result = []
    for artifact in stage.requires:
        path = _bound_path(config, artifact)
        if path is None:
            if artifact.required_when == "always-selected":
                continue
            continue
        result.append(_BoundArtifact(stage.name, artifact, path))
    return tuple(result)


def _bound_provides(config: RunConfig, stage: StageSpec) -> Tuple[_BoundArtifact, ...]:
    result = []
    for artifact in stage.provides:
        path = _bound_path(config, artifact)
        if path is not None:
            result.append(_BoundArtifact(stage.name, artifact, path))
    return tuple(result)


def _selection_roots(
    config: RunConfig,
    selection: PlanSelection,
) -> Tuple[str, Tuple[str, ...], Tuple[PlanIssue, ...]]:
    issues: List[PlanIssue] = []
    has_range = selection.from_stage is not None or selection.until_stage is not None
    is_explicit = (
        selection.selection_mode == "explicit" or bool(selection.explicit_stages)
    )
    if is_explicit and has_range:
        issues.append(_plan_issue(
            "KAM-PLAN-E101",
            "selection",
            "explicit stage selection cannot be combined with a range",
        ))

    for field, names in (
        ("selection.explicit_stages", selection.explicit_stages),
        ("selection.from_stage", (selection.from_stage,) if selection.from_stage else ()),
        ("selection.until_stage", (selection.until_stage,) if selection.until_stage else ()),
    ):
        for name in names:
            if name not in STAGE_BY_NAME:
                issues.append(_plan_issue(
                    "KAM-PLAN-E100", field,
                    "unknown pipeline stage: {0}".format(name),
                ))

    if any(issue.level == "error" for issue in issues):
        mode = "explicit" if is_explicit else "range" if has_range else "launch"
        return mode, (), _sort_issues(issues)

    if is_explicit:
        mode = "explicit"
        seen: Set[str] = set()
        duplicates: Set[str] = set()
        for name in selection.explicit_stages:
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        for name in sorted(duplicates, key=_stage_index):
            issues.append(_plan_issue(
                "KAM-PLAN-W100",
                "selection.explicit_stages",
                "duplicate explicit stage was collapsed: {0}".format(name),
            ))
        roots = tuple(name for name in STAGE_NAMES if name in seen)
    elif has_range:
        mode = "range"
        start = _stage_index(selection.from_stage or STAGE_NAMES[0])
        finish = _stage_index(selection.until_stage or STAGE_NAMES[-1])
        if start > finish:
            issues.append(_plan_issue(
                "KAM-PLAN-E102",
                "selection",
                "from_stage must not follow until_stage in canonical order",
            ))
            roots = ()
        else:
            roots = STAGE_NAMES[start:finish + 1]
    else:
        mode = "launch"
        roots = tuple(
            name for name in STAGE_NAMES
            if config.stages[name].get("launch") is True
        )
    if not roots and not any(issue.level == "error" for issue in issues):
        message = (
            "the valid launch selection contains no stages"
            if mode == "launch"
            else "the valid explicit selection contains no stages"
        )
        issues.append(_plan_issue(
            "KAM-PLAN-W101",
            "selection",
            message,
        ))
    return mode, roots, _sort_issues(issues)


def _validate_selected_readiness(config: RunConfig, roots: Tuple[str, ...]) -> None:
    changed = False
    stages = {name: dict(values) for name, values in config.stages.items()}
    for name in roots:
        if stages[name].get("launch") is not True:
            stages[name]["launch"] = True
            changed = True
    if not changed:
        return
    active = RunConfig(
        config.schema_version,
        config.config_path,
        config.workspace,
        stages,
    )
    issues = validate_configuration(active)
    errors = tuple(issue for issue in issues if issue.level == "error")
    if errors:
        raise ConfigurationError(errors)


def _inspect_path(path: Path) -> ArtifactObservation:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return ArtifactObservation(path, "missing")
    if stat.S_ISLNK(info.st_mode):
        try:
            target = os.stat(path)
        except FileNotFoundError:
            target_kind = "missing"
        else:
            if stat.S_ISREG(target.st_mode):
                target_kind = "file"
            elif stat.S_ISDIR(target.st_mode):
                target_kind = "directory"
            else:
                target_kind = "other"
        return ArtifactObservation(path, "symlink", target_kind)
    if stat.S_ISREG(info.st_mode):
        return ArtifactObservation(path, "file")
    if stat.S_ISDIR(info.st_mode):
        return ArtifactObservation(path, "directory")
    return ArtifactObservation(path, "other")


def _potential_stage_names(
    config: RunConfig,
    selection: PlanSelection,
) -> Tuple[str, ...]:
    """Return stages whose requirements can be reached by this selection."""

    _, roots, issues = _selection_roots(config, selection)
    if any(issue.level == "error" for issue in issues):
        return ()
    selected = set(roots)
    if not selection.include_dependencies:
        return tuple(name for name in STAGE_NAMES if name in selected)

    provisions = {
        stage.name: _bound_provides(config, stage) for stage in STAGES
    }
    changed = True
    while changed:
        changed = False
        for consumer in STAGES:
            if consumer.name not in selected:
                continue
            for requirement in _bound_requires(config, consumer):
                candidates = []
                for producer_name in STAGE_NAMES[:consumer.index]:
                    if config.stages[producer_name].get("launch") is not True:
                        continue
                    candidates.extend(
                        item for item in provisions[producer_name]
                        if item.path == requirement.path
                        and item.spec.kind == requirement.spec.kind
                    )
                if candidates and candidates[-1].stage not in selected:
                    selected.add(candidates[-1].stage)
                    changed = True
    return tuple(name for name in STAGE_NAMES if name in selected)


def _relevant_requirements(
    config: RunConfig,
    selection: PlanSelection,
) -> Tuple[_BoundArtifact, ...]:
    names = set(_potential_stage_names(config, selection))
    return tuple(
        item
        for stage in STAGES
        if stage.name in names
        for item in _bound_requires(config, stage)
    )


def inspect_plan_artifacts(
    config: RunConfig,
    selection: PlanSelection = PlanSelection(),
) -> ArtifactSnapshot:
    """Observe only registry-declared requirement paths without mutation."""

    observations: Dict[Path, ArtifactObservation] = {}
    for requirement in _relevant_requirements(config, selection):
        if requirement.path in observations:
            continue
        try:
            observations[requirement.path] = _inspect_path(requirement.path)
        except OSError as error:
            raise _ArtifactInspectionError(
                requirement.stage + ":" + requirement.spec.identifier,
                requirement.path,
                error,
            )
    return ArtifactSnapshot(observations)


def _observation_satisfies(observation: ArtifactObservation, kind: str) -> bool:
    if observation.state == kind:
        return True
    return observation.state == "symlink" and observation.target_kind == kind


def _approved_replacement(
    earlier: _BoundArtifact,
    later: _BoundArtifact,
) -> bool:
    return later.spec.replaces == earlier.spec.identifier


def _reason_for(name: str, roots: Set[str], mode: str) -> str:
    if name not in roots:
        return "dependency"
    return mode


def build_plan(
    config: RunConfig,
    selection: PlanSelection = PlanSelection(),
    *,
    artifact_snapshot: Optional[ArtifactSnapshot] = None,
) -> PlanResult:
    """Build a deterministic structural plan without executing any stage."""

    config_errors = tuple(
        issue for issue in validate_configuration(config)
        if issue.level == "error"
    )
    if config_errors:
        raise ConfigurationError(config_errors)

    mode, roots, selection_issues = _selection_roots(config, selection)
    if any(issue.level == "error" for issue in selection_issues):
        return PlanResult(None, selection_issues)
    _validate_selected_readiness(config, roots)

    if not roots:
        plan = ExecutionPlan(
            1, config, selection, mode, (), (),
            tuple(issue for issue in selection_issues if issue.level == "warning"),
        )
        return PlanResult(plan, selection_issues)

    issues: List[PlanIssue] = list(selection_issues)
    selected: Set[str] = set(roots)
    root_set = set(roots)
    requirements: Dict[str, Tuple[_BoundArtifact, ...]] = {
        stage.name: _bound_requires(config, stage) for stage in STAGES
    }
    provisions: Dict[str, Tuple[_BoundArtifact, ...]] = {
        stage.name: _bound_provides(config, stage) for stage in STAGES
    }

    live_snapshot = artifact_snapshot
    if live_snapshot is None:
        try:
            live_snapshot = inspect_plan_artifacts(config, selection)
        except _ArtifactInspectionError as error:
            issue = _plan_issue(
                "KAM-PLAN-E205",
                error.field,
                "artifact metadata inspection failed for {0}: {1}".format(
                    error.path, error.cause
                ),
            )
            return PlanResult(None, _sort_issues(issues + [issue]))

    input_resolutions: Dict[str, List[ArtifactResolution]] = {
        name: [] for name in STAGE_NAMES
    }
    dependency_names: Dict[str, Set[str]] = {
        name: set() for name in STAGE_NAMES
    }

    def candidates(requirement: _BoundArtifact) -> List[_BoundArtifact]:
        found = []
        consumer_index = _stage_index(requirement.stage)
        for producer_name in STAGE_NAMES[:consumer_index]:
            for provided in provisions[producer_name]:
                if provided.path == requirement.path and provided.spec.kind == requirement.spec.kind:
                    found.append(provided)
        return found

    processed: Set[Tuple[str, str, Path]] = set()
    changed = True
    while changed:
        changed = False
        for consumer in STAGE_NAMES:
            if consumer not in selected:
                continue
            for requirement in requirements[consumer]:
                identity = (consumer, requirement.spec.identifier, requirement.path)
                if identity in processed:
                    continue
                possible = candidates(requirement)
                selected_candidates = [
                    item for item in possible if item.stage in selected
                ]
                if not selected_candidates and selection.include_dependencies:
                    enabled = [
                        item for item in possible
                        if config.stages[item.stage].get("launch") is True
                    ]
                    if enabled:
                        chosen = enabled[-1]
                        if chosen.stage not in selected:
                            selected.add(chosen.stage)
                            changed = True
                        selected_candidates = [chosen]

                if selected_candidates:
                    selected_candidates.sort(key=lambda item: _stage_index(item.stage))
                    if len(selected_candidates) > 1:
                        for earlier, later in zip(
                            selected_candidates, selected_candidates[1:]
                        ):
                            if not _approved_replacement(earlier, later):
                                issues.append(_plan_issue(
                                    "KAM-PLAN-E202",
                                    consumer + ":" + requirement.spec.identifier,
                                    "multiple selected producers provide {0}".format(
                                        requirement.path
                                    ),
                                ))
                    chosen = selected_candidates[-1]
                    dependency_names[consumer].add(chosen.stage)
                    input_resolutions[consumer].append(ArtifactResolution(
                        requirement.spec.identifier,
                        requirement.path,
                        requirement.spec.kind,
                        consumer,
                        "selected-stage",
                        chosen.stage,
                        "planned",
                    ))
                    processed.add(identity)
                    continue

                observation = live_snapshot.observations.get(requirement.path)
                field = consumer + ":" + requirement.spec.identifier
                if observation is None:
                    issues.append(_plan_issue(
                        "KAM-PLAN-E204",
                        field,
                        "artifact snapshot has no observation for {0}".format(
                            requirement.path
                        ),
                    ))
                    processed.add(identity)
                    continue
                if observation.state == "missing":
                    issues.append(_plan_issue(
                        "KAM-PLAN-E200",
                        field,
                        "required external artifact is missing: {0}".format(
                            requirement.path
                        ),
                    ))
                    processed.add(identity)
                    continue
                if not _observation_satisfies(observation, requirement.spec.kind):
                    issues.append(_plan_issue(
                        "KAM-PLAN-E201",
                        field,
                        "required artifact must be a {0}: {1}".format(
                            requirement.spec.kind, requirement.path
                        ),
                    ))
                    processed.add(identity)
                    continue
                input_resolutions[consumer].append(ArtifactResolution(
                    requirement.spec.identifier,
                    requirement.path,
                    requirement.spec.kind,
                    consumer,
                    "external",
                    None,
                    observation.state,
                ))
                processed.add(identity)

    selected_provisions: List[_BoundArtifact] = [
        item
        for name in STAGE_NAMES
        if name in selected
        for item in provisions[name]
    ]
    for index, earlier in enumerate(selected_provisions):
        for later in selected_provisions[index + 1:]:
            if earlier.path != later.path or earlier.spec.kind != later.spec.kind:
                continue
            if _approved_replacement(earlier, later):
                continue
            issues.append(_plan_issue(
                "KAM-PLAN-E203",
                later.stage + ":" + later.spec.identifier,
                "selected outputs collide at {0}".format(later.path),
            ))

    ordered_issues = _sort_issues(issues)
    if any(issue.level == "error" for issue in ordered_issues):
        return PlanResult(None, ordered_issues)

    planned_stages = []
    for name in STAGE_NAMES:
        if name not in selected:
            continue
        outputs = tuple(ArtifactResolution(
            item.spec.identifier,
            item.path,
            item.spec.kind,
            name,
            "selected-stage",
            name,
            "planned",
        ) for item in provisions[name])
        inputs = tuple(sorted(
            input_resolutions[name],
            key=lambda item: (item.identifier, str(item.path)),
        ))
        dependencies = tuple(
            candidate for candidate in STAGE_NAMES
            if candidate in dependency_names[name]
        )
        planned_stages.append(PlannedStage(
            STAGE_BY_NAME[name],
            _reason_for(name, root_set, mode),
            dependencies,
            inputs,
            outputs,
        ))

    warnings = tuple(
        issue for issue in ordered_issues if issue.level == "warning"
    )
    plan = ExecutionPlan(
        1,
        config,
        selection,
        mode,
        tuple(name for name in STAGE_NAMES if name in root_set),
        tuple(planned_stages),
        warnings,
    )
    return PlanResult(plan, ordered_issues)


__all__ = [
    "ArtifactObservation",
    "ArtifactResolution",
    "ArtifactSnapshot",
    "ExecutionPlan",
    "OBSERVATION_STATES",
    "PLAN_ISSUE_CATALOG",
    "PlanIssue",
    "PlanResult",
    "PlanSelection",
    "PlannedStage",
    "build_plan",
    "inspect_plan_artifacts",
    "stage_registry",
]
