# Copyright (c) 2025, Vegan Netwerk Nederland
# License: MIT

"""
Add missing Ponto OAuth2 Critical Operation Rules.

This patch adds rules for check_authorization_status, get_authorization_url,
and revoke_authorization endpoints that were missing from the fixture.
"""

import frappe


def execute():
    """Add missing Ponto OAuth2 Critical Operation Rules."""
    # Import the setup function which only creates rules that don't exist
    from verenigingen.setup.critical_operation_rules_setup import (
        add_missing_critical_operation_rules,
    )

    result = add_missing_critical_operation_rules()

    if result["created"] > 0:
        frappe.db.commit()
        print(f"Added {result['created']} missing Critical Operation Rules")
