import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
    """
    Remove legacy fields from Membership doctype:
    - auto_renew (moved to billing system)
    - next_billing_date (replaced by dues schedule system)
    - dues_schedule_section and related fields (moved to separate system)
    """

    # First, let's check if these fields still exist in the database
    # If they do, we need to remove them carefully

    # Check if the doctype exists and has been loaded
    if not frappe.db.exists("DocType", "Membership"):
        return

    # Prepare migration - get the doctype meta if needed for validation
    # membership_meta = frappe.get_meta("Membership")  # Available if needed

    # Fields to remove from database if they exist
    fields_to_remove = [
        "auto_renew",
        "next_billing_date",
        "dues_schedule_section",
        "member_dues_schedule",
        "dues_schedule_status",
        "view_dues_schedule",
        "view_payments",
    ]

    # Check if table exists
    if not frappe.db.sql("SELECT 1 FROM information_schema.tables WHERE table_name = 'tabMembership'"):
        print("Membership table does not exist, skipping field removal")
        return

    # Get actual columns in the database table
    db_columns = frappe.db.sql(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'tabMembership'
    """,
        as_dict=True,
    )

    existing_db_columns = [col["COLUMN_NAME"] for col in db_columns]

    # Remove columns that exist in database but not in current doctype definition
    for field in fields_to_remove:
        if field in existing_db_columns:
            try:
                print(f"Removing column {field} from tabMembership")
                frappe.db.sql(f"ALTER TABLE `tabMembership` DROP COLUMN `{field}`")
                frappe.db.commit()
                print(f"Successfully removed column {field}")
            except Exception as e:
                print(f"Warning: Could not remove column {field}: {str(e)}")
                # Continue with other fields
                continue

    # Clear any cached doctype data
    frappe.clear_cache(doctype="Membership")

    # Also need to handle Membership Type dues_schedule_template requirement
    # during migration by creating default templates if needed
    handle_membership_type_templates()

    print("✅ Membership legacy fields migration completed")


def handle_membership_type_templates():
    """Ensure all Membership Types have dues_schedule_template to prevent migration errors"""

    # Get all membership types
    membership_types = frappe.get_all("Membership Type", fields=["name", "dues_schedule_template"])

    for mt in membership_types:
        if not mt.dues_schedule_template:
            # Check if fixture template exists first (preferred approach)
            fixture_template_name = f"{mt.membership_type_name} Template"
            if frappe.db.exists("Membership Dues Schedule", fixture_template_name):
                # Use fixture template
                frappe.db.set_value(
                    "Membership Type", mt.name, "dues_schedule_template", fixture_template_name
                )
                print(f"Linked existing fixture template for {mt.name}: {fixture_template_name}")
            else:
                # Only create if no fixture exists (legacy fallback)
                try:
                    template_name = create_default_dues_schedule_template(mt.name)
                    if template_name:
                        # Update the membership type
                        frappe.db.set_value(
                            "Membership Type", mt.name, "dues_schedule_template", template_name
                        )
                        print(f"Created fallback dues schedule template for {mt.name}: {template_name}")
                except Exception as e:
                    print(f"Warning: Could not create template for {mt.name}: {str(e)}")


def create_default_dues_schedule_template(membership_type_name):
    """Create a default dues schedule template for a membership type"""

    # Check if template already exists
    template_name = f"{membership_type_name} Template"
    if frappe.db.exists("Membership Dues Schedule", template_name):
        return template_name

    try:
        # Get the membership type document
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)

        # Create template
        template = frappe.new_doc("Membership Dues Schedule")
        template.schedule_name = template_name
        template.is_template = 1  # Mark as template

        # Set basic values - use membership type data if available
        template.membership_type = membership_type_name
        template.billing_frequency = getattr(mt_doc, "billing_period", "Annual") or "Annual"

        # Set suggested amounts - use existing membership type amounts if available
        if hasattr(mt_doc, "amount") and mt_doc.amount:
            template.suggested_amount = mt_doc.amount
            template.minimum_amount = mt_doc.amount
        else:
            # Default amounts
            template.suggested_amount = 50.0
            template.minimum_amount = 25.0

        template.dues_rate = template.suggested_amount
        template.contribution_mode = "Fixed"
        template.status = "Template"

        # Insert the template
        template.insert()
        frappe.db.commit()

        return template.name

    except Exception as e:
        print(f"Error creating template for {membership_type_name}: {str(e)}")
        return None
