"""
Employee User Linking Utilities

Handles creation and linking of User accounts for Employees created from Volunteers
"""

import frappe
from frappe import _
from frappe.utils import cint


def safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


def create_user_for_volunteer(volunteer_doc):
    """Create a User account for a volunteer if it doesn't exist - SECURE VERSION"""
    try:
        # Check if user already exists with this email
        if not volunteer_doc.email:
            frappe.logger().info(f"Volunteer {volunteer_doc.name} has no email, skipping user creation")
            return None

        existing_user = frappe.db.get_value("User", {"email": volunteer_doc.email}, "name")
        if existing_user:
            frappe.logger().info(f"User already exists for email {volunteer_doc.email}")
            return existing_user

        # Validate current user has permission to create users
        if not frappe.has_permission("User", "create"):
            # Use AccountCreationManager for secure user creation instead
            frappe.logger().info(
                f"Using AccountCreationManager for secure user creation: {volunteer_doc.email}"
            )
            return _create_user_via_account_creation_manager(volunteer_doc)

        # Create new user with proper permission validation
        user = frappe.new_doc("User")
        user.email = volunteer_doc.email
        user.first_name = (
            volunteer_doc.volunteer_name.split()[0]
            if volunteer_doc.volunteer_name
            else "Verenigingen Volunteer"
        )
        user.last_name = (
            " ".join(volunteer_doc.volunteer_name.split()[1:])
            if len(volunteer_doc.volunteer_name.split()) > 1
            else ""
        )
        user.send_welcome_email = 0  # Don't send welcome email yet
        user.enabled = 1

        # Add appropriate roles (check if roles exist and can be assigned)
        available_roles = [r.name for r in frappe.get_all("Role", fields=["name"])]

        if "Employee" in available_roles:
            try:
                user.append("roles", {"role": "Employee"})
                frappe.logger().info(f"Added Employee role for user {volunteer_doc.email}")
            except Exception as e:
                frappe.logger().warning(f"Could not add Employee role: {str(e)}")

        if "Verenigingen Volunteer" in available_roles:
            try:
                user.append("roles", {"role": "Verenigingen Volunteer"})
                frappe.logger().info(f"Added Verenigingen Volunteer role for user {volunteer_doc.email}")
            except Exception as e:
                frappe.logger().warning(f"Could not add Verenigingen Volunteer role: {str(e)}")

        # Add basic roles that should always be assignable
        try:
            user.append("roles", {"role": "System User"})
            frappe.logger().info(f"Added System User role for user {volunteer_doc.email}")
        except Exception as e:
            frappe.logger().warning(f"Could not add System User role: {str(e)}")

        # Insert with proper permissions - NO ignore_permissions=True
        user.insert()
        frappe.logger().info(f"Created user {user.name} for volunteer {volunteer_doc.name}")

        return user.name

    except Exception as e:
        safe_log_error(f"Error creating user for volunteer {volunteer_doc.name}: {str(e)}")
        return None


def update_employee_with_user(employee_name, user_id):
    """Update employee record with user_id - SECURE VERSION"""
    try:
        # Validate current user has permission to modify employees
        if not frappe.has_permission("Employee", "write"):
            frappe.logger().warning(f"Insufficient permissions to update employee {employee_name}")
            return False

        employee = frappe.get_doc("Employee", employee_name)
        employee.user_id = user_id

        # Save with proper permissions - NO ignore_permissions=True
        employee.save()
        frappe.logger().info(f"Updated employee {employee_name} with user_id {user_id}")
        return True

    except frappe.PermissionError as e:
        safe_log_error(f"Permission denied updating employee {employee_name}: {str(e)}")
        return False
    except Exception as e:
        safe_log_error(f"Error updating employee {employee_name} with user_id: {str(e)}")
        return False


def create_employee_for_approved_volunteer(volunteer_doc):
    """Create employee for volunteer when membership is approved - SECURE VERSION with proper permissions"""
    try:
        # Validate current user has permission to create employees
        if not frappe.has_permission("Employee", "create"):
            frappe.logger().warning(
                f"Insufficient permissions to create employee for volunteer {volunteer_doc.name}"
            )
            return None

        # Check if employee already exists
        if volunteer_doc.employee_id and frappe.db.exists("Employee", volunteer_doc.employee_id):
            frappe.logger().info(
                f"Employee {volunteer_doc.employee_id} already exists for volunteer {volunteer_doc.name}"
            )
            return volunteer_doc.employee_id

        # Get member data to access first_name and last_name
        member_doc = None
        first_name = "Unknown"
        last_name = ""

        if volunteer_doc.member:
            member_doc = frappe.get_doc("Member", volunteer_doc.member)
            first_name = member_doc.first_name or "Unknown"
            last_name = member_doc.last_name or ""
        else:
            # Fallback: Parse volunteer_name if no member link
            name_parts = volunteer_doc.volunteer_name.split() if volunteer_doc.volunteer_name else ["Unknown"]
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Create employee manually since create_minimal_employee was removed
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": first_name,
                "last_name": last_name,
                "personal_email": volunteer_doc.email,
                "company": frappe.defaults.get_defaults().get("company") or "Vereniging Veganisme",
                "employee_name": f"{first_name} {last_name}",
                "status": "Active",
                "employment_type": "Volunteer",
            }
        )

        employee.insert()
        employee_id = employee.name

        frappe.logger().info(f"Created employee {employee_id} for volunteer {volunteer_doc.name}")

        # Create user if needed and link to employee
        if volunteer_doc.email:
            user_id = create_user_for_volunteer(volunteer_doc)
            if user_id and employee_id:
                update_employee_with_user(employee_id, user_id)

        return employee_id

    except Exception as e:
        safe_log_error(f"Error creating employee for approved volunteer {volunteer_doc.name}: {str(e)}")
        return None


@frappe.whitelist()
def fix_existing_employee_user_links():
    """Fix existing employees without user_id links"""
    try:
        # Get all employees created from volunteers
        employees_without_users = frappe.db.sql(
            """
            SELECT
                e.name as employee_id,
                e.personal_email,
                e.company_email,
                v.name as volunteer_id,
                v.email as volunteer_email,
                v.volunteer_name
            FROM `tabEmployee` e
            LEFT JOIN `tabVolunteer` v ON v.employee_id = e.name
            WHERE e.user_id IS NULL OR e.user_id = ''
            AND v.name IS NOT NULL
        """,
            as_dict=True,
        )

        fixed_count = 0
        errors = []

        for record in employees_without_users:
            try:
                # Determine which email to use
                email = record.volunteer_email or record.personal_email or record.company_email
                if not email:
                    errors.append(f"No email found for volunteer {record.volunteer_id}")
                    continue

                # Check if user exists
                existing_user = frappe.db.get_value("User", {"email": email}, "name")

                if existing_user:
                    # Link existing user
                    if update_employee_with_user(record.employee_id, existing_user):
                        fixed_count += 1
                else:
                    # Create new user
                    volunteer_doc = frappe.get_doc("Volunteer", record.volunteer_id)
                    user_id = create_user_for_volunteer(volunteer_doc)
                    if user_id and update_employee_with_user(record.employee_id, user_id):
                        fixed_count += 1

            except Exception as e:
                errors.append(f"Error processing employee {record.employee_id}: {str(e)}")

        return {
            "success": True,
            "fixed_count": fixed_count,
            "total_processed": len(employees_without_users),
            "errors": errors,
        }

    except Exception as e:
        frappe.log_error(f"Error fixing employee user links: {str(e)}")
        return {"success": False, "error": str(e)}


def enhanced_create_minimal_employee(volunteer_doc):
    """Enhanced version of create_minimal_employee that includes user creation"""
    try:
        # First create the employee using the existing method
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id and volunteer_doc.email:
            # Create or link user
            user_id = create_user_for_volunteer(volunteer_doc)
            if user_id:
                update_employee_with_user(employee_id, user_id)

        return employee_id

    except Exception as e:
        frappe.log_error(f"Error in enhanced employee creation: {str(e)}")
        raise


def _create_user_via_account_creation_manager(volunteer_doc):
    """Create user via secure AccountCreationManager when direct permissions insufficient"""
    try:
        from verenigingen.utils.account_creation_manager import AccountCreationManager
        from verenigingen.utils.secure_context_manager import get_creation_user, secure_user_context

        # Create account creation request with secure context
        with secure_user_context(
            get_creation_user(), f"volunteer_account_creation_{volunteer_doc.name}"
        ) as ctx:
            request_doc = frappe.get_doc(
                {
                    "doctype": "Account Creation Request",
                    "request_type": "Volunteer",
                    "source_record": volunteer_doc.name,
                    "email": volunteer_doc.email,
                    "full_name": volunteer_doc.volunteer_name or f"{volunteer_doc.name} Volunteer",
                    "status": "Queued",
                    "justification": "Volunteer user account creation via employee workflow",
                    "requested_by": frappe.session.user,
                }
            )

            # Add required roles for volunteers (check availability)
            available_roles = [r.name for r in frappe.get_all("Role", fields=["name"])]

            if "Employee" in available_roles:
                request_doc.append("requested_roles", {"role": "Employee"})
            if "Verenigingen Volunteer" in available_roles:
                request_doc.append("requested_roles", {"role": "Verenigingen Volunteer"})

            request_doc.insert()
            ctx.log_operation("account_creation_request", request_doc.name)

        # Process immediately if we have system permissions
        if frappe.session.user in ["Administrator"] or frappe.has_permission("User", "create"):
            manager = AccountCreationManager(request_doc.name)
            manager.process_complete_pipeline()
            return request_doc.created_user
        else:
            frappe.logger().info(
                f"Account creation request {request_doc.name} queued for background processing"
            )
            return None

    except Exception as e:
        safe_log_error(
            f"Error creating user via AccountCreationManager for volunteer {volunteer_doc.name}: {str(e)}"
        )
        return None
