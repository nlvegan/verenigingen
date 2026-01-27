"""Sync Module Profile fixtures with proper flag handling.

Module Profile's on_update hook queues a background job with a document lock.
During normal fixture sync (bench migrate), the in_install flag is not set,
causing the job to be queued asynchronously. If migration fails after the
lock is created, subsequent retries fail with DocumentLockedError.

This patch syncs Module Profiles with in_install=True to ensure the
update_all_users job runs synchronously, avoiding stale locks.

See: https://github.com/frappe/frappe/issues/36368
"""

import frappe


def execute():
    """Sync Module Profile fixtures with in_install flag set."""
    # Set flag to ensure Module Profile.on_update runs synchronously
    # This prevents stale document locks if migration fails
    original_in_install = frappe.flags.in_install
    frappe.flags.in_install = True

    try:
        sync_module_profiles()
    finally:
        # Restore original flag state
        frappe.flags.in_install = original_in_install


def sync_module_profiles():
    """Create or update Module Profile documents."""
    module_profiles = get_module_profile_definitions()

    for profile_data in module_profiles:
        profile_name = profile_data["name"]
        block_modules = profile_data["block_modules"]

        if frappe.db.exists("Module Profile", profile_name):
            # Update existing profile
            doc = frappe.get_doc("Module Profile", profile_name)
            doc.block_modules = []
            for module in block_modules:
                doc.append("block_modules", {"module": module})
            doc.save()
        else:
            # Create new profile
            doc = frappe.new_doc("Module Profile")
            doc.name = profile_name
            doc.module_profile_name = profile_name
            for module in block_modules:
                doc.append("block_modules", {"module": module})
            doc.insert()


def get_module_profile_definitions():
    """Return Module Profile definitions.

    These match the fixtures/module_profile.json file.
    """
    # Common blocked modules for most profiles
    common_blocked = [
        "Assets",
        "Automation",
        "Bulk Transaction",
        "CRM",
        "Custom",
        "E Boekhouden",
        "E-Boekhouden",
        "EBICS",
        "EDI",
        "Email",
        "ERPNext Integrations",
        "Geo",
        "Integrations",
        "Klarna Kosma Integration",
        "Maintenance",
        "Manufacturing",
        "Owl Theme",
        "Payment Gateways",
        "Payments",
        "Payroll",
        "Printing",
        "Quality Management",
        "Regional",
        "Setup",
        "Social",
        "Stock",
        "Subcontracting",
        "Support",
        "Telephony",
        "Utilities",
        "Verenigingen Payments",
        "Workflow",
    ]

    return [
        {
            "name": "Verenigingen Member",
            "block_modules": common_blocked
            + [
                "Accounts",
                "Buying",
                "Communication",
                "Contacts",
                "Desk",
                "HR",
                "Projects",
                "Website",
            ],
        },
        {
            "name": "Verenigingen Volunteer",
            "block_modules": common_blocked
            + [
                "Accounts",
                "Communication",
                "Contacts",
                "HR",
                "Projects",
                "Selling",
                "Website",
            ],
        },
        {
            "name": "Verenigingen Chapter Board Member",
            "block_modules": common_blocked + ["Contacts", "HR", "Projects", "Website"],
        },
        {
            "name": "Verenigingen Auditor",
            "block_modules": common_blocked + ["Communication", "Contacts", "HR", "Projects", "Website"],
        },
        {
            "name": "Verenigingen National Board Member",
            "block_modules": common_blocked + ["Contacts", "HR"],
        },
        {
            "name": "Verenigingen Treasurer",
            "block_modules": common_blocked + ["Contacts", "HR", "Projects", "Website"],
        },
        {
            "name": "Verenigingen Webhook User",
            "block_modules": common_blocked
            + [
                "Communication",
                "Contacts",
                "Desk",
                "HR",
                "Portal",
                "Projects",
                "Website",
            ],
        },
    ]
