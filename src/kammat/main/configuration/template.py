"""Schema-derived configuration templates and confined atomic writing."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from .model import freeze
from .schema import ROOT_FIELDS, SCHEMA


PathLike = Union[str, os.PathLike]
TEMPLATE_PROFILES = frozenset({"minimal", "full"})

# Values are reviewed placeholders. Field identity, order, requiredness, and
# defaults remain owned exclusively by ROOT_FIELDS and SCHEMA.
TEMPLATE_SEEDS = MappingProxyType({
    "workspace": "./workspace",
    "network.launch": False,
    "network.existing": True,
    "network.net_save_path": "./inputs/network.xml",
    "pt.launch": False,
    "pt.number_of_threads": 1,
    "pt.net_path": "./inputs/network.xml",
    "pt.output_net_path": "./inputs/network.xml",
    "population.launch": False,
    "population.existing": True,
    "population.ncores": 1,
    "population.xml_path": "./inputs/population.xml",
    "config.launch": False,
    "config.net_path": "./inputs/network.xml",
    "config.population_path": "./inputs/population.xml",
    "config.number_of_threads": 1,
    "config.last_iteration": 0,
    "config.output_config_path": "./workspace/config.xml",
    "config.matsim_output_directory": "./workspace/model",
    "config.write_events_interval": 1,
    "config.disable_innovations_after_fraction": 0.8,
    "config.mutation_range": 0.0,
    "model.launch": False,
    "model.config_path": "./workspace/config.xml",
    "model.ram_limit": "4g",
    "analysis.launch": False,
    "analysis.events_path": "./workspace/model/output_events.xml.gz",
    "analysis.net_path": "./workspace/model/output_network.xml.gz",
    "analysis.output_counts_path": "./workspace/analysis/counts.csv",
    "analysis.output_turns_path": "./workspace/analysis/turns.csv",
    "analysis.output_net_counts_path": "./workspace/analysis/network-counts.csv",
    "comparison.launch": False,
    "comparison.difference_thresh": 0.0,
    "gis.launch": False,
    "gis.project_path": "./workspace/project.qgz",
})


def _lexical_absolute(value: PathLike, base: Optional[Path] = None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return Path(os.path.abspath(os.fspath(path)))


def _portable_path(path: Path, base: Path) -> str:
    try:
        relative = os.path.relpath(str(path), str(base))
    except ValueError:
        return str(path)
    if relative == ".":
        return "."
    if not relative.startswith(("..", "." + os.sep)) and not Path(relative).is_absolute():
        return "." + os.sep + relative
    return relative


def _json_primitive(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, tuple):
        return all(_json_primitive(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _json_primitive(item)
            for key, item in value.items()
        )
    return False


def _mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable(item) for item in value]
    return value


def _validate_seed_registry() -> None:
    root_names = {spec.name for spec in ROOT_FIELDS}
    known = {"workspace"}
    required = {"workspace"}
    for stage, specs in SCHEMA.items():
        for spec in specs:
            dotted = stage + "." + spec.name
            known.add(dotted)
            if spec.required_when == "always" and spec.default is None:
                required.add(dotted)
    if "schema_version" not in root_names or root_names != {"schema_version", "workspace"}:
        raise RuntimeError("template root schema drift")
    if not required.issubset(TEMPLATE_SEEDS):
        raise RuntimeError("template seeds omit required fields")
    if not set(TEMPLATE_SEEDS).issubset(known):
        raise RuntimeError("template seeds contain unknown fields")
    if any(
        key.endswith(".launch") and value is not False
        for key, value in TEMPLATE_SEEDS.items()
    ):
        raise RuntimeError("template launch seeds must be false")
    if not all(_json_primitive(value) for value in TEMPLATE_SEEDS.values()):
        raise RuntimeError("template seeds must be finite JSON primitives")


_validate_seed_registry()


@dataclass(frozen=True)
class ConfigTemplate:
    """One immutable schema-version-1 template bound to its destination."""

    profile: str
    destination: Path
    workspace: Path
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.profile not in TEMPLATE_PROFILES:
            raise ValueError("unknown configuration template profile")
        destination = Path(self.destination)
        workspace = Path(self.workspace)
        if not destination.is_absolute() or not workspace.is_absolute():
            raise ValueError("template destination and workspace must be absolute")
        data = dict(self.data)
        if tuple(data) != ("schema_version", "workspace", *tuple(SCHEMA)):
            raise ValueError("template root order must match schema")
        if data["schema_version"] != 1:
            raise ValueError("template schema version must be one")
        if not _json_primitive(data):
            raise TypeError("template data must contain finite JSON primitives")
        for stage, specs in SCHEMA.items():
            section = data.get(stage)
            if not isinstance(section, Mapping):
                raise ValueError("template must contain every stage object")
            expected = tuple(
                spec.name for spec in specs
                if self.profile == "full" or spec.required_when == "always"
            )
            if tuple(section) != expected:
                raise ValueError("template stage fields must follow schema order")
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "data", freeze(data))


def build_config_template(
    destination: PathLike,
    profile: str = "minimal",
    workspace: Optional[PathLike] = None,
) -> ConfigTemplate:
    """Build one deterministic template without touching the filesystem."""

    if profile not in TEMPLATE_PROFILES:
        raise ValueError("unknown configuration template profile: {0}".format(profile))
    target = _lexical_absolute(destination)
    root = target.parent
    workspace_path = _lexical_absolute(
        "workspace" if workspace is None else workspace,
        root,
    )
    data: Dict[str, Any] = {
        "schema_version": 1,
        "workspace": _portable_path(workspace_path, root),
    }
    for stage, specs in SCHEMA.items():
        section: Dict[str, Any] = {}
        for spec in specs:
            if profile == "minimal" and spec.required_when != "always":
                continue
            dotted = stage + "." + spec.name
            if dotted in TEMPLATE_SEEDS:
                value = TEMPLATE_SEEDS[dotted]
            elif spec.default is not None:
                value = spec.default
            else:
                value = None
            if spec.value_kind == "path" and value is not None:
                value = _portable_path(_lexical_absolute(str(value), root), root)
            section[spec.name] = value
        data[stage] = section
    return ConfigTemplate(profile, target, workspace_path, data)


def format_config_template(template: ConfigTemplate) -> str:
    """Serialize one template with the shared deterministic JSON policy."""

    if not isinstance(template, ConfigTemplate):
        raise TypeError("template must be ConfigTemplate")
    return json.dumps(_mutable(template.data), ensure_ascii=False, indent=2) + "\n"


def write_config_template(template: ConfigTemplate) -> Path:
    """Atomically create the explicit destination without overwriting anything."""

    if not isinstance(template, ConfigTemplate):
        raise TypeError("template must be ConfigTemplate")
    destination = template.destination
    parent = destination.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise OSError("template parent must be an existing real directory")
    if os.path.lexists(str(destination)):
        raise FileExistsError("template destination already exists")
    text = format_config_template(template)
    descriptor = -1
    temporary: Optional[Path] = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".kammat-config-",
            suffix=".tmp",
            dir=str(parent),
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # A same-directory hard link is an atomic create-if-absent operation and
        # therefore cannot overwrite a destination created by a racing writer.
        os.link(str(temporary), str(destination))
        temporary.unlink()
        temporary = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(str(parent), flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is unavailable on some supported filesystems.
            pass
        return destination
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "ConfigTemplate",
    "TEMPLATE_PROFILES",
    "TEMPLATE_SEEDS",
    "build_config_template",
    "format_config_template",
    "write_config_template",
]
