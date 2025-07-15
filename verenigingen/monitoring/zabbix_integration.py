#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix Integration for Verenigingen

This is a thin wrapper that imports from the main implementation in scripts/monitoring/
All monitoring logic is maintained in scripts/monitoring/zabbix_integration.py
"""

import frappe

# Import the implementation module
import verenigingen.scripts.monitoring.zabbix_integration as zabbix_impl


@frappe.whitelist(allow_guest=True)
def get_metrics_for_zabbix():
    """Get metrics for Zabbix monitoring."""
    return zabbix_impl.get_metrics_for_zabbix()


@frappe.whitelist(allow_guest=True)
def health_check():
    """Health check endpoint for monitoring."""
    return zabbix_impl.health_check()


@frappe.whitelist()
def zabbix_webhook_receiver():
    """Receive webhooks from Zabbix for auto-remediation."""
    return zabbix_impl.zabbix_webhook_receiver()
