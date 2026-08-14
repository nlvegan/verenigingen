# Setup and configuration utilities for Verenigingen app

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.page.setup_wizard.setup_wizard import make_records

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
)


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
            },
            {
                # Idempotency key for the Procurios membership import. Defined
                # here (not only in the v15_0 patch) because patches are
                # skipped on fresh installs — CI builds a fresh site, so the
                # field must come from make_custom_fields/after_install too.
                "fieldname": "procurios_membership_id",
                "label": "Procurios Membership ID",
                "fieldtype": "Data",
                "read_only": 1,
                "no_copy": 1,
                "search_index": 1,
                "insert_after": "amended_from",
                "description": "Procurios membership Id this record was imported from (idempotency key).",
                "translatable": 0,
            },
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


def _is_initial_setup_complete() -> bool:
    """
    Check if initial setup has already been completed.

    Returns True if the initial_setup_complete flag is set in Verenigingen Settings.
    """
    try:
        if not frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            return False
        return bool(
            frappe.db.get_value("Verenigingen Settings", "Verenigingen Settings", "initial_setup_complete")
        )
    except Exception:
        return False


def _mark_initial_setup_complete():
    """
    Mark initial setup as complete by setting the flag in Verenigingen Settings.
    """
    try:
        if frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            frappe.db.set_value(
                "Verenigingen Settings",
                "Verenigingen Settings",
                "initial_setup_complete",
                1,
            )
            frappe.db.commit()
            print("✅ Marked initial setup as complete")
    except Exception as e:
        print(f"⚠️ Could not mark initial setup complete: {str(e)}")


def execute_after_install():
    """
    Function executed after the app is installed
    Sets up necessary configurations for the Verenigingen app

    This function is idempotent - it checks initial_setup_complete flag
    and skips reference data creation if already run.
    """
    try:
        # Check if initial setup has already been completed
        if _is_initial_setup_complete():
            print("✅ Initial setup already complete - skipping reference data creation")
            return

        # Validate dependencies
        validate_app_dependencies()

        # Create default Verenigingen Settings FIRST (critical for campaign donations)
        create_default_verenigingen_settings()

        # Create E-Boekhouden custom fields first
        create_eboekhouden_custom_fields()

        # Create default E-Boekhouden Settings
        create_default_eboekhouden_settings()

        # Execute the setup function from this file
        setup_verenigingen()

        # Create all reference data (Membership Types, Team Roles, etc.)
        # This is now done here instead of via fixtures to prevent migration overwrites
        create_all_reference_data()

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
            frappe.logger().warning("Security setup failed: %s", str(e))

        # Set up webhook user for secure payment processing
        try:
            from verenigingen.setup.webhook_user_setup import setup_webhook_user

            webhook_result = setup_webhook_user()
            if webhook_result.get("success"):
                print("✅ Webhook user setup completed successfully")
            else:
                print(f"⚠️ Webhook user setup failed: {webhook_result.get('message')}")
        except Exception as e:
            print(f"⚠️ Webhook user setup failed: {str(e)}")
            frappe.logger().warning("Webhook user setup failed: %s", str(e))

        # Set up public document creator user for secure public form processing
        try:
            from verenigingen.setup.public_document_creator_setup import setup_public_document_creator

            creator_result = setup_public_document_creator()
            if creator_result.get("success"):
                print("✅ Public document creator setup completed successfully")
            else:
                print(f"⚠️ Public document creator setup failed: {creator_result.get('message')}")
        except Exception as e:
            print(f"⚠️ Public document creator setup failed: {str(e)}")
            frappe.logger().warning("Public document creator setup failed: %s", str(e))

        # Mark initial setup as complete to prevent re-running on future migrations
        _mark_initial_setup_complete()

        # Log the successful setup
        frappe.logger().info("Verenigingen setup completed successfully")
        print("Verenigingen app setup completed successfully")

    except Exception as e:
        frappe.logger().error("Error during Verenigingen setup: %s", str(e))
        print(f"Error during setup: {str(e)}")


def create_eboekhouden_custom_fields():
    """E-Boekhouden custom fields are now created via fixtures"""
    print("✅ E-Boekhouden custom fields created via fixtures")


def create_default_verenigingen_settings():
    """
    Create default Verenigingen Settings single document.

    CRITICAL: This is required for campaign donation functionality and many other features.
    Without this, the system will fail with "Unable to load system settings" errors.
    """
    try:
        if not frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            # Get default company if exists using standardized query approach
            from verenigingen.utils.validation_utilities import get_all_active_records

            companies = get_all_active_records("Company", fields=["name"], limit=1, order_by="name")
            default_company = companies[0].name if companies else "Your Company"

            settings = frappe.get_doc(
                {
                    "doctype": "Verenigingen Settings",
                    # Company settings
                    "company": default_company,
                    "company_name": default_company,
                    # Email settings - must be configured by administrator
                    "organization_email_domain": "",
                    "member_contact_email": "",
                    "support_email": "",
                    "creation_user": frappe.session.user or "Administrator",
                    # Campaign/Donation settings (REQUIRED for campaign donations)
                    "auto_create_donors": 1,
                    "minimum_donation_amount": 1.00,
                    "default_donor_type": "Individual",
                    # Member settings
                    "enable_chapter_management": 1,
                    "member_id_start": 1000,
                    "last_member_id": 1000,
                    "default_grace_period_days": 30,
                    "max_fee_adjustments_per_year": 2,
                    # Automation settings (disabled by default for safety)
                    # NOTE: SEPA bank details (company_iban / company_bic /
                    # creditor_id / company_account_holder) and the termination
                    # system settings now live on the "Verenigingen Payments
                    # Settings" doctype, not here. They used to be seeded into
                    # this dict but Frappe silently drops unknown keys, so the
                    # values were never applied. Keys removed to avoid the
                    # misleading no-op seed.
                    "automate_donation_payment_entries": 0,
                    "auto_cancel_sepa_mandates": 0,
                    "auto_end_board_positions": 0,
                    "send_termination_notifications": 0,
                }
            )

            settings.insert(ignore_permissions=True)
            frappe.db.commit()
            print("✅ Created default Verenigingen Settings")

        settings = frappe.get_doc("Verenigingen Settings")
        _seed_default_document_categories(settings)
        return settings
    except Exception as e:
        print(f"⚠️ Failed to create Verenigingen Settings: {str(e)}")
        # Don't fail installation if settings creation fails
        return None


def _seed_default_document_categories(settings):
    """Ensure default board document categories exist in Settings.

    Idempotent — only adds categories that aren't already present.
    """
    defaults = [
        {
            "category_name": "Policy",
            "category_icon": "📋",
            "folder_keywords": "statuten, huishoudelijk reglement, programma, platform, perspectieven, jaarplanning, basisgroepvoorzitters, aangenomen stukken",
        },
        {
            "category_name": "Meeting Minutes",
            "category_icon": "📝",
            "folder_keywords": "notulen, congres, aggregaat, conferentie, kaderdag, vergadering, bestuursvergadering, ledenvergadering, congrescommissie",
        },
        {
            "category_name": "Financial Report",
            "category_icon": "💰",
            "folder_keywords": "financien, jaarrekening, begroting, kascontrole",
        },
        {
            "category_name": "Intern Bulletin",
            "category_icon": "📰",
            "folder_keywords": "intern bulletin",
        },
        {"category_name": "Other", "category_icon": "📎"},
    ]

    existing_names = {row.category_name for row in (settings.board_document_categories or [])}

    added = []
    for cat in defaults:
        if cat["category_name"] not in existing_names:
            settings.append("board_document_categories", cat)
            added.append(cat["category_name"])

    if added:
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"✅ Seeded default document categories: {', '.join(added)}")
    else:
        print("✅ Default document categories already present")


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
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        if settings and settings.get("tax_exempt_for_contributions"):
            # Import and run the tax setup
            from verenigingen.utils import setup_dutch_tax_exemption

            setup_dutch_tax_exemption()
            print("Tax exemption templates set up during installation")
    except Exception as e:
        frappe.logger().error("Error setting up tax exemption during install: %s", str(e))
        print(f"Warning: Could not set up tax exemption during install: {str(e)}")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
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
@high_security_api(operation_type=OperationType.ADMIN)
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
@critical_api(operation_type=OperationType.ADMIN)
def fix_btw_installation():
    """Fix BTW installation issues"""
    try:
        # Reinstall custom fields
        install_missing_btw_fields()

        # Set up tax templates if needed
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
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

        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()

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
@critical_api(operation_type=OperationType.ADMIN)
def setup_termination_system_manual():
    """Manual setup endpoint for termination system"""
    try:
        setup_termination_system_integration()
        return {"success": True, "message": "Termination system setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
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
            from verenigingen.utils.settings_utils import get_verenigingen_settings

            settings = get_verenigingen_settings()
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
        status["roles_exist"] = frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN)

        return {"success": True, "status": status}

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.ADMIN)
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

    if frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN):
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
            from verenigingen.api.membership_email_templates import create_default_email_templates

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

        # Note: Donation Type DocType was removed - no longer creating default types

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
                        <td>{{ frappe.utils.format_date(membership.start_date) }}</td>
                    </tr>
                    <tr>
                        <td><strong>Valid Until:</strong></td>
                        <td>{{ frappe.utils.format_date(membership.renewal_date) }}</td>
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

                <p>If you continue to experience issues, please contact our support team.</p>

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
                    # Use frappe.get_doc approach instead of install_fixtures
                    import json

                    with open(fixture_path, "r") as f:
                        fixture_data = json.load(f)

                    if isinstance(fixture_data, list):
                        for doc_data in fixture_data:
                            if "doctype" in doc_data:
                                doc = frappe.get_doc(doc_data)
                                doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
                    else:
                        if "doctype" in fixture_data:
                            doc = frappe.get_doc(fixture_data)
                            doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
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
@critical_api(operation_type=OperationType.ADMIN)
def run_complete_setup():
    """Run the complete setup process manually"""
    try:
        execute_after_install()
        return {"success": True, "message": "Complete setup completed successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_membership_application_system_manual():
    """Manual setup endpoint for membership application system"""
    try:
        setup_membership_application_system()
        return {"success": True, "message": "Membership application system setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_workspace_manual():
    """Manual setup endpoint for workspace"""
    try:
        setup_workspace()
        return {"success": True, "message": "Workspace setup completed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def create_default_membership_types():
    """Create default Dutch membership types if they don't exist"""
    print("   👥 Setting up default membership types...")

    # Dutch association membership types
    # Note: dues_schedule_template is created automatically via after_insert hook
    membership_types = [
        {
            "membership_type_name": "Lid",
            "minimum_amount": 3.0,
            "is_active": 1,
            "description": "Standaard lidmaatschap met volledige rechten",
            "role_profile": "Verenigingen Member",
        },
        {
            "membership_type_name": "Huisgenootlid",
            "minimum_amount": 0.0,
            "is_active": 1,
            "description": "Lidmaatschap voor huisgenoten van bestaande leden (gereduceerd tarief)",
            "role_profile": "Verenigingen Member",
        },
        {
            "membership_type_name": "Aspirant",
            "minimum_amount": 3.0,
            "is_active": 1,
            "description": "Proeflidmaatschap voor nieuwe aanmeldingen (geen contributie)",
            "role_profile": "Verenigingen Member",
        },
        {
            "membership_type_name": "Erelid",
            "minimum_amount": 0.0,
            "is_active": 1,
            "description": "Erelidmaatschap - geen contributie verschuldigd",
            "role_profile": "Verenigingen Member",
        },
        {
            "membership_type_name": "Donateur",
            "minimum_amount": 0.0,
            "is_active": 1,
            "description": "Donateur - steunt de vereniging zonder lidmaatschapsrechten",
            "role_profile": "Verenigingen Member",
        },
    ]

    created_count = 0
    for mt_data in membership_types:
        name = mt_data["membership_type_name"]
        if not frappe.db.exists("Membership Type", name):
            try:
                doc = frappe.get_doc({"doctype": "Membership Type", **mt_data})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created membership type: {name}")
            except Exception as e:
                print(f"   ⚠️ Could not create membership type '{name}': {str(e)}")
        else:
            print(f"   ✓ Membership type already exists: {name}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   👥 Created {created_count} default membership types")

    return created_count


def create_default_team_roles():
    """Create default team roles if they don't exist"""
    print("   🎭 Setting up default team roles...")

    team_roles = [
        {
            "role_name": "Team Leader",
            "description": "Leads the team and coordinates activities. Responsible for team management and decision-making.",
            "permissions_level": "Leader",
            "is_team_leader": 1,
            "is_unique": 1,
            "is_active": 1,
        },
        {
            "role_name": "Team Member",
            "description": "General team member participating in team activities and projects.",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1,
        },
        {
            "role_name": "Coordinator",
            "description": "Coordinates specific aspects of team work and assists team leadership.",
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1,
        },
        {
            "role_name": "Secretary",
            "description": "Maintains team records, minutes, and handles administrative tasks.",
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 1,
            "is_active": 1,
        },
        {
            "role_name": "Treasurer",
            "description": "Manages team finances, budgets, and financial reporting.",
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 1,
            "is_active": 1,
        },
        {
            "role_name": "Verenigingen Auditor",
            "description": "Audit committee member with read-only access to all financial records, accounting transactions, and compliance reports. Responsible for financial oversight and audit functions.",
            "permissions_level": "Coordinator",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1,
        },
    ]

    created_count = 0
    for role_data in team_roles:
        name = role_data["role_name"]
        if not frappe.db.exists("Team Role", name):
            try:
                doc = frappe.get_doc({"doctype": "Team Role", **role_data})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created team role: {name}")
            except Exception as e:
                print(f"   ⚠️ Could not create team role '{name}': {str(e)}")
        else:
            print(f"   ✓ Team role already exists: {name}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   🎭 Created {created_count} default team roles")

    return created_count


def create_default_teams():
    """Create default teams if they don't exist"""
    print("   👥 Setting up default teams...")

    teams = [
        {
            "team_name": "Kascommissie",
            "description": "Audit committee responsible for financial oversight, reviewing accounting practices, ensuring compliance with financial regulations, and providing independent financial audit services for the association.",
            "status": "Active",
            "team_type": "Committee",
            "is_association_wide": 1,
            "start_date": "2024-01-01",
            "objectives": "<p>The Kascommissie (Audit Committee) provides independent oversight of the association's financial operations.</p>",
        },
    ]

    created_count = 0
    for team_data in teams:
        name = team_data["team_name"]
        if not frappe.db.exists("Team", name):
            try:
                doc = frappe.get_doc({"doctype": "Team", **team_data})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created team: {name}")
            except Exception as e:
                print(f"   ⚠️ Could not create team '{name}': {str(e)}")
        else:
            print(f"   ✓ Team already exists: {name}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   👥 Created {created_count} default teams")

    return created_count


def create_default_regions():
    """Create default Dutch regions if they don't exist"""
    print("   🗺️ Setting up default regions...")

    regions = [
        {
            "region_name": "Noord-Holland",
            "region_code": "NH",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "1000-1999",
            "coverage_description": "Amsterdam and surrounding areas",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
        {
            "region_name": "Utrecht",
            "region_code": "UT",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "3400-3999",
            "coverage_description": "Utrecht province",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
        {
            "region_name": "Zuid-Holland",
            "region_code": "ZH",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "2000-2999",
            "coverage_description": "Rotterdam, Den Haag and surrounding areas",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
        {
            "region_name": "Gelderland",
            "region_code": "GLD",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "6500-7000,8200-8299",
            "coverage_description": "Arnhem, Nijmegen and surrounding areas",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
        {
            "region_name": "Noord-Brabant",
            "region_code": "NB",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "4700-5000,5100-5299",
            "coverage_description": "Eindhoven, Breda, Tilburg and surrounding areas",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
        {
            "region_name": "Limburg",
            "region_code": "LB",
            "country": "Netherlands",
            "is_active": 1,
            "postal_code_patterns": "5900-6500",
            "coverage_description": "Maastricht and surrounding areas",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        },
    ]

    created_count = 0
    for region_data in regions:
        name = region_data["region_name"]
        if not frappe.db.exists("Region", name):
            try:
                doc = frappe.get_doc({"doctype": "Region", **region_data})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created region: {name}")
            except Exception as e:
                print(f"   ⚠️ Could not create region '{name}': {str(e)}")
        else:
            # Self-heal canonical fields on a pre-existing region. A region row
            # may have been created elsewhere (e.g. a test, or before this seed
            # ran) without `country`, in which case Frappe applies the global
            # `country` default, which is not guaranteed to be "Netherlands" on a
            # fresh site. Enforce the canonical country so downstream consumers
            # (and the seed's own invariant) are reliable. This does not count as
            # a "created" region, so idempotency (created == 0) is preserved.
            current_country = frappe.db.get_value("Region", name, "country")
            if current_country != region_data["country"]:
                frappe.db.set_value("Region", name, "country", region_data["country"], update_modified=False)
                frappe.db.commit()
                print(
                    f"   🛠️ Corrected country for region '{name}': "
                    f"{current_country!r} -> {region_data['country']!r}"
                )
            else:
                print(f"   ✓ Region already exists: {name}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   🗺️ Created {created_count} default regions")

    return created_count


def create_default_payment_modes():
    """Create default payment modes if they don't exist"""
    print("   💳 Setting up default payment modes...")

    payment_modes = [
        # Online payment gateways
        {"mode_of_payment": "Mollie", "type": "General"},
        {"mode_of_payment": "Ponto", "type": "Bank"},
        # Traditional payment methods (for legacy data compatibility)
        {"mode_of_payment": "Bank Transfer", "type": "Bank"},
        {"mode_of_payment": "SEPA Direct Debit", "type": "Bank"},
        {"mode_of_payment": "Cash", "type": "Cash"},
    ]

    created_count = 0
    for pm_data in payment_modes:
        name = pm_data["mode_of_payment"]
        if not frappe.db.exists("Mode of Payment", name):
            try:
                doc = frappe.get_doc({"doctype": "Mode of Payment", **pm_data})
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✓ Created payment mode: {name}")
            except Exception as e:
                print(f"   ⚠️ Could not create payment mode '{name}': {str(e)}")
        else:
            print(f"   ✓ Payment mode already exists: {name}")

    if created_count > 0:
        frappe.db.commit()
        print(f"   💳 Created {created_count} default payment modes")

    return created_count


def create_membership_items():
    """Create membership-related items and item groups"""
    print("   📦 Setting up membership items...")

    # Ensure Memberships item group exists
    if not frappe.db.exists("Item Group", "Memberships"):
        try:
            # Get parent item group
            parent = "All Item Groups"
            if not frappe.db.exists("Item Group", parent):
                parent = ""

            doc = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "is_group": 0,
                    "parent_item_group": parent,
                }
            )
            doc.insert(ignore_permissions=True)
            print("   ✓ Created item group: Memberships")
        except Exception as e:
            print(f"   ⚠️ Could not create item group 'Memberships': {str(e)}")
    else:
        print("   ✓ Item group already exists: Memberships")

    # Create MEMBERSHIP item
    if not frappe.db.exists("Item", "MEMBERSHIP"):
        try:
            doc = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": "MEMBERSHIP",
                    "item_name": "Membership",
                    "item_group": (
                        "Memberships" if frappe.db.exists("Item Group", "Memberships") else "Services"
                    ),
                    "stock_uom": "Nos",
                    "is_stock_item": 0,
                    "is_sales_item": 1,
                    "is_service_item": 1,
                    "description": "Standard membership item for association dues",
                }
            )
            doc.insert(ignore_permissions=True)
            print("   ✓ Created item: MEMBERSHIP")
        except Exception as e:
            print(f"   ⚠️ Could not create item 'MEMBERSHIP': {str(e)}")
    else:
        print("   ✓ Item already exists: MEMBERSHIP")

    frappe.db.commit()


def configure_website_cors():
    """Configure CORS settings if not already set.

    Only enables CORS if cors_allowed_origins is empty.
    Uses the site URL to determine allowed origins automatically.
    """
    print("   🌐 Checking CORS configuration...")

    try:
        website_settings = frappe.get_single("Website Settings")

        # Only configure if CORS origins not already set
        if website_settings.get("cors_allowed_origins"):
            print("   ✓ CORS already configured, skipping")
            return

        # Get the site URL to use as allowed origin
        site_url = frappe.utils.get_url()

        website_settings.enable_cors = 1
        website_settings.cors_allowed_origins = site_url
        website_settings.cors_allowed_methods = "GET, POST, PUT, DELETE, OPTIONS"
        website_settings.cors_allowed_headers = (
            "Content-Type, Authorization, X-Frappe-CSRF-Token, X-Frappe-Cmd"
        )
        website_settings.cors_allow_credentials = 1
        website_settings.cors_max_age = 86400
        website_settings.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"   ✓ CORS configured with origin: {site_url}")

    except Exception as e:
        print(f"   ⚠️ Could not configure CORS: {str(e)}")


def create_all_reference_data():
    """
    Create all reference data that was previously in fixtures.

    This function is called by execute_after_install() and creates:
    - Donation Types
    - Membership Types
    - Team Roles
    - Teams (e.g., Kascommissie)
    - Regions (Dutch provinces)
    - Payment Modes
    - Membership Items
    - CORS configuration
    """
    print("\n📊 Creating reference data...")

    # Note: Donation Type DocType was removed
    create_default_membership_types()
    create_default_team_roles()
    create_default_teams()
    create_default_regions()
    create_default_payment_modes()
    create_membership_items()
    configure_website_cors()
    create_background_service_user()

    print("📊 Reference data creation complete\n")


def create_background_service_user():
    """Create background service user for webhooks and scheduled tasks.

    Only creates if user doesn't exist. Uses .local domain to indicate
    this is a system user, not a real email address.
    """
    print("   🤖 Setting up background service user...")

    user_email = "background.service@verenigingen.local"

    if frappe.db.exists("User", user_email):
        print(f"   ✓ Service user already exists: {user_email}")
        return

    try:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Background",
                "last_name": "Service",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "language": "en",
                "time_zone": "Europe/Amsterdam",
                "roles": [{"role": "Verenigingen Webhook User"}],
            }
        )
        user.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"   ✓ Created service user: {user_email}")
    except Exception as e:
        print(f"   ⚠️ Could not create service user: {str(e)}")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_donation_types_manual():
    """DEPRECATED: Donation Type DocType was removed"""
    return {"success": False, "message": "Donation Type feature has been removed"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def verify_donation_type_setup():
    """DEPRECATED: Donation Type DocType was removed"""
    return {"success": False, "message": "Donation Type feature has been removed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def _normalize_template_count(result):
    """Normalize the differing return shapes of the email-template helpers to an int.

    The three helpers each return a different type:
    - create_application_email_templates() -> int (count)
    - create_default_email_templates() -> dict with a "templates" list
    - create_comprehensive_email_templates() -> OperationResult whose .data dict
      carries "created"/"total"
    Without this normalization the old ``int + dict`` arithmetic raised TypeError,
    so the manual endpoint always reported success=False even though templates were
    created.
    """
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        return len(result.get("templates", []))
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data.get("created", data.get("total", 0)) or 0
    return 0


def create_email_templates_manual():
    """Manual endpoint to create email templates"""
    try:
        print("🔧 Manually creating email templates...")

        # Create basic templates
        basic_count = _normalize_template_count(create_application_email_templates())

        # Create enhanced templates
        enhanced_count = 0
        try:
            from verenigingen.api.membership_email_templates import create_default_email_templates

            enhanced_count = _normalize_template_count(create_default_email_templates())
        except Exception as e:
            print(f"Enhanced templates failed: {str(e)}")

        # Create comprehensive templates
        comprehensive_count = 0
        try:
            from verenigingen.api.email_template_manager import create_comprehensive_email_templates

            comprehensive_count = _normalize_template_count(create_comprehensive_email_templates())
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
@high_security_api(operation_type=OperationType.ADMIN)
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
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
@critical_api(operation_type=OperationType.ADMIN)
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
                "module": "Verenigingen",
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
                "name": "Verenigingen-Configure-Security",
                "title": "Configure Security Settings",
                # This step used to carry "Go to Settings", which is not one of
                # the Select options Onboarding Step accepts. A plain insert
                # throws on it; a fixture import stores it verbatim (in_import
                # suppresses Select validation), which is how it survived. The
                # fixture now matches this value.
                "action": "Update Settings",
                "action_label": "Configure Security Settings",
                "description": "Configure critical security settings to ensure proper data access control, audit compliance, and permission management for your association.",
                "is_complete": 0,
                "is_mandatory": 1,
                "is_skipped": 0,
                "reference_document": "System Settings",
                "show_form_tour": 0,
                "show_full_form": 0,
                "validate_action": 1,
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


def ensure_required_payment_modes():
    """
    Ensure required payment modes exist during migration.

    This is called by after_migrate to ensure existing sites have the required
    payment modes for membership applications to work correctly.
    """
    from verenigingen.utils.application_helpers import ensure_payment_modes_exist

    created = ensure_payment_modes_exist()
    if created:
        print(f"   ✓ Created missing payment modes: {', '.join(created)}")
