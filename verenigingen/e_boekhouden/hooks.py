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

# Scheduled tasks specific to E-Boekhouden
scheduler_events = {
    "daily": ["verenigingen.e_boekhouden.utils.eboekhouden_api.daily_sync_check"],
    "weekly": ["verenigingen.e_boekhouden.utils.cleanup_utils.cleanup_old_logs"],
}

# Document events specific to E-Boekhouden operations
doc_events = {
    "Account": {"before_save": ["verenigingen.e_boekhouden.utils.eboekhouden_api.validate_account_mapping"]},
    "Sales Invoice": {
        "on_submit": ["verenigingen.e_boekhouden.utils.eboekhouden_api.sync_invoice_to_eboekhouden"]
    },
}

# Website context for E-Boekhouden specific pages
website_context = {"eboekhouden_integration_enabled": True}

# Fixtures for E-Boekhouden specific setup data
fixtures = [
    {
        "dt": "Custom Field",
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
