#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix Integration for Vereinigingen

This module imports from the enhanced implementation in scripts/monitoring/
The enhanced version consolidates features from multiple implementations:
- Original monitoring implementation
- Advanced Zabbix 7.0 features
- Auto-remediation capabilities
- Performance metrics

All API endpoints remain the same for backward compatibility.
"""

import os
import sys

# Add scripts directory to path to import from scripts/monitoring
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
scripts_path = os.path.join(app_path, "scripts", "monitoring")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

try:
    # Import all functions and classes from enhanced implementation
    # Log successful import
    import frappe
    from zabbix_integration_enhanced import (  # Main API endpoints; Metric collection functions; Health check functions; Webhook processing; Alert handling; Utility functions; Classes
        ZabbixIntegration,
        check_database_health,
        check_disk_space,
        check_financial_health,
        check_redis_health,
        check_scheduler_health,
        check_subscription_health,
        create_issue_from_alert,
        format_metrics_for_zabbix_v7,
        get_business_metrics,
        get_error_breakdown_metrics,
        get_financial_metrics,
        get_metrics_for_zabbix,
        get_performance_percentiles,
        get_subscription_metrics,
        get_system_metrics,
        handle_auto_remediation,
        health_check,
        is_valid_zabbix_request,
        log_alert,
        process_legacy_webhook,
        process_zabbix_v7_webhook,
        should_auto_remediate,
        validate_webhook_signature,
        zabbix_webhook_receiver,
    )

    frappe.logger().info("Successfully imported enhanced Zabbix integration")

except ImportError as e:
    # Log error and raise to prevent silent failures
    import frappe

    frappe.log_error(
        f"Failed to import enhanced Zabbix integration: {str(e)}\n"
        "Please ensure scripts/monitoring/zabbix_integration_enhanced.py exists",
        "Zabbix Integration Import Error",
    )
    raise Exception("Could not import enhanced Zabbix integration. " "Check error logs for details.")
