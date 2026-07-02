#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix Integration for Verenigingen

This is a thin wrapper that imports from the main implementation in scripts/monitoring/
All monitoring logic is maintained in scripts/monitoring/zabbix_integration.py
"""

import importlib.util
import os
import sys

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, webhook_api

# Add the scripts directory to the Python path
scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)


def _import_monitoring_functions():
    """Import monitoring functions with error handling."""
    try:
        # Import the monitoring module functions  # noqa: E402
        from monitoring.zabbix_integration import (  # noqa: E402  # noqa: E402
            get_metrics_for_zabbix as _get_metrics_for_zabbix,
            health_check as _health_check,  # noqa: E402
            is_valid_request as _is_valid_request,
            zabbix_webhook_receiver as _zabbix_webhook_receiver,
        )

        return _get_metrics_for_zabbix, _health_check, _zabbix_webhook_receiver, _is_valid_request
    except ImportError as e:
        frappe.log_error(f"Failed to import monitoring functions: {str(e)}")
        return None, None, None, None


(
    _get_metrics_for_zabbix,
    _health_check,
    _zabbix_webhook_receiver,
    _is_valid_request,
) = _import_monitoring_functions()


def _require_zabbix_auth():
    """Deny the request unless it is an authorized monitoring caller.

    Enforced here (before the swallowing try/except below) so an unauthenticated
    request gets a clean 403 instead of a 200 error envelope. Fails CLOSED if the
    scripts implementation could not be imported.
    """
    if _is_valid_request is None or not _is_valid_request():
        raise frappe.PermissionError(_("Unauthorized monitoring request"))


@frappe.whitelist(allow_guest=True)
def get_metrics_for_zabbix():
    """Get metrics for Zabbix monitoring."""
    _require_zabbix_auth()
    try:
        # Debug: Log the current user
        frappe.logger().info(f"get_metrics_for_zabbix called by user: {frappe.session.user}")

        # Call the actual implementation now that authentication is bypassed
        result = _get_metrics_for_zabbix()
        frappe.logger().info(f"get_metrics_for_zabbix result: {type(result)}")
        return result
    except Exception as e:
        frappe.log_error(f"Error in get_metrics_for_zabbix: {str(e)}")
        # Return basic metrics in case of error
        return {
            "timestamp": frappe.utils.now_datetime().isoformat(),
            "metrics": {"frappe.status": "error", "frappe.error": str(e)},
        }


@frappe.whitelist(allow_guest=True)
def health_check():
    """Health check endpoint for monitoring."""
    _require_zabbix_auth()
    try:
        return _health_check()
    except Exception as e:
        frappe.log_error(f"Error in health_check: {str(e)}")
        # Return basic health status in case of error
        return {"status": "unhealthy", "error": str(e), "timestamp": frappe.utils.now_datetime().isoformat()}


@frappe.whitelist()
@webhook_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def zabbix_webhook_receiver():
    """Receive webhooks from Zabbix for auto-remediation."""
    return _zabbix_webhook_receiver()
