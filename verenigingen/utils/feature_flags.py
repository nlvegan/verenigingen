"""
Feature Flags for Verenigingen
Controls which features are enabled/disabled
"""

import frappe
from frappe import _


def is_dues_schedule_system_enabled():
    """
    Check if the new dues schedule system is enabled

    Returns:
        bool: True if dues schedule system should be active, False otherwise
    """
    # Dues schedule is always enabled (it's the new default)
    return True


def get_payment_system_status():
    """
    Get the status of the payment system

    Returns:
        dict: Status of dues schedule system
    """
    return {
        "dues_schedule_enabled": is_dues_schedule_system_enabled(),
        "recommended_system": "dues_schedule",
        "migration_status": "dues_schedule_active",
    }


def check_feature_availability(feature_name):
    """
    Check if a specific feature is available

    Args:
        feature_name: Name of the feature to check

    Returns:
        bool: True if feature is available, False otherwise
    """
    feature_map = {
        "dues_schedule_creation": True,
        "dues_schedule_invoicing": True,
        "member_portal": True,
        "admin_dashboard": True,
        "chapter_management": True,
        "volunteer_management": True,
        "sepa_direct_debit": True,
    }

    return feature_map.get(feature_name, False)


def get_system_info():
    """
    Get information about the current system configuration

    Returns:
        dict: System information and status
    """
    return {
        "payment_system": "membership_dues_schedule",
        "version": "2.0",
        "features": {
            "dues_schedule_system": True,
            "sepa_direct_debit": True,
            "member_portal": True,
            "chapter_management": True,
            "volunteer_management": True,
            "termination_workflows": True,
        },
        "migration_status": "complete",
    }
