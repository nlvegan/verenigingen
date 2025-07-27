"""
Workspace debugging API
"""
import frappe

from verenigingen.utils.security.api_security_framework import high_security_api, standard_api, utility_api


@utility_api
@frappe.whitelist()
def check_workspace_status():
    """Check Verenigingen workspace status and links"""

    try:
        workspace = frappe.get_doc("Workspace", "Verenigingen")

        result = {
            "name": workspace.name,
            "modified": str(workspace.modified),
            "links_count": len(workspace.links),
            "public": workspace.public,
            "hidden": workspace.is_hidden,
            "workflow_demo_found": False,
            "page_links": [],
            "broken_links": [],
            "content_length": len(workspace.content or ""),
            "content_preview": (workspace.content or "")[:300] if workspace.content else "No content",
        }

        # Check for workflow demo link and collect page links
        for link in workspace.links:
            if link.link_type == "Page":
                result["page_links"].append(
                    {"label": link.label, "link_to": link.link_to, "hidden": link.hidden}
                )
                if link.link_to == "/workflow_demo":
                    result["workflow_demo_found"] = True

        # Check for broken DocType and Report links
        for link in workspace.links:
            if link.link_type == "DocType" and link.link_to:
                if not frappe.db.exists("DocType", link.link_to):
                    result["broken_links"].append(f"DocType: {link.link_to}")
            elif link.link_type == "Report" and link.link_to:
                if not frappe.db.exists("Report", link.link_to):
                    result["broken_links"].append(f"Report: {link.link_to}")

        return {"success": True, "data": result}

    except Exception as e:
        return {"success": False, "error": str(e)}


@utility_api
@frappe.whitelist()
def check_eboekhouden_workspace():
    """Check if E-Boekhouden workspace exists and is valid"""
    try:
        # Check if workspace exists in database
        exists_in_db = frappe.db.exists("Workspace", "E-Boekhouden")

        result = {
            "exists_in_database": bool(exists_in_db),
            "workspace_data": None,
            "broken_links": [],
            "fixtures_status": "Not checked",
        }

        if exists_in_db:
            workspace = frappe.get_doc("Workspace", "E-Boekhouden")
            result["workspace_data"] = {
                "name": workspace.name,
                "label": workspace.label,
                "public": workspace.public,
                "hidden": workspace.is_hidden,
                "links_count": len(workspace.links),
                "module": workspace.module,
            }

            # Check for broken links
            for link in workspace.links:
                if link.link_type == "DocType" and link.link_to:
                    if not frappe.db.exists("DocType", link.link_to):
                        result["broken_links"].append(
                            {"type": "DocType", "link_to": link.link_to, "label": link.label}
                        )

        return {"success": True, "data": result}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_dues_system_status():
    """Check core dues invoice submission system status"""

    status = {
        "database_connection": False,
        "payment_history_doctype": False,
        "dues_schedule_doctype": False,
        "auto_submit_available": False,
        "invoice_generation_api": False,
        "payment_history_sync": False,
    }

    try:
        # Database connection
        frappe.db.sql("SELECT 1")
        status["database_connection"] = True

        # Member Payment History doctype
        meta = frappe.get_meta("Member Payment History")
        if meta:
            status["payment_history_doctype"] = True

        # Membership Dues Schedule doctype
        meta = frappe.get_meta("Membership Dues Schedule")
        if meta:
            status["dues_schedule_doctype"] = True

        # Auto-submit setting in System Settings
        try:
            from frappe.core.doctype.system_settings.system_settings import get_system_settings

            settings = get_system_settings()
            if hasattr(settings, "auto_submit_invoices"):
                status["auto_submit_available"] = True
        except:
            pass

        # Invoice generation API
        try:
            from verenigingen.api.manual_invoice_generation import generate_dues_invoice_for_member

            status["invoice_generation_api"] = True
        except:
            pass

        # Payment history sync
        try:
            from verenigingen.events.subscribers.payment_history_queue import refresh_financial_history

            status["payment_history_sync"] = True
        except:
            pass

        # Summary
        working_components = sum(status.values())
        total_components = len(status)
        health_percentage = (working_components / total_components) * 100

        return {
            "success": True,
            "status": status,
            "summary": {
                "working_components": working_components,
                "total_components": total_components,
                "health_percentage": health_percentage,
                "overall_status": "HEALTHY" if health_percentage >= 80 else "NEEDS_ATTENTION",
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "status": status}


@high_security_api
@frappe.whitelist()
def fix_eboekhouden_workspace_content():
    """Fix the E-Boekhouden workspace content structure"""
    import json

    try:
        workspace = frappe.get_doc("Workspace", "E-Boekhouden")

        # Update the content with proper structure
        new_content = [
            {
                "id": "MigrationHeader",
                "type": "header",
                "data": {"text": '<span class="h4"><b>E-Boekhouden Integration</b></span>', "col": 12},
            },
            {"id": "MigrationCard", "type": "card", "data": {"card_name": "Migration & Settings", "col": 4}},
            {"id": "MappingCard", "type": "card", "data": {"card_name": "Mapping & Configuration", "col": 4}},
            {"id": "MonitoringCard", "type": "card", "data": {"card_name": "Monitoring & Logs", "col": 4}},
        ]

        workspace.content = json.dumps(new_content)
        workspace.save()
        frappe.db.commit()

        return {
            "success": True,
            "message": "E-Boekhouden workspace content updated successfully",
            "new_content_preview": workspace.content[:200] + "...",
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@utility_api
@frappe.whitelist()
def check_eboekhouden_doctypes():
    """Check which E-Boekhouden doctypes exist in the database"""
    try:
        expected_doctypes = [
            "E-Boekhouden Migration",
            "E-Boekhouden Settings",
            "E-Boekhouden Dashboard",
            "E-Boekhouden Ledger Mapping",
            "E-Boekhouden Item Mapping",
            "E-Boekhouden Account Map",
            "EBoekhouden Payment Mapping",
            "E-Boekhouden Import Log",
        ]

        existing_doctypes = []
        missing_doctypes = []

        for doctype in expected_doctypes:
            if frappe.db.exists("DocType", doctype):
                existing_doctypes.append(doctype)
            else:
                missing_doctypes.append(doctype)

        return {
            "success": True,
            "total_expected": len(expected_doctypes),
            "existing_count": len(existing_doctypes),
            "missing_count": len(missing_doctypes),
            "existing_doctypes": existing_doctypes,
            "missing_doctypes": missing_doctypes,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@high_security_api
@frappe.whitelist()
def add_missing_eboekhouden_doctypes():
    """Add the missing E-Boekhouden doctypes to the workspace"""
    try:
        # First check which doctypes actually exist
        doctype_check = check_eboekhouden_doctypes()
        if not doctype_check["success"]:
            return doctype_check

        existing_doctypes = doctype_check["existing_doctypes"]
        workspace = frappe.get_doc("Workspace", "E-Boekhouden")

        # Check which existing doctypes are missing from workspace
        existing_links = [link.link_to for link in workspace.links if link.link_type == "DocType"]

        missing_from_workspace = []
        for doctype in existing_doctypes:
            if doctype not in existing_links:
                missing_from_workspace.append(doctype)

        if not missing_from_workspace:
            return {
                "success": True,
                "message": "All existing E-Boekhouden doctypes are already in the workspace",
                "added_count": 0,
                "existing_doctypes": existing_doctypes,
                "workspace_links": existing_links,
            }

        # Add missing doctypes to workspace
        added_count = 0
        for doctype in missing_from_workspace:
            if doctype == "E-Boekhouden Account Map":
                workspace.append(
                    "links",
                    {
                        "label": "Account Mapping",
                        "link_to": doctype,
                        "link_type": "DocType",
                        "type": "Link",
                        "hidden": 0,
                    },
                )
                added_count += 1
            elif doctype == "EBoekhouden Payment Mapping":
                workspace.append(
                    "links",
                    {
                        "label": "Payment Mapping",
                        "link_to": doctype,
                        "link_type": "DocType",
                        "type": "Link",
                        "hidden": 0,
                    },
                )
                added_count += 1

        # Update the link count for "Mapping & Configuration" card break if we added any
        if added_count > 0:
            for link in workspace.links:
                if link.type == "Card Break" and link.label == "Mapping & Configuration":
                    link.link_count = 3 + added_count  # Original 3 + new additions
                    break

            workspace.save()
            frappe.db.commit()

        return {
            "success": True,
            "message": f"Added {added_count} missing doctypes to E-Boekhouden workspace",
            "added_doctypes": missing_from_workspace,
            "added_count": added_count,
            "total_links": len(workspace.links),
            "existing_doctypes": existing_doctypes,
            "missing_from_db": doctype_check["missing_doctypes"],
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@high_security_api
@frappe.whitelist()
def force_reload_workspace():
    """Force reload the workspace from JSON file"""

    try:
        # Delete existing workspace
        if frappe.db.exists("Workspace", "Verenigingen"):
            frappe.delete_doc("Workspace", "Verenigingen", force=True)

        # Reload from fixtures
        frappe.reload_doc("verenigingen", "workspace", "verenigingen")
        frappe.db.commit()

        return {"success": True, "message": "Workspace reloaded successfully"}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@high_security_api
@frappe.whitelist()
def create_minimal_workspace():
    """Create minimal workspace and add workflow demo link"""

    try:
        # Create basic workspace if it doesn't exist
        if not frappe.db.exists("Workspace", "Verenigingen"):
            workspace = frappe.get_doc(
                {
                    "doctype": "Workspace",
                    "name": "Verenigingen",
                    "label": "Verenigingen",
                    "module": "E-Boekhouden",
                    "icon": "non-profit",
                    "public": 1,
                    "is_hidden": 0,
                }
            )
            workspace.insert(ignore_permissions=True)
        else:
            workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if workflow demo link exists
        workflow_demo_exists = False
        for link in workspace.links:
            if link.link_to == "/workflow_demo":
                workflow_demo_exists = True
                break

        # Add workflow demo link if it doesn't exist
        if not workflow_demo_exists:
            workspace.append(
                "links",
                {
                    "type": "Link",
                    "label": "Membership Application Workflow Demo",
                    "link_type": "Page",
                    "link_to": "/workflow_demo",
                    "hidden": 0,
                    "is_query_report": 0,
                    "onboard": 0,
                },
            )
            workspace.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Workspace created/updated. Workflow demo link {'already exists' if workflow_demo_exists else 'added'}.",
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@high_security_api
@frappe.whitelist()
def restore_full_workspace_structure():
    """Restore full workspace structure with all sections and links"""

    try:
        # Update workspace content directly in database to avoid validation
        content = """[
            {"id":"MembersHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Members/Memberships</b></span>","col":12}},
            {"id":"MembershipsCard","type":"card","data":{"card_name":"Memberships","col":4}},
            {"id":"DonationsCard","type":"card","data":{"card_name":"Donations","col":4}},
            {"id":"ANBICard","type":"card","data":{"card_name":"ANBI Tax Benefits","col":4}},
            {"id":"Spacer1","type":"spacer","data":{"col":12}},
            {"id":"VolunteeringHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Volunteering</b></span>","col":12}},
            {"id":"VolunteersCard","type":"card","data":{"card_name":"Volunteers","col":4}},
            {"id":"Spacer2","type":"spacer","data":{"col":12}},
            {"id":"ChaptersHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Chapters/Teams</b></span>","col":12}},
            {"id":"ChaptersCard","type":"card","data":{"card_name":"Chapters","col":4}},
            {"id":"TeamsCard","type":"card","data":{"card_name":"Teams and Commissions","col":4}},
            {"id":"Spacer3","type":"spacer","data":{"col":12}},
            {"id":"FinancialHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>","col":12}},
            {"id":"PaymentCard","type":"card","data":{"card_name":"Payment Processing","col":4}},
            {"id":"BankingCard","type":"card","data":{"card_name":"Banking","col":4}},
            {"id":"AccountingCard","type":"card","data":{"card_name":"Accounting (Misc.)","col":4}},
            {"id":"Spacer4","type":"spacer","data":{"col":12}},
            {"id":"ReportsHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Reports</b></span>","col":12}},
            {"id":"ReportsCard","type":"card","data":{"card_name":"Reports","col":8}},
            {"id":"Spacer5","type":"spacer","data":{"col":12}},
            {"id":"SettingsHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Settings</b></span>","col":12}},
            {"id":"SettingsCard","type":"card","data":{"card_name":"Settings","col":4}}
        ]"""

        # Update workspace content
        frappe.db.sql("UPDATE tabWorkspace SET content = %s WHERE name = 'Verenigingen'", (content,))

        # Clear existing links
        frappe.db.sql("DELETE FROM `tabWorkspace Link` WHERE parent = 'Verenigingen'")

        # Define essential links with proper structure
        links = [
            # Memberships section
            ("Card Break", "Memberships", None, None, 0, 5),
            ("Link", "Member", "DocType", "Member", 1, 0),
            ("Link", "Membership", "DocType", "Membership", 1, 0),
            ("Link", "Membership Type", "DocType", "Membership Type", 0, 0),
            ("Link", "Contribution Amendment Request", "DocType", "Contribution Amendment Request", 0, 0),
            ("Link", "Membership Termination Request", "DocType", "Membership Termination Request", 0, 0),
            # Donations section
            ("Card Break", "Donations", None, None, 0, 3),
            ("Link", "Donor", "DocType", "Donor", 0, 0),
            ("Link", "Donation", "DocType", "Donation", 0, 0),
            ("Link", "Donation Type", "DocType", "Donation Type", 0, 0),
            # ANBI section - skip problematic page links for now
            ("Card Break", "ANBI Tax Benefits", None, None, 0, 1),
            ("Link", "ANBI Donation Summary", "Report", "ANBI Donation Summary", 0, 0),
            # Volunteers section
            ("Card Break", "Volunteers", None, None, 0, 2),
            ("Link", "Volunteer", "DocType", "Volunteer", 1, 0),
            ("Link", "Volunteer Activity", "DocType", "Volunteer Activity", 0, 0),
            # Chapters section
            ("Card Break", "Chapters", None, None, 0, 2),
            ("Link", "Chapter", "DocType", "Chapter", 1, 0),
            ("Link", "Region", "DocType", "Region", 0, 0),
            # Teams section
            ("Card Break", "Teams and Commissions", None, None, 0, 1),
            ("Link", "Team", "DocType", "Team", 0, 0),
            # Payment Processing section
            ("Card Break", "Payment Processing", None, None, 0, 3),
            ("Link", "SEPA Mandate", "DocType", "SEPA Mandate", 0, 0),
            ("Link", "Direct Debit Batch", "DocType", "Direct Debit Batch", 0, 0),
            ("Link", "Payment Entry", "DocType", "Payment Entry", 0, 0),
            # Banking section
            ("Card Break", "Banking", None, None, 0, 3),
            ("Link", "Bank Account", "DocType", "Bank Account", 0, 0),
            ("Link", "Bank Transaction", "DocType", "Bank Transaction", 0, 0),
            ("Link", "Bank Reconciliation Tool", "DocType", "Bank Reconciliation Tool", 0, 0),
            # Accounting section
            ("Card Break", "Accounting (Misc.)", None, None, 0, 3),
            ("Link", "Sales Invoice", "DocType", "Sales Invoice", 0, 0),
            ("Link", "Purchase Invoice", "DocType", "Purchase Invoice", 0, 0),
            ("Link", "Journal Entry", "DocType", "Journal Entry", 0, 0),
            # Reports section (including workflow demo)
            ("Card Break", "Reports", None, None, 0, 6),
            ("Link", "Expiring Memberships", "Report", "Expiring Memberships", 0, 0),
            ("Link", "New Members", "Report", "New Members", 0, 0),
            ("Link", "Members Without Chapter", "Report", "Members Without Chapter", 0, 0),
            ("Link", "Overdue Member Payments", "Report", "Overdue Member Payments", 0, 0),
            ("Link", "Termination Compliance Report", "Report", "Termination Compliance Report", 0, 0),
            # Settings section
            ("Card Break", "Settings", None, None, 0, 2),
            ("Link", "Verenigingen Settings", "DocType", "Verenigingen Settings", 0, 0),
            ("Link", "Brand Settings", "DocType", "Brand Settings", 0, 0),
        ]

        # Insert links
        for idx, (type_, label, link_type, link_to, onboard, link_count) in enumerate(links, 1):
            name = frappe.generate_hash("", 10)
            frappe.db.sql(
                """
                INSERT INTO `tabWorkspace Link` (
                    name, parent, parenttype, parentfield, idx, type, label,
                    link_type, link_to, hidden, is_query_report, onboard, link_count
                ) VALUES (
                    %s, 'Verenigingen', 'Workspace', 'links', %s, %s, %s, %s, %s, 0, %s, %s, %s
                )
            """,
                (
                    name,
                    idx,
                    type_,
                    label,
                    link_type,
                    link_to,
                    1 if link_type == "Report" else 0,
                    onboard,
                    link_count,
                ),
            )

        # Add workflow demo link separately using database insert
        name = frappe.generate_hash("", 10)
        frappe.db.sql(
            """
            INSERT INTO `tabWorkspace Link` (
                name, parent, parenttype, parentfield, idx, type, label,
                link_type, link_to, hidden, is_query_report, onboard, link_count
            ) VALUES (
                %s, 'Verenigingen', 'Workspace', 'links', %s, 'Link',
                'Membership Application Workflow Demo', 'Page', '/workflow_demo',
                0, 0, 0, 0
            )
        """,
            (name, len(links) + 1),
        )

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Workspace structure restored with {len(links) + 1} links and proper content sections",
        }

    except Exception as e:
        frappe.db.rollback()
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
