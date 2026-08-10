"""Public presentation-neutral configuration package."""

from .model import (
    ConfigResult,
    ConfigurationError,
    FieldSpec,
    ISSUE_CATALOG,
    RunConfig,
    STAGE_ORDER,
    ValidationIssue,
)
from .schema import (
    FIELD_MAP,
    GUI_FIELD_KEYS,
    LEGACY_ROOT_KEYS,
    PATH_ROLES,
    ROOT_FIELDS,
    ROOT_GUI_KEYS,
    SCHEMA,
)
from .service import (
    GUI_KEYS,
    create_config,
    has_errors,
    load_run_config,
    materialize_workspace,
    normalize_config,
    to_legacy_mapping,
    validate_configuration,
    write_settings,
)
from .projection import (
    apply_config_overrides,
    configuration_to_primitive,
    format_configuration_json,
)
from .template import (
    ConfigTemplate,
    TEMPLATE_PROFILES,
    TEMPLATE_SEEDS,
    build_config_template,
    format_config_template,
    write_config_template,
)

__all__ = [
    "ConfigResult",
    "ConfigTemplate",
    "ConfigurationError",
    "FIELD_MAP",
    "FieldSpec",
    "GUI_FIELD_KEYS",
    "GUI_KEYS",
    "ISSUE_CATALOG",
    "LEGACY_ROOT_KEYS",
    "PATH_ROLES",
    "RunConfig",
    "ROOT_FIELDS",
    "ROOT_GUI_KEYS",
    "SCHEMA",
    "STAGE_ORDER",
    "TEMPLATE_PROFILES",
    "TEMPLATE_SEEDS",
    "ValidationIssue",
    "apply_config_overrides",
    "build_config_template",
    "configuration_to_primitive",
    "create_config",
    "format_config_template",
    "format_configuration_json",
    "has_errors",
    "load_run_config",
    "materialize_workspace",
    "normalize_config",
    "to_legacy_mapping",
    "validate_configuration",
    "write_settings",
    "write_config_template",
]
