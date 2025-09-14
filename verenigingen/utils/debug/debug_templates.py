import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_template_comparison():
    """Compare templates to understand minimum amount discrepancy"""

    templates_to_check = ["Template-Daily Access", "Template-Daglid"]
    result = {"templates": []}

    for template_name in templates_to_check:
        try:
            template = frappe.get_doc("Membership Dues Schedule", template_name)
            result["templates"].append(
                {
                    "name": template.name,
                    "is_template": template.is_template,
                    "minimum_amount": template.minimum_amount,
                    "suggested_amount": template.suggested_amount,
                    "dues_rate": template.dues_rate,
                    "membership_type": template.membership_type,
                    "contribution_mode": template.contribution_mode,
                }
            )
        except frappe.DoesNotExistError:
            result["templates"].append({"name": template_name, "error": "Template not found"})

    # Also check where the 5€ might be coming from
    # Let's look for any global settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        settings_fields = {}
        meta = frappe.get_meta("Verenigingen Settings")
        for field in meta.fields:
            if any(
                keyword in field.fieldname.lower() for keyword in ["minimum", "amount", "contribution", "fee"]
            ):
                settings_fields[field.fieldname] = getattr(settings, field.fieldname, None)
        result["verenigingen_settings"] = settings_fields
    except Exception as e:
        result["verenigingen_settings"] = {"error": str(e)}

    return result
