"""Pure schema-ordered configuration projection and copied updates."""

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from .model import ConfigResult, RunConfig
from .schema import FIELD_MAP, SCHEMA
from .service import normalize_config


def _portable_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(str(path), str(base))
    except ValueError:
        return str(path)


def _primitive(value: Any, base: Path, resolved: bool) -> Any:
    if isinstance(value, Path):
        return str(value) if resolved else _portable_path(value, base)
    if isinstance(value, Mapping):
        return {key: _primitive(item, base, resolved) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_primitive(item, base, resolved) for item in value]
    if isinstance(value, frozenset):
        return sorted(_primitive(item, base, resolved) for item in value)
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError("configuration contains a non-JSON primitive")


def configuration_to_primitive(
    config: RunConfig,
    resolved: bool = False,
) -> Mapping[str, Any]:
    """Return schema-version-1 data in exact schema declaration order."""

    if not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig")
    if type(resolved) is not bool:
        raise TypeError("resolved must be an exact boolean")
    base = config.config_path.parent
    result: Dict[str, Any] = {
        "schema_version": 1,
        "workspace": _primitive(config.workspace, base, resolved),
    }
    for stage, specs in SCHEMA.items():
        result[stage] = {
            spec.name: _primitive(config.stages[stage].get(spec.name), base, resolved)
            for spec in specs
        }
    return result


def format_configuration_json(config: RunConfig, resolved: bool = False) -> str:
    """Format an effective configuration with one trailing newline."""

    return json.dumps(
        configuration_to_primitive(config, resolved),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def apply_config_overrides(
    config: RunConfig,
    changes: Mapping[str, Any],
) -> ConfigResult:
    """Apply canonical stage-field scalar changes to a copied configuration."""

    if not isinstance(config, RunConfig):
        raise TypeError("config must be RunConfig")
    if not isinstance(changes, Mapping):
        raise TypeError("changes must be a mapping")
    raw = configuration_to_primitive(config, resolved=True)
    for dotted, value in changes.items():
        if not isinstance(dotted, str) or dotted.count(".") != 1:
            raise KeyError("override field must be one canonical stage field")
        stage, field = dotted.split(".", 1)
        if stage not in FIELD_MAP or field not in FIELD_MAP[stage]:
            raise KeyError("unknown configuration field: {0}".format(dotted))
        raw[stage][field] = value
    return normalize_config(
        raw,
        config_path=config.config_path,
        source_version=1,
        _source_label="json",
    )


__all__ = [
    "apply_config_overrides",
    "configuration_to_primitive",
    "format_configuration_json",
]
