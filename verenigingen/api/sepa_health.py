"""
SEPA Health Check API.

Provides a health status endpoint for monitoring SEPA infrastructure.
This endpoint can be used by external monitoring tools (Zabbix, Prometheus, etc.)
to track the health of SEPA-related components.
"""
import frappe
from frappe.utils import add_days, now_datetime

from verenigingen.api.sepa_duplicate_prevention import check_redis_health


@frappe.whitelist()
def get_sepa_health() -> dict:
    """
    Get SEPA infrastructure health status.

    Returns a dictionary with overall status and individual check results:
    - status: "healthy" or "degraded"
    - timestamp: Current datetime string
    - checks: Dictionary of individual health checks

    Individual checks:
    - redis: Redis connectivity and lock capability
    - pending_batches: Count of batches awaiting processing
    - unreconciled: Count of old unreconciled transactions
    - recent_uploads: Recent upload activity

    Returns:
        dict with status, timestamp, and checks
    """
    checks = {}
    overall_healthy = True

    # Check 1: Redis connectivity
    checks["redis"] = _check_redis()
    if not checks["redis"]["healthy"]:
        overall_healthy = False

    # Check 2: Pending batches
    checks["pending_batches"] = _check_pending_batches()

    # Check 3: Unreconciled transactions
    checks["unreconciled"] = _check_unreconciled()
    if not checks["unreconciled"]["healthy"]:
        overall_healthy = False

    # Check 4: Recent upload logs
    checks["recent_uploads"] = _check_recent_uploads()

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": str(now_datetime()),
        "checks": checks,
    }


def _check_redis() -> dict:
    """
    Check Redis connectivity and SEPA lock capability.

    Returns:
        Dict with healthy, message, and locks_enabled
    """
    try:
        redis_health = check_redis_health()
        return {
            "healthy": redis_health.get("healthy", False),
            "message": redis_health.get("message", ""),
            "locks_enabled": frappe.conf.get("use_redis_locks_for_sepa", False),
        }
    except Exception as e:
        return {
            "healthy": False,
            "message": str(e),
            "locks_enabled": frappe.conf.get("use_redis_locks_for_sepa", False),
        }


def _check_pending_batches() -> dict:
    """
    Check count of pending Direct Debit Batches.

    Batches in Pending Approval, Approved, or Exported states
    are awaiting further processing.

    Returns:
        Dict with healthy, count, and warning flag
    """
    try:
        # Note: Direct Debit Batch status options are:
        # Draft, Generated, Submitted, Processed, Failed
        # Map these to the conceptual pending states
        pending_count = frappe.db.count(
            "Direct Debit Batch",
            filters={"status": ["in", ["Draft", "Generated", "Submitted"]]},
        )
        return {
            "healthy": True,
            "count": pending_count,
            "warning": pending_count > 5,
        }
    except Exception as e:
        return {
            "healthy": False,
            "count": 0,
            "warning": False,
            "error": str(e),
        }


def _check_unreconciled() -> dict:
    """
    Check count of unreconciled transactions older than 7 days.

    Uses Direct Debit Batch Invoice child table with status=Pending.

    Returns:
        Dict with healthy, count, and threshold
    """
    threshold = 50
    try:
        seven_days_ago = add_days(now_datetime(), -7)
        # Count pending invoice items in batches older than 7 days
        unreconciled = frappe.db.count(
            "Direct Debit Batch Invoice",
            filters={
                "status": "Pending",
                "creation": ["<", seven_days_ago],
            },
        )
        return {
            "healthy": unreconciled < threshold,
            "count": unreconciled,
            "threshold": threshold,
        }
    except Exception as e:
        return {
            "healthy": False,
            "count": 0,
            "threshold": threshold,
            "error": str(e),
        }


def _check_recent_uploads() -> dict:
    """
    Check count of SEPA Batch Upload Logs from the last 24 hours.

    Returns:
        Dict with healthy and count_24h
    """
    try:
        one_day_ago = add_days(now_datetime(), -1)
        recent_uploads = frappe.db.count(
            "SEPA Batch Upload Log",
            filters={"upload_time": [">=", one_day_ago]},
        )
        return {
            "healthy": True,
            "count_24h": recent_uploads,
        }
    except Exception as e:
        return {
            "healthy": False,
            "count_24h": 0,
            "error": str(e),
        }
