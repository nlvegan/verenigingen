"""
Startup verification checks for critical Verenigingen services.

These checks run on application startup to verify that critical
infrastructure is properly configured.
"""
import frappe
from frappe.utils import cint


def verify_sepa_redis_on_startup() -> dict:
    """
    Verify SEPA Redis configuration on startup.

    Checks if Redis locks are enabled for SEPA processing and logs
    appropriate warnings if not configured for multi-worker safety.

    Returns:
        dict with check results:
            - checked: bool - True if check completed
            - redis_enabled: bool - True if use_redis_locks_for_sepa is set
            - multi_worker: bool - True if gunicorn_workers > 1
            - warning: str or None - Warning message if any
    """
    result = {
        "checked": True,
        "redis_enabled": False,
        "multi_worker": False,
        "warning": None,
    }

    # Check Redis locks configuration
    redis_enabled = frappe.conf.get("use_redis_locks_for_sepa", False)
    result["redis_enabled"] = redis_enabled

    # Check if multi-worker
    gunicorn_workers = cint(frappe.conf.get("gunicorn_workers", 1))
    result["multi_worker"] = gunicorn_workers > 1

    if result["multi_worker"] and not redis_enabled:
        warning = (
            "SEPA SAFETY WARNING: Multi-worker environment detected "
            f"({gunicorn_workers} workers) but Redis locks are not enabled. "
            "Set 'use_redis_locks_for_sepa': true in site_config.json to "
            "prevent duplicate payment processing."
        )
        result["warning"] = warning
        frappe.logger("sepa").warning(warning)

    if redis_enabled:
        # Verify Redis is actually reachable
        try:
            from verenigingen.api.sepa_duplicate_prevention import check_redis_health

            health = check_redis_health()
            if not health.get("healthy"):
                result["warning"] = "Redis locks enabled but Redis health check failed"
                frappe.logger("sepa").error(result["warning"])
        except Exception as e:
            result["warning"] = f"Redis health check error: {e}"
            frappe.logger("sepa").error(result["warning"])

    return result


def run_all_startup_checks():
    """Run all startup verification checks."""
    results = {}

    # SEPA Redis check
    results["sepa_redis"] = verify_sepa_redis_on_startup()

    return results
