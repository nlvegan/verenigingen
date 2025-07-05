import frappe


def get_context(context):
    """Context for the email template installation page"""
    if hasattr(context, "__setattr__"):
        context.no_cache = 1

    # Check what templates are missing vs available
    basic_templates = [
        "membership_application_confirmation",
        "membership_welcome",
        "volunteer_welcome",
        "membership_payment_failed",
    ]

    missing_templates = []
    existing_templates = []

    for template_name in basic_templates:
        if frappe.db.exists("Email Template", template_name):
            existing_templates.append(
                {"name": template_name, "title": template_name.replace("_", " ").title()}
            )
        else:
            missing_templates.append(
                {"name": template_name, "title": template_name.replace("_", " ").title()}
            )

    context.missing_templates = missing_templates
    context.existing_templates = existing_templates
    context.all_installed = len(missing_templates) == 0
    context.page_title = "Install Email Templates"

    return context


@frappe.whitelist()
def install_templates():
    """Install all missing email templates"""
    try:
        # Import and run the installation functions
        from verenigingen.setup import create_application_email_templates

        print("📧 Installing missing email templates...")

        # Install basic templates
        basic_count = create_application_email_templates()

        # Enable all newly created templates
        basic_templates = [
            "membership_application_confirmation",
            "membership_welcome",
            "volunteer_welcome",
            "membership_payment_failed",
        ]

        for template_name in basic_templates:
            if frappe.db.exists("Email Template", template_name):
                frappe.db.set_value("Email Template", template_name, "enabled", 1)

        # Also enable enhanced and comprehensive templates if they exist
        enhanced_templates = ["membership_application_rejected", "membership_rejection_incomplete"]
        for template_name in enhanced_templates:
            if frappe.db.exists("Email Template", template_name):
                frappe.db.set_value("Email Template", template_name, "enabled", 1)

        # Enable comprehensive templates (all expense and notification templates)
        comprehensive_templates = frappe.get_all(
            "Email Template",
            filters=[
                ["name", "like", "expense_%"],
                ["name", "like", "termination_%"],
                ["name", "like", "donation_%"],
            ],
            fields=["name"],
        )
        for template in comprehensive_templates:
            frappe.db.set_value("Email Template", template.name, "enabled", 1)

        # Install enhanced templates
        enhanced_count = 0
        try:
            from verenigingen.api.membership_application_review import create_default_email_templates

            enhanced_result = create_default_email_templates()
            enhanced_count = enhanced_result if isinstance(enhanced_result, int) else 0
        except Exception as e:
            print(f"Enhanced templates skipped: {str(e)}")

        # Install comprehensive templates
        comprehensive_count = 0
        try:
            from verenigingen.api.email_template_manager import create_comprehensive_email_templates

            comprehensive_result = create_comprehensive_email_templates()
            comprehensive_count = comprehensive_result if isinstance(comprehensive_result, int) else 0
        except Exception as e:
            print(f"Comprehensive templates skipped: {str(e)}")

        total_installed = basic_count + enhanced_count + comprehensive_count

        # Mark onboarding step as complete if it exists
        try:
            if frappe.db.exists("Onboarding Step", "Verenigingen-Install-Email-Templates"):
                step = frappe.get_doc("Onboarding Step", "Verenigingen-Install-Email-Templates")
                step.is_complete = 1
                step.save(ignore_permissions=True)
                frappe.db.commit()
        except Exception:
            pass

        return {
            "success": True,
            "message": f"✅ Successfully installed {total_installed} email templates!",
            "templates_installed": total_installed,
            "basic_count": basic_count,
            "enhanced_count": enhanced_count,
            "comprehensive_count": comprehensive_count,
        }

    except Exception as e:
        frappe.log_error(f"Email template installation failed: {str(e)}")
        return {"success": False, "message": f"❌ Error installing email templates: {str(e)}"}
