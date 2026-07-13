"""
conftest.py for unit tests.
Provides sys.modules stubs for optional packages that may not be installed
in every environment (e.g. sentry_core) so that test modules can be
collected even when the real packages are absent.
"""

import sys
import types


def _make_module(name: str) -> types.ModuleType:
    """Create a lightweight stub module and register it in sys.modules."""
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------------------
# Stub out sentry_core and the sub-modules imported by test_database_models
# ---------------------------------------------------------------------------
if "sentry_core" not in sys.modules:
    sentry_core = _make_module("sentry_core")
    sentry_core_database = _make_module("sentry_core.database")
    sentry_core_database_models = _make_module("sentry_core.database.models")

    # Provide the model names imported in test_database_models.py as plain
    # sentinel classes so the import succeeds and the skip mark takes effect.
    for _cls_name in ("User", "Case", "Finding", "SLAPolicy"):
        setattr(sentry_core_database_models, _cls_name, type(_cls_name, (), {}))

    sentry_core.database = sentry_core_database
    sentry_core_database.models = sentry_core_database_models
