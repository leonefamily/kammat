"""Schema-version-1 field inventory and path-role policy."""

from dataclasses import replace
from typing import Any, Dict, Optional, Tuple

from .model import FieldSpec, PATH_ROLE_VALUES, STAGE_ORDER


PATH_ROLES = PATH_ROLE_VALUES

ROOT_FIELDS = (
    FieldSpec(
        name="schema_version",
        value_kind="int",
        required_when="always",
        default=1,
        legacy_keys=("schema_version",),
        validator_codes=("KAM-CFG-E100", "KAM-CFG-E200"),
    ),
    FieldSpec(
        name="workspace",
        value_kind="path",
        required_when="always",
        legacy_keys=("wd.root",),
        validator_codes=("KAM-CFG-E102", "KAM-CFG-E200", "KAM-CFG-E300"),
    ),
)
LEGACY_ROOT_KEYS = {"wd": ("root",)}


def field(
    name: str,
    kind: str,
    *,
    nullable: bool = False,
    required: str = "optional",
    default: Any = None,
    gui: Optional[str] = None,
    role: Optional[str] = None,
    allowed: Tuple[Any, ...] = (),
) -> FieldSpec:
    if role is not None and role not in PATH_ROLES:
        raise ValueError("unknown path role: {0}".format(role))
    validator_codes = ["KAM-CFG-E200"]
    if required == "always":
        validator_codes.append("KAM-CFG-E102")
    if allowed:
        validator_codes.append("KAM-CFG-E201")
    if role is not None:
        validator_codes.extend(("KAM-CFG-E300", "KAM-CFG-E302"))
        if role not in {"generated_file", "generated_directory"}:
            validator_codes.append("KAM-CFG-E301")
    return FieldSpec(
        name=name,
        value_kind=kind,
        nullable=nullable,
        required_when=required,
        default=default,
        gui_key=gui,
        path_role=role,
        allowed_values=allowed,
        validator_codes=tuple(validator_codes),
    )


SCHEMA: Dict[str, Tuple[FieldSpec, ...]] = {
    "network": (
        field("launch", "bool", required="always"),
        field("existing", "bool", required="always"),
        field("nettype", "str", nullable=True, allowed=("generic", "ceda")),
        field("shp_path", "path", nullable=True, role="existing_file"),
        field("restrict_uturns", "bool", nullable=True),
        field("ncores", "int", nullable=True),
        field("lane_connections_path", "path", nullable=True, role="optional_existing_file"),
        field("lane_definitions_save_path", "path", nullable=True, role="generated_file"),
        field("internal_maneuvers", "bool", nullable=True),
        field("edges_save_path", "path", nullable=True, role="generated_file"),
        field("nodes_save_path", "path", nullable=True, role="generated_file"),
        field("net_save_path", "path", required="always", role="upstream_or_existing_file"),
    ),
    "pt": (
        field("launch", "bool", required="always"),
        field("gtfs_folder", "path", nullable=True, role="existing_directory"),
        field("number_of_threads", "int", required="always"),
        field("net_path", "path", required="always", role="upstream_or_existing_file"),
        field("output_net_path", "path", required="always", role="generated_file"),
        field("output_schedule_path", "path", nullable=True, role="generated_file"),
        field("output_vehicles_path", "path", nullable=True, role="generated_file"),
    ),
    "population": (
        field("launch", "bool", required="always"),
        field("existing", "bool", required="always"),
        field("ncores", "int", required="always"),
        field("sample", "float", nullable=True),
        field("include_teleported", "bool", nullable=True),
        field("incremental_capacity_allocation_parts", "int", nullable=True),
        field("facilities_path", "path", nullable=True, role="existing_file"),
        field("categories_path", "path", nullable=True, role="existing_file"),
        field("diaries_path", "path", nullable=True, role="existing_file"),
        field("distances_path", "path", nullable=True, role="existing_file"),
        field("clusters_path", "path", nullable=True, role="optional_existing_file"),
        field("citylog_points_path", "path", nullable=True, role="optional_existing_file"),
        field("staying_path", "path", nullable=True, role="optional_existing_file"),
        field("target_probabilities_path", "path", nullable=True, role="optional_existing_file"),
        field("time_courses_path", "path", nullable=True, role="optional_existing_file"),
        field("city_logistics_path", "path", nullable=True, role="optional_existing_file"),
        field("times_path", "path", nullable=True, role="optional_existing_file"),
        field("modal_split_path", "path", nullable=True, role="optional_existing_file"),
        field("indices_path", "path", nullable=True, role="optional_existing_file"),
        field("relations_path", "path", nullable=True, role="optional_existing_file"),
        field("stops_path", "path", nullable=True, role="optional_existing_file"),
        field("oneway_flows_path", "path", nullable=True, role="optional_existing_file"),
        field("freight_points_path", "path", nullable=True, role="optional_existing_file"),
        field("transit_points_path", "path", nullable=True, role="optional_existing_file"),
        field("xml_path", "path", required="always", role="upstream_or_existing_file"),
        field("csv_path", "path", nullable=True, role="generated_file"),
        field("pickle_path", "path", nullable=True, role="generated_file"),
        field("modal_split_save_path", "path", nullable=True, role="generated_file"),
        field("facilities_counts_save_path", "path", nullable=True, role="generated_file"),
        field("relational_matrices_save_directory", "path", nullable=True, role="generated_directory"),
    ),
    "config": (
        field("launch", "bool", required="always"),
        field("net_path", "path", required="always", role="upstream_or_existing_file"),
        field("population_path", "path", required="always", role="upstream_or_existing_file"),
        field("number_of_threads", "int", required="always"),
        field("last_iteration", "int", required="always"),
        field("output_config_path", "path", required="always", role="generated_file"),
        field("matsim_output_directory", "path", required="always", role="generated_directory"),
        field("schedule_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("vehicles_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("lane_definitions_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("scoring_parameters_path", "path", nullable=True, role="optional_existing_file"),
        field("minibus_parameters_path", "path", nullable=True, role="optional_existing_file"),
        field("write_events_interval", "int", required="always"),
        field("disable_innovations_after_fraction", "float", required="always"),
        field("mutation_range", "float", required="always"),
    ),
    "model": (
        field("launch", "bool", required="always"),
        field("executable_path", "path", nullable=True, role="external_file"),
        field("config_path", "path", required="always", role="upstream_or_existing_file"),
        field("ram_limit", "str", required="always"),
        field("custom_class", "str", nullable=True),
    ),
    "analysis": (
        field("launch", "bool", required="always"),
        field("events_path", "path", required="always", role="upstream_or_existing_file"),
        field("net_path", "path", required="always", role="upstream_or_existing_file"),
        field("legs_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("schedule_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_counts_path", "path", required="always", role="generated_file"),
        field("output_turns_path", "path", required="always", role="generated_file"),
        field("output_net_counts_path", "path", required="always", role="generated_file"),
        field("output_transfers_path", "path", nullable=True, role="generated_file"),
        field("output_pt_counts_path", "path", nullable=True, role="generated_file"),
        field("output_pt_net_counts_path", "path", nullable=True, role="generated_file"),
        field("output_pt_stops_counts_path", "path", nullable=True, role="generated_file"),
        field("links_nodes_groups", "path", nullable=True, role="optional_existing_file"),
        field("road_links_ids", "path", nullable=True, role="optional_existing_file"),
        field("pt_links_ids", "path", nullable=True, role="optional_existing_file"),
        field("pt_lines_ids", "path", nullable=True, role="optional_existing_file"),
        field("output_ribbon_diagrams_directory", "path", nullable=True, role="generated_directory"),
        field("output_road_links_intensities_directory", "path", nullable=True, role="generated_directory"),
        field("output_pt_links_intensities_directory", "path", nullable=True, role="generated_directory"),
        field("output_pt_lines_intensities_directory", "path", nullable=True, role="generated_directory"),
        field("cordon_poly_path", "path", nullable=True, role="optional_existing_file"),
        field("output_cordon_stats_path", "path", nullable=True, role="generated_file"),
        field("volume_poly_path", "path", nullable=True, role="optional_existing_file"),
        field("output_volume_stats_path", "path", nullable=True, role="generated_file"),
        field("output_road_db_path", "path", nullable=True, role="generated_file"),
        field("output_road_db_flush_interval", "int", nullable=True),
    ),
    "comparison": (
        field("launch", "bool", required="always"),
        field("orig_net_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("edge_net_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("net_counts_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("pt_net_counts_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("pt_stops_counts_path", "path", nullable=True, role="upstream_or_existing_file"),
        field("network_intensities_path", "path", nullable=True, role="optional_existing_file"),
        field("intersection_intensities_path", "path", nullable=True, role="optional_existing_file"),
        field("prev_net_counts_path", "path", nullable=True, role="optional_existing_file"),
        field("prev_pt_net_counts_path", "path", nullable=True, role="optional_existing_file"),
        field("prev_pt_stops_counts_path", "path", nullable=True, role="optional_existing_file"),
        field("network_differences_save_path", "path", nullable=True, role="generated_file"),
        field("network_differences_stats_save_path", "path", nullable=True, role="generated_file"),
        field("intersection_differences_save_path", "path", nullable=True, role="generated_file"),
        field("intersection_differences_stats_save_path", "path", nullable=True, role="generated_file"),
        field("diff_net_counts_save_path", "path", nullable=True, role="generated_file"),
        field("diff_pt_net_counts_save_path", "path", nullable=True, role="generated_file"),
        field("diff_pt_stops_counts_save_path", "path", nullable=True, role="generated_file"),
        field("difference_thresh", "float", required="always"),
    ),
    "gis": (
        field("launch", "bool", required="always"),
        field("qgis_path", "path", nullable=True, role="external_directory_or_executable"),
        field("project_path", "path", required="always", role="generated_file"),
        field("input_facilities", "path", nullable=True, role="upstream_or_existing_file"),
        field("input_edges", "path", nullable=True, role="upstream_or_existing_file"),
        field("input_nodes", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_road_counts", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_pt_counts", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_pt_stops", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_cordons_stats", "path", nullable=True, role="upstream_or_existing_file"),
        field("output_volumes_stats", "path", nullable=True, role="upstream_or_existing_file"),
        field("comparison_rw_road_diffs", "path", nullable=True, role="upstream_or_existing_file"),
        field("comparison_rw_road_intersection_diffs", "path", nullable=True, role="upstream_or_existing_file"),
        field("comparison_model_road_diffs", "path", nullable=True, role="upstream_or_existing_file"),
        field("comparison_model_pt_diffs", "path", nullable=True, role="upstream_or_existing_file"),
        field("comparison_model_pt_stops_diffs", "path", nullable=True, role="upstream_or_existing_file"),
    ),
}


ROOT_GUI_KEYS = frozenset({"-PARENTPATH-", "-WDPATH-"})
GUI_FIELD_KEYS = {
    "network.launch": "-USENET-",
    "network.existing": "-USENET-",
    "network.nettype": "-NETGEN-",
    "network.shp_path": "-NETPATH-",
    "network.restrict_uturns": "-UTURNS-",
    "network.ncores": "-THREADS-",
    "network.lane_connections_path": "-LCONPATH-",
    "network.lane_definitions_save_path": "-ELDEFPATH-",
    "network.internal_maneuvers": "-SIMPLEINT-",
    "network.net_save_path": "-ENETPATH-",
    "pt.launch": "-GTFSPATH-",
    "pt.gtfs_folder": "-GTFSPATH-",
    "pt.number_of_threads": "-THREADS-",
    "pt.output_schedule_path": "-ESCHEDPATH-",
    "pt.output_vehicles_path": "-EVEHSPATH-",
    "population.launch": "-USEPOP-",
    "population.existing": "-USEPOP-",
    "population.ncores": "-THREADS-",
    "population.sample": "-POPFRAC-",
    "population.include_teleported": "-WRITETP-",
    "population.incremental_capacity_allocation_parts": "-INCRCAP-",
    "population.facilities_path": "-POPPATH-",
    "population.categories_path": "-CATPATH-",
    "population.diaries_path": "-DIARPATH-",
    "population.distances_path": "-DISTPATH-",
    "population.clusters_path": "-CLUSTPATH-",
    "population.citylog_points_path": "-CLOGSPATH-",
    "population.staying_path": "-STAYPATH-",
    "population.target_probabilities_path": "-TARGPATH-",
    "population.time_courses_path": "-TCOURPATH-",
    "population.city_logistics_path": "-CLOGPATH-",
    "population.times_path": "-TIMEPATH-",
    "population.modal_split_path": "-MSPATH-",
    "population.indices_path": "-INDPATH-",
    "population.relations_path": "-RELPATH-",
    "population.stops_path": "-STOPPATH-",
    "population.oneway_flows_path": "-OFLOWPATH-",
    "population.freight_points_path": "-FREPATH-",
    "population.transit_points_path": "-TRANPATH-",
    "population.xml_path": "-EPOPPATH-",
    "config.number_of_threads": "-THREADS-",
    "config.last_iteration": "-ITERS-",
    "config.scoring_parameters_path": "-SCPARSPATH-",
    "config.minibus_parameters_path": "-PPARSPATH-",
    "config.write_events_interval": "-ITERS-",
    "config.disable_innovations_after_fraction": "-MUTFRAC-",
    "config.mutation_range": "-TIMEMUT-",
    "model.launch": "-RUNMOD-",
    "model.executable_path": "-MATSIMPATH-",
    "model.ram_limit": "-MATSIMRAM-",
    "model.custom_class": "-CCLASS-",
    "analysis.launch": "-ANALYZE-",
    "analysis.links_nodes_groups": "-LINKGROUPS-",
    "analysis.road_links_ids": "-LINKINTENS-",
    "analysis.pt_links_ids": "-PTLINKINTENS-",
    "analysis.pt_lines_ids": "-PTLINEINTENS-",
    "analysis.cordon_poly_path": "-CORDPOLYPATH-",
    "analysis.volume_poly_path": "-VOLPOLYPATH-",
    "analysis.output_road_db_path": "-EVENTSDB-",
    "analysis.output_road_db_flush_interval": "-DBFLUSH-",
    "comparison.launch": "-COMPARE-",
    "comparison.network_intensities_path": "-NINTPATH-",
    "comparison.intersection_intensities_path": "-IINTPATH-",
    "comparison.prev_net_counts_path": "-PMODPATH-",
    "gis.launch": "-QGIS-",
    "gis.qgis_path": "-QGISPATH-",
}

SCHEMA = {
    stage: tuple(
        replace(
            spec,
            gui_key=GUI_FIELD_KEYS.get(stage + "." + spec.name),
            legacy_keys=(spec.name,),
        )
        for spec in specs
    )
    for stage, specs in SCHEMA.items()
}


if tuple(SCHEMA) != STAGE_ORDER:
    raise RuntimeError("schema stage order drift")


FIELD_MAP = {
    stage: {spec.name: spec for spec in specs}
    for stage, specs in SCHEMA.items()
}
