"""Data-only canonical pipeline stage and artifact registry."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional, Tuple


ARTIFACT_KINDS = frozenset({"file", "directory"})
REQUIREMENT_POLICIES = frozenset({
    "always-selected",
    "when-present",
    "when-paired-present",
    "when-consumer-family-selected",
    "one-of-configured-layers",
})


class RegistryError(RuntimeError):
    """Raised when the static stage registry violates its invariants."""


@dataclass(frozen=True)
class PathBinding:
    """Bind an artifact to one canonical configuration field."""

    field: str
    relative_parts: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or self.field.count(".") != 1:
            raise ValueError("artifact field must be one canonical dotted name")
        stage, name = self.field.split(".", 1)
        if not stage or not name:
            raise ValueError("artifact field components must be non-empty")
        parts = tuple(self.relative_parts)
        if any(not isinstance(part, str) or not part or "/" in part or "\\" in part
               for part in parts):
            raise ValueError("artifact relative parts must be non-empty path names")
        object.__setattr__(self, "relative_parts", parts)


@dataclass(frozen=True)
class ArtifactSpec:
    """One immutable cross-stage artifact requirement or provision."""

    identifier: str
    kind: str
    binding: PathBinding
    required_when: str
    replaces: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("artifact identifier must be non-empty")
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError("unknown artifact kind: {0}".format(self.kind))
        if self.required_when not in REQUIREMENT_POLICIES:
            raise ValueError(
                "unknown artifact requirement policy: {0}".format(
                    self.required_when
                )
            )
        if self.replaces is not None and (
            not isinstance(self.replaces, str) or not self.replaces
        ):
            raise ValueError("replacement artifact identifier must be non-empty")


@dataclass(frozen=True)
class StageSpec:
    """One stage's planning metadata, deliberately without execution behavior."""

    name: str
    description: str
    index: int
    dependencies: Tuple[str, ...] = ()
    requires: Tuple[ArtifactSpec, ...] = ()
    provides: Tuple[ArtifactSpec, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("stage name must be non-empty")
        if not isinstance(self.description, str) or not self.description:
            raise ValueError("stage description must be non-empty")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("stage index must be a nonnegative integer")
        dependencies = tuple(self.dependencies)
        requires = tuple(self.requires)
        provides = tuple(self.provides)
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("stage dependencies must be unique")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "requires", requires)
        object.__setattr__(self, "provides", provides)


def _artifact(
    identifier: str,
    field: str,
    *,
    kind: str = "file",
    policy: str = "always-selected",
    relative_parts: Tuple[str, ...] = (),
    replaces: Optional[str] = None,
) -> ArtifactSpec:
    return ArtifactSpec(
        identifier,
        kind,
        PathBinding(field, relative_parts),
        policy,
        replaces,
    )


STAGES = (
    StageSpec(
        "network",
        "Build or select the effective MATSim network",
        0,
        provides=(
            _artifact("network.effective", "network.net_save_path"),
            _artifact("network.edges", "network.edges_save_path", policy="when-present"),
            _artifact("network.nodes", "network.nodes_save_path", policy="when-present"),
            _artifact("network.lanes", "network.lane_definitions_save_path", policy="when-present"),
        ),
    ),
    StageSpec(
        "pt",
        "Add public transport data to the effective network",
        1,
        dependencies=("network",),
        requires=(
            _artifact("network.effective", "pt.net_path"),
        ),
        provides=(
            _artifact(
                "pt.effective-network",
                "pt.output_net_path",
                replaces="network.effective",
            ),
            _artifact("pt.schedule", "pt.output_schedule_path", policy="when-present"),
            _artifact("pt.vehicles", "pt.output_vehicles_path", policy="when-present"),
        ),
    ),
    StageSpec(
        "population",
        "Build or select the MATSim population",
        2,
        provides=(
            _artifact("population.xml", "population.xml_path"),
            _artifact(
                "population.facilities-counts",
                "population.facilities_counts_save_path",
                policy="when-present",
            ),
        ),
    ),
    StageSpec(
        "config",
        "Generate the MATSim configuration",
        3,
        dependencies=("network", "population"),
        requires=(
            _artifact("network.effective", "config.net_path"),
            _artifact("population.xml", "config.population_path"),
            _artifact("pt.schedule", "config.schedule_path", policy="when-paired-present"),
            _artifact("pt.vehicles", "config.vehicles_path", policy="when-paired-present"),
            _artifact("network.lanes", "config.lane_definitions_path", policy="when-present"),
        ),
        provides=(
            _artifact("config.matsim", "config.output_config_path"),
            _artifact(
                "config.model-root",
                "config.matsim_output_directory",
                kind="directory",
            ),
        ),
    ),
    StageSpec(
        "model",
        "Run MATSim",
        4,
        dependencies=("config",),
        requires=(
            _artifact("config.matsim", "model.config_path"),
        ),
        provides=(
            _artifact(
                "model.events",
                "config.matsim_output_directory",
                relative_parts=("output_events.xml.gz",),
            ),
            _artifact(
                "model.network",
                "config.matsim_output_directory",
                relative_parts=("output_network.xml.gz",),
            ),
            _artifact(
                "model.legs",
                "config.matsim_output_directory",
                relative_parts=("output_legs.csv.gz",),
            ),
            _artifact(
                "model.schedule",
                "config.matsim_output_directory",
                relative_parts=("output_transitSchedule.xml.gz",),
            ),
        ),
    ),
    StageSpec(
        "analysis",
        "Analyze MATSim outputs",
        5,
        dependencies=("model",),
        requires=(
            _artifact("model.events", "analysis.events_path"),
            _artifact("model.network", "analysis.net_path"),
            _artifact("model.legs", "analysis.legs_path", policy="when-present"),
            _artifact("model.schedule", "analysis.schedule_path", policy="when-present"),
        ),
        provides=(
            _artifact("analysis.road-counts", "analysis.output_counts_path"),
            _artifact("analysis.turns", "analysis.output_turns_path"),
            _artifact("analysis.road-net-counts", "analysis.output_net_counts_path"),
            _artifact("analysis.transfers", "analysis.output_transfers_path", policy="when-present"),
            _artifact("analysis.pt-counts", "analysis.output_pt_counts_path", policy="when-present"),
            _artifact("analysis.pt-net-counts", "analysis.output_pt_net_counts_path", policy="when-present"),
            _artifact("analysis.pt-stop-counts", "analysis.output_pt_stops_counts_path", policy="when-present"),
            _artifact("analysis.cordon-stats", "analysis.output_cordon_stats_path", policy="when-present"),
            _artifact("analysis.volume-stats", "analysis.output_volume_stats_path", policy="when-present"),
        ),
    ),
    StageSpec(
        "comparison",
        "Compare current, observed, or previous results",
        6,
        dependencies=("analysis",),
        requires=(
            _artifact("network.edges", "comparison.edge_net_path", policy="when-present"),
            _artifact("analysis.road-net-counts", "comparison.net_counts_path", policy="when-present"),
            _artifact("analysis.pt-net-counts", "comparison.pt_net_counts_path", policy="when-present"),
            _artifact("analysis.pt-stop-counts", "comparison.pt_stops_counts_path", policy="when-present"),
        ),
        provides=(
            _artifact("comparison.rw-network-diff", "comparison.network_differences_save_path", policy="when-present"),
            _artifact("comparison.rw-intersection-diff", "comparison.intersection_differences_save_path", policy="when-present"),
            _artifact("comparison.model-road-diff", "comparison.diff_net_counts_save_path", policy="when-present"),
            _artifact("comparison.model-pt-diff", "comparison.diff_pt_net_counts_save_path", policy="when-present"),
            _artifact("comparison.model-pt-stop-diff", "comparison.diff_pt_stops_counts_save_path", policy="when-present"),
        ),
    ),
    StageSpec(
        "gis",
        "Generate a QGIS project from configured layers",
        7,
        requires=(
            _artifact("population.facilities-counts", "gis.input_facilities", policy="one-of-configured-layers"),
            _artifact("network.edges", "gis.input_edges", policy="one-of-configured-layers"),
            _artifact("network.nodes", "gis.input_nodes", policy="one-of-configured-layers"),
            _artifact("analysis.road-net-counts", "gis.output_road_counts", policy="one-of-configured-layers"),
            _artifact("analysis.pt-net-counts", "gis.output_pt_counts", policy="one-of-configured-layers"),
            _artifact("analysis.pt-stop-counts", "gis.output_pt_stops", policy="one-of-configured-layers"),
            _artifact("analysis.cordon-stats", "gis.output_cordons_stats", policy="one-of-configured-layers"),
            _artifact("analysis.volume-stats", "gis.output_volumes_stats", policy="one-of-configured-layers"),
            _artifact("comparison.rw-network-diff", "gis.comparison_rw_road_diffs", policy="one-of-configured-layers"),
            _artifact("comparison.rw-intersection-diff", "gis.comparison_rw_road_intersection_diffs", policy="one-of-configured-layers"),
            _artifact("comparison.model-road-diff", "gis.comparison_model_road_diffs", policy="one-of-configured-layers"),
            _artifact("comparison.model-pt-diff", "gis.comparison_model_pt_diffs", policy="one-of-configured-layers"),
            _artifact("comparison.model-pt-stop-diff", "gis.comparison_model_pt_stops_diffs", policy="one-of-configured-layers"),
        ),
        provides=(
            _artifact("gis.project", "gis.project_path"),
        ),
    ),
)


STAGE_NAMES = tuple(stage.name for stage in STAGES)
STAGE_BY_NAME = MappingProxyType({stage.name: stage for stage in STAGES})


def _validate_registry(stages: Tuple[StageSpec, ...]) -> None:
    approved = (
        "network", "pt", "population", "config",
        "model", "analysis", "comparison", "gis",
    )
    if tuple(stage.name for stage in stages) != approved:
        raise RegistryError("registry must contain the exact approved stage order")
    indices = tuple(stage.index for stage in stages)
    if indices != tuple(range(len(stages))):
        raise RegistryError("registry indices must match canonical tuple positions")
    if len(set(indices)) != len(indices):
        raise RegistryError("registry indices must be unique")
    names = {stage.name for stage in stages}
    for stage in stages:
        for dependency in stage.dependencies:
            if dependency not in names:
                raise RegistryError("unknown dependency: {0}".format(dependency))
            if dependency == stage.name:
                raise RegistryError("stage may not depend on itself")
            if approved.index(dependency) >= stage.index:
                raise RegistryError("stage dependencies must point backward")
        identifiers = [item.identifier for item in stage.requires]
        identifiers.extend(item.identifier for item in stage.provides)
        if len(identifiers) != len(set(identifiers)):
            raise RegistryError(
                "stage artifact identifiers must be unique: {0}".format(stage.name)
            )
    replacement_targets = {
        item.replaces
        for stage in stages
        for item in stage.provides
        if item.replaces is not None
    }
    provided_ids = {
        item.identifier for stage in stages for item in stage.provides
    }
    if not replacement_targets.issubset(provided_ids):
        raise RegistryError("replacement must name a provided predecessor artifact")


_validate_registry(STAGES)


def stage_registry() -> Tuple[StageSpec, ...]:
    """Return the immutable canonical stage registry."""

    return STAGES


__all__ = [
    "ARTIFACT_KINDS",
    "ArtifactSpec",
    "PathBinding",
    "REQUIREMENT_POLICIES",
    "RegistryError",
    "STAGES",
    "STAGE_BY_NAME",
    "STAGE_NAMES",
    "StageSpec",
    "stage_registry",
]
