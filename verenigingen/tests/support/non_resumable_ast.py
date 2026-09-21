"""Re-export shim (#1189) -- the real module moved to
``scripts/validation/non_resumable_ast.py``.

It moved so ``scripts/validation/savepoint_rollback_validator.py`` (the standalone,
pre-commit-invokable entry point for the #561 savepoint-rollback ratchet) could import these
predicates without pulling in ``frappe``: this module lives under ``verenigingen.tests``, and
importing ANY submodule of that package runs ``verenigingen/tests/__init__.py``, which does
``import frappe`` at module scope -- unavailable to the stdlib-only CI job that runs
pre-commit-style validators.

This file stays as a plain re-export so its other two bench-side consumers
(``test_termination_non_resumable_errors.py``, ``test_handle_api_error_endpoints_non_resumable.py``)
do not need an import change. There is still exactly ONE implementation, at the path above.
"""

from scripts.validation.non_resumable_ast import (  # noqa: F401
    CATCH_ALLS,
    GUARD_CLASSES,
    GUARD_NAME,
    catches_bare_exception,
    names_the_non_resumable_classes,
    reraises_non_resumable,
    reraises_unconditionally,
)
