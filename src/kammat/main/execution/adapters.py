"""Explicit stage-to-argv adapters and pure execution preparation."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from kammat.main.configuration import RunConfig
from kammat.main.pipeline import ExecutionPlan, PlannedStage
from kammat.main.stages import STAGES, STAGE_NAMES
from kammat.model.matsim import get_matsim_runnable_class, get_matsim_version
from .model import (
    ExecutionEnvironment,
    OutputExpectation,
    PreparationResult,
    PreparedStage,
    ProcessInvocation,
    RunContext,
    StageAvailability,
    execution_issue,
)


ARG_ENCODINGS = frozenset({"scalar", "flag", "comma-int", "semicolon-comma-int"})
OUTPUT_ACTIVATIONS = frozenset({"planned", "all-fields-present"})
EXECUTION_FAMILIES = frozenset({
    "python", "python-java-resource", "java", "qgis-python",
})


class ExecutionRegistryError(RuntimeError):
    """The static execution adapter/output registry is inconsistent."""


class PreparationError(RuntimeError):
    """One stage invocation cannot be prepared safely."""

    def __init__(self, issue: Any) -> None:
        self.issue = issue
        super().__init__(issue.message)


@dataclass(frozen=True)
class ArgSpec:
    field: str
    option: str
    encoding: str = "scalar"
    allow_empty: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("argument field must be non-empty")
        if not isinstance(self.option, str) or not self.option.startswith("-"):
            raise ValueError("argument option must start with a dash")
        if self.encoding not in ARG_ENCODINGS:
            raise ValueError("unknown argument encoding")
        if type(self.allow_empty) is not bool:
            raise TypeError("allow_empty must be an exact boolean")


@dataclass(frozen=True)
class OutputRule:
    identifier: str
    activation: str = "planned"
    fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("output rule identifier must be non-empty")
        if self.activation not in OUTPUT_ACTIVATIONS:
            raise ValueError("unknown output activation")
        fields = tuple(self.fields)
        if self.activation == "planned" and fields:
            raise ValueError("planned output rule may not name fields")
        if self.activation == "all-fields-present" and not fields:
            raise ValueError("conditional output rule requires fields")
        if any(not isinstance(item, str) or item.count(".") != 1 for item in fields):
            raise ValueError("output fields must use canonical dotted names")
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True)
class StageAdapter:
    stage: str
    prepare: Callable[[PlannedStage, RunConfig, RunContext, ExecutionEnvironment], PreparedStage]
    execution_family: str
    runtime_requirement: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage or not callable(self.prepare):
            raise ValueError("stage adapter requires name and callable")
        if self.execution_family not in EXECUTION_FAMILIES:
            raise ValueError("unknown execution family")
        if not isinstance(self.runtime_requirement, str) or not self.runtime_requirement:
            raise ValueError("stage adapter requires a runtime requirement")


def _arg(field: str, option: str, encoding: str = "scalar") -> ArgSpec:
    return ArgSpec(field, option, encoding)


NETWORK_CEDA_ARGS = (
    _arg("shp_path", "--shp-path"),
    _arg("lane_connections_path", "--lane-connections-path"),
    _arg("net_save_path", "--net-save-path"),
    _arg("edges_save_path", "--edges-save-path"),
    _arg("nodes_save_path", "--nodes-save-path"),
    _arg("lane_definitions_save_path", "--lane-definitions-save-path"),
    _arg("ncores", "--ncores"),
    _arg("internal_maneuvers", "--internal-maneuvers", "flag"),
)
NETWORK_GENERIC_ARGS = (
    _arg("shp_path", "--shp-path"),
    _arg("net_save_path", "--net-save-path"),
    _arg("edges_save_path", "--edges-save-path"),
    _arg("nodes_save_path", "--nodes-save-path"),
    _arg("restrict_uturns", "--restrict-uturns", "flag"),
)
PT_ARGS = (
    _arg("gtfs_folder", "--gtfs-folder"),
    _arg("number_of_threads", "--number-of-threads"),
    _arg("net_path", "--net-path"),
    _arg("output_net_path", "--output-net-path"),
    _arg("output_schedule_path", "--output-schedule-path"),
    _arg("output_vehicles_path", "--output-vehicles-path"),
)
POPULATION_ARGS = (
    _arg("facilities_path", "--facilities-path"),
    _arg("categories_path", "--categories-path"),
    _arg("diaries_path", "--diaries-path"),
    _arg("distances_path", "--distances-path"),
    _arg("xml_path", "--xml-path"),
    _arg("csv_path", "--csv-path"),
    _arg("pickle_path", "--pickle-path"),
    _arg("modal_split_path", "--modal-split-path"),
    _arg("modal_split_save_path", "--modal-split-save-path"),
    _arg("facilities_counts_save_path", "--facilities-counts-save-path"),
    _arg("relational_matrices_save_directory", "--relational-matrices-save-directory"),
    _arg("clusters_path", "--clusters-path"),
    _arg("citylog_points_path", "--citylog-points-path"),
    _arg("freight_points_path", "--freight-points-path"),
    _arg("transit_points_path", "--transit-points-path"),
    _arg("staying_path", "--staying-path"),
    _arg("target_probabilities_path", "--target-probabilities-path"),
    _arg("time_courses_path", "--time-courses-path"),
    _arg("city_logistics_path", "--city-logistics-path"),
    _arg("times_path", "--times-path"),
    _arg("indices_path", "--indices-path"),
    _arg("relations_path", "--relations-path"),
    _arg("stops_path", "--stops-path"),
    _arg("oneway_flows_path", "--oneway-flows-path"),
    _arg("ncores", "--ncores"),
    _arg("sample", "--sample"),
    _arg("include_teleported", "--include-teleported", "flag"),
    _arg("incremental_capacity_allocation_parts", "--incremental-capacity-allocation-parts"),
)
CONFIG_ARGS = (
    _arg("net_path", "--net-path"),
    _arg("population_path", "--population-path"),
    _arg("output_config_path", "--output-config-path"),
    _arg("schedule_path", "--schedule-path"),
    _arg("vehicles_path", "--vehicles-path"),
    _arg("number_of_threads", "--number-of-threads"),
    _arg("last_iteration", "--last-iteration"),
    _arg("matsim_output_directory", "--matsim-output-directory"),
    _arg("lane_definitions_path", "--lane-definitions-path"),
    _arg("write_events_interval", "--write-events-interval"),
    _arg("disable_innovations_after_fraction", "--disable-innovations-after-fraction"),
    _arg("mutation_range", "--mutation-range"),
    _arg("scoring_parameters_path", "--scoring-parameters-path"),
    _arg("minibus_parameters_path", "--minibus-parameters-path"),
)
ANALYSIS_ARGS = (
    _arg("events_path", "--events-path"),
    _arg("net_path", "--net-path"),
    _arg("legs_path", "--legs-path"),
    _arg("output_transfers_path", "--output-transfers-path"),
    _arg("output_counts_path", "--output-counts-path"),
    _arg("output_turns_path", "--output-turns-path"),
    _arg("output_net_counts_path", "--output-net-counts-path"),
    _arg("schedule_path", "--schedule-path"),
    _arg("output_pt_counts_path", "--output-pt-counts-path"),
    _arg("output_pt_net_counts_path", "--output-pt-net-counts-path"),
    _arg("output_pt_stops_counts_path", "--output-pt-stops-counts-path"),
    _arg("links_nodes_groups", "--links-nodes-groups"),
    _arg("output_ribbon_diagrams_directory", "--output-ribbon-diagrams-directory"),
    _arg("road_links_ids", "--road-links-ids"),
    _arg("output_road_links_intensities_directory", "--output-road-links-intensities-directory"),
    _arg("pt_links_ids", "--pt-links-ids"),
    _arg("pt_lines_ids", "--pt-lines-ids"),
    _arg("output_pt_links_intensities_directory", "--output-pt-links-intensities-directory"),
    _arg("output_pt_lines_intensities_directory", "--output-pt-lines-intensities-directory"),
    _arg("cordon_poly_path", "--cordon-poly-path"),
    _arg("output_cordon_stats_path", "--output-cordon-stats-path"),
    _arg("volume_poly_path", "--volume-poly-path"),
    _arg("output_volume_stats_path", "--output-volume-stats-path"),
    _arg("output_road_db_path", "--output-road-db-path"),
    _arg("output_road_db_flush_interval", "--output-road-db-flush-interval"),
)
COMPARISON_ARGS = (
    _arg("orig_net_path", "--orig-net-path"),
    _arg("edge_net_path", "--edge-net-path"),
    _arg("net_counts_path", "--net-counts-path"),
    _arg("network_intensities_path", "--network-intensities-path"),
    _arg("network_differences_save_path", "--network-differences-save-path"),
    _arg("network_differences_stats_save_path", "--network-differences-stats-save-path"),
    _arg("intersection_intensities_path", "--intersection-intensities-path"),
    _arg("intersection_differences_save_path", "--intersection-differences-save-path"),
    _arg("intersection_differences_stats_save_path", "--intersection-differences-stats-save-path"),
    _arg("difference_thresh", "--difference-thresh"),
    _arg("prev_net_counts_path", "--prev-net-counts-path"),
    _arg("prev_pt_net_counts_path", "--prev-pt-net-counts-path"),
    _arg("prev_pt_stops_counts_path", "--prev-pt-stops-counts-path"),
    _arg("pt_net_counts_path", "--pt-net-counts-path"),
    _arg("pt_stops_counts_path", "--pt-stops-counts-path"),
    _arg("diff_net_counts_save_path", "--diff-net-counts-save-path"),
    _arg("diff_pt_net_counts_save_path", "--diff-pt-net-counts-save-path"),
    _arg("diff_pt_stops_counts_save_path", "--diff-pt-stops-counts-save-path"),
)
GIS_ARGS = (
    _arg("project_path", "--project-path"),
    _arg("input_facilities", "--input-facilities"),
    _arg("input_edges", "--input-edges"),
    _arg("input_nodes", "--input-nodes"),
    _arg("output_road_counts", "--output-road-counts"),
    _arg("output_pt_counts", "--output-pt-counts"),
    _arg("output_pt_stops", "--output-pt-stops"),
    _arg("output_cordons_stats", "--output-cordons-stats"),
    _arg("output_volumes_stats", "--output-volumes-stats"),
    _arg("comparison_rw_road_diffs", "--comparison-rw-road-diffs"),
    _arg("comparison_rw_road_intersection_diffs", "--comparison-rw-road-intersection-diffs"),
    _arg("comparison_model_road_diffs", "--comparison-model-road-diffs"),
    _arg("comparison_model_pt_diffs", "--comparison-model-pt-diffs"),
    _arg("comparison_model_pt_stops_diffs", "--comparison-model-pt-stops-diffs"),
)


FIELD_CLASSIFICATIONS = MappingProxyType({
    "network": MappingProxyType({
        "control": ("launch", "existing"),
        "selector": ("nettype",),
        "argv": tuple(sorted(set(
            spec.field for spec in NETWORK_CEDA_ARGS + NETWORK_GENERIC_ARGS
        ))),
        "tool": (),
        "output-policy": (),
    }),
    "pt": MappingProxyType({
        "control": ("launch",), "selector": (),
        "argv": tuple(spec.field for spec in PT_ARGS), "tool": (),
        "output-policy": (),
    }),
    "population": MappingProxyType({
        "control": ("launch", "existing"), "selector": (),
        "argv": tuple(spec.field for spec in POPULATION_ARGS), "tool": (),
        "output-policy": (),
    }),
    "config": MappingProxyType({
        "control": ("launch",), "selector": (),
        "argv": tuple(spec.field for spec in CONFIG_ARGS), "tool": (),
        "output-policy": (),
    }),
    "model": MappingProxyType({
        "control": ("launch",), "selector": (), "argv": ("config_path", "ram_limit"),
        "tool": ("executable_path", "custom_class"), "output-policy": (),
    }),
    "analysis": MappingProxyType({
        "control": ("launch",), "selector": (),
        "argv": tuple(spec.field for spec in ANALYSIS_ARGS), "tool": (),
        "output-policy": (),
    }),
    "comparison": MappingProxyType({
        "control": ("launch",), "selector": (),
        "argv": tuple(spec.field for spec in COMPARISON_ARGS), "tool": (),
        "output-policy": (),
    }),
    "gis": MappingProxyType({
        "control": ("launch",), "selector": (),
        "argv": tuple(spec.field for spec in GIS_ARGS), "tool": ("qgis_path",),
        "output-policy": (),
    }),
})


OUTPUT_RULES = MappingProxyType({
    "network": (
        OutputRule("network.effective"), OutputRule("network.edges"),
        OutputRule("network.nodes"), OutputRule("network.lanes"),
    ),
    "pt": (
        OutputRule("pt.effective-network"), OutputRule("pt.schedule"),
        OutputRule("pt.vehicles"),
    ),
    "population": (
        OutputRule("population.xml"), OutputRule("population.facilities-counts"),
    ),
    "config": (
        OutputRule("config.matsim"), OutputRule("config.model-root"),
    ),
    "model": (
        OutputRule("model.events"), OutputRule("model.network"),
        OutputRule("model.legs"),
        OutputRule(
            "model.schedule",
            "all-fields-present",
            ("config.schedule_path", "config.vehicles_path"),
        ),
    ),
    "analysis": (
        OutputRule("analysis.road-counts"), OutputRule("analysis.turns"),
        OutputRule("analysis.road-net-counts"), OutputRule("analysis.transfers"),
        OutputRule("analysis.pt-counts"), OutputRule("analysis.pt-net-counts"),
        OutputRule("analysis.pt-stop-counts"), OutputRule("analysis.cordon-stats"),
        OutputRule("analysis.volume-stats"),
    ),
    "comparison": (
        OutputRule("comparison.rw-network-diff"),
        OutputRule("comparison.rw-intersection-diff"),
        OutputRule("comparison.model-road-diff"),
        OutputRule("comparison.model-pt-diff"),
        OutputRule("comparison.model-pt-stop-diff"),
    ),
    "gis": (OutputRule("gis.project"),),
})


def encode_arguments(values: Mapping[str, Any], specs: Sequence[ArgSpec]) -> Tuple[str, ...]:
    """Encode only explicit reviewed arguments."""

    result = []
    for spec in specs:
        if spec.field not in values:
            raise ValueError("argument field is absent: {0}".format(spec.field))
        value = values[spec.field]
        if value is None:
            continue
        if spec.encoding == "flag":
            if type(value) is not bool:
                raise TypeError("flag field must be an exact boolean: {0}".format(spec.field))
            if value:
                result.append(spec.option)
            continue
        if isinstance(value, bool):
            raise TypeError("scalar argument may not be boolean: {0}".format(spec.field))
        if spec.encoding == "comma-int":
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise TypeError("comma-int argument must be an integer sequence")
            if any(type(item) is not int for item in value):
                raise TypeError("comma-int items must be exact integers")
            encoded = ",".join(str(item) for item in value)
        elif spec.encoding == "semicolon-comma-int":
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise TypeError(
                    "semicolon-comma-int argument must be a sequence of groups"
                )
            groups = []
            for group in value:
                if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
                    raise TypeError("semicolon-comma-int groups must be sequences")
                if any(type(item) is not int for item in group):
                    raise TypeError(
                        "semicolon-comma-int items must be exact integers"
                    )
                groups.append(",".join(str(item) for item in group))
            encoded = ";".join(groups)
        else:
            if not isinstance(value, (str, int, float, Path)):
                raise TypeError("unsupported scalar argument type: {0}".format(spec.field))
            encoded = str(value)
        if not encoded and not spec.allow_empty:
            raise ValueError("empty argument is not permitted: {0}".format(spec.field))
        if "\x00" in encoded:
            raise ValueError("argument contains NUL: {0}".format(spec.field))
        result.extend((spec.option, encoded))
    return tuple(result)


def _field(config: RunConfig, dotted: str) -> Any:
    stage, name = dotted.split(".", 1)
    return config.stages[stage][name]


def _outputs(
    planned_stage: PlannedStage,
    config: RunConfig,
) -> Tuple[OutputExpectation, ...]:
    rules = {rule.identifier: rule for rule in OUTPUT_RULES[planned_stage.spec.name]}
    result = []
    for output in planned_stage.outputs:
        rule = rules.get(output.identifier)
        if rule is None:
            raise ExecutionRegistryError(
                "planned output has no execution rule: {0}".format(output.identifier)
            )
        active = rule.activation == "planned" or all(
            _field(config, field) is not None for field in rule.fields
        )
        if active:
            result.append(OutputExpectation(output.identifier, output.path, output.kind))
    return tuple(result)


def _missing_dependency(stage: str, field: str, message: str, hint: Optional[str] = None) -> PreparationError:
    return PreparationError(execution_issue(
        "KAM-EXEC-E102", stage + ":" + field, message, hint
    ))


def _require_file(path: Optional[Path], stage: str, field: str) -> Path:
    if path is None:
        raise _missing_dependency(stage, field, "required executable or file is unavailable")
    normalized = Path(path)
    try:
        if not normalized.is_file():
            raise _missing_dependency(
                stage, field, "required file is unavailable: {0}".format(normalized)
            )
    except OSError as error:
        raise _missing_dependency(
            stage,
            field,
            "required file cannot be inspected: {0} ({1})".format(
                normalized, type(error).__name__
            ),
        )
    return normalized


def _require_executable(
    path: Optional[Path], stage: str, field: str, platform: str
) -> Path:
    normalized = _require_file(path, stage, field)
    if platform == "posix" and not os.access(str(normalized), os.X_OK):
        raise _missing_dependency(
            stage,
            field,
            "required executable is not executable: {0}".format(normalized),
        )
    return normalized


def _python_prepared(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
    relative_script: str,
    specs: Sequence[ArgSpec],
    *,
    executable: Optional[Path] = None,
    environment_overrides: Optional[Mapping[str, str]] = None,
    environment_path_prepend: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> PreparedStage:
    stage = planned_stage.spec.name
    interpreter = _require_executable(
        executable or environment.python_executable,
        stage,
        "executable",
        environment.platform,
    )
    script = _require_file(environment.package_root / relative_script, stage, "script")
    argv = (
        str(interpreter), "-u", str(script),
        *encode_arguments(config.stages[stage], specs),
    )
    invocation = ProcessInvocation(
        stage,
        argv,
        context.workspace,
        environment_overrides or {},
        environment_path_prepend or {},
        context.log_directory / (stage + ".log"),
    )
    return PreparedStage(planned_stage, invocation, _outputs(planned_stage, config))


def prepare_network(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    nettype = config.stages["network"]["nettype"]
    if nettype == "ceda":
        return _python_prepared(
            planned_stage, config, context, environment,
            "input/network/ceda.py", NETWORK_CEDA_ARGS,
        )
    if nettype == "generic":
        return _python_prepared(
            planned_stage, config, context, environment,
            "input/network/generic.py", NETWORK_GENERIC_ARGS,
        )
    raise PreparationError(execution_issue(
        "KAM-EXEC-E101",
        "network:nettype",
        "selected network stage requires nettype ceda or generic",
    ))


def prepare_pt(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    _require_file(
        environment.package_root / "bin" / "pt2matsim-22.3-shaded.jar",
        "pt",
        "pt2matsim-jar",
    )
    _require_file(
        environment.package_root / "defaults" / "matsim" / "vehicles.xml",
        "pt",
        "default-vehicles",
    )
    return _python_prepared(
        planned_stage, config, context, environment,
        "input/network/pt.py", PT_ARGS,
    )


def prepare_population(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    return _python_prepared(
        planned_stage, config, context, environment,
        "input/population/load.py", POPULATION_ARGS,
    )


def prepare_config(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    return _python_prepared(
        planned_stage, config, context, environment,
        "model/config.py", CONFIG_ARGS,
    )


def prepare_model(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    values = config.stages["model"]
    java = _require_executable(
        environment.java_executable, "model", "java", environment.platform
    )
    jar = _require_file(values["executable_path"], "model", "executable_path")
    custom_class = values["custom_class"]
    try:
        if custom_class:
            runnable = custom_class
        else:
            runnable = get_matsim_runnable_class(get_matsim_version(jar))
    except Exception as error:
        raise _missing_dependency(
            "model",
            "executable_path",
            "MATSim runnable class cannot be resolved ({0})".format(
                type(error).__name__
            ),
        )
    argv = (
        str(java),
        "-Xmx{0}".format(values["ram_limit"]),
        "-cp",
        str(jar),
        str(runnable),
        str(values["config_path"]),
    )
    invocation = ProcessInvocation(
        "model", argv, context.workspace, {}, {},
        context.log_directory / "model.log",
    )
    return PreparedStage(planned_stage, invocation, _outputs(planned_stage, config))


def prepare_analysis(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    return _python_prepared(
        planned_stage, config, context, environment,
        "output/analysis.py", ANALYSIS_ARGS,
    )


def prepare_comparison(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    return _python_prepared(
        planned_stage, config, context, environment,
        "output/comparison.py", COMPARISON_ARGS,
    )


def _qgis_interpreter(path: Optional[Path], platform: str) -> Path:
    if path is None:
        raise _missing_dependency("gis", "qgis_path", "QGIS runtime is unavailable")
    root = Path(path)
    if root.is_file():
        return root
    if not root.is_dir():
        raise _missing_dependency(
            "gis", "qgis_path", "QGIS runtime is unavailable: {0}".format(root)
        )
    relative = (
        ("python.exe",),
        ("bin", "python.exe"),
        ("apps", "Python312", "python.exe"),
        ("apps", "Python311", "python.exe"),
        ("apps", "Python39", "python.exe"),
    ) if platform == "windows" else (
        ("python3",),
        ("python",),
        ("bin", "python3"),
        ("Contents", "MacOS", "bin", "python3"),
    )
    for parts in relative:
        candidate = root.joinpath(*parts)
        if candidate.is_file():
            return candidate
    raise _missing_dependency(
        "gis",
        "qgis_path",
        "QGIS directory contains no approved Python interpreter: {0}".format(root),
        "configure the exact QGIS-capable Python executable",
    )


def prepare_gis(
    planned_stage: PlannedStage,
    config: RunConfig,
    context: RunContext,
    environment: ExecutionEnvironment,
) -> PreparedStage:
    qgis_value = config.stages["gis"]["qgis_path"]
    interpreter = _require_executable(
        _qgis_interpreter(qgis_value, environment.platform),
        "gis",
        "qgis_path",
        environment.platform,
    )
    root = Path(qgis_value) if qgis_value is not None else interpreter.parent
    if root.is_file():
        root = root.parent
    if environment.platform == "windows":
        additions = (
            str(root / "apps" / "qgis" / "python"),
            str(root / "apps" / "qgis" / "python" / "plugins"),
            str(environment.package_root.parent),
        )
    else:
        additions = (
            str(root / "share" / "qgis" / "python" / "plugins"),
            str(root / "share" / "qgis" / "python"),
            "/usr/share/qgis/python/plugins",
            "/usr/share/qgis/python",
            str(environment.package_root.parent),
        )
    return _python_prepared(
        planned_stage, config, context, environment,
        "output/gis/qgis_project.py", GIS_ARGS,
        executable=interpreter,
        environment_path_prepend={"PYTHONPATH": tuple(dict.fromkeys(additions))},
    )


ADAPTERS = MappingProxyType({
    "network": StageAdapter(
        "network", prepare_network, "python",
        "Python interpreter and configured network converter script",
    ),
    "pt": StageAdapter(
        "pt", prepare_pt, "python-java-resource",
        "Python interpreter and packaged PT2MATSim resources",
    ),
    "population": StageAdapter(
        "population", prepare_population, "python",
        "Python interpreter and packaged population script",
    ),
    "config": StageAdapter(
        "config", prepare_config, "python",
        "Python interpreter and packaged MATSim configuration script",
    ),
    "model": StageAdapter(
        "model", prepare_model, "java",
        "Java executable and configured MATSim executable JAR",
    ),
    "analysis": StageAdapter(
        "analysis", prepare_analysis, "python",
        "Python interpreter and packaged analysis script",
    ),
    "comparison": StageAdapter(
        "comparison", prepare_comparison, "python",
        "Python interpreter and packaged comparison script",
    ),
    "gis": StageAdapter(
        "gis", prepare_gis, "qgis-python",
        "Configured QGIS Python interpreter and packaged GIS script",
    ),
})


def _validate_registry() -> None:
    if tuple(ADAPTERS) != STAGE_NAMES:
        raise ExecutionRegistryError("adapter registry must match canonical stages")
    if any(ADAPTERS[name].stage != name for name in STAGE_NAMES):
        raise ExecutionRegistryError("adapter key/name mismatch")
    provided = {
        stage.name: tuple(item.identifier for item in stage.provides)
        for stage in STAGES
    }
    if tuple(OUTPUT_RULES) != STAGE_NAMES:
        raise ExecutionRegistryError("output rules must match canonical stages")
    for stage in STAGE_NAMES:
        rule_ids = tuple(rule.identifier for rule in OUTPUT_RULES[stage])
        if rule_ids != provided[stage] or len(rule_ids) != len(set(rule_ids)):
            raise ExecutionRegistryError(
                "output rule coverage/order mismatch: {0}".format(stage)
            )


_validate_registry()


def default_execution_environment() -> ExecutionEnvironment:
    """Resolve the native executable/package environment without executing tools."""

    java = shutil.which("java")
    return ExecutionEnvironment(
        "windows" if os.name == "nt" else "posix",
        Path(sys.executable).resolve(),
        None if java is None else Path(java).resolve(),
        Path(__file__).resolve().parents[2],
    )


_STATIC_PYTHON_SCRIPTS = MappingProxyType({
    "pt": "input/network/pt.py",
    "population": "input/population/load.py",
    "config": "model/config.py",
    "analysis": "output/analysis.py",
    "comparison": "output/comparison.py",
})


def _available_file(
    path: Optional[Path],
    platform: str,
    executable: bool = False,
) -> Tuple[bool, str]:
    if path is None:
        return False, "required path is not configured"
    candidate = Path(path)
    try:
        if not candidate.is_file():
            return False, "required file is unavailable: {0}".format(candidate)
        if executable and platform == "posix" and not os.access(str(candidate), os.X_OK):
            return False, "required executable is not executable: {0}".format(candidate)
    except OSError as error:
        return False, "required path cannot be inspected ({0})".format(type(error).__name__)
    return True, str(candidate)


def _python_runtime_status(
    environment: ExecutionEnvironment,
    relative_script: str,
) -> Tuple[bool, str]:
    python_ok, python_detail = _available_file(
        environment.python_executable,
        environment.platform,
        executable=True,
    )
    if not python_ok:
        return False, python_detail
    script_ok, script_detail = _available_file(
        environment.package_root / relative_script,
        environment.platform,
    )
    if not script_ok:
        return False, script_detail
    return True, "{0}; {1}".format(environment.python_executable, script_detail)


def inspect_stage_availability(
    config: Optional[RunConfig] = None,
    environment: Optional[ExecutionEnvironment] = None,
) -> Tuple[StageAvailability, ...]:
    """Inspect exact adapter requirements without importing or executing tools."""

    if config is not None and not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig or None")
    effective = environment or default_execution_environment()
    rows = []
    for spec in STAGES:
        adapter = ADAPTERS[spec.name]
        available = False
        status = "unavailable"
        detail: Optional[str]
        if spec.name == "network":
            if config is None:
                status = "configuration-required"
                detail = "network.nettype selects the exact converter script"
            else:
                script = {
                    "ceda": "input/network/ceda.py",
                    "generic": "input/network/generic.py",
                }.get(config.stages["network"].get("nettype"))
                if script is None:
                    detail = "network.nettype must be ceda or generic"
                else:
                    available, detail = _python_runtime_status(effective, script)
        elif spec.name in _STATIC_PYTHON_SCRIPTS:
            available, detail = _python_runtime_status(
                effective,
                _STATIC_PYTHON_SCRIPTS[spec.name],
            )
            if available and spec.name == "pt":
                for resource in (
                    effective.package_root / "bin" / "pt2matsim-22.3-shaded.jar",
                    effective.package_root / "defaults" / "matsim" / "vehicles.xml",
                ):
                    available, detail = _available_file(
                        resource,
                        effective.platform,
                    )
                    if not available:
                        break
        elif spec.name == "model":
            if config is None:
                status = "configuration-required"
                detail = "model.executable_path supplies the MATSim JAR"
            else:
                available, detail = _available_file(
                    effective.java_executable,
                    effective.platform,
                    executable=True,
                )
                if available:
                    jar = config.stages["model"].get("executable_path")
                    available, detail = _available_file(
                        jar,
                        effective.platform,
                    )
                if available and not config.stages["model"].get("custom_class"):
                    try:
                        get_matsim_runnable_class(get_matsim_version(Path(jar)))
                    except Exception as error:
                        available = False
                        detail = "MATSim runnable class cannot be resolved ({0})".format(
                            type(error).__name__
                        )
        else:
            if config is None:
                status = "configuration-required"
                detail = "gis.qgis_path supplies the QGIS runtime"
            else:
                qgis_value = config.stages["gis"].get("qgis_path")
                try:
                    interpreter = _qgis_interpreter(qgis_value, effective.platform)
                except PreparationError as error:
                    detail = error.issue.message
                except (OSError, TypeError, ValueError) as error:
                    detail = "QGIS interpreter cannot be resolved ({0})".format(
                        type(error).__name__
                    )
                else:
                    available, detail = _available_file(
                        interpreter,
                        effective.platform,
                        executable=True,
                    )
                    if available:
                        available, detail = _available_file(
                            effective.package_root / "output/gis/qgis_project.py",
                            effective.platform,
                        )
        if status != "configuration-required":
            status = "available" if available else "unavailable"
        rows.append(StageAvailability(
            spec.name,
            spec.description,
            spec.dependencies,
            adapter.execution_family,
            adapter.runtime_requirement,
            status,
            detail,
        ))
    return tuple(rows)


def prepare_execution(
    plan: ExecutionPlan,
    context: RunContext,
    environment: ExecutionEnvironment,
    adapters: Mapping[str, StageAdapter] = ADAPTERS,
) -> PreparationResult:
    """Prepare every selected stage without exposing a partial result."""

    issues = []
    prepared = []
    if context.workspace != plan.config.workspace:
        issues.append(execution_issue(
            "KAM-EXEC-E101",
            "run:workspace",
            "run context workspace does not match the execution plan",
        ))
    if tuple(adapters) != STAGE_NAMES or any(
        name not in adapters or adapters[name].stage != name for name in STAGE_NAMES
    ):
        issues.append(execution_issue(
            "KAM-EXEC-E100",
            "run:adapters",
            "execution adapter registry does not match canonical stages",
        ))
    if issues:
        return PreparationResult((), tuple(issues))
    for planned_stage in plan.stages:
        name = planned_stage.spec.name
        try:
            prepared.append(adapters[name].prepare(
                planned_stage, plan.config, context, environment
            ))
        except PreparationError as error:
            issues.append(error.issue)
        except (ExecutionRegistryError, KeyError, TypeError, ValueError, OSError) as error:
            issues.append(execution_issue(
                "KAM-EXEC-E101",
                name + ":invocation",
                "stage invocation cannot be prepared ({0})".format(
                    type(error).__name__
                ),
            ))
    if issues:
        return PreparationResult((), tuple(issues))
    return PreparationResult(tuple(prepared), ())


__all__ = [
    "ADAPTERS",
    "ANALYSIS_ARGS",
    "ARG_ENCODINGS",
    "ArgSpec",
    "COMPARISON_ARGS",
    "CONFIG_ARGS",
    "ExecutionRegistryError",
    "EXECUTION_FAMILIES",
    "FIELD_CLASSIFICATIONS",
    "GIS_ARGS",
    "NETWORK_CEDA_ARGS",
    "NETWORK_GENERIC_ARGS",
    "OUTPUT_RULES",
    "OutputRule",
    "POPULATION_ARGS",
    "PT_ARGS",
    "PreparationError",
    "StageAdapter",
    "default_execution_environment",
    "encode_arguments",
    "inspect_stage_availability",
    "prepare_execution",
]
