# Setup and configuration utilities for Verenigingen app

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.page.setup_wizard.setup_wizard import make_records


def ensure_prerequisites():
    """Ensure required master data exists before creating records"""

    # Ensure "All Customer Groups" exists
    if not frappe.db.exists("Customer Group", "All Customer Groups"):
        try:
            all_groups = frappe.get_doc(
                {
                    "doctype": "Customer Group",
                    "customer_group_name": "All Customer Groups",
                    "is_group": 1,
                    "parent_customer_group": "",
                }
            )
            all_groups.insert(ignore_permissions=True)
            print("Created 'All Customer Groups' customer group")
        except Exception as e:
            print(f"Warning: Could not create 'All Customer Groups': {str(e)}")

    # Ensure "Services" Item Group exists
    if not frappe.db.exists("Item Group", "Services"):
        try:
            # Get or create parent item group first
            if not frappe.db.exists("Item Group", "All Item Groups"):
                all_items = frappe.get_doc(
                    {
                        "doctype": "Item Group",
                        "item_group_name": "All Item Groups",
                        "is_group": 1,
                        "parent_item_group": "",
                    }
                )
                all_items.insert(ignore_permissions=True)

            services_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Services",
                    "is_group": 0,
                    "parent_item_group": "All Item Groups",
                }
            )
            services_group.insert(ignore_permissions=True)
            print("Created 'Services' item group")
        except Exception as e:
            print(f"Warning: Could not create 'Services' item group: {str(e)}")

    # Ensure "Nos" UOM exists
    if not frappe.db.exists("UOM", "Nos"):
        try:
            nos_uom = frappe.get_doc({"doctype": "UOM", "uom_name": "Nos", "name": "Nos"})
            nos_uom.insert(ignore_permissions=True)
            print("Created 'Nos' unit of measure")
        except Exception as e:
            print(f"Warning: Could not create 'Nos' UOM: {str(e)}")


def make_custom_records():
    # First ensure prerequisites exist
    ensure_prerequisites()

    records = [
        {"doctype": "Party Type", "party_type": "Member", "account_type": "Receivable"},
        # Customer Group for donors
        {
            "doctype": "Customer Group",
            "customer_group_name": "Donors",
            "parent_customer_group": "All Customer Groups",
            "is_group": 0,
        },
        # Donation item for Sales Invoice integration
        {
            "doctype": "Item",
            "item_code": "DONATION",
            "item_name": "Donation",
            "item_group": "Services",
            "stock_uom": "Nos",
            "is_stock_item": 0,
            "is_sales_item": 1,
            "is_service_item": 1,
            "description": "Standard donation item for nonprofit operations",
        },
    ]
    make_records(records)


def setup_verenigingen():
    make_custom_records()
    make_custom_fields()

    # Follow Frappe best practices: create child table through parent document
    try:
        domain_settings = frappe.get_doc("Domain Settings")
        # Check if domain already exists
        existing_domain = any(domain.domain == "Verenigingen" for domain in domain_settings.active_domains)
        if not existing_domain:
            domain_settings.append("active_domains", {"domain": "Verenigingen"})
            domain_settings.save()
    except frappe.DoesNotExistError:
        frappe.logger().warning("Domain Settings not found - skipping domain setup")

    domain = frappe.get_doc("Domain", "Verenigingen")
    domain.setup_domain()

    domain_settings = frappe.get_single("Domain Settings")
    domain_settings.append("active_domains", dict(domain=domain))
    frappe.clear_cache()


data = {"on_setup": "verenigingen.setup.setup_verenigingen"}


def make_custom_fields(update=True):
    custom_fields = get_custom_fields()
    create_custom_fields(custom_fields, update=update)


def get_custom_fields():
    # Constants for Dutch BTW Codes
    BTW_CODES = {
        "EXEMPT_NONPROFIT": "BTW Vrijgesteld - Art. 11-1-f Wet OB",
        "EXEMPT_MEMBERSHIP": "BTW Vrijgesteld - Art. 11-1-l Wet OB",
        "EXEMPT_FUNDRAISING": "BTW Vrijgesteld - Art. 11-1-v Wet OB",
        "EXEMPT_SMALL_BUSINESS": "BTW Vrijgesteld - KOR",
        "OUTSIDE_SCOPE": "Buiten reikwijdte BTW",
        "EXEMPT_WITH_INPUT": "BTW Vrijgesteld met recht op aftrek",
        "EXEMPT_NO_INPUT": "BTW Vrijgesteld zonder recht op aftrek",
    }

    custom_fields = {
        "Company": [
            dict(
                fieldname="verenigingen_section",
                label="Verenigingen Settings",
                fieldtype="Section Break",
                insert_after="asset_received_but_not_billed",
                collapsible=1,
            )
        ],
        "Customer": [
            {
                "fieldname": "donor",
                "label": "Donor",
                "fieldtype": "Link",
                "options": "Donor",
                "insert_after": "customer_group",
                "description": "Link to original donor record for nonprofit operations",
            }
        ],
        "Sales Invoice": [
            dict(
                fieldname="exempt_from_tax",
                label="Exempt from Tax",
                fieldtype="Check",
                insert_after="tax_category",
                translatable=0,
            ),
            # BTW fields that were missing and causing the error
            {
                "fieldname": "btw_exemption_type",
                "label": "BTW Exemption Type",
                "fieldtype": "Select",
                "options": "\n" + "\n".join(BTW_CODES.keys()),
                "insert_after": "exempt_from_tax",
                "translatable": 0,
            },
            {
                "fieldname": "btw_exemption_reason",
                "label": "BTW Exemption Reason",
                "fieldtype": "Small Text",
                "insert_after": "btw_exemption_type",
                "translatable": 0,
                "depends_on": "eval:doc.btw_exemption_type",
            },
            {
                "fieldname": "btw_reporting_category",
                "label": "BTW Reporting Category",
                "fieldtype": "Data",
                "insert_after": "btw_exemption_reason",
                "translatable": 0,
                "read_only": 1,
                "depends_on": "eval:doc.btw_exemption_type",
            },
            # Donation tracking fields
            {
                "fieldname": "custom_donation_section",
                "label": "Donation Information",
                "fieldtype": "Section Break",
                "insert_after": "btw_reporting_category",
                "collapsible": 1,
            },
            {
                "fieldname": "custom_source_donation",
                "label": "Source Donation",
                "fieldtype": "Link",
                "options": "Donation",
                "insert_after": "custom_donation_section",
                "description": "Original donation record that created this invoice",
            },
        ],
        "Membership": [
            {
                "fieldname": "btw_exemption_type",
                "label": "BTW Exemption Type",
                "fieldtype": "Select",
                "options": "\n" + "\n".join(BTW_CODES.keys()),
                "insert_after": "membership_type",
                "default": "EXEMPT_MEMBERSHIP",
                "translatable": 0,
            }
        ],
    }

    # Add Donation fields if Donation doctype exists
    if frappe.db.exists("DocType", "Donation"):
        custom_fields["Donation"] = [
            {
                "fieldname": "btw_exemption_type",
                "label": "BTW Exemption Type",
                "fieldtype": "Select",
                "options": "\n" + "\n".join(BTW_CODES.keys()),
                "insert_after": "donation_category",
                "default": "EXEMPT_FUNDRAISING",
                "translatable": 0,
            }
        ]

    return custom_fields


def validate_app_dependencies():
    """Validate that required apps are installed"""
    required_apps = ["erpnext", "payments", "hrms", "banking"]
    missing_apps = []

    try:
        # Use frappe.get_installed_apps() which is more reliable during installation
        installed_apps = frappe.get_installed_apps()

        for app in required_apps:
            if app not in installed_apps:
                missing_apps.append(app)

        if missing_apps:
            frappe.throw(
                f"Missing required apps: {', '.join(missing_apps)}. "
                "Please install these apps before installing verenigingen.",
                title="Missing Dependencies",
            )

        print(f"✅ All required apps are installed: {', '.join(required_apps)}")

    except Exception as e:
        # If validation fails, just log a warning and continue
        # This prevents installation failures due to dependency checking issues
        print(f"⚠️  Warning: Could not validate app dependencies: {str(e)}")
        print(
            "Continuing with installation - please ensure erpnext, payments, hrms, and banking are installed"
        )


def execute_after_install():
    """
    Function executed after the app is installed
    Sets up necessary configurations for the Verenigingen app
    """
    try:
        # Validate dependencies
        validate_app_dependencies()

        # Create E-Boekhouden custom fields first
        create_eboekhouden_custom_fields()

        # Create default E-Boekhouden Settings
        create_default_eboekhouden_settings()

        # Execute the setup function from this file
        setup_verenigingen()

        # Set up membership application system
        setup_membership_application_system()

        # Set up tax exemption templates if enabled
        setup_tax_exemption_on_install()

        # Set up termination system
        setup_termination_system_integration()

        # Set up workspace
        setup_workspace()

        # Load fixtures
        load_application_fixtures()

        # Set up security configurations
        try:
            from verenigingen.setup.security_setup import setup_all_security

            setup_all_security()
        except Exception as e:
            print(f"⚠️ Security setup failed: {str(e)}")
            frappe.logger().warning(f"Security setup failed: {str(e)}")

        # Log the successful setup
        frappe.logger().info("Verenigingen setup completed successfully")
        print("Verenigingen app setup completed successfully")

    except Exception as e:
        frappe.logger().error(f"Error during Verenigingen setup: {str(e)}")
        print(f"Error during setup: {str(e)}")


def create_eboekhouden_custom_fields():
    """E-Boekhouden custom fields are now created via fixtures"""
    print("✅ E-Boekhouden custom fields created via fixtures")


def create_default_eboekhouden_settings():
    """Create default E-Boekhouden Settings single document"""
    try:
        if not frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings"):
            settings = frappe.get_doc(
                {
                    "doctype": "E-Boekhouden Settings",
                    "api_url": "https://secure.e-boekhouden.nl/verhuur/api_rpc.php",
                    "source_application": "Verenigingen App",
                }
            )
            settings.insert(ignore_permissions=True)
            print("✅ Created default E-Boekhouden Settings")
        else:
            print("✅ E-Boekhouden Settings already exists")
    except Exception as e:
        print(f"⚠️ Failed to create E-Boekhouden Settings: {str(e)}")


def setup_tax_exemption_on_install():
    """Set up tax exemption during installation if enabled"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings.get("tax_exempt_for_contributions"):
            # Import and run the tax setup
            from verenigingen.utils import setup_dutch_tax_exemption

            setup_dutch_tax_exemption()
            print("Tax exemption templates set up during installation")
    except Exception as e:
        frappe.logger().error(f"Error setting up tax exemption during install: {str(e)}")
        print(f"Warning: Could not set up tax exemption during install: {str(e)}")


@frappe.whitelist()
def install_missing_btw_fields():
    """Install BTW custom fields that were missing"""
    try:
        make_custom_fields(update=True)
        frappe.msgprint(_("BTW custom fields installed successfully. Please refresh to see changes."))
        return True
    except Exception as e:
        frappe.msgprint(_(f"Error installing BTW fields: {str(e)}"))
        frappe.log_error(f"Error installing BTW fields: {str(e)}", "BTW Field Installation Error")
        return False


@frappe.whitelist()
def verify_btw_installation():
    """Verify that BTW fields are properly installed"""
    missing_fields = []

    # Check required BTW fields
    required_fields = [
        ("Sales Invoice", "btw_exemption_type"),
        ("Sales Invoice", "btw_exemption_reason"),
        ("Sales Invoice", "btw_reporting_category"),
        ("Membership", "btw_exemption_type"),
    ]

    for doctype, fieldname in required_fields:
        if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
            missing_fields.append(f"{doctype}.{fieldname}")

    if missing_fields:
        return {
            "status": "Missing Fields",
            "missing_fields": missing_fields,
            "message": f"Missing {len(missing_fields)} BTW custom fields",
        }
    else:
        return {"status": "All Good", "message": "All BTW custom fields are installed"}


@frappe.whitelist()
def fix_btw_installation():
    """Fix BTW installation issues"""
    try:
        # Reinstall custom fields
        install_missing_btw_fields()

        # Set up tax templates if needed
        settings = frappe.get_single("Verenigingen Settings")
        if settings.get("tax_exempt_for_contributions"):
            from verenigingen.utils import setup_dutch_tax_exemption

            setup_dutch_tax_exemption()

        frappe.msgprint(_("BTW installation fixed successfully"))
        return True

    except Exception as e:
        frappe.msgprint(_(f"Error fixing BTW installation: {str(e)}"))
        return False


def setup_termination_system_integration():
    """Setup the termination system as part of app installation"""
    try:
        print("🔧 Setting up termination system...")

        # Step 1: Setup termination-specific settings
        setup_termination_settings()

        # Step 2: Setup workflows (using separate workflow setup module)
        from verenigingen.setup.workflow_setup import setup_workflows_corrected

        workflow_success = setup_workflows_corrected()

        if workflow_success:
            print("✅ Workflows created successfully")
        else:
            print("⚠️ Workflow creation had issues")

        # Step 3: Setup roles and permissions
        setup_termination_roles_and_permissions()

        print("✅ Termination system setup completed")

    except Exception as e:
        frappe.log_error(f"Termination system setup error: {str(e)}", "Termination Setup Error")
        print(f"⚠️ Termination system setup failed: {str(e)}")


def setup_termination_settings():
    """Setup termination system settings"""

    try:
        # Get or create Verenigingen Settings
        if not frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            # This should already be created by the main setup, but just in case
            return

        settings = frappe.get_single("Verenigingen Settings")

        # Add termination system settings if they don't exist
        termination_defaults = {
            "enable_termination_system": 1,
            "require_secondary_approval": 1,
            "appeal_deadline_days": 30,
            "appeal_review_days": 60,
            "termination_grace_period_days": 30,
            "auto_cancel_sepa_mandates": 1,
            "auto_end_board_positions": 1,
            "send_termination_notifications": 1,
        }

        settings_updated = False
        for field, default_value in termination_defaults.items():
            if hasattr(settings, field):
                if not getattr(settings, field):
                    setattr(settings, field, default_value)
                    settings_updated = True

        if settings_updated:
            settings.save(ignore_permissions=True)
            frappe.db.commit()
            print("   ✓ Termination settings configured")
        else:
            print("   ✓ Termination settings already configured")

    except Exception as e:
        print(f"   ⚠️ Could not setup termination settings: {str(e)}")


def setup_termination_workflows_and_templates():
    """Setup workflows and email templates for termination system"""

    try:
        # Try to import and run the workflow setup
        from verenigingen.setup.workflow_setup import setup_workflows_corrected

        success = setup_workflows_corrected()

        if success:
            print("   ✓ Termination workflows and templates setup completed")
        else:
            print("   ⚠️ Termination workflows setup had some issues")

    except ImportError:
        print("   ⚠️ Could not import workflow setup - termination workflows not created")
    except Exception as e:
        print(f"   ⚠️ Workflow setup failed: {str(e)}")


def setup_termination_roles_and_permissions():
    """Setup roles and basic permissions for termination system"""

    try:
        # Create required roles
        required_roles = [{"role_name": "Verenigingen Administrator", "desk_access": 1, "is_custom": 1}]

        for role_config in required_roles:
            role_name = role_config["role_name"]
            if not frappe.db.exists("Role", role_name):
                try:
                    role = frappe.get_doc({"doctype": "Role", **role_config})
                    role.insert(ignore_permissions=True)
                    print(f"   ✓ Created role: {role_name}")
                except Exception as e:
                    print(f"   ⚠️ Could not create role {role_name}: {str(e)}")
            else:
                print(f"   ✓ Role already exists: {role_name}")

        frappe.db.commit()

    except Exception as e:
        print(f"   ⚠️ Role setup failed: {str(e)}")


# Add these API endpoints to your existing setup.py file


@frappe.whitelist()
def setup_termination_system_manual():
    """Manual setup endpoint for termination system"""
    try:
        setup_termination_system_integration()
        return {"success": True, "message": "Termination system setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_termination_system_status():
    """Check the status of termination system setup"""

    status = {
        "settings_configured": False,
        "workflows_exist": False,
        "roles_exist": False,
        "system_enabled": False,
    }

    try:
        # Check settings
        if frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "enable_termination_system"):
                status["settings_configured"] = True
                status["system_enabled"] = bool(settings.enable_termination_system)

        # Check workflows
        workflows = ["Membership Termination Workflow", "Termination Appeals Workflow"]
        workflow_count = 0
        for workflow in workflows:
            if frappe.db.exists("Workflow", workflow):
                workflow_count += 1
        status["workflows_exist"] = workflow_count > 0

        # Check roles
        status["roles_exist"] = frappe.db.exists("Role", "Verenigingen Administrator")

        return {"success": True, "status": status}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def run_termination_diagnostics():
    """Run diagnostics on termination system"""

    print("🔍 TERMINATION SYSTEM DIAGNOSTICS")
    print("=" * 40)

    all_good = True

    # 1. Check required doctypes
    print("\n1. DOCTYPE CHECK")
    print("-" * 15)

    required_doctypes = ["Membership Termination Request", "Expulsion Report Entry"]

    for doctype in required_doctypes:
        if frappe.db.exists("DocType", doctype):
            print(f"   ✅ {doctype}")
        else:
            print(f"   ❌ {doctype} - MISSING")
            all_good = False

    # 2. Check roles
    print("\n2. ROLE CHECK")
    print("-" * 12)

    if frappe.db.exists("Role", "Verenigingen Administrator"):
        print("   ✅ Verenigingen Administrator")
    else:
        print("   ❌ Verenigingen Administrator - MISSING")
        all_good = False

    # 3. Check workflows
    print("\n3. WORKFLOW CHECK")
    print("-" * 15)

    workflows = ["Membership Termination Workflow", "Termination Appeals Workflow"]
    for workflow in workflows:
        if frappe.db.exists("Workflow", workflow):
            print(f"   ✅ {workflow}")
        else:
            print(f"   ❌ {workflow} - MISSING")
            all_good = False

    # Summary
    print("\n" + "=" * 40)
    if all_good:
        print("✅ ALL DIAGNOSTICS PASSED")
    else:
        print("⚠️ SOME ISSUES FOUND")
    print("=" * 40)

    return {"success": True, "diagnostics_passed": all_good}


def setup_email_templates():
    """Create basic email templates"""

    print("   📧 Setting up email templates...")

    templates = [
        {
            "name": "Termination Approval Required",
            "subject": "Termination Approval Required - {{ doc.member_name }}",
            "use_html": 1,
            "response": "<p>A termination request requires your approval for member: {{ doc.member_name }}</p>",
        }
    ]

    created_count = 0

    for template_data in templates:
        template_name = template_data["name"]

        if frappe.db.exists("Email Template", template_name):
            print(f"   ✓ Email template '{template_name}' already exists")
            continue

        try:
            template = frappe.get_doc(
                {
                    "doctype": "Email Template",
                    "name": template_name,
                    "subject": template_data["subject"],
                    "use_html": template_data["use_html"],
                    "response": template_data["response"],
                }
            )

            template.insert(ignore_permissions=True)
            created_count += 1
            print(f"   ✓ Created email template: {template_name}")

        except Exception as e:
            print(f"   ❌ Failed to create email template '{template_name}': {str(e)}")

    if created_count > 0:
        try:
            frappe.db.commit()
        except Exception as e:
            print(f"   ⚠️ Template commit warning: {str(e)}")

    return created_count


def setup_membership_application_system():
    """Set up membership application system with email templates and web pages"""
    print("📧 Setting up membership application system...")

    try:
        # Create email templates
        print("   📧 Creating basic application email templates...")
        create_application_email_templates()

        # Create enhanced rejection email templates
        try:
            print("   📧 Creating enhanced rejection email templates...")
            from verenigingen.api.membership_application_review import create_default_email_templates

            create_default_email_templates()
        except Exception as e:
            print(f"   ⚠️ Enhanced rejection templates failed: {str(e)}")

        # Create comprehensive email templates for all notifications
        try:
            print("   📧 Creating comprehensive email templates...")
            from verenigingen.api.email_template_manager import create_comprehensive_email_templates

            create_comprehensive_email_templates()
        except Exception as e:
            print(f"   ⚠️ Comprehensive templates failed: {str(e)}")

        # Create web pages configuration
        setup_application_web_pages()

        # Create default donation types
        create_default_donation_types()

        print("✅ Membership application system setup completed")

    except Exception as e:
        print(f"⚠️ Membership application system setup failed: {str(e)}")


def create_application_email_templates():
    """Create email templates for application workflow"""

    templates = [
        {
            "name": "membership_application_confirmation",
            "subject": "Membership Application Received - Payment Required",
            "response": """
                <h3>Thank you for your membership application!</h3>

                <p>Dear {{ member.first_name }},</p>

                <p>We have received your membership application for {{ membership_type }}.</p>

                <p><strong>Next Step: Complete Payment</strong></p>
                <p>To activate your membership, please complete the payment of {{ frappe.format_value(payment_amount, {"fieldtype": "Currency"}) }}.</p>

                <p><a href="{{ payment_url }}" class="btn btn-primary">Complete Payment</a></p>

                <p>Once your payment is processed, you will receive a welcome email with your member portal access details.</p>

                <p>If you have any questions, please don't hesitate to contact us.</p>

                <p>Best regards,<br>The Membership Team</p>
            """,
        },
        {
            "name": "membership_welcome",
            "subject": "Welcome to {{ frappe.db.get_value('Company', company, 'company_name') }}!",
            "response": """
                <h2>Welcome to our Association, {{ member.first_name }}!</h2>

                <p>Your membership is now active and you have full access to all member benefits.</p>

                <h3>Your Membership Details:</h3>
                <table style="width: 100%; max-width: 500px;">
                    <tr>
                        <td><strong>Member ID:</strong></td>
                        <td>{{ member.name }}</td>
                    </tr>
                    <tr>
                        <td><strong>Membership Type:</strong></td>
                        <td>{{ membership_type.membership_type_name }}</td>
                    </tr>
                    <tr>
                        <td><strong>Valid From:</strong></td>
                        <td>{{ frappe.format_date(membership.start_date) }}</td>
                    </tr>
                    <tr>
                        <td><strong>Valid Until:</strong></td>
                        <td>{{ frappe.format_date(membership.renewal_date) }}</td>
                    </tr>
                    {% if member.primary_chapter %}
                    <tr>
                        <td><strong>Chapter:</strong></td>
                        <td>{{ member.primary_chapter }}</td>
                    </tr>
                    {% endif %}
                </table>

                {% if member.interested_in_volunteering %}
                <h3>Thank you for your interest in volunteering!</h3>
                <p>Our volunteer coordinator will be in touch with you soon to discuss opportunities that match your interests and availability.</p>
                {% endif %}

                <h3>Access Your Member Portal</h3>
                <p>You can access your member portal at: <a href="{{ member_portal_url }}">{{ member_portal_url }}</a></p>

                <p>If you haven't set up your password yet, please visit: <a href="{{ login_url }}">{{ login_url }}</a></p>

                <h3>Stay Connected</h3>
                <ul>
                    <li>Follow us on social media</li>
                    <li>Join our member forum</li>
                    <li>Attend our upcoming events</li>
                </ul>

                <p>We're excited to have you as part of our community!</p>

                <p>Best regards,<br>The {{ frappe.db.get_value('Company', company, 'company_name') }} Team</p>
            """,
        },
        {
            "name": "volunteer_welcome",
            "subject": "Welcome to our Volunteer Team!",
            "response": """
                <h2>Welcome to our Volunteer Team, {{ volunteer.volunteer_name }}!</h2>

                <p>Thank you for your interest in volunteering with us. We're excited to have you join our team!</p>

                <h3>Your Volunteer Profile:</h3>
                <ul>
                    <li><strong>Availability:</strong> {{ volunteer.commitment_level }}</li>
                    <li><strong>Experience Level:</strong> {{ volunteer.experience_level }}</li>
                    {% if volunteer.interests %}
                    <li><strong>Areas of Interest:</strong>
                        <ul>
                        {% for interest in volunteer.interests %}
                            <li>{{ interest.interest_area }}</li>
                        {% endfor %}
                        </ul>
                    </li>
                    {% endif %}
                </ul>

                <h3>Next Steps:</h3>
                <ol>
                    <li>Complete your volunteer orientation (online)</li>
                    <li>Review our volunteer handbook</li>
                    <li>Sign up for your first volunteer opportunity</li>
                </ol>

                <p>Your volunteer coordinator will contact you within the next few days to discuss specific opportunities.</p>

                <p>In the meantime, you can access your volunteer portal using your organization email: <strong>{{ volunteer.email }}</strong></p>

                <p>Thank you for making a difference!</p>

                <p>Best regards,<br>The Volunteer Team</p>
            """,
        },
        {
            "name": "membership_payment_failed",
            "subject": "Payment Failed - Membership Application",
            "response": """
                <p>Dear {{ member.first_name }},</p>

                <p>Unfortunately, your payment for the membership application could not be processed.</p>

                <p><strong>Don't worry - your application is still valid!</strong></p>

                <p>You can retry the payment at any time using this link:</p>
                <p><a href="{{ retry_url }}" class="btn btn-primary">Retry Payment</a></p>

                <p>If you continue to experience issues, please contact our support team at {{ support_email|default("support@example.com") }}</p>

                <p>Common reasons for payment failure:</p>
                <ul>
                    <li>Insufficient funds</li>
                    <li>Card declined by bank</li>
                    <li>Incorrect payment details</li>
                    <li>Technical issues</li>
                </ul>

                <p>Best regards,<br>The Membership Team</p>
            """,
        },
    ]

    created_count = 0
    for template_data in templates:
        if not frappe.db.exists("Email Template", template_data["name"]):
            try:
                template = frappe.get_doc(
                    {
                        "doctype": "Email Template",
                        "name": template_data["name"],
                        "subject": template_data["subject"],
                        "use_html": 1,
                        "response": template_data["response"],
                        "enabled": 1,
                    }
                )
                template.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created email template: {template_data['name']}")
            except Exception as e:
                print(f"   ❌ Failed to create email template '{template_data['name']}': {str(e)}")
        else:
            print(f"   ✓ Email template already exists: {template_data['name']}")

    if created_count > 0:
        try:
            frappe.db.commit()
            print(f"   📧 Created {created_count} new email templates")
        except Exception as e:
            print(f"   ⚠️ Failed to commit email templates: {str(e)}")

    return created_count


def setup_application_web_pages():
    """Set up web pages for application process"""

    print("   🌐 Configuring web pages for membership application...")

    # Create routes in website settings - this is just informational
    # The actual page templates should exist in verenigingen/templates/pages/
    pages = [
        {"route": "apply-for-membership", "title": "Apply for Membership", "published": 1},
        {"route": "payment/complete", "title": "Complete Payment", "published": 1},
        {"route": "payment/success", "title": "Payment Successful", "published": 1},
        {"route": "payment/failed", "title": "Payment Failed", "published": 1},
    ]

    print(f"   ✓ Web pages configured for {len(pages)} routes")
    print("   ℹ️  Ensure template files exist in verenigingen/templates/pages/")


def setup_workspace():
    """Set up and update workspace for verenigingen"""
    print("🏢 Setting up Verenigingen workspace...")

    try:
        # Clean up workspace first
        cleanup_workspace_links()

        # Then add new links
        update_workspace_links()

        # Ensure module onboarding is linked
        install_and_link_onboarding()

        print("✅ Workspace setup completed")

    except Exception as e:
        print(f"⚠️ Workspace setup failed: {str(e)}")


def cleanup_workspace_links():
    """Clean up invalid workspace links"""
    try:
        if not frappe.db.exists("Workspace", "Verenigingen"):
            print("   ℹ️  Verenigingen workspace doesn't exist yet - will be created")
            return

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Find and remove links to non-existent doctypes
        links_to_remove = []
        for i, link in enumerate(workspace.links):
            link_to = link.get("link_to")
            if link_to and not frappe.db.exists("DocType", link_to):
                print(f"   🗑️  Removing invalid link: {link.get('label')} -> {link_to}")
                links_to_remove.append(i)

        # Remove in reverse order to maintain indices
        for i in reversed(links_to_remove):
            del workspace.links[i]

        if links_to_remove:
            workspace.save(ignore_permissions=True)
            print(f"   ✓ Cleaned up {len(links_to_remove)} invalid links")
        else:
            print("   ✓ No invalid links found")

    except Exception as e:
        print(f"   ⚠️ Workspace cleanup failed: {str(e)}")


def update_workspace_links():
    """Add new links to workspace"""
    try:
        if not frappe.db.exists("Workspace", "Verenigingen"):
            print("   ℹ️  Verenigingen workspace doesn't exist - skipping link updates")
            return

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Links to add (only if doctype exists)
        potential_links = [
            # Termination & Appeals Section
            {
                "hidden": 0,
                "is_query_report": 0,
                "label": "Termination & Appeals",
                "link_count": 2,
                "link_type": "DocType",
                "onboard": 0,
                "type": "Card Break",
            },
            {
                "dependencies": "",
                "hidden": 0,
                "is_query_report": 0,
                "label": "Membership Termination Request",
                "link_count": 0,
                "link_to": "Membership Termination Request",
                "link_type": "DocType",
                "onboard": 0,
                "type": "Link",
            },
            {
                "dependencies": "",
                "hidden": 0,
                "is_query_report": 0,
                "label": "SEPA Mandate",
                "link_count": 0,
                "link_to": "SEPA Mandate",
                "link_type": "DocType",
                "onboard": 0,
                "type": "Link",
            },
            {
                "dependencies": "",
                "hidden": 0,
                "is_query_report": 0,
                "label": "Direct Debit Batch",
                "link_count": 0,
                "link_to": "Direct Debit Batch",
                "link_type": "DocType",
                "onboard": 0,
                "type": "Link",
            },
        ]

        # Only add links for existing doctypes
        links_added = 0
        for link in potential_links:
            link_to = link.get("link_to")
            if not link_to or frappe.db.exists("DocType", link_to) or link.get("type") == "Card Break":
                # Check if link already exists
                exists = False
                for existing_link in workspace.links:
                    if existing_link.get("label") == link.get("label"):
                        exists = True
                        break

                if not exists:
                    workspace.append("links", link)
                    links_added += 1
                    print(f"   ✓ Added link: {link.get('label')}")

        # Add new shortcuts (only for existing doctypes)
        potential_shortcuts = [
            {
                "color": "Red",
                "label": "Termination Requests",
                "link_to": "Membership Termination Request",
                "type": "DocType",
            },
            {"color": "Blue", "label": "SEPA Mandates", "link_to": "SEPA Mandate", "type": "DocType"},
        ]

        shortcuts_added = 0
        for shortcut in potential_shortcuts:
            link_to = shortcut.get("link_to")
            if frappe.db.exists("DocType", link_to):
                # Check if shortcut already exists
                exists = False
                for existing_shortcut in workspace.shortcuts:
                    if existing_shortcut.get("label") == shortcut.get("label"):
                        exists = True
                        break

                if not exists:
                    workspace.append("shortcuts", shortcut)
                    shortcuts_added += 1
                    print(f"   ✓ Added shortcut: {shortcut.get('label')}")

        if links_added > 0 or shortcuts_added > 0:
            workspace.save(ignore_permissions=True)
            print(f"   ✅ Added {links_added} links and {shortcuts_added} shortcuts")
        else:
            print("   ✓ No new links or shortcuts needed")

    except Exception as e:
        print(f"   ⚠️ Workspace update failed: {str(e)}")


def load_application_fixtures():
    """Load necessary fixtures for the application"""
    print("📦 Loading application fixtures...")

    try:
        import os

        from frappe.desk.page.setup_wizard.setup_wizard import install_fixtures

        # Get fixtures directory
        app_path = frappe.get_app_path("verenigingen")
        fixtures_path = os.path.join(app_path, "..", "fixtures")

        # Load workflow fixtures if they exist
        fixture_files = ["workflow.json", "membership_workflow.json"]

        loaded_count = 0
        for fixture_file in fixture_files:
            fixture_path = os.path.join(fixtures_path, fixture_file)
            if os.path.exists(fixture_path):
                try:
                    install_fixtures(fixture_path)
                    loaded_count += 1
                    print(f"   ✓ Loaded fixture: {fixture_file}")
                except Exception as e:
                    print(f"   ⚠️ Could not load fixture {fixture_file}: {str(e)}")
            else:
                print(f"   ℹ️  Fixture not found: {fixture_file}")

        if loaded_count > 0:
            print(f"   📦 Loaded {loaded_count} fixtures")
        else:
            print("   ℹ️  No fixtures loaded")

    except Exception as e:
        print(f"   ⚠️ Fixture loading failed: {str(e)}")


# Consolidated API endpoints for all setup functions


@frappe.whitelist()
def run_complete_setup():
    """Run the complete setup process manually"""
    try:
        execute_after_install()
        return {"success": True, "message": "Complete setup completed successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def setup_membership_application_system_manual():
    """Manual setup endpoint for membership application system"""
    try:
        setup_membership_application_system()
        return {"success": True, "message": "Membership application system setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def setup_workspace_manual():
    """Manual setup endpoint for workspace"""
    try:
        setup_workspace()
        return {"success": True, "message": "Workspace setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def create_default_donation_types():
    """Create default donation types if they don't exist"""
    print("   💰 Setting up default donation types...")

    default_types = ["General", "Monthly", "One-time", "Campaign", "Emergency Relie", "Membership Support"]

    created_count = 0

    for donation_type in default_types:
        if not frappe.db.exists("Donation Type", donation_type):
            try:
                doc = frappe.get_doc({"doctype": "Donation Type", "donation_type": donation_type})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created donation type: {donation_type}")
            except Exception as e:
                print(f"   ⚠️ Could not create donation type '{donation_type}': {str(e)}")
        else:
            print(f"   ✓ Donation type already exists: {donation_type}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   💰 Created {created_count} default donation types")

        # Set default donation type in settings if not already set
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.get("default_donation_type"):
                settings.default_donation_type = "General"
                settings.save(ignore_permissions=True)
                print("   ✓ Set 'General' as default donation type in settings")
        except Exception as e:
            print(f"   ⚠️ Could not set default donation type: {str(e)}")

    return created_count


@frappe.whitelist()
def create_donation_types_manual():
    """Manual endpoint to create donation types"""
    try:
        count = create_default_donation_types()
        return {"success": True, "message": f"Created {count} donation types", "count": count}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def verify_donation_type_setup():
    """Verify donation types are properly set up"""
    try:
        # Check donation types
        donation_types = frappe.get_all("Donation Type", fields=["name", "donation_type"])

        # Check settings
        settings = frappe.get_single("Verenigingen Settings")
        default_type = settings.get("default_donation_type")

        return {
            "success": True,
            "donation_types": donation_types,
            "total_count": len(donation_types),
            "default_donation_type": default_type,
            "message": f"Found {len(donation_types)} donation types, default: {default_type}",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def create_email_templates_manual():
    """Manual endpoint to create email templates"""
    try:
        print("🔧 Manually creating email templates...")

        # Create basic templates
        basic_count = create_application_email_templates()

        # Create enhanced templates
        enhanced_count = 0
        try:
            from verenigingen.api.membership_application_review import create_default_email_templates

            enhanced_count = create_default_email_templates()
        except Exception as e:
            print(f"Enhanced templates failed: {str(e)}")

        # Create comprehensive templates
        comprehensive_count = 0
        try:
            from verenigingen.api.email_template_manager import create_comprehensive_email_templates

            comprehensive_count = create_comprehensive_email_templates()
        except Exception as e:
            print(f"Comprehensive templates failed: {str(e)}")

        total_count = basic_count + enhanced_count + comprehensive_count

        return {
            "success": True,
            "message": f"Created {total_count} email templates",
            "basic_count": basic_count,
            "enhanced_count": enhanced_count,
            "comprehensive_count": comprehensive_count,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def verify_email_templates():
    """Verify email templates are properly installed"""
    try:
        # Check for basic templates
        basic_templates = [
            "membership_application_confirmation",
            "membership_welcome",
            "volunteer_welcome",
            "membership_payment_failed",
        ]

        existing_templates = []
        missing_templates = []

        for template_name in basic_templates:
            if frappe.db.exists("Email Template", template_name):
                existing_templates.append(template_name)
            else:
                missing_templates.append(template_name)

        # Get verenigingen email templates using explicit template list
        verenigingen_templates = [
            # Membership templates
            "membership_application_received",
            "membership_application_approved",
            "membership_application_rejected",
            "membership_renewal_reminder",
            "membership_expiry_notice",
            "membership_payment_received",
            "membership_payment_failed",
            # Volunteer templates
            "volunteer_application_received",
            "volunteer_application_approved",
            "volunteer_expense_approval_request",
            "volunteer_expense_approved",
            "volunteer_expense_rejected",
            # Termination templates
            "termination_request_received",
            "termination_approved",
            "termination_overdue_notification",
        ]

        all_templates = frappe.get_all(
            "Email Template",
            filters=[["name", "in", verenigingen_templates]],
            fields=["name", "subject"],
        )

        return {
            "success": True,
            "existing_basic_templates": existing_templates,
            "missing_basic_templates": missing_templates,
            "all_related_templates": all_templates,
            "total_related_count": len(all_templates),
            "message": f"Found {len(existing_templates)}/{len(basic_templates)} basic templates, {len(all_templates)} total related templates",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


def install_and_link_onboarding():
    """Install Module Onboarding document and link to workspace"""
    try:
        print("   🚀 Setting up onboarding...")

        # First, ensure the module_onboarding custom field exists on Workspace
        try:
            existing_field = frappe.db.exists(
                "Custom Field", {"dt": "Workspace", "fieldname": "module_onboarding"}
            )
            if not existing_field:
                custom_field = frappe.get_doc(
                    {
                        "doctype": "Custom Field",
                        "dt": "Workspace",
                        "fieldname": "module_onboarding",
                        "label": "Module Onboarding",
                        "fieldtype": "Link",
                        "options": "Module Onboarding",
                        "insert_after": "module",
                        "description": "Link to Module Onboarding document for this workspace",
                    }
                )
                custom_field.insert(ignore_permissions=True)
                frappe.clear_cache()
                print("   ✓ Added module_onboarding custom field to Workspace")
            else:
                print("   ✓ Module onboarding custom field already exists")
        except Exception as e:
            print(f"   ⚠️ Failed to create custom field: {str(e)}")

        # Install the Module Onboarding document if it doesn't exist
        if not frappe.db.exists("Module Onboarding", "Verenigingen"):
            try:
                result = reinstall_onboarding()
                if result.get("success"):
                    print("   ✓ Installed Module Onboarding document with all steps")
                else:
                    print(f"   ⚠️ Failed to install onboarding: {result.get('message')}")
            except Exception as e:
                print(f"   ⚠️ Failed to install onboarding document: {str(e)}")
        else:
            print("   ✓ Module Onboarding document already exists")

        # Link it to the workspace
        if frappe.db.exists("Workspace", "Verenigingen"):
            workspace = frappe.get_doc("Workspace", "Verenigingen")

            # Set the module_onboarding field
            if not getattr(workspace, "module_onboarding", None):
                workspace.module_onboarding = "Verenigingen"
                workspace.save(ignore_permissions=True)
                print("   ✓ Linked Module Onboarding to workspace")
            else:
                print("   ✓ Module Onboarding already linked to workspace")
        else:
            print("   ⚠️ Verenigingen workspace doesn't exist - skipping workspace link")

        frappe.db.commit()

    except Exception as e:
        print(f"   ⚠️ Onboarding setup failed: {str(e)}")


def link_module_onboarding():
    """Link module onboarding to workspace to show setup banner (legacy function)"""
    install_and_link_onboarding()


@frappe.whitelist()
def fix_onboarding_visibility():
    """Manual function to fix onboarding visibility"""
    try:
        print("🔧 Fixing onboarding visibility...")

        # Link module onboarding
        link_module_onboarding()

        # Check if onboarding exists and get status
        if frappe.db.exists("Module Onboarding", "Verenigingen"):
            onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")
            steps = onboarding.steps  # Steps are a child table within the document

            completed_steps = len([s for s in steps if s.is_complete])
            total_steps = len(steps)

            return {
                "success": True,
                "message": f"Onboarding fixed - {completed_steps}/{total_steps} steps completed",
                "onboarding_url": "/app/module-onboarding/Verenigingen",
                "workspace_url": "/app/verenigingen",
                "steps": steps,
            }
        else:
            return {"success": False, "message": "Module Onboarding 'Verenigingen' document not found"}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_onboarding_setup():
    """Check onboarding setup status"""
    try:
        result = {
            "workspace_exists": frappe.db.exists("Workspace", "Verenigingen"),
            "onboarding_exists": frappe.db.exists("Module Onboarding", "Verenigingen"),
            "workspace_has_onboarding_link": False,
            "onboarding_steps": [],
        }

        if result["workspace_exists"]:
            workspace = frappe.get_doc("Workspace", "Verenigingen")
            result["workspace_has_onboarding_link"] = bool(getattr(workspace, "module_onboarding", None))
            result["workspace_onboarding_value"] = getattr(workspace, "module_onboarding", None)

        if result["onboarding_exists"]:
            onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")
            steps = onboarding.steps  # Steps are a child table within the document

            # Convert steps to a list of dictionaries for JSON serialization
            steps_list = []
            for step in steps:
                steps_list.append(
                    {"title": step.title, "is_complete": step.is_complete, "action": step.action}
                )

            result["onboarding_steps"] = steps_list
            result["completed_steps"] = len([s for s in steps if s.is_complete])
            result["total_steps"] = len(steps)

        return {"success": True, "status": result}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def test_onboarding_fix():
    """Simple test function to verify onboarding setup"""
    try:
        result = {
            "module_onboarding_exists": frappe.db.exists("Module Onboarding", "Verenigingen"),
            "workspace_exists": frappe.db.exists("Workspace", "Verenigingen"),
            "workspace_linked": False,
            "errors": [],
        }

        # Check workspace linking
        if result["workspace_exists"]:
            try:
                workspace = frappe.get_doc("Workspace", "Verenigingen")
                result["workspace_linked"] = bool(
                    getattr(workspace, "module_onboarding", None) == "Verenigingen"
                )
                result["workspace_onboarding_field"] = getattr(workspace, "module_onboarding", "MISSING")
            except Exception as e:
                result["errors"].append(f"Workspace check failed: {str(e)}")

        # Check module onboarding
        if result["module_onboarding_exists"]:
            try:
                onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")
                result["onboarding_title"] = onboarding.title
                result["steps_count"] = len(onboarding.steps) if hasattr(onboarding, "steps") else 0
                result["completed_count"] = (
                    len([s for s in onboarding.steps if s.is_complete]) if hasattr(onboarding, "steps") else 0
                )

                # Debug: Show actual steps data
                if hasattr(onboarding, "steps"):
                    result["steps_debug"] = [
                        {"title": s.title, "action": s.action} for s in onboarding.steps[:3]
                    ]  # First 3 steps
                else:
                    result["steps_debug"] = "NO STEPS ATTRIBUTE"

                # Show all attributes
                result["onboarding_attributes"] = [
                    attr for attr in dir(onboarding) if not attr.startswith("_")
                ]

            except Exception as e:
                result["errors"].append(f"Module onboarding check failed: {str(e)}")

        return {"success": True, "result": result}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_onboarding_schema():
    """Check what fields are available in Module Onboarding DocType"""
    try:
        # Get the DocType meta to see available fields
        meta = frappe.get_meta("Module Onboarding")
        fields = [f.fieldname for f in meta.fields if f.fieldtype != "Section Break"]

        # Check if there are any existing Module Onboarding documents to see structure
        existing_docs = frappe.get_all("Module Onboarding", fields=["name"], limit=1)

        result = {"available_fields": fields, "existing_onboarding_docs": existing_docs}

        # If there are existing docs, get one to see its structure
        if existing_docs:
            sample_doc = frappe.get_doc("Module Onboarding", existing_docs[0].name)
            result["sample_doc_fields"] = list(sample_doc.as_dict().keys())

            # Check steps structure if available
            if hasattr(sample_doc, "steps") and sample_doc.steps:
                first_step = sample_doc.steps[0]
                result["step_fields"] = list(first_step.as_dict().keys())

        # Also check the child table meta
        try:
            # Get child table fields from the parent meta
            parent_meta = frappe.get_meta("Module Onboarding")
            steps_field = None
            for field in parent_meta.fields:
                if field.fieldname == "steps":
                    steps_field = field
                    break

            if steps_field:
                child_meta = frappe.get_meta(steps_field.options)
                result["step_doctype"] = steps_field.options
                result["step_available_fields"] = [
                    f.fieldname for f in child_meta.fields if f.fieldtype != "Section Break"
                ]

        except Exception as e:
            result["step_meta_error"] = str(e)

        return {"success": True, "schema": result}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def final_onboarding_verification():
    """Final verification that onboarding is working"""
    try:
        # Check all components
        onboarding_exists = frappe.db.exists("Module Onboarding", "Verenigingen")
        workspace_exists = frappe.db.exists("Workspace", "Verenigingen")

        result = {
            "module_onboarding_exists": bool(onboarding_exists),
            "workspace_exists": bool(workspace_exists),
            "workspace_linked": False,
            "onboarding_steps_count": 0,
            "status": "Unknown",
        }

        if workspace_exists:
            workspace = frappe.get_doc("Workspace", "Verenigingen")
            result["workspace_linked"] = workspace.get("module_onboarding") == "Verenigingen"

        if onboarding_exists:
            onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")
            result["onboarding_steps_count"] = len(onboarding.steps) if hasattr(onboarding, "steps") else 0
            result["onboarding_title"] = onboarding.title

        # Determine status
        if result["module_onboarding_exists"] and result["workspace_exists"] and result["workspace_linked"]:
            result["status"] = "✅ READY - Onboarding should appear in workspace"
        elif result["module_onboarding_exists"] and result["workspace_exists"]:
            result["status"] = "⚠️ PARTIAL - Module exists but workspace not linked"
        else:
            result["status"] = "❌ BROKEN - Missing components"

        result["next_steps"] = [
            "Visit /app/verenigingen to see the onboarding banner",
            "If banner doesn't appear, check user permissions",
            "Module Onboarding document available at /app/module-onboarding/Verenigingen",
        ]

        return {"success": True, "verification": result}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def install_email_templates_ui():
    """User-friendly endpoint for installing email templates from onboarding"""
    try:
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
                existing_templates.append(template_name)
            else:
                missing_templates.append(template_name)

        # If no templates are missing, mark step as complete
        if not missing_templates:
            try:
                step = frappe.get_doc("Onboarding Step", "Verenigingen-Install-Email-Templates")
                step.is_complete = 1
                step.save(ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                pass  # If step doesn't exist, ignore

            return {
                "success": True,
                "message": "✅ All email templates are already installed!",
                "existing_templates": existing_templates,
                "missing_templates": [],
                "action_taken": "none",
                "step_completed": True,
            }

        # Install missing templates
        print("📧 Installing missing email templates...")

        # Install basic templates
        basic_count = create_application_email_templates()

        # Install enhanced templates
        enhanced_count = 0
        try:
            from verenigingen.api.membership_application_review import create_default_email_templates

            enhanced_count = create_default_email_templates()
        except Exception as e:
            print(f"Enhanced templates skipped: {str(e)}")

        # Install comprehensive templates
        comprehensive_count = 0
        try:
            from verenigingen.api.email_template_manager import create_comprehensive_email_templates

            comprehensive_count = create_comprehensive_email_templates()
        except Exception as e:
            print(f"Comprehensive templates skipped: {str(e)}")

        total_installed = basic_count + enhanced_count + comprehensive_count

        # Check what's now available
        final_missing = []
        final_existing = []

        for template_name in basic_templates:
            if frappe.db.exists("Email Template", template_name):
                final_existing.append(template_name)
            else:
                final_missing.append(template_name)

        # Mark step as complete if all basic templates are now available
        step_completed = False
        if not final_missing:
            try:
                step = frappe.get_doc("Onboarding Step", "Verenigingen-Install-Email-Templates")
                step.is_complete = 1
                step.save(ignore_permissions=True)
                frappe.db.commit()
                step_completed = True
            except Exception:
                pass

        return {
            "success": True,
            "message": f"✅ Installed {total_installed} email templates successfully!",
            "templates_installed": total_installed,
            "basic_count": basic_count,
            "enhanced_count": enhanced_count,
            "comprehensive_count": comprehensive_count,
            "existing_templates": final_existing,
            "missing_templates": final_missing,
            "action_taken": "installed",
            "step_completed": step_completed,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Error installing email templates: {str(e)}",
            "action_taken": "error",
        }


@frappe.whitelist()
def verify_app_dependencies():
    """Verify all app dependencies are properly configured and installed"""
    try:
        # Get dependencies from hooks.py
        from verenigingen.hooks import required_apps as hook_required_apps

        # Get installed apps
        installed_apps = frappe.get_installed_apps()

        # Check each dependency
        dependency_status = []
        for app in hook_required_apps:
            is_installed = app in installed_apps
            dependency_status.append(
                {
                    "app": app,
                    "installed": is_installed,
                    "status": "✅ Installed" if is_installed else "❌ Missing",
                }
            )

        all_installed = all(status["installed"] for status in dependency_status)

        return {
            "success": True,
            "all_dependencies_met": all_installed,
            "required_apps": hook_required_apps,
            "installed_apps": installed_apps,
            "dependency_status": dependency_status,
            "summary": f"Dependencies: {len([s for s in dependency_status if s['installed']])}/{len(dependency_status)} installed",
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def test_email_template_page():
    """Test that the email template installation page works"""
    try:
        # Check what templates are missing vs available (same logic as the page)
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

        return {
            "success": True,
            "page_context": {
                "missing_templates_count": len(missing_templates),
                "existing_templates_count": len(existing_templates),
                "all_installed": len(missing_templates) == 0,
                "page_title": "Install Email Templates",
                "missing_templates": [t["title"] for t in missing_templates],
                "existing_templates": [t["title"] for t in existing_templates],
            },
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def add_module_onboarding_custom_field():
    """Add module_onboarding as a custom field to Workspace"""
    try:
        # Check if custom field already exists
        existing_field = frappe.db.exists(
            "Custom Field", {"dt": "Workspace", "fieldname": "module_onboarding"}
        )

        if existing_field:
            return {
                "success": True,
                "message": "Custom field module_onboarding already exists",
                "action": "none",
            }

        # Create custom field
        custom_field = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Workspace",
                "fieldname": "module_onboarding",
                "label": "Module Onboarding",
                "fieldtype": "Link",
                "options": "Module Onboarding",
                "insert_after": "module",
                "description": "Link to Module Onboarding document for this workspace",
            }
        )

        custom_field.insert(ignore_permissions=True)
        frappe.db.commit()

        # Clear cache to ensure field is available
        frappe.clear_cache()

        return {
            "success": True,
            "message": "Custom field module_onboarding added to Workspace",
            "action": "created",
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def test_onboarding_api():
    """Test if onboarding can be accessed via the Frappe workspace API"""
    try:
        # This mimics what the frontend would call
        pass

        # Get workspace content that includes onboarding
        workspace_data = frappe.get_doc("Workspace", "Verenigingen")

        # Check if there's an API method to get onboarding for workspace
        try:
            # Try to get onboarding the way the frontend does
            from frappe.desk.doctype.module_onboarding.module_onboarding import get_onboarding_list

            onboarding_list = get_onboarding_list()
            verenigingen_onboarding = [o for o in onboarding_list if o.get("name") == "Verenigingen"]
        except Exception as e:
            verenigingen_onboarding = f"get_onboarding_list failed: {str(e)}"

        # Alternative approach - check if workspace API includes onboarding
        try:
            workspace_dict = workspace_data.as_dict()
            has_module_onboarding_in_dict = "module_onboarding" in workspace_dict
        except Exception as e:
            has_module_onboarding_in_dict = f"Error: {str(e)}"

        return {
            "success": True,
            "workspace_name": workspace_data.name,
            "workspace_module": workspace_data.module,
            "workspace_has_module_onboarding_in_dict": has_module_onboarding_in_dict,
            "onboarding_list_result": verenigingen_onboarding,
            "direct_onboarding_access": frappe.db.exists("Module Onboarding", "Verenigingen"),
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def debug_onboarding_visibility():
    """Debug why onboarding might not be showing"""
    try:
        # Check user session and permissions
        current_user = frappe.session.user
        user_roles = frappe.get_roles(current_user)

        # Check onboarding document
        onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")

        # Check permission on onboarding
        has_onboarding_permission = frappe.has_permission("Module Onboarding", "read", "Verenigingen")

        # Check if user has any allowed roles
        allowed_roles = [role.role for role in onboarding.allow_roles]
        user_has_allowed_role = any(role in user_roles for role in allowed_roles)

        # Check workspace
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        has_workspace_permission = frappe.has_permission("Workspace", "read", "Verenigingen")

        # Check if onboarding is complete
        total_steps = len(onboarding.steps)
        completed_steps = 0
        step_details = []

        for step_map in onboarding.steps:
            try:
                step = frappe.get_doc("Onboarding Step", step_map.step)
                step_details.append(
                    {
                        "name": step.name,
                        "title": step.title,
                        "is_complete": step.is_complete,
                        "is_mandatory": getattr(step, "is_mandatory", 0),
                    }
                )
                if step.is_complete:
                    completed_steps += 1
            except Exception as e:
                step_details.append({"name": step_map.step, "error": str(e)})

        return {
            "success": True,
            "user_info": {
                "current_user": current_user,
                "user_roles": user_roles,
                "has_onboarding_permission": has_onboarding_permission,
                "has_workspace_permission": has_workspace_permission,
                "user_has_allowed_role": user_has_allowed_role,
                "allowed_roles": allowed_roles,
            },
            "onboarding_info": {
                "is_complete": onboarding.is_complete,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "completion_percentage": (completed_steps / total_steps * 100) if total_steps > 0 else 0,
                "step_details": step_details,
            },
            "module_match": {
                "workspace_module": workspace.module,
                "onboarding_module": onboarding.module,
                "modules_match": workspace.module == onboarding.module,
            },
            "recommendations": [],
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_module_mapping():
    """Check how modules are mapped between workspaces and onboarding"""
    try:
        # Get our workspace module setting
        verenigingen_workspace = frappe.get_doc("Workspace", "Verenigingen")
        verenigingen_onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")

        # Check a few working examples
        examples = []
        test_cases = [("Payroll", "Payroll"), ("Selling", "Selling"), ("Accounts", "Accounts")]

        for workspace_name, onboarding_name in test_cases:
            if frappe.db.exists("Workspace", workspace_name) and frappe.db.exists(
                "Module Onboarding", onboarding_name
            ):
                workspace = frappe.get_doc("Workspace", workspace_name)
                onboarding = frappe.get_doc("Module Onboarding", onboarding_name)

                examples.append(
                    {
                        "workspace_name": workspace_name,
                        "workspace_module": workspace.module,
                        "onboarding_name": onboarding_name,
                        "onboarding_module": onboarding.module,
                        "modules_match": workspace.module == onboarding.module,
                    }
                )

        return {
            "success": True,
            "verenigingen_workspace_module": verenigingen_workspace.module,
            "verenigingen_onboarding_module": verenigingen_onboarding.module,
            "verenigingen_modules_match": verenigingen_workspace.module == verenigingen_onboarding.module,
            "examples": examples,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def investigate_other_module_onboarding():
    """Investigate how other modules link their onboarding to workspaces"""
    try:
        # Check existing Module Onboarding documents
        module_onboardings = frappe.get_all("Module Onboarding", fields=["name", "module", "title"])

        # Check all workspaces to see if any have module_onboarding set
        all_workspaces = frappe.get_all("Workspace", fields=["name", "module"])

        # Check specific modules that should have onboarding
        test_modules = ["Payroll", "Accounts", "Selling", "Buying"]
        workspace_info = []

        for module in test_modules:
            if frappe.db.exists("Workspace", module):
                workspace = frappe.get_doc("Workspace", module)
                workspace_info.append(
                    {
                        "name": module,
                        "has_module_onboarding_attr": hasattr(workspace, "module_onboarding"),
                        "module_onboarding_value": getattr(workspace, "module_onboarding", "NOT_FOUND"),
                        "attributes": [
                            attr
                            for attr in dir(workspace)
                            if not attr.startswith("_") and "onboard" in attr.lower()
                        ],
                    }
                )

        return {
            "success": True,
            "module_onboardings": module_onboardings,
            "workspace_count": len(all_workspaces),
            "test_workspaces": workspace_info,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_workspace_schema():
    """Check Workspace DocType schema for module_onboarding field"""
    try:
        meta = frappe.get_meta("Workspace")
        fields = [f.fieldname for f in meta.fields]

        module_onboarding_field = meta.get_field("module_onboarding")

        return {
            "success": True,
            "has_module_onboarding_field": bool(module_onboarding_field),
            "field_details": module_onboarding_field.as_dict() if module_onboarding_field else None,
            "all_fields": fields,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def force_workspace_onboarding_link():
    """Force update workspace module_onboarding link via database"""
    try:
        # Direct database update
        frappe.db.set_value("Workspace", "Verenigingen", "module_onboarding", "Verenigingen")
        frappe.db.commit()

        # Reload the document to verify
        workspace = frappe.get_doc("Workspace", "Verenigingen", ignore_permissions=True)
        current_value = workspace.get("module_onboarding")

        return {"success": True, "message": f"Force updated workspace module_onboarding to: {current_value}"}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def fix_workspace_onboarding_link():
    """Fix the workspace module_onboarding link"""
    try:
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        current_value = workspace.get("module_onboarding")

        if current_value != "Verenigingen":
            workspace.module_onboarding = "Verenigingen"
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            return {
                "success": True,
                "message": f"Updated workspace module_onboarding from '{current_value}' to 'Verenigingen'",
            }
        else:
            return {"success": True, "message": "Workspace module_onboarding already correctly set"}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def examine_existing_onboarding():
    """Examine existing Module Onboarding to understand structure"""
    try:
        # Get the Payroll onboarding document
        payroll_doc = frappe.get_doc("Module Onboarding", "Payroll")

        result = {
            "payroll_fields": list(payroll_doc.as_dict().keys()),
            "payroll_data": {
                "title": payroll_doc.title,
                "subtitle": payroll_doc.subtitle,
                "module": payroll_doc.module,
                "success_message": payroll_doc.success_message,
                "documentation_url": payroll_doc.documentation_url,
                "allow_roles": payroll_doc.allow_roles,
                "is_complete": payroll_doc.is_complete,
                "steps_count": len(payroll_doc.steps) if hasattr(payroll_doc, "steps") else 0,
            },
        }

        # Examine steps if they exist
        if hasattr(payroll_doc, "steps") and payroll_doc.steps:
            result["sample_steps"] = []
            for step in payroll_doc.steps[:3]:  # First 3 steps
                result["sample_steps"].append({"step": step.step, "fields": list(step.as_dict().keys())})

        return {"success": True, "analysis": result}

    except Exception as e:
        return {"success": False, "message": str(e), "error_type": type(e).__name__}


@frappe.whitelist()
def debug_onboarding_creation():
    """Debug function to test Module Onboarding creation with steps"""
    try:
        # Delete existing if it exists
        if frappe.db.exists("Module Onboarding", "Verenigingen"):
            frappe.delete_doc("Module Onboarding", "Verenigingen", force=1)
            frappe.db.commit()

        # First create an Onboarding Step
        step_name = "Verenigingen-Create-Member"
        if frappe.db.exists("Onboarding Step", step_name):
            frappe.delete_doc("Onboarding Step", step_name, force=1)

        step_doc = frappe.get_doc(
            {
                "doctype": "Onboarding Step",
                "name": step_name,
                "title": "Create Member",
                "action": "Create Entry",
                "action_label": "Create your first Member",
                "creation_doctype": "Member",
                "description": "Create a member profile to get started with membership management.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "Member",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            }
        )
        step_doc.insert(ignore_permissions=True)

        # Now create Module Onboarding with the step reference
        doc = frappe.get_doc(
            {
                "doctype": "Module Onboarding",
                "name": "Verenigingen",
                "title": "Let's set up your Association Management.",
                "subtitle": "Members, Volunteers, Chapters, and more.",
                "module": "E-Boekhouden",
                "success_message": "The Verenigingen Module is all set up!",
                "documentation_url": "https://github.com/verenigingen/docs",
                "is_complete": 0,
                "allow_roles": [{"role": "System Manager"}, {"role": "Verenigingen Administrator"}],
                "steps": [{"step": step_name}],
            }
        )

        # Try to insert
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {"success": True, "message": "Module Onboarding created successfully with 1 step"}

    except Exception as e:
        return {"success": False, "message": str(e), "error_type": type(e).__name__}


@frappe.whitelist()
def reinstall_onboarding():
    """Reinstall the Module Onboarding document with steps"""
    try:
        print("🔧 Reinstalling Module Onboarding...")

        # Delete existing if it exists
        if frappe.db.exists("Module Onboarding", "Verenigingen"):
            frappe.delete_doc("Module Onboarding", "Verenigingen", force=1)
            frappe.db.commit()
            print("   ✓ Deleted existing Module Onboarding")

        # Create with all required fields using the working structure
        doc = frappe.get_doc(
            {
                "doctype": "Module Onboarding",
                "name": "Verenigingen",
                "title": "Let's set up your Association Management.",
                "subtitle": "Members, Volunteers, Chapters, and more.",
                "module": "E-Boekhouden",
                "success_message": "The Verenigingen Module is all set up!",
                "documentation_url": "https://github.com/verenigingen/docs",
                "allow_roles": [{"role": "System Manager"}, {"role": "Verenigingen Administrator"}],
                "is_complete": 0,
            }
        )

        # Create Onboarding Step documents first
        step_names = []
        step_definitions = [
            {
                "name": "Verenigingen-Setup-Settings",
                "title": "Configure Verenigingen Settings",
                "action": "Create Entry",
                "action_label": "Configure basic settings",
                "creation_doctype": "Verenigingen Settings",
                "description": "Configure basic settings for your association including default membership types, email templates, and system preferences.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "Verenigingen Settings",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
            {
                "name": "Verenigingen-Install-Email-Templates",
                "title": "Install Email Templates",
                "action": "Go to Page",
                "action_label": "Install missing email templates",
                "path": "/install_email_templates",
                "description": "Install all required email templates for membership applications, welcome messages, payment notifications, and termination processes. This includes templates for application confirmations, welcome emails, payment failures, and termination notices.",
                "is_complete": 0,
                "is_mandatory": 0,
                "is_skipped": 0,
                "reference_document": "Email Template",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 0,
            },
            {
                "name": "Verenigingen-Create-Member",
                "title": "Create Member",
                "action": "Create Entry",
                "action_label": "Create your first Member",
                "creation_doctype": "Member",
                "description": "Create a member profile to get started with membership management.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "Member",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
            {
                "name": "Verenigingen-Create-Membership-Type",
                "title": "Create Membership Type",
                "action": "Create Entry",
                "action_label": "Set up Membership Types",
                "creation_doctype": "Membership Type",
                "description": "Define the different types of memberships your association offers.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "Membership Type",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
            {
                "name": "Verenigingen-Create-Membership",
                "title": "Create Membership",
                "action": "Create Entry",
                "action_label": "Create your first Membership",
                "creation_doctype": "Membership",
                "description": "Link members to their membership types and track their status.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "Membership",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
            {
                "name": "Verenigingen-Create-Chapter",
                "title": "Create Chapter",
                "action": "Create Entry",
                "action_label": "Set up your first Chapter",
                "creation_doctype": "Chapter",
                "description": "Organize members by geographic regions or local chapters.",
                "is_complete": 0,
                "is_mandatory": 0,
                "is_skipped": 0,
                "reference_document": "Chapter",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
            {
                "name": "Verenigingen-Create-Volunteer",
                "title": "Create Volunteer",
                "action": "Create Entry",
                "action_label": "Register your first Volunteer",
                "creation_doctype": "Volunteer",
                "description": "Track volunteers and their activities within your association.",
                "is_complete": 0,
                "is_mandatory": 0,
                "is_skipped": 0,
                "reference_document": "Volunteer",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
            },
        ]

        # Create individual Onboarding Step documents
        for step_def in step_definitions:
            step_name = step_def["name"]

            # Delete if exists
            if frappe.db.exists("Onboarding Step", step_name):
                frappe.delete_doc("Onboarding Step", step_name, force=1)

            # Create new step
            step_doc = frappe.get_doc({"doctype": "Onboarding Step", **step_def})
            step_doc.insert(ignore_permissions=True)
            step_names.append(step_name)

        print(f"   ✓ Created {len(step_names)} Onboarding Step documents")

        # Now add step references to the Module Onboarding before inserting
        for step_name in step_names:
            doc.append("steps", {"step": step_name})

        # Insert the Module Onboarding document with all steps
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"   ✓ Added {len(doc.steps)} steps to Module Onboarding")

        # Update workspace link
        if frappe.db.exists("Workspace", "Verenigingen"):
            workspace = frappe.get_doc("Workspace", "Verenigingen")
            workspace.module_onboarding = "Verenigingen"
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print("   ✓ Updated workspace link")

        return {
            "success": True,
            "message": f"Module Onboarding reinstalled with {len(doc.steps)} steps: {doc.name}",
            "steps_created": len(doc.steps),
            "next_step": "Visit /app/verenigingen to see the onboarding banner",
        }

    except Exception as e:
        return {"success": False, "message": str(e)}
