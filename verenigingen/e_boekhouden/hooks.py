"""
E-Boekhouden Module Hooks

This file defines the module-specific configuration for the E-Boekhouden
integration. It follows ERPNext's modular architecture pattern.
"""

# Module info
app_name = "e_boekhouden"
app_title = "E-Boekhouden Integration"
app_description = "Dutch accounting system integration for ERPNext"
app_version = "1.0.0"
app_publisher = "Verenigingen App"

# Module-specific DocTypes (will be loaded automatically from doctype folders)
# No explicit declaration needed - Frappe autodiscovers from directory structure

# NOTE: Frappe only loads hooks.py from the app root, not submodules.
# These were never active. The real doc_events for Sales Invoice are in
# vereinigingen/hooks/doc_events.py. Scheduler tasks for e-boekhouden
# are in verenigingen/hooks/scheduler.py. Dead references removed 2026-02-21.

# Website context for E-Boekhouden specific pages
website_context = {"eboekhouden_integration_enabled": True}

# Fixtures for E-Boekhouden specific setup data
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Account-eboekhouden_account_id",
                    "Customer-eboekhouden_customer_id",
                    "Supplier-eboekhouden_supplier_id",
                ],
            ]
        ],
    }
]
