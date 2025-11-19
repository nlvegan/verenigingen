#!/usr/bin/env python3
"""Workspace Reports Organizer - Reorganize reports sections and copy financial reports"""

import frappe


@frappe.whitelist()
def get_reports_structure(workspace_name="Verenigingen"):
    """Get current reports structure in workspace"""

    # Get all report links
    reports_links = frappe.db.sql(
        """
        SELECT wl.label, wl.link_to, wl.link_type, wl.idx, wl.name
        FROM `tabWorkspace Link` wl
        WHERE wl.parent = %s
        AND wl.type = 'Link'
        AND wl.link_type = 'Report'
        ORDER BY wl.idx
    """,
        workspace_name,
        as_dict=True,
    )

    # Categorize reports by type
    member_reports = []
    financial_reports = []
    system_reports = []
    other_reports = []

    for report in reports_links:
        label_lower = report.label.lower()

        if any(
            keyword in label_lower
            for keyword in ["revenue", "payment", "invoice", "dues", "financial", "overdue"]
        ):
            financial_reports.append(report)
        elif any(keyword in label_lower for keyword in ["termination", "compliance", "audit"]):
            system_reports.append(report)
        elif any(
            keyword in label_lower for keyword in ["member", "membership", "chapter", "age", "volunteer"]
        ):
            member_reports.append(report)
        else:
            other_reports.append(report)

    return {
        "workspace": workspace_name,
        "total_reports": len(reports_links),
        "all_reports": reports_links,
        "categorized": {
            "member_reports": member_reports,
            "financial_reports": financial_reports,
            "system_reports": system_reports,
            "other_reports": other_reports,
        },
    }


@frappe.whitelist()
def reorganize_reports_section(workspace_name="Verenigingen", dry_run=True):
    """Reorganize reports section with proper Card Breaks"""

    if dry_run:
        print(f"🔍 DRY RUN - Analyzing {workspace_name} reports reorganization")
    else:
        print(f"🔧 EXECUTING - Reorganizing {workspace_name} reports section")

    # Get current structure
    structure = get_reports_structure(workspace_name)

    print("\n📊 CURRENT REPORTS STRUCTURE:")
    print(f"Total reports: {structure['total_reports']}")
    print(f"Member & Chapter reports: {len(structure['categorized']['member_reports'])}")
    print(f"Financial reports: {len(structure['categorized']['financial_reports'])}")
    print(f"System reports: {len(structure['categorized']['system_reports'])}")
    print(f"Other reports: {len(structure['categorized']['other_reports'])}")

    if not dry_run:
        # Find the Reports Card Break
        reports_card_break = frappe.db.sql(
            """
            SELECT name, idx FROM `tabWorkspace Link`
            WHERE parent = %s AND type = 'Card Break' AND label = 'Reports'
        """,
            workspace_name,
            as_dict=True,
        )

        if not reports_card_break:
            print("❌ Could not find 'Reports' Card Break")
            return False

        base_idx = reports_card_break[0].idx

        # Delete existing generic Reports Card Break
        frappe.db.sql(
            'DELETE FROM `tabWorkspace Link` WHERE parent = %s AND type = "Card Break" AND label = "Reports"',
            workspace_name,
        )

        # Create new Card Breaks and reorganize links
        new_sections = [
            ("Member & Chapter Reports", structure["categorized"]["member_reports"]),
            ("Financial Reports", structure["categorized"]["financial_reports"]),
            ("System Reports", structure["categorized"]["system_reports"]),
        ]

        current_idx = base_idx

        for section_name, section_reports in new_sections:
            if not section_reports:  # Skip empty sections
                continue

            # Create Card Break
            card_break_doc = frappe.get_doc(
                {
                    "doctype": "Workspace Link",
                    "parent": workspace_name,
                    "parenttype": "Workspace",
                    "parentfield": "links",
                    "type": "Card Break",
                    "label": section_name,
                    "link_count": len(section_reports),
                    "idx": current_idx,
                }
            )
            card_break_doc.insert(ignore_permissions=True)
            current_idx += 1

            # Update report links to follow this Card Break
            for report in section_reports:
                frappe.db.sql(
                    """
                    UPDATE `tabWorkspace Link`
                    SET idx = %s
                    WHERE name = %s
                """,
                    (current_idx, report.name),
                )
                current_idx += 1

        # Handle other reports under original Reports section if any
        if structure["categorized"]["other_reports"]:
            card_break_doc = frappe.get_doc(
                {
                    "doctype": "Workspace Link",
                    "parent": workspace_name,
                    "parenttype": "Workspace",
                    "parentfield": "links",
                    "type": "Card Break",
                    "label": "Other Reports",
                    "link_count": len(structure["categorized"]["other_reports"]),
                    "idx": current_idx,
                }
            )
            card_break_doc.insert(ignore_permissions=True)
            current_idx += 1

            for report in structure["categorized"]["other_reports"]:
                frappe.db.sql(
                    """
                    UPDATE `tabWorkspace Link`
                    SET idx = %s
                    WHERE name = %s
                """,
                    (current_idx, report.name),
                )
                current_idx += 1

        frappe.db.commit()
        print("✅ Reports section reorganized successfully")

    return True


@frappe.whitelist()
def check_payments_workspace():
    """Check for existing payments workspace"""
    workspaces = frappe.get_all("Workspace", fields=["name", "title"])
    payments_workspaces = [ws for ws in workspaces if "payment" in ws.name.lower()]

    return {
        "all_workspaces": [ws.name for ws in workspaces],
        "payments_workspaces": payments_workspaces,
        "found_payments": len(payments_workspaces) > 0,
    }


@frappe.whitelist()
def copy_financial_section_to_payments_workspace(dry_run=True):
    """Copy Financial Reports section from Verenigingen to Verenigingen Payments workspace"""

    source_workspace = "Verenigingen"
    target_workspace = "Verenigingen Payments"

    if dry_run:
        print(f"🔍 DRY RUN - Copying Financial Reports from {source_workspace} to {target_workspace}")
    else:
        print("🔧 EXECUTING - Copying Financial Reports section")

    # Check if target workspace exists
    if not frappe.db.exists("Workspace", target_workspace):
        print(f"❌ Target workspace '{target_workspace}' does not exist")
        return False

    # Get financial reports from source
    structure = get_reports_structure(source_workspace)
    financial_reports = structure["categorized"]["financial_reports"]

    if not financial_reports:
        print("❌ No financial reports found to copy")
        return False

    print(f"\n📊 FINANCIAL REPORTS TO COPY ({len(financial_reports)}):")
    for report in financial_reports:
        print(f"  - {report.label} → {report.link_to}")

    if not dry_run:
        # Get highest idx in target workspace
        max_idx_result = frappe.db.sql(
            """
            SELECT COALESCE(MAX(idx), 0) as max_idx
            FROM `tabWorkspace Link`
            WHERE parent = %s
        """,
            target_workspace,
            as_dict=True,
        )

        next_idx = max_idx_result[0].max_idx + 1

        # Create Financial Reports Card Break in target workspace
        card_break_doc = frappe.get_doc(
            {
                "doctype": "Workspace Link",
                "parent": target_workspace,
                "parenttype": "Workspace",
                "parentfield": "links",
                "type": "Card Break",
                "label": "Financial Reports",
                "link_count": len(financial_reports),
                "idx": next_idx,
            }
        )
        card_break_doc.insert(ignore_permissions=True)
        next_idx += 1

        # Copy each financial report link
        for report in financial_reports:
            new_link_doc = frappe.get_doc(
                {
                    "doctype": "Workspace Link",
                    "parent": target_workspace,
                    "parenttype": "Workspace",
                    "parentfield": "links",
                    "type": "Link",
                    "label": report.label,
                    "link_to": report.link_to,
                    "link_type": report.link_type,
                    "link_count": 0,
                    "idx": next_idx,
                }
            )
            new_link_doc.insert(ignore_permissions=True)
            next_idx += 1

        frappe.db.commit()
        print(f"✅ Financial Reports section copied to {target_workspace}")

    return True
