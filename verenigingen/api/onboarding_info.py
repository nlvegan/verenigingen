"""
Get onboarding information
"""

import frappe

from verenigingen.utils.security.rate_limiting import standard_api, utility_api


@utility_api()
@frappe.whitelist()
def get_onboarding_info():
    """Get detailed onboarding information"""

    try:
        # Check if Verenigingen onboarding exists
        if not frappe.db.exists("Module Onboarding", "Verenigingen"):
            return {"success": False, "error": "Verenigingen Module Onboarding not found"}

        # Get the onboarding document
        onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")

        # Get onboarding steps - check what fields exist first
        try:
            steps = frappe.get_all(
                "Onboarding Step",
                filters={"reference_document": "Verenigingen"},
                fields=["name", "title", "action", "is_complete"],
                order_by="idx",
            )
        except Exception:
            # Try different filter
            try:
                steps = frappe.get_all(
                    "Onboarding Step", fields=["name", "title", "action", "is_complete"], order_by="idx"
                )
                # Filter manually
                steps = [s for s in steps if "Verenigingen" in s.name]
            except Exception as e:
                steps = []
                str(e)

        return {
            "success": True,
            "onboarding": {
                "name": onboarding.name,
                "title": onboarding.title,
                "is_complete": onboarding.is_complete,
                "module": getattr(onboarding, "module", ""),
                "subtitle": getattr(onboarding, "subtitle", ""),
                "success_message": getattr(onboarding, "success_message", ""),
            },
            "steps": steps,
            "steps_count": len(steps),
            "direct_url": f"/app/module-onboarding/{onboarding.name}",
            "workspace_url": "/app/Verenigingen",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@utility_api()
@frappe.whitelist()
def get_direct_onboarding_link():
    """Get the direct link to access Verenigingen onboarding"""

    try:
        base_url = frappe.utils.get_url()

        # Check if onboarding exists
        if frappe.db.exists("Module Onboarding", "Verenigingen"):
            return {
                "success": True,
                "message": "Verenigingen onboarding is available",
                "links": {
                    "direct_onboarding": f"{base_url}/app/module-onboarding/Verenigingen",
                    "onboarding_list": f"{base_url}/app/module-onboarding",
                    "workspace": f"{base_url}/app/Verenigingen",
                },
                "instructions": [
                    "Click on the direct onboarding link above",
                    "OR go to your Verenigingen workspace and look for setup guides",
                    "OR search for 'Module Onboarding' in ERPNext search bar",
                ],
            }
        else:
            return {"success": False, "error": "Verenigingen Module Onboarding not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}
