"""
Security Package for Verenigingen Operations

This package provides comprehensive security measures including:
- API Security Framework (decorators, authorization, rate limiting)
- CSRF protection
- Role-based authorization
- Comprehensive audit logging

Architecture (see docs/REFACTOR_API_SECURITY_FRAMEWORK.md):
- types.py: Shared enums and data classes (lowest layer)
- authorization_policy.py: Pure authorization decision logic
- authorization_engine.py: Authorization I/O layer (uses policy)
- input_validator.py: Pure input validation
- environment_validator.py: Environment-based access control
- rate_limit_engine.py: Rate limiting with COR integration
- audit_emitter.py: Security audit event emission
- frappe_whitelist_adapter.py: Façade for Frappe whitelist registration
- self_service_access_controller.py: Self-service access validation with TOCTOU protection
- api_security_framework.py: Orchestrator (uses all above)

Import from the submodule that defines what you need, not from this package:

    from verenigingen.utils.security.api_security_framework import get_security_framework

This __init__ deliberately imports nothing at module level. It used to
re-export 13 submodules, which made `import verenigingen.utils.security.<anything>`
run all 13 first. CPython takes the submodule lock before the package lock
(importlib._bootstrap._find_and_load acquires the lock for the full dotted
name, then _find_and_load_unlocked re-enters the import of a parent whose spec
is still _initializing), so under a threaded web worker one thread could hold
the package lock inside this file while a second held a submodule lock and
waited for the package -- a cycle CPython reports as _DeadlockError. This
package has the widest exposure of any barrel in the app: ~394 files import
`api_security_framework` at module level, essentially every request path. See
verenigingen/services/billing/__init__.py, where this shape first surfaced in
production, and issue #396, which covers this and other barrel packages.

Note this is 3.13+ behaviour: python 3.12's _find_and_load_unlocked re-imports
the parent only when it is absent from sys.modules, so the cycle never closed.

`setup_all_security()` stays defined here (an `after_migrate` hook path,
"verenigingen.utils.security.setup_all_security", resolves it as an attribute
of this module), but its submodule imports are deferred inside the function
body. A function body only runs when called -- here, once, single-threaded,
during `bench migrate`, long after this module has finished initializing --
so those imports cannot participate in the deadlock the way a module-level
import can.

verenigingen/tests/utils/test_barrel_init_no_self_import.py keeps this file
honest, alongside every other barrel package in the app.
"""


def setup_all_security():
    """
    Setup all security measures during app initialization

    This function initializes and configures all security components:
    - CSRF protection
    - Rate limiting (via COR - Critical Operation Rules)
    - Authorization system
    - Audit logging
    """
    # Deliberately imported here, not at module level (see this module's
    # docstring) - but ALSO deliberately above the try/except below, not
    # inside it: an ImportError here is a real setup failure and must
    # propagate/log loudly, not be swallowed into a silent `return False`
    # the after_migrate hook never checks.
    from .audit_logging import setup_audit_logging
    from .authorization import setup_authorization
    from .csrf_protection import setup_csrf_protection

    try:
        # Setup individual components
        setup_csrf_protection()
        # Rate limiting now handled by COR (Critical Operation Rules)
        # Configured in fixtures/critical_operation_rule*.json
        setup_authorization()
        setup_audit_logging()

        # Log successful security setup
        from .audit_logging import log_sepa_event
        from .types import AuditSeverity

        log_sepa_event(
            "security_system_initialized",
            details={
                "components": ["csrf_protection", "rate_limiting_cor", "authorization", "audit_logging"],
                "status": "all_components_active",
            },
            severity=AuditSeverity.INFO,
        )

        return True

    except Exception as e:
        import frappe

        frappe.log_error(f"Security setup failed: {str(e)}", "Security System Setup Error")
        return False
