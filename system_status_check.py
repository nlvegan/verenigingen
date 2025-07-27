#!/usr/bin/env python3
"""
Simple system status check for Dues Invoice Submission System
"""

import frappe


@frappe.whitelist()
def check_system_status():
    """Check core system status - callable via bench execute"""

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
            "status": status,
            "summary": {
                "working_components": working_components,
                "total_components": total_components,
                "health_percentage": health_percentage,
                "overall_status": "HEALTHY" if health_percentage >= 80 else "NEEDS_ATTENTION",
            },
        }

    except Exception as e:
        return {"error": str(e), "status": status}


@frappe.whitelist()
def check_field_reference_sample():
    """Check a sample of field reference issues to understand their nature"""

    issues = []

    # Check SQL alias issue
    try:
        # This should be valid SQL - checking if 'volunteer' field exists in Team Member
        result = frappe.db.sql(
            """
            SELECT volunteer, volunteer_name
            FROM `tabTeam Member`
            WHERE volunteer IS NOT NULL
            LIMIT 1
        """,
            as_dict=True,
        )
        issues.append(
            {
                "type": "SQL_alias_check",
                "status": "VALID",
                "description": "volunteer field exists in Team Member table",
                "result_count": len(result),
            }
        )
    except Exception as e:
        issues.append({"type": "SQL_alias_check", "status": "ERROR", "description": str(e)})

    # Check another common pattern
    try:
        # Check Member doctype fields
        meta = frappe.get_meta("Member")
        fields = [f.fieldname for f in meta.fields]
        has_email = "email" in fields
        has_email_id = "email_id" in fields

        issues.append(
            {
                "type": "field_mapping_check",
                "status": "INFO",
                "description": f"Member has 'email': {has_email}, has 'email_id': {has_email_id}",
                "field_count": len(fields),
            }
        )
    except Exception as e:
        issues.append({"type": "field_mapping_check", "status": "ERROR", "description": str(e)})

    return {"field_reference_issues": issues}
