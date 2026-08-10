#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May  7 18:05:36 2024

@author: leonefamily
"""

"""Developed for Stable public facade for Kammat configuration."""

import json
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

#TODO(idrees): fix the naming convention, for now its okay as it stands out the changed code.
from kammat.main.configuration import (
    ConfigResult,
    ConfigTemplate,
    ConfigurationError,
    FIELD_MAP,
    FieldSpec,
    GUI_FIELD_KEYS,
    GUI_KEYS,
    ISSUE_CATALOG,
    LEGACY_ROOT_KEYS,
    RunConfig,
    ROOT_GUI_KEYS,
    ROOT_FIELDS,
    SCHEMA,
    STAGE_ORDER,
    TEMPLATE_PROFILES,
    TEMPLATE_SEEDS,
    ValidationIssue,
    apply_config_overrides,
    build_config_template,
    configuration_to_primitive,
    create_config,
    format_config_template,
    format_configuration_json,
    has_errors,
    load_run_config,
    materialize_workspace,
    normalize_config,
    to_legacy_mapping,
    validate_configuration,
    write_settings,
    write_config_template,
)


Config = Dict[str, Dict[str, Any]]
PathLike = Union[Path, str]


def _raw_mapping_has_relative_path(config: Mapping[str, Any]) -> bool:
    candidates = []
    workspace = config.get("workspace")
    if workspace is None and isinstance(config.get("wd"), Mapping):
        workspace = config["wd"].get("root")
    if workspace is not None:
        candidates.append(workspace)
    for stage, specs in SCHEMA.items():
        section = config.get(stage)
        if not isinstance(section, Mapping):
            continue
        for spec in specs:
            value = section.get(spec.name)
            if spec.value_kind == "path" and value is not None and value != "":
                candidates.append(value)
    for value in candidates:
        if isinstance(value, (str, os.PathLike)) and not Path(value).is_absolute():
            return True
    return False


def load_config(p: PathLike) -> Dict[str, Any]:
    """Load raw UTF-8 JSON without normalization for compatibility."""
    with open(p, mode="r", encoding="utf-8") as stream:
        return json.load(stream)


def ensure_is_file(
    p: PathLike,
    check_exists: bool = False,
    check_parent_exists: bool = False,
    expl: Optional[str] = "",
) -> None:
    """Validate a legacy file-path boundary without creating anything."""
    path = Path(p).resolve()
    explanation = ", ({0})".format(expl) if expl else ""
    if check_exists and not path.exists():
        raise FileNotFoundError("{0} file does not exist{1}".format(p, explanation))
    if check_parent_exists and not path.parent.exists():
        raise FileNotFoundError(
            "Parent folder of {0} does not exist{1}".format(p, explanation)
        )
    if not path.is_file() and path.suffix == "":
        raise RuntimeError("{0} was supposed to be a file{1}".format(p, explanation))


def ensure_is_directory(
    p: PathLike,
    check_exists: bool = False,
    expl: Optional[str] = "",
) -> None:
    """Validate a legacy directory-path boundary without creating anything."""
    path = Path(p).resolve()
    explanation = ", ({0})".format(expl) if expl else ""
    if check_exists and not path.exists():
        raise FileNotFoundError("{0} directory does not exist{1}".format(p, explanation))
    if not path.is_directory() and path.suffix != "":
        raise RuntimeError("{0} was supposed to be a directory{1}".format(p, explanation))


def validate_config(
    config: Union[ConfigResult, RunConfig, Mapping[str, Any]],
    config_path: Optional[PathLike] = None,
) -> List[str]:
    """Validate through the shared core and return enabled stages in legacy order."""
    if isinstance(config, ConfigResult):
        result = config
    elif isinstance(config, RunConfig):
        result = ConfigResult(
            config,
            validate_configuration(config),
            1,
            {},
        )
    elif isinstance(config, Mapping):
        if config_path is None and _raw_mapping_has_relative_path(config):
            raise ConfigurationError((ValidationIssue(
                "KAM-CFG-E300",
                "error",
                "$",
                "raw mapping with relative paths requires explicit config_path provenance",
            ),))
        raw_version = config.get("schema_version", 0)
        source_version = raw_version if type(raw_version) is int else -1
        result = normalize_config(
            config,
            config_path=config_path or (Path(os.path.abspath("settings.json"))),
            source_version=source_version,
        )
    else:
        raise TypeError("config must be ConfigResult, RunConfig, or mapping")
    for issue in result.issues:
        if issue.level == "warning":
            warnings.warn(
                "{0} {1}: {2}".format(issue.code, issue.field, issue.message),
                UserWarning,
                stacklevel=2,
            )
    if result.config is None or has_errors(result.issues):
        raise ConfigurationError(tuple(
            issue for issue in result.issues if issue.level == "error"
        ))
    return [
        stage for stage in STAGE_ORDER
        if result.config.stages[stage].get("launch") is True
    ]


__all__ = [
    "Config",
    "ConfigResult",
    "ConfigTemplate",
    "ConfigurationError",
    "FIELD_MAP",
    "FieldSpec",
    "GUI_FIELD_KEYS",
    "GUI_KEYS",
    "ISSUE_CATALOG",
    "LEGACY_ROOT_KEYS",
    "RunConfig",
    "ROOT_GUI_KEYS",
    "ROOT_FIELDS",
    "SCHEMA",
    "STAGE_ORDER",
    "TEMPLATE_PROFILES",
    "TEMPLATE_SEEDS",
    "ValidationIssue",
    "apply_config_overrides",
    "build_config_template",
    "configuration_to_primitive",
    "create_config",
    "ensure_is_directory",
    "ensure_is_file",
    "format_config_template",
    "format_configuration_json",
    "has_errors",
    "load_config",
    "load_run_config",
    "materialize_workspace",
    "normalize_config",
    "to_legacy_mapping",
    "validate_config",
    "validate_configuration",
    "write_settings",
    "write_config_template",
]
