import json

import frappe
from frappe import _


@frappe.whitelist()
def rebuild_workspace(force_enable=False):
    """Rebuild the workspace with proper structure based on fixtures

    Returns:
        dict: Success status with message and details
    """

    # SAFETY GUARD: Prevent accidental workspace destruction
    if not force_enable:
        return {
            "success": False,
            "message": "🛡️ WORKSPACE REBUILD DISABLED FOR SAFETY. This would destroy current workspace structure. Use force_enable=True to override.",
        }

    # Check permissions
    if not frappe.has_permission("Workspace", "write"):
        frappe.throw(_("Insufficient permissions to rebuild workspace"), frappe.PermissionError)

    try:
        # Backup existing workspace if it exists
        backup_workspace = None
        if frappe.db.exists("Workspace", "Verenigingen"):
            try:
                backup_workspace = frappe.get_doc("Workspace", "Verenigingen").as_dict()
                frappe.delete_doc("Workspace", "Verenigingen", force=True)
            except Exception as e:
                frappe.log_error(f"Failed to backup/delete existing workspace: {str(e)}", "Workspace Rebuild")
                return {"success": False, "error": f"Failed to remove existing workspace: {str(e)}"}

        # Create new workspace with proper structure
        workspace = frappe.new_doc("Workspace")
        workspace.name = "Verenigingen"
        workspace.label = "Verenigingen"
        workspace.title = "Verenigingen"
        workspace.icon = "non-profit"
        workspace.indicator_color = "green"
        workspace.module = "Verenigingen"
        workspace.public = 1

        # Set the content with proper sections
        workspace.content = json.dumps(
            [
                {
                    "id": "NFcjh9I8BH",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Members/Memberships</b></span>', "col": 12},
                },
                {"id": "oIk2CrSoAH", "type": "card", "data": {"card_name": "Memberships", "col": 4}},
                {"id": "BillingCard", "type": "card", "data": {"card_name": "Billing & Dues", "col": 4}},
                {
                    "id": "ApplicationsCard",
                    "type": "card",
                    "data": {"card_name": "Applications & Requests", "col": 4},
                },
                {"id": "ZvroSYo9F3", "type": "card", "data": {"card_name": "Donations", "col": 4}},
                {"id": "zGoLYG0xRM", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "jMy1CTqEJS",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Volunteering</b></span>', "col": 12},
                },
                {"id": "2vHgUjgQcL", "type": "card", "data": {"card_name": "Volunteers", "col": 4}},
                {"id": "ExpenseCard", "type": "card", "data": {"card_name": "Volunteer Expenses", "col": 4}},
                {"id": "zGoLYG0xRM2", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "jMy1CTqEJS2",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Chapters/Teams</b></span>', "col": 12},
                },
                {"id": "S8Mi0T41U7", "type": "card", "data": {"card_name": "Chapters", "col": 4}},
                {
                    "id": "XXEhdaTHF_",
                    "type": "card",
                    "data": {"card_name": "Teams and Commissions", "col": 4},
                },
                {"id": "zGoLYG0xRM3", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "CommunicationHeader",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Communication & Newsletters</b></span>', "col": 12},
                },
                {"id": "CommunicationCard", "type": "card", "data": {"card_name": "Communication", "col": 4}},
                {"id": "zGoLYG0xRM6", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "jMy1CTqEJS3",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Financial</b></span>', "col": 12},
                },
                {"id": "PaymentCard", "type": "card", "data": {"card_name": "Payment Processing", "col": 4}},
                {"id": "lYnozqzRgf", "type": "card", "data": {"card_name": "Banking", "col": 4}},
                {"id": "VN3xecH16c", "type": "card", "data": {"card_name": "Accounting (Misc.)", "col": 4}},
                {"id": "zGoLYG0xRM4", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "jMy1CTqEJS4",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Reports</b></span>', "col": 12},
                },
                {"id": "ReportsCard", "type": "card", "data": {"card_name": "Reports", "col": 8}},
                {"id": "zGoLYG0xRM5", "type": "spacer", "data": {"col": 12}},
                {
                    "id": "SettingsHeader",
                    "type": "header",
                    "data": {"text": '<span class="h4"><b>Settings & Configuration</b></span>', "col": 12},
                },
                {"id": "SettingsCard", "type": "card", "data": {"card_name": "Settings", "col": 4}},
                {"id": "PortalsCard", "type": "card", "data": {"card_name": "Portal Pages", "col": 4}},
            ]
        )

        # Add links organized by card
        links = []

        # Memberships Card
        links.append({"label": "Memberships", "type": "Card Break"})
        links.append({"label": "Member", "link_to": "Member", "link_type": "DocType", "onboard": 1})
        links.append({"label": "Membership", "link_to": "Membership", "link_type": "DocType", "onboard": 1})
        links.append({"label": "Membership Type", "link_to": "Membership Type", "link_type": "DocType"})
        links.append(
            {
                "label": "Membership Dues Schedule",
                "link_to": "Membership Dues Schedule",
                "link_type": "DocType",
            }
        )
        links.append(
            {
                "label": "Contribution Amendment Request",
                "link_to": "Contribution Amendment Request",
                "link_type": "DocType",
            }
        )

        # Billing & Dues Card
        links.append({"label": "Billing & Dues", "type": "Card Break"})
        links.append({"label": "Sales Invoice", "link_to": "Sales Invoice", "link_type": "DocType"})
        links.append({"label": "Payment Entry", "link_to": "Payment Entry", "link_type": "DocType"})

        # Applications & Requests Card
        links.append({"label": "Applications & Requests", "type": "Card Break"})
        links.append(
            {
                "label": "Membership Termination Request",
                "link_to": "Membership Termination Request",
                "link_type": "DocType",
            }
        )
        links.append(
            {
                "label": "Pending Membership Applications",
                "link_to": "Pending Membership Applications",
                "link_type": "Report",
                "is_query_report": 1,
            }
        )

        # Donations Card
        links.append({"label": "Donations", "type": "Card Break"})
        links.append({"label": "Donor", "link_to": "Donor", "link_type": "DocType"})
        links.append({"label": "Donation", "link_to": "Donation", "link_type": "DocType"})
        links.append({"label": "Donation Type", "link_to": "Donation Type", "link_type": "DocType"})
        links.append(
            {
                "label": "Periodic Donation Agreement",
                "link_to": "Periodic Donation Agreement",
                "link_type": "DocType",
            }
        )
        links.append({"label": "Donation Campaign", "link_to": "Donation Campaign", "link_type": "DocType"})

        # Volunteers Card
        links.append({"label": "Volunteers", "type": "Card Break"})
        links.append({"label": "Volunteer", "link_to": "Volunteer", "link_type": "DocType", "onboard": 1})
        links.append({"label": "Volunteer Activity", "link_to": "Volunteer Activity", "link_type": "DocType"})

        # Volunteer Expenses Card
        links.append({"label": "Volunteer Expenses", "type": "Card Break"})
        links.append({"label": "Volunteer Expense", "link_to": "Volunteer Expense", "link_type": "DocType"})
        links.append({"label": "Expense Category", "link_to": "Expense Category", "link_type": "DocType"})
        links.append({"label": "Expense Claim", "link_to": "Expense Claim", "link_type": "DocType"})

        # Chapters Card
        links.append({"label": "Chapters", "type": "Card Break"})
        links.append({"label": "Chapter", "link_to": "Chapter", "link_type": "DocType", "onboard": 1})
        links.append({"label": "Chapter Role", "link_to": "Chapter Role", "link_type": "DocType"})
        links.append({"label": "Region", "link_to": "Region", "link_type": "DocType"})

        # Teams and Commissions Card
        links.append({"label": "Teams and Commissions", "type": "Card Break"})
        links.append({"label": "Team", "link_to": "Team", "link_type": "DocType"})

        # Communication Card - ONLY newsletter related items
        links.append({"label": "Communication", "type": "Card Break"})
        links.append(
            {
                "label": "Newsletter",
                "link_to": "Newsletter",
                "link_type": "DocType",
                "description": "Create and send newsletters",
            }
        )
        links.append(
            {
                "label": "Email Group",
                "link_to": "Email Group",
                "link_type": "DocType",
                "description": "Manage email groups",
            }
        )
        links.append(
            {
                "label": "Email Group Member",
                "link_to": "Email Group Member",
                "link_type": "DocType",
                "description": "Manage group members",
            }
        )
        links.append(
            {
                "label": "Email Template",
                "link_to": "Email Template",
                "link_type": "DocType",
                "description": "Email templates",
            }
        )
        links.append(
            {
                "label": "Communication",
                "link_to": "Communication",
                "link_type": "DocType",
                "description": "Communication logs",
            }
        )

        # Payment Processing Card
        links.append({"label": "Payment Processing", "type": "Card Break"})
        links.append({"label": "Payment Entry", "link_to": "Payment Entry", "link_type": "DocType"})
        links.append({"label": "Payment Request", "link_to": "Payment Request", "link_type": "DocType"})
        links.append({"label": "Payment Order", "link_to": "Payment Order", "link_type": "DocType"})
        links.append({"label": "SEPA Mandate", "link_to": "SEPA Mandate", "link_type": "DocType"})
        links.append({"label": "Direct Debit Batch", "link_to": "Direct Debit Batch", "link_type": "DocType"})
        links.append({"label": "SEPA Payment Retry", "link_to": "SEPA Payment Retry", "link_type": "DocType"})

        # Banking Card
        links.append({"label": "Banking", "type": "Card Break"})
        links.append({"label": "Bank Account", "link_to": "Bank Account", "link_type": "DocType"})
        links.append({"label": "Bank Transaction", "link_to": "Bank Transaction", "link_type": "DocType"})
        links.append(
            {
                "label": "Bank Reconciliation Tool",
                "link_to": "Bank Reconciliation Tool",
                "link_type": "DocType",
            }
        )
        links.append(
            {"label": "Bank Statement Import", "link_to": "Bank Statement Import", "link_type": "DocType"}
        )
        links.append({"label": "Bank Guarantee", "link_to": "Bank Guarantee", "link_type": "DocType"})

        # Accounting (Misc.) Card
        links.append({"label": "Accounting (Misc.)", "type": "Card Break"})
        links.append({"label": "Journal Entry", "link_to": "Journal Entry", "link_type": "DocType"})
        links.append({"label": "Purchase Invoice", "link_to": "Purchase Invoice", "link_type": "DocType"})
        links.append({"label": "Account", "link_to": "Account", "link_type": "DocType"})
        links.append(
            {"label": "Accounting Dimension", "link_to": "Accounting Dimension", "link_type": "DocType"}
        )

        # Reports Card
        links.append({"label": "Reports", "type": "Card Break"})
        # Member & Chapter Reports
        links.append({"label": "Member & Chapter Reports", "type": "Card Break"})
        for report in [
            "Expiring Memberships",
            "New Members",
            "Members Without Chapter",
            "Members Without Active Memberships",
            "Members Without Dues Schedule",
        ]:
            links.append({"label": report, "link_to": report, "link_type": "Report", "is_query_report": 1})

        # Financial Reports
        links.append({"label": "Financial Reports", "type": "Card Break"})
        for report in [
            "Overdue Member Payments",
            "Chapter Expense Report",
            "Membership Dues Coverage Analysis",
        ]:
            links.append({"label": report, "link_to": report, "link_type": "Report", "is_query_report": 1})

        # System Reports
        links.append({"label": "System Reports", "type": "Card Break"})
        for report in ["Termination Compliance Report", "Users by Team"]:
            links.append({"label": report, "link_to": report, "link_type": "Report", "is_query_report": 1})

        # Settings Card
        links.append({"label": "Settings", "type": "Card Break"})
        links.append(
            {"label": "Verenigingen Settings", "link_to": "Verenigingen Settings", "link_type": "DocType"}
        )
        links.append({"label": "Brand Settings", "link_to": "Brand Settings", "link_type": "DocType"})

        # Add all links to workspace with validation
        validated_links = []
        skipped_links = []

        for link in links:
            # Validate DocType/Report exists before adding
            if link.get("link_type") == "DocType":
                if frappe.db.exists("DocType", link.get("link_to")):
                    workspace.append("links", link)
                    validated_links.append(link.get("link_to"))
                else:
                    skipped_links.append(f"DocType: {link.get('link_to')}")
            elif link.get("link_type") == "Report":
                if frappe.db.exists("Report", link.get("link_to")):
                    workspace.append("links", link)
                    validated_links.append(link.get("link_to"))
                else:
                    skipped_links.append(f"Report: {link.get('link_to')}")
            else:
                # Card breaks and other non-link items
                workspace.append("links", link)

        # Save workspace WITHOUT bypassing permissions
        workspace.insert()
        frappe.db.commit()
        frappe.clear_cache()

        # Log the rebuild action
        frappe.log_error(
            f"Workspace rebuilt by {frappe.session.user}. Links: {len(validated_links)}, Skipped: {len(skipped_links)}",
            "Workspace Rebuild Success",
        )

        return {
            "success": True,
            "message": "Workspace rebuilt successfully",
            "total_links": len(workspace.links),
            "validated_links": len(validated_links),
            "skipped_links": skipped_links if skipped_links else None,
            "sections": [
                "Memberships",
                "Volunteering",
                "Chapters/Teams",
                "Communication",
                "Financial",
                "Reports",
                "Settings",
            ],
        }

    except Exception as e:
        # Attempt to restore backup if rebuild failed
        if backup_workspace:
            try:
                restored = frappe.new_doc("Workspace")
                for key, value in backup_workspace.items():
                    if key not in [
                        "doctype",
                        "modified",
                        "modified_by",
                        "owner",
                        "creation",
                        "idx",
                        "docstatus",
                    ]:
                        setattr(restored, key, value)
                restored.insert()
                frappe.db.commit()
                frappe.log_error(
                    f"Restored workspace backup after failed rebuild: {str(e)}", "Workspace Rollback"
                )
            except Exception as restore_error:
                frappe.log_error(
                    f"Failed to restore workspace backup: {str(restore_error)}", "Workspace Restore Error"
                )

        frappe.log_error(f"Workspace rebuild failed: {str(e)}", "Workspace Rebuild Error")
        return {
            "success": False,
            "error": f"Workspace rebuild failed: {str(e)}",
            "traceback": frappe.get_traceback(),
        }
