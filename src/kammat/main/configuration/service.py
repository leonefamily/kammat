"""Configuration source adapters, normalization, validation, and filesystem ports."""

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from .model import (
    ConfigResult,
    ConfigurationError,
    ISSUE_CATALOG,
    RunConfig,
    STAGE_ORDER,
    ValidationIssue,
    thaw,
)
from .schema import FIELD_MAP, SCHEMA


PathLike = Union[str, os.PathLike]

GUI_KEYS = frozenset({
    "-ANALYZE-", "-CATPATH-", "-CCLASS-", "-CLOGPATH-", "-CLOGSPATH-",
    "-CLUSTPATH-", "-COMPARE-", "-CORDPOLYPATH-", "-DBFLUSH-",
    "-DIARPATH-", "-DISTPATH-", "-ELDEFPATH-", "-ENETPATH-",
    "-EPOPPATH-", "-ESCHEDPATH-", "-EVEHSPATH-", "-EVENTSDB-",
    "-FREPATH-", "-GTFSPATH-", "-IINTPATH-", "-INCRCAP-", "-INDPATH-",
    "-ITERS-", "-LCONPATH-", "-LINKGROUPS-", "-LINKINTENS-",
    "-MATSIMPATH-", "-MATSIMRAM-", "-MSPATH-", "-MUTFRAC-",
    "-NETGEN-", "-NETPATH-", "-NINTPATH-", "-OFLOWPATH-",
    "-PARENTPATH-", "-PMODPATH-", "-POPFRAC-", "-POPPATH-",
    "-PPARSPATH-", "-PTLINEINTENS-", "-PTLINKINTENS-", "-QGIS-",
    "-QGISPATH-", "-RELPATH-", "-RUNMOD-", "-SCPARSPATH-",
    "-SIMPLEINT-", "-STAYPATH-", "-STOPPATH-", "-TARGPATH-",
    "-TCOURPATH-", "-THREADS-", "-TIMEMUT-", "-TIMEPATH-",
    "-TRANPATH-", "-USENET-", "-USEPOP-", "-UTURNS-",
    "-VOLPOLYPATH-", "-WDPATH-", "-WRITETP-",
})

ISSUE_CODES = frozenset(ISSUE_CATALOG)

WORKSPACE_DIRECTORIES = (
    "network",
    "population",
    "population/relations",
    "model",
    "analysis",
    "analysis/nodes",
    "analysis/links",
    "analysis/links/road",
    "analysis/links/pt",
    "comparison",
)

_ENV_PATTERN = re.compile(
    r"(^~)|\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})"
    r"|%[A-Za-z_][A-Za-z0-9_]*%"
)
_RAM_PATTERN = re.compile(r"^[1-9][0-9]*[kmgKMG]$")
_CLASS_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)+$")
_LEGACY_INT_PATTERN = re.compile(r"^[+-]?[0-9]+$")
_LEGACY_FLOAT_PATTERN = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)


def _issue(
    code: str,
    field: str,
    message: str,
    *,
    level: str = "error",
    hint: Optional[str] = None,
) -> ValidationIssue:
    return ValidationIssue(code, level, field, message, hint)


def _lexical_absolute(value: PathLike, base: Optional[Path] = None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        if base is None:
            raise ValueError("relative path requires explicit provenance")
        path = base / path
    return Path(os.path.abspath(os.fspath(path)))


def _sort_issues(issues: Iterable[ValidationIssue]) -> Tuple[ValidationIssue, ...]:
    stage_rank = {stage: index + 2 for index, stage in enumerate(STAGE_ORDER)}

    def key(issue: ValidationIssue) -> Tuple[int, str, str, str]:
        root = issue.field.split(".", 1)[0]
        if root in {"schema_version", "$"} or (
            "." not in issue.field
            and root not in {"workspace", *STAGE_ORDER}
        ):
            rank = 0
        elif root == "workspace":
            rank = 1
        else:
            rank = stage_rank.get(root, len(stage_rank) + 2)
        return rank, issue.field, issue.code, issue.message

    unique: Dict[Tuple[str, str, str, str], ValidationIssue] = {}
    for issue in issues:
        identity = (issue.code, issue.level, issue.field, issue.message)
        unique.setdefault(identity, issue)
    return tuple(sorted(unique.values(), key=key))


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def _normalize_scalar(
    value: Any,
    kind: str,
    source_version: int,
    field_path: str,
    issues: List[ValidationIssue],
) -> Any:
    if kind == "bool":
        if type(value) is bool:
            return value
    elif kind == "int":
        if type(value) is int:
            return value
        if (
            source_version == 0
            and isinstance(value, str)
            and _LEGACY_INT_PATTERN.fullmatch(value.strip())
        ):
            try:
                converted = int(value)
            except ValueError:
                pass
            else:
                issues.append(_issue(
                    "KAM-CFG-W101", field_path,
                    "legacy integer string was converted",
                    level="warning",
                ))
                return converted
    elif kind == "float":
        if type(value) in {int, float} and not isinstance(value, bool):
            if math.isfinite(float(value)):
                return value
        if (
            source_version == 0
            and isinstance(value, str)
            and _LEGACY_FLOAT_PATTERN.fullmatch(value.strip())
        ):
            try:
                converted = float(value)
            except ValueError:
                converted = float("nan")
            if math.isfinite(converted):
                issues.append(_issue(
                    "KAM-CFG-W101", field_path,
                    "legacy decimal string was converted",
                    level="warning",
                ))
                return converted
    elif kind == "str" and isinstance(value, str):
        return value.strip()
    issues.append(_issue(
        "KAM-CFG-E200",
        field_path,
        "expected {0}, received {1}".format(kind, type(value).__name__),
    ))
    return value


def _normalize_path(
    value: Any,
    base: Path,
    field_path: str,
    issues: List[ValidationIssue],
) -> Any:
    if not isinstance(value, (str, os.PathLike)):
        issues.append(_issue(
            "KAM-CFG-E200", field_path,
            "expected path string, received {0}".format(type(value).__name__),
        ))
        return value
    text = os.fspath(value)
    if not isinstance(text, str):
        text = str(text)
    if "\x00" in text:
        issues.append(_issue("KAM-CFG-E300", field_path, "path contains NUL"))
        return Path(text.replace("\x00", ""))
    if _ENV_PATTERN.search(text):
        issues.append(_issue(
            "KAM-CFG-E300", field_path,
            "home and environment-variable expansion is prohibited",
        ))
    try:
        return _lexical_absolute(text, base)
    except (OSError, ValueError) as error:
        issues.append(_issue("KAM-CFG-E300", field_path, str(error)))
        return Path(text)


def _source_version(raw: Mapping[str, Any], issues: List[ValidationIssue]) -> Optional[int]:
    if "schema_version" not in raw:
        return 0
    value = raw["schema_version"]
    if type(value) is not int:
        issues.append(_issue(
            "KAM-CFG-E100", "schema_version",
            "schema_version must be an integer and boolean is not accepted",
        ))
        return None
    if value not in {0, 1}:
        issues.append(_issue(
            "KAM-CFG-E100", "schema_version",
            "unsupported schema version {0}".format(value),
        ))
        return value
    return value


def normalize_config(
    raw: Mapping[str, Any],
    *,
    config_path: PathLike,
    source_version: int,
    _source_label: str = "json",
    _provenance_seed: Optional[Mapping[str, str]] = None,
) -> ConfigResult:
    """Normalize one decoded mapping using explicit source provenance."""
    issues: List[ValidationIssue] = []
    if not isinstance(raw, Mapping):
        return ConfigResult(
            None,
            (_issue("KAM-CFG-E002", "$", "configuration root must be an object"),),
            source_version,
            {},
        )
    if source_version not in {0, 1}:
        return ConfigResult(
            None,
            (_issue(
                "KAM-CFG-E100", "schema_version",
                "unsupported schema version {0}".format(source_version),
            ),),
            source_version,
            {},
        )

    try:
        path = _lexical_absolute(config_path)
    except ValueError as error:
        return ConfigResult(
            None,
            (_issue("KAM-CFG-E300", "$", str(error)),),
            source_version,
            {},
        )
    base = path.parent
    provenance: Dict[str, str] = dict(_provenance_seed or {})
    working: Mapping[str, Any] = raw
    if source_version == 0:
        issues.append(_issue(
            "KAM-CFG-W100", "schema_version",
            "schema-version-0 configuration was adapted in memory",
            level="warning",
        ))
        wd = raw.get("wd", {})
        workspace_value = wd.get("root") if isinstance(wd, Mapping) else None
    else:
        workspace_value = raw.get("workspace")
        allowed_root = {"schema_version", "workspace", *STAGE_ORDER}
        for name in sorted(set(raw).difference(allowed_root)):
            issues.append(_issue(
                "KAM-CFG-E101", name,
                "unknown schema-version-1 root field",
            ))

    if workspace_value is None:
        issues.append(_issue("KAM-CFG-E102", "workspace", "workspace is required"))
        workspace = base
        provenance.setdefault("workspace", "default")
    else:
        workspace = _normalize_path(workspace_value, base, "workspace", issues)
        if not isinstance(workspace, Path):
            workspace = base
        provenance.setdefault("workspace", _source_label)

    stages: Dict[str, Dict[str, Any]] = {}
    for stage in STAGE_ORDER:
        section = working.get(stage)
        if not isinstance(section, Mapping):
            issues.append(_issue(
                "KAM-CFG-E102" if section is None else "KAM-CFG-E200",
                stage,
                "stage section must be an object",
            ))
            section = {}
        known = FIELD_MAP[stage]
        if source_version == 1:
            for name in sorted(set(section).difference(known)):
                issues.append(_issue(
                    "KAM-CFG-E101", stage + "." + name,
                    "unknown schema-version-1 stage field",
                ))
        normalized: Dict[str, Any] = {}
        for spec in SCHEMA[stage]:
            field_path = stage + "." + spec.name
            if spec.name not in section:
                if spec.required_when == "always":
                    issues.append(_issue(
                        "KAM-CFG-E102", field_path, "required field is missing"
                    ))
                normalized[spec.name] = spec.default
                provenance.setdefault(field_path, "default")
                continue
            value = section[spec.name]
            provenance.setdefault(field_path, _source_label)
            if value is None or (isinstance(value, str) and not value.strip()):
                if spec.nullable:
                    normalized[spec.name] = None
                else:
                    issues.append(_issue(
                        "KAM-CFG-E102", field_path, "field may not be null or blank"
                    ))
                    normalized[spec.name] = None
                continue
            if spec.value_kind == "path":
                value = _normalize_path(value, base, field_path, issues)
            else:
                value = _normalize_scalar(
                    value, spec.value_kind, source_version, field_path, issues
                )
            if spec.allowed_values and value not in spec.allowed_values:
                issues.append(_issue(
                    "KAM-CFG-E201", field_path,
                    "value must be one of {0}".format(spec.allowed_values),
                ))
            normalized[spec.name] = value
        if source_version == 0:
            for name in sorted(set(section).difference(known)):
                normalized[name] = section[name]
                provenance.setdefault(stage + "." + name, _source_label)
                issues.append(_issue(
                    "KAM-CFG-W102", stage + "." + name,
                    "unknown legacy field was preserved for audit and omitted from projection",
                    level="warning",
                ))
        stages[stage] = normalized

    config = RunConfig(1, path, workspace, stages)
    semantic = validate_configuration(config)
    return ConfigResult(
        config,
        _sort_issues([*issues, *semantic]),
        source_version,
        provenance,
    )


def _path_issue(
    issues: List[ValidationIssue],
    field: str,
    path: Path,
    expected: str,
) -> None:
    if not path.exists():
        issues.append(_issue(
            "KAM-CFG-E301", field,
            "required {0} does not exist: {1}".format(expected, path),
        ))
    elif expected == "file" and not path.is_file():
        issues.append(_issue("KAM-CFG-E302", field, "expected an existing file"))
    elif expected == "directory" and not path.is_dir():
        issues.append(_issue("KAM-CFG-E302", field, "expected an existing directory"))


def _generated_path_issue(
    issues: List[ValidationIssue],
    field: str,
    path: Path,
    expected: str,
) -> None:
    if path.exists():
        if expected == "file" and not path.is_file():
            issues.append(_issue(
                "KAM-CFG-E302", field,
                "generated file path is an existing non-file",
            ))
        elif expected == "directory" and not path.is_dir():
            issues.append(_issue(
                "KAM-CFG-E302", field,
                "generated directory path is an existing non-directory",
            ))
        return
    ancestor = path.parent
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if ancestor.exists() and not ancestor.is_dir():
        issues.append(_issue(
            "KAM-CFG-E302", field,
            "generated path has a non-directory ancestor: {0}".format(ancestor),
        ))


def _relation(
    issues: List[ValidationIssue],
    field: str,
    condition: bool,
    message: str,
) -> None:
    if not condition:
        issues.append(_issue("KAM-CFG-E400", field, message))


def validate_configuration(config: RunConfig) -> Tuple[ValidationIssue, ...]:
    """Return every safely discoverable stage and filesystem issue."""
    issues: List[ValidationIssue] = []
    stages = config.stages
    produced = set()
    for stage, specs in SCHEMA.items():
        if stages[stage].get("launch") is not True:
            continue
        for spec in specs:
            value = stages[stage].get(spec.name)
            if isinstance(value, Path) and spec.path_role in {"generated_file", "generated_directory"}:
                produced.add(value)
    if stages["network"].get("launch") is True:
        produced.add(stages["network"].get("net_save_path"))
    if stages["population"].get("launch") is True:
        produced.add(stages["population"].get("xml_path"))
    model_output = stages["config"].get("matsim_output_directory")
    if stages["model"].get("launch") is True and isinstance(model_output, Path):
        produced.update({
            model_output / "output_events.xml.gz",
            model_output / "output_network.xml.gz",
            model_output / "output_legs.csv.gz",
            model_output / "output_transitSchedule.xml.gz",
        })

    for stage, specs in SCHEMA.items():
        values = stages[stage]
        active = values.get("launch") is True or stage in {"network", "population", "config"}
        if not active:
            continue
        for spec in specs:
            value = values.get(spec.name)
            if not isinstance(value, Path):
                continue
            field_path = stage + "." + spec.name
            role = spec.path_role
            if role == "generated_file":
                _generated_path_issue(issues, field_path, value, "file")
                continue
            if role == "generated_directory":
                _generated_path_issue(issues, field_path, value, "directory")
                continue
            if role == "upstream_or_existing_file":
                if value in produced:
                    continue
                _path_issue(issues, field_path, value, "file")
            elif role in {"existing_file", "optional_existing_file", "external_file"}:
                _path_issue(issues, field_path, value, "file")
            elif role in {"existing_directory", "optional_existing_directory"}:
                _path_issue(issues, field_path, value, "directory")
            elif role == "external_directory_or_executable":
                if not value.exists():
                    issues.append(_issue(
                        "KAM-CFG-E301", field_path,
                        "external directory or executable does not exist: {0}".format(value),
                    ))

    network = stages["network"]
    _relation(
        issues, "network.existing",
        network.get("existing") is (network.get("launch") is not True),
        "existing must be the inverse of launch",
    )
    if network.get("launch") is True:
        _relation(issues, "network.nettype", network.get("nettype") in {"generic", "ceda"}, "generated network requires generic or ceda")
        _relation(issues, "network.shp_path", isinstance(network.get("shp_path"), Path), "generated network requires shp_path")
        if network.get("nettype") == "ceda":
            _relation(issues, "network.ncores", type(network.get("ncores")) is int and network["ncores"] > 0, "CEDA ncores must be positive")
            _relation(
                issues, "network.lane_definitions_save_path",
                bool(network.get("lane_connections_path")) == bool(network.get("lane_definitions_save_path")),
                "lane connection input and lane-definition output must be paired",
            )
            _relation(issues, "network.restrict_uturns", network.get("restrict_uturns") is None, "restrict_uturns applies only to generic generation")
        elif network.get("nettype") == "generic":
            _relation(issues, "network.restrict_uturns", type(network.get("restrict_uturns")) is bool, "generic generation requires restrict_uturns")
            for name in ("ncores", "lane_connections_path", "internal_maneuvers"):
                _relation(issues, "network." + name, network.get(name) is None, name + " applies only to CEDA generation")
    else:
        _relation(issues, "network.net_save_path", isinstance(network.get("net_save_path"), Path), "reused network path is required")

    pt = stages["pt"]
    _relation(issues, "pt.number_of_threads", type(pt.get("number_of_threads")) is int and pt["number_of_threads"] > 0, "thread count must be positive")
    _relation(
        issues, "pt.output_schedule_path",
        bool(pt.get("output_schedule_path")) == bool(pt.get("output_vehicles_path")),
        "schedule and vehicles paths must be paired",
    )
    _relation(issues, "pt.net_path", pt.get("net_path") == network.get("net_save_path"), "PT input network must equal the effective network output")
    _relation(issues, "pt.output_net_path", pt.get("output_net_path") == network.get("net_save_path"), "PT output network must equal the effective network output")
    if pt.get("launch") is True:
        _relation(issues, "pt.gtfs_folder", isinstance(pt.get("gtfs_folder"), Path), "selected PT generation requires gtfs_folder")
        _relation(issues, "pt.output_schedule_path", isinstance(pt.get("output_schedule_path"), Path), "selected PT generation requires schedule and vehicles outputs")

    population = stages["population"]
    _relation(
        issues, "population.existing",
        population.get("existing") is (population.get("launch") is not True),
        "existing must be the inverse of launch",
    )
    _relation(issues, "population.ncores", type(population.get("ncores")) is int and population["ncores"] > 0, "ncores must be positive")
    sample = population.get("sample")
    if sample is not None:
        _relation(issues, "population.sample", type(sample) in {int, float} and 0.0 < sample <= 1.0, "sample must be in (0, 1]")
    parts = population.get("incremental_capacity_allocation_parts")
    if parts is not None:
        _relation(issues, "population.incremental_capacity_allocation_parts", type(parts) is int and parts > 0, "incremental parts must be positive")
    if population.get("launch") is True:
        for name in ("facilities_path", "categories_path", "diaries_path", "distances_path"):
            _relation(issues, "population." + name, isinstance(population.get(name), Path), "population generation requires {0}".format(name))
    _relation(
        issues, "population.oneway_flows_path",
        not (population.get("oneway_flows_path") and (population.get("freight_points_path") or population.get("transit_points_path"))),
        "one-way flows are mutually exclusive with freight/transit point sources",
    )

    config_stage = stages["config"]
    _relation(issues, "config.net_path", config_stage.get("net_path") == network.get("net_save_path"), "config network must equal the effective network output")
    _relation(issues, "config.population_path", config_stage.get("population_path") == population.get("xml_path"), "config population must equal the effective population output")
    _relation(issues, "config.schedule_path", config_stage.get("schedule_path") == pt.get("output_schedule_path"), "config schedule must equal the effective PT schedule")
    _relation(issues, "config.vehicles_path", config_stage.get("vehicles_path") == pt.get("output_vehicles_path"), "config vehicles must equal the effective PT vehicles")
    _relation(issues, "config.lane_definitions_path", config_stage.get("lane_definitions_path") == network.get("lane_definitions_save_path"), "config lane definitions must equal the effective network lane definitions")
    for name in ("number_of_threads",):
        _relation(issues, "config." + name, type(config_stage.get(name)) is int and config_stage[name] > 0, name + " must be positive")
    for name in ("last_iteration", "write_events_interval"):
        _relation(issues, "config." + name, type(config_stage.get(name)) is int and config_stage[name] >= 0, name + " must be nonnegative")
    fraction = config_stage.get("disable_innovations_after_fraction")
    _relation(issues, "config.disable_innovations_after_fraction", type(fraction) in {int, float} and 0.0 <= fraction <= 1.0, "fraction must be in [0, 1]")
    mutation = config_stage.get("mutation_range")
    _relation(issues, "config.mutation_range", type(mutation) in {int, float} and mutation >= 0.0, "mutation range must be nonnegative")
    _relation(
        issues, "config.schedule_path",
        bool(config_stage.get("schedule_path")) == bool(config_stage.get("vehicles_path")),
        "schedule and vehicles paths must be paired",
    )

    model = stages["model"]
    if model.get("launch") is True:
        _relation(issues, "model.executable_path", isinstance(model.get("executable_path"), Path), "selected model requires executable_path")
    _relation(issues, "model.ram_limit", isinstance(model.get("ram_limit"), str) and bool(_RAM_PATTERN.fullmatch(model["ram_limit"])), "RAM limit must be a positive integer followed by k, m, or g")
    _relation(issues, "model.config_path", model.get("config_path") == config_stage.get("output_config_path"), "model config must equal the generated MATSim config")
    if model.get("custom_class") is not None:
        _relation(issues, "model.custom_class", isinstance(model.get("custom_class"), str) and bool(_CLASS_PATTERN.fullmatch(model["custom_class"])), "custom class must be a dotted Java class name")

    analysis = stages["analysis"]
    if analysis.get("launch") is True:
        for selector, output in (
            ("links_nodes_groups", "output_ribbon_diagrams_directory"),
            ("road_links_ids", "output_road_links_intensities_directory"),
            ("pt_links_ids", "output_pt_links_intensities_directory"),
            ("pt_lines_ids", "output_pt_lines_intensities_directory"),
            ("cordon_poly_path", "output_cordon_stats_path"),
            ("volume_poly_path", "output_volume_stats_path"),
        ):
            _relation(issues, "analysis." + selector, not analysis.get(selector) or bool(analysis.get(output)), selector + " requires " + output)
        if analysis.get("output_road_db_path"):
            interval = analysis.get("output_road_db_flush_interval")
            _relation(issues, "analysis.output_road_db_flush_interval", type(interval) is int and interval > 0, "database flush interval must be positive")

    comparison = stages["comparison"]
    threshold = comparison.get("difference_thresh")
    _relation(issues, "comparison.difference_thresh", type(threshold) in {int, float} and 0.0 <= threshold <= 1.0, "difference threshold must be in [0, 1]")
    if comparison.get("launch") is True:
        for name, expected in (
            ("net_counts_path", analysis.get("output_net_counts_path")),
            ("pt_net_counts_path", analysis.get("output_pt_net_counts_path")),
            ("pt_stops_counts_path", analysis.get("output_pt_stops_counts_path")),
        ):
            _relation(issues, "comparison." + name, comparison.get(name) == expected, name + " must equal the current analysis output")
        families = (
            comparison.get("network_intensities_path"),
            comparison.get("intersection_intensities_path"),
            comparison.get("prev_net_counts_path"),
            comparison.get("prev_pt_net_counts_path"),
            comparison.get("prev_pt_stops_counts_path"),
        )
        _relation(issues, "comparison", any(families), "selected comparison requires at least one observed or previous-model family")

    gis = stages["gis"]
    if gis.get("launch") is True:
        _relation(issues, "gis.qgis_path", isinstance(gis.get("qgis_path"), Path), "selected GIS requires qgis_path")
        layer_names = tuple(name for name in FIELD_MAP["gis"] if name.startswith("input_") or name.startswith("output_") or name.startswith("comparison_"))
        _relation(issues, "gis", any(gis.get(name) for name in layer_names), "selected GIS requires at least one input layer")

    return _sort_issues(issues)


def _load_raw(path: PathLike) -> Any:
    with open(path, mode="r", encoding="utf-8") as stream:
        return json.load(stream)


def load_run_config(path: PathLike) -> ConfigResult:
    """Load, version, normalize, and validate a JSON configuration."""
    source = _lexical_absolute(path, Path.cwd())
    try:
        raw = _load_raw(source)
    except FileNotFoundError:
        return ConfigResult(
            None,
            (_issue("KAM-CFG-E001", "$", "configuration file does not exist"),),
            None,
            {},
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return ConfigResult(
            None,
            (_issue("KAM-CFG-E001", "$", "cannot decode configuration: {0}".format(error)),),
            None,
            {},
        )
    if not isinstance(raw, Mapping):
        return ConfigResult(
            None,
            (_issue("KAM-CFG-E002", "$", "configuration root must be an object"),),
            None,
            {},
        )
    version_issues: List[ValidationIssue] = []
    version = _source_version(raw, version_issues)
    if version not in {0, 1}:
        return ConfigResult(None, _sort_issues(version_issues), version, {})
    result = normalize_config(raw, config_path=source, source_version=version)
    return ConfigResult(
        result.config,
        _sort_issues([*version_issues, *result.issues]),
        result.source_version,
        result.provenance,
    )


def _optional_path(value: Any) -> Optional[Path]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return Path(value)


def _load_neighbor(path: Path, stage: str) -> Tuple[Dict[str, Any], List[ValidationIssue]]:
    if not path.is_file():
        return {}, [_issue(
            "KAM-CFG-W200", stage,
            "neighboring settings metadata is unavailable",
            level="warning",
        )]
    result = load_run_config(path)
    if result.config is None or has_errors(result.issues):
        return {}, [_issue(
            "KAM-CFG-W200", stage,
            "neighboring settings metadata is invalid and was not merged",
            level="warning",
        )]
    values = thaw(result.config.stages[stage])
    return {name: values[name] for name in FIELD_MAP[stage] if name in values}, []


def create_config(gui_values: Mapping[str, Any]) -> ConfigResult:
    """Build the effective configuration solely from complete primitive GUI values."""
    issues: List[ValidationIssue] = []
    if not isinstance(gui_values, Mapping):
        return ConfigResult(None, (_issue("KAM-CFG-E002", "$", "GUI values must be a mapping"),), None, {})
    missing = sorted(GUI_KEYS.difference(gui_values))
    extra = sorted(set(gui_values).difference(GUI_KEYS))
    for key in missing:
        issues.append(_issue("KAM-CFG-E102", "gui." + key, "required GUI value is missing"))
    for key in extra:
        issues.append(_issue("KAM-CFG-E101", "gui." + key, "unknown GUI value"))
    for key, value in gui_values.items():
        if not isinstance(value, (type(None), bool, int, float, str)):
            issues.append(_issue("KAM-CFG-E200", "gui." + key, "GUI values must be primitive"))
    boolean_keys = {
        "-ANALYZE-", "-COMPARE-", "-EVENTSDB-", "-NETGEN-", "-QGIS-",
        "-RUNMOD-", "-SIMPLEINT-", "-USENET-", "-USEPOP-", "-UTURNS-",
        "-WRITETP-",
    }
    integer_keys = {"-DBFLUSH-", "-INCRCAP-", "-ITERS-", "-MATSIMRAM-", "-THREADS-"}
    number_keys = {"-MUTFRAC-", "-POPFRAC-", "-TIMEMUT-"}
    for key in sorted(boolean_keys.intersection(gui_values)):
        if type(gui_values[key]) is not bool:
            issues.append(_issue("KAM-CFG-E200", "gui." + key, "expected GUI boolean"))
    for key in sorted(integer_keys.intersection(gui_values)):
        if type(gui_values[key]) is not int:
            issues.append(_issue("KAM-CFG-E200", "gui." + key, "expected GUI integer"))
    for key in sorted(number_keys.intersection(gui_values)):
        value = gui_values[key]
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            issues.append(_issue("KAM-CFG-E200", "gui." + key, "expected finite GUI number"))
    for key in sorted(set(gui_values).difference(boolean_keys | integer_keys | number_keys)):
        if not isinstance(gui_values[key], str):
            issues.append(_issue("KAM-CFG-E200", "gui." + key, "expected GUI string"))
    if issues:
        return ConfigResult(None, _sort_issues(issues), None, {})

    values = dict(gui_values)
    parent_text = values["-PARENTPATH-"].strip()
    if not parent_text or not Path(parent_text).is_absolute() or _ENV_PATTERN.search(parent_text):
        return ConfigResult(None, (_issue(
            "KAM-CFG-E300", "gui.-PARENTPATH-",
            "parent path must be an explicit absolute path without expansion syntax",
        ),), None, {})
    parent = _lexical_absolute(parent_text)
    wd_name = str(values["-WDPATH-"]).strip()
    if not wd_name:
        return ConfigResult(None, (_issue("KAM-CFG-E102", "gui.-WDPATH-", "working-directory name is required"),), None, {})
    if Path(wd_name).is_absolute() or _ENV_PATTERN.search(wd_name) or "\x00" in wd_name:
        return ConfigResult(None, (_issue(
            "KAM-CFG-E300", "gui.-WDPATH-",
            "working-directory name must be a relative lexical path without expansion syntax",
        ),), None, {})
    workspace = _lexical_absolute(wd_name, parent)
    try:
        workspace.relative_to(parent)
    except ValueError:
        return ConfigResult(None, (_issue("KAM-CFG-E300", "workspace", "GUI workspace must remain beneath the selected parent"),), None, {})

    network_dir = workspace / "network"
    population_dir = workspace / "population"
    model_dir = workspace / "model"
    analysis_dir = workspace / "analysis"
    nodes_dir = analysis_dir / "nodes"
    road_dir = analysis_dir / "links" / "road"
    pt_dir = analysis_dir / "links" / "pt"
    comparison_dir = workspace / "comparison"

    use_network = values["-USENET-"] is True
    use_population = values["-USEPOP-"] is True
    net_neighbor: Dict[str, Any] = {}
    pop_neighbor: Dict[str, Any] = {}
    neighbor_issues: List[ValidationIssue] = []
    if use_network:
        existing_net = _lexical_absolute(values["-ENETPATH-"], workspace)
        net_neighbor, found = _load_neighbor(existing_net.parent.parent / "settings.json", "network")
        neighbor_issues.extend(found)
    if use_population:
        existing_pop = _lexical_absolute(values["-EPOPPATH-"], workspace)
        pop_neighbor, found = _load_neighbor(existing_pop.parent.parent / "settings.json", "population")
        neighbor_issues.extend(found)

    network: Dict[str, Any] = dict(net_neighbor)
    if use_network:
        network.update({
            "launch": False,
            "existing": True,
            "net_save_path": values["-ENETPATH-"],
            "lane_definitions_save_path": _optional_path(values["-ELDEFPATH-"]),
        })
    else:
        nettype = "generic" if values["-NETGEN-"] is True else "ceda"
        network = {
            "launch": True,
            "existing": False,
            "nettype": nettype,
            "shp_path": values["-NETPATH-"],
            "restrict_uturns": values["-UTURNS-"] if nettype == "generic" else None,
            "ncores": int(values["-THREADS-"]) if nettype == "ceda" else None,
            "lane_connections_path": _optional_path(values["-LCONPATH-"]) if nettype == "ceda" else None,
            "lane_definitions_save_path": network_dir / "lane_definitions.xml" if nettype == "ceda" and values["-LCONPATH-"] else None,
            "internal_maneuvers": values["-SIMPLEINT-"] if nettype == "ceda" else None,
            "edges_save_path": network_dir / "edges.shp",
            "nodes_save_path": network_dir / "nodes.shp",
            "net_save_path": network_dir / "net.xml",
        }

    pt_launch = bool(values["-GTFSPATH-"]) and not use_network
    pt = {
        "launch": pt_launch,
        "gtfs_folder": _optional_path(values["-GTFSPATH-"]) if pt_launch else None,
        "number_of_threads": int(values["-THREADS-"]),
        "net_path": network["net_save_path"],
        "output_net_path": network["net_save_path"],
        "output_schedule_path": network_dir / "schedule.xml" if pt_launch else _optional_path(values["-ESCHEDPATH-"]) if use_network else None,
        "output_vehicles_path": network_dir / "vehicles.xml" if pt_launch else _optional_path(values["-EVEHSPATH-"]) if use_network else None,
    }

    population: Dict[str, Any] = dict(pop_neighbor)
    if use_population:
        population.update({
            "launch": False,
            "existing": True,
            "xml_path": values["-EPOPPATH-"],
            "ncores": int(values["-THREADS-"]),
        })
    else:
        population = {
            "launch": True,
            "existing": False,
            "ncores": int(values["-THREADS-"]),
            "sample": values["-POPFRAC-"],
            "include_teleported": values["-WRITETP-"],
            "incremental_capacity_allocation_parts": int(values["-INCRCAP-"]),
            "facilities_path": values["-POPPATH-"],
            "categories_path": values["-CATPATH-"],
            "diaries_path": values["-DIARPATH-"],
            "distances_path": values["-DISTPATH-"],
            "clusters_path": _optional_path(values["-CLUSTPATH-"]),
            "citylog_points_path": _optional_path(values["-CLOGSPATH-"]),
            "staying_path": _optional_path(values["-STAYPATH-"]),
            "target_probabilities_path": _optional_path(values["-TARGPATH-"]),
            "time_courses_path": _optional_path(values["-TCOURPATH-"]),
            "city_logistics_path": _optional_path(values["-CLOGPATH-"]),
            "times_path": _optional_path(values["-TIMEPATH-"]),
            "modal_split_path": _optional_path(values["-MSPATH-"]),
            "indices_path": _optional_path(values["-INDPATH-"]),
            "relations_path": _optional_path(values["-RELPATH-"]),
            "stops_path": _optional_path(values["-STOPPATH-"]),
            "oneway_flows_path": _optional_path(values["-OFLOWPATH-"]),
            "freight_points_path": None if values["-OFLOWPATH-"] else _optional_path(values["-FREPATH-"]),
            "transit_points_path": None if values["-OFLOWPATH-"] else _optional_path(values["-TRANPATH-"]),
            "xml_path": population_dir / "population.xml.gz",
            "csv_path": None,
            "pickle_path": population_dir / "population.zx",
            "modal_split_save_path": population_dir / "modal_split.csv",
            "facilities_counts_save_path": population_dir / "facilities_counts.shp",
            "relational_matrices_save_directory": population_dir / "relations",
        }

    config_stage = {
        "launch": True,
        "net_path": network["net_save_path"],
        "population_path": population["xml_path"],
        "number_of_threads": int(values["-THREADS-"]),
        "last_iteration": int(values["-ITERS-"]) - 1,
        "output_config_path": workspace / "config.xml",
        "matsim_output_directory": model_dir,
        "schedule_path": pt["output_schedule_path"],
        "vehicles_path": pt["output_vehicles_path"],
        "lane_definitions_path": network.get("lane_definitions_save_path"),
        "scoring_parameters_path": _optional_path(values["-SCPARSPATH-"]),
        "minibus_parameters_path": _optional_path(values["-PPARSPATH-"]),
        "write_events_interval": int(values["-ITERS-"]) - 1,
        "disable_innovations_after_fraction": values["-MUTFRAC-"],
        "mutation_range": values["-TIMEMUT-"] * 60,
    }
    model = {
        "launch": values["-RUNMOD-"],
        "executable_path": _optional_path(values["-MATSIMPATH-"]),
        "config_path": config_stage["output_config_path"],
        "ram_limit": "{0}m".format(int(values["-MATSIMRAM-"])),
        "custom_class": str(values["-CCLASS-"]).strip() or None,
    }
    analysis = {
        "launch": values["-RUNMOD-"] is True and values["-ANALYZE-"] is True,
        "events_path": model_dir / "output_events.xml.gz",
        "net_path": model_dir / "output_network.xml.gz",
        "legs_path": model_dir / "output_legs.csv.gz",
        "schedule_path": model_dir / "output_transitSchedule.xml.gz",
        "output_counts_path": analysis_dir / "counts.json.gz",
        "output_turns_path": analysis_dir / "turns.json.gz",
        "output_net_counts_path": analysis_dir / "counts.shp",
        "output_transfers_path": analysis_dir / "transfers.csv.gz",
        "output_pt_counts_path": analysis_dir / "pt.json.gz",
        "output_pt_net_counts_path": analysis_dir / "pt.shp",
        "output_pt_stops_counts_path": analysis_dir / "pt_stops.shp",
        "links_nodes_groups": _optional_path(values["-LINKGROUPS-"]),
        "road_links_ids": _optional_path(values["-LINKINTENS-"]),
        "pt_links_ids": _optional_path(values["-PTLINKINTENS-"]),
        "pt_lines_ids": _optional_path(values["-PTLINEINTENS-"]),
        "output_ribbon_diagrams_directory": nodes_dir,
        "output_road_links_intensities_directory": road_dir,
        "output_pt_links_intensities_directory": pt_dir,
        "output_pt_lines_intensities_directory": pt_dir,
        "cordon_poly_path": _optional_path(values["-CORDPOLYPATH-"]),
        "output_cordon_stats_path": analysis_dir / "cordons_stats.shp",
        "volume_poly_path": _optional_path(values["-VOLPOLYPATH-"]),
        "output_volume_stats_path": analysis_dir / "volume_stats.shp",
        "output_road_db_path": analysis_dir / "road.db" if values["-EVENTSDB-"] else None,
        "output_road_db_flush_interval": int(values["-DBFLUSH-"]) if values["-EVENTSDB-"] else None,
    }

    previous = {}
    pmod = _optional_path(values["-PMODPATH-"])
    if pmod is not None:
        pmod = _lexical_absolute(pmod, workspace)
        previous, found = _load_neighbor(pmod / "settings.json", "analysis")
        neighbor_issues.extend(found)
    comparison = {
        "launch": analysis["launch"] is True and values["-COMPARE-"] is True,
        "orig_net_path": network.get("shp_path"),
        "edge_net_path": network.get("edges_save_path"),
        "net_counts_path": analysis["output_net_counts_path"],
        "pt_net_counts_path": analysis["output_pt_net_counts_path"],
        "pt_stops_counts_path": analysis["output_pt_stops_counts_path"],
        "network_intensities_path": _optional_path(values["-NINTPATH-"]),
        "intersection_intensities_path": _optional_path(values["-IINTPATH-"]),
        "prev_net_counts_path": previous.get("output_net_counts_path"),
        "prev_pt_net_counts_path": previous.get("output_pt_net_counts_path"),
        "prev_pt_stops_counts_path": previous.get("output_pt_stops_counts_path"),
        "network_differences_save_path": comparison_dir / "network_differences.shp",
        "network_differences_stats_save_path": comparison_dir / "network_differences.csv",
        "intersection_differences_save_path": comparison_dir / "intersection_differences.shp",
        "intersection_differences_stats_save_path": comparison_dir / "intersection_differences.csv",
        "diff_net_counts_save_path": comparison_dir / "prev_model_network_differences.shp",
        "diff_pt_net_counts_save_path": comparison_dir / "prev_model_pt_network_differences.shp",
        "diff_pt_stops_counts_save_path": comparison_dir / "prev_model_pt_stops_differences.shp",
        "difference_thresh": 0.25,
    }
    gis = {
        "launch": values["-QGIS-"],
        "qgis_path": _optional_path(values["-QGISPATH-"]),
        "project_path": workspace / "view.qgs",
        "input_facilities": population.get("facilities_counts_save_path"),
        "input_edges": network.get("edges_save_path"),
        "input_nodes": network.get("nodes_save_path"),
        "output_road_counts": analysis["output_net_counts_path"],
        "output_pt_counts": analysis["output_pt_net_counts_path"],
        "output_pt_stops": analysis["output_pt_stops_counts_path"],
        "output_cordons_stats": analysis["output_cordon_stats_path"],
        "output_volumes_stats": analysis["output_volume_stats_path"],
        "comparison_rw_road_diffs": comparison["network_differences_save_path"],
        "comparison_rw_road_intersection_diffs": comparison["intersection_differences_save_path"],
        "comparison_model_road_diffs": comparison["diff_net_counts_save_path"],
        "comparison_model_pt_diffs": comparison["diff_pt_net_counts_save_path"],
        "comparison_model_pt_stops_diffs": comparison["diff_pt_stops_counts_save_path"],
    }
    raw = {
        "schema_version": 1,
        "workspace": ".",
        "network": network,
        "pt": pt,
        "population": population,
        "config": config_stage,
        "model": model,
        "analysis": analysis,
        "comparison": comparison,
        "gis": gis,
    }
    provenance = {"workspace": "derived"}
    for stage in STAGE_ORDER:
        for name in raw[stage]:
            provenance[stage + "." + name] = "derived"
    gui_fields = {
        "network": {
            "launch", "existing", "nettype", "shp_path", "restrict_uturns",
            "ncores", "lane_connections_path",
            "internal_maneuvers", "net_save_path", "lane_definitions_save_path",
        },
        "pt": {
            "launch", "gtfs_folder", "number_of_threads", "output_schedule_path",
            "output_vehicles_path",
        },
        "population": {
            "launch", "existing", "ncores", "sample", "include_teleported",
            "incremental_capacity_allocation_parts", "facilities_path",
            "categories_path", "diaries_path", "distances_path", "clusters_path",
            "citylog_points_path", "staying_path", "target_probabilities_path",
            "time_courses_path", "city_logistics_path", "times_path",
            "modal_split_path", "indices_path", "relations_path", "stops_path",
            "oneway_flows_path", "freight_points_path", "transit_points_path",
            "xml_path",
        },
        "config": {
            "number_of_threads", "last_iteration", "scoring_parameters_path",
            "minibus_parameters_path", "write_events_interval",
            "disable_innovations_after_fraction", "mutation_range",
        },
        "model": {"launch", "executable_path", "ram_limit", "custom_class"},
        "analysis": {
            "launch", "links_nodes_groups", "road_links_ids", "pt_links_ids", "pt_lines_ids",
            "cordon_poly_path", "volume_poly_path", "output_road_db_path",
            "output_road_db_flush_interval",
        },
        "comparison": {
            "launch", "network_intensities_path", "intersection_intensities_path"
        },
        "gis": {"launch", "qgis_path"},
    }
    for stage, names in gui_fields.items():
        for name in names:
            if name in raw[stage]:
                provenance[stage + "." + name] = "gui"
    for name in net_neighbor:
        if name not in {"launch", "existing", "net_save_path", "lane_definitions_save_path"}:
            provenance["network." + name] = "legacy-neighbor"
    for name in pop_neighbor:
        if name not in {"launch", "existing", "xml_path", "ncores"}:
            provenance["population." + name] = "legacy-neighbor"
    for name in (
        "prev_net_counts_path", "prev_pt_net_counts_path", "prev_pt_stops_counts_path"
    ):
        provenance["comparison." + name] = (
            "legacy-neighbor" if previous.get(name.replace("prev_", "output_")) is not None
            else "default"
        )
    provenance["comparison.difference_thresh"] = "default"
    result = normalize_config(
        raw,
        config_path=workspace / "settings.json",
        source_version=1,
        _source_label="gui",
        _provenance_seed=provenance,
    )
    return ConfigResult(
        result.config,
        _sort_issues([*neighbor_issues, *result.issues]),
        1,
        result.provenance,
    )


def materialize_workspace(config: RunConfig) -> Tuple[Path, ...]:
    """Create only the approved workspace directory tree."""
    validation_issues = validate_configuration(config)
    if has_errors(validation_issues):
        raise ConfigurationError(validation_issues)
    workspace = config.workspace
    if workspace.is_symlink():
        raise RuntimeError("workspace may not be a symlink: {0}".format(workspace))
    nearest = workspace
    while not nearest.exists():
        if nearest.parent == nearest:
            raise RuntimeError("workspace has no existing ancestor: {0}".format(workspace))
        nearest = nearest.parent
    ancestor = nearest.resolve(strict=True)
    lexical_ancestor = nearest.absolute()
    try:
        lexical_tail = workspace.absolute().relative_to(lexical_ancestor)
    except ValueError as error:
        raise RuntimeError("workspace provenance is not lexical: {0}".format(workspace)) from error
    prospective_root = ancestor / lexical_tail
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace.resolve(strict=True)
    if root != prospective_root:
        raise RuntimeError("workspace escapes through a symlink: {0}".format(workspace))
    created: List[Path] = []
    for relative in WORKSPACE_DIRECTORIES:
        target = workspace / relative
        if target.exists() and not target.is_dir():
            raise RuntimeError("workspace target is not a directory: {0}".format(target))
        nearest = target
        while not nearest.exists():
            nearest = nearest.parent
        try:
            nearest.resolve(strict=True).relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                "workspace target escapes through a symlink: {0}".format(target)
            ) from error
        target.mkdir(parents=True, exist_ok=True)
        try:
            target.resolve(strict=True).relative_to(root)
        except ValueError as error:
            raise RuntimeError("workspace target escapes through a symlink: {0}".format(target)) from error
        created.append(target)
    return tuple(created)


def _serialize_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(os.fspath(path), os.fspath(base))
    except ValueError:
        return str(path)


def _primitive(config: RunConfig, destination: Path) -> Dict[str, Any]:
    base = destination.parent
    data: Dict[str, Any] = {
        "schema_version": 1,
        "workspace": _serialize_path(config.workspace, base),
    }
    for stage in STAGE_ORDER:
        section: Dict[str, Any] = {}
        values = config.stages[stage]
        for spec in SCHEMA[stage]:
            value = values.get(spec.name)
            if isinstance(value, Path):
                value = _serialize_path(value, base)
            elif not isinstance(value, (type(None), bool, int, float, str)):
                raise TypeError("unsupported serialized value at {0}.{1}".format(stage, spec.name))
            section[spec.name] = value
        data[stage] = section
    return data


def write_settings(config: RunConfig, path: Optional[PathLike] = None) -> Path:
    """Atomically write deterministic UTF-8 schema-version-1 JSON."""
    validation_issues = validate_configuration(config)
    if has_errors(validation_issues):
        raise ConfigurationError(validation_issues)
    destination = _lexical_absolute(path or config.config_path, config.workspace)
    if not destination.parent.is_dir():
        raise FileNotFoundError("settings destination parent does not exist: {0}".format(destination.parent))
    try:
        destination.relative_to(config.workspace)
    except ValueError as error:
        raise RuntimeError("settings destination must remain inside workspace") from error
    if destination.is_symlink():
        raise RuntimeError("settings destination may not be a symlink")
    try:
        destination.parent.resolve(strict=True).relative_to(
            config.workspace.resolve(strict=True)
        )
    except ValueError as error:
        raise RuntimeError("settings destination escapes through a symlink") from error
    data = _primitive(config, destination)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix="." + destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=4)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
        return destination
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def to_legacy_mapping(config: RunConfig) -> Dict[str, Dict[str, Any]]:
    """Create one copied legacy projection for current GUI/runner consumers."""
    workspace = config.workspace
    result: Dict[str, Dict[str, Any]] = {
        "wd": {
            "root": workspace,
            "model": workspace / "model",
            "analysis": workspace / "analysis",
            "nodes": workspace / "analysis" / "nodes",
            "links": workspace / "analysis" / "links",
            "road_links": workspace / "analysis" / "links" / "road",
            "pt_links": workspace / "analysis" / "links" / "pt",
            "comparison": workspace / "comparison",
        }
    }
    for stage in STAGE_ORDER:
        result[stage] = {
            spec.name: thaw(config.stages[stage].get(spec.name))
            for spec in SCHEMA[stage]
        }
    return result
