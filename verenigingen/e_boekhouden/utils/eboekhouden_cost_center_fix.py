"""
Fix for E-Boekhouden cost center migration with proper parent-child relationships
"""

import json

import frappe


def migrate_cost_centers_with_hierarchy(settings):
    """
    Migrate cost centers with proper parent-child hierarchy
    """
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        # Get Cost Centers data
        api = EBoekhoudenAPI(settings)
        result = api.get_cost_centers()

        if not result["success"]:
            return {"success": False, "error": f"Failed to fetch Cost Centers: {result['error']}"}

        # Parse JSON response
        data = json.loads(result["data"])
        cost_centers_data = data.get("items", [])

        if not cost_centers_data:
            return {"success": True, "message": "No cost centers to migrate"}

        company = settings.default_company
        if not company:
            return {"success": False, "error": "No default company set"}

        # Get or create root cost center
        root_cc = ensure_root_cost_center(company)
        if not root_cc:
            return {"success": False, "error": "Could not create root cost center"}

        # Build parent-child relationships first
        parent_map = {}  # Maps E-Boekhouden ID to its parent ID
        root_level_ccs = []  # Cost centers with no parent
        has_children = set()  # Track which cost centers have children

        for cc_data in cost_centers_data:
            cc_id = cc_data.get("id")
            parent_id = cc_data.get("parentId", 0) or 0

            if cc_id:
                if parent_id > 0:
                    parent_map[cc_id] = parent_id
                    has_children.add(parent_id)  # Parent has at least one child
                else:
                    root_level_ccs.append(cc_id)

        # Sort cost centers to create parents before children
        def get_depth(cc_id, depth=0):
            """Get depth of cost center in hierarchy"""
            if cc_id in root_level_ccs:
                return 0
            parent_id = parent_map.get(cc_id)
            if not parent_id or parent_id not in parent_map:
                return depth
            return get_depth(parent_id, depth + 1)

        # Sort by depth (parents first) then by ID
        sorted_cost_centers = sorted(
            cost_centers_data, key=lambda cc: (get_depth(cc.get("id", 0)), cc.get("id", 0))
        )

        # Create mapping of e-boekhouden ID to ERPNext cost center name
        id_to_name_map = {}
        created_count = 0
        skipped_count = 0
        errors = []

        # Create all cost centers with proper hierarchy
        for cc_data in sorted_cost_centers:
            try:
                # Get parent for this cost center
                cc_id = cc_data.get("id")
                parent_id = cc_data.get("parentId", 0) or 0

                # Determine ERPNext parent
                if parent_id > 0 and parent_id in id_to_name_map:
                    # Use the already created parent
                    erpnext_parent = id_to_name_map[parent_id]
                else:
                    # Use root cost center
                    erpnext_parent = root_cc

                result = create_cost_center_safe(
                    cc_data, company, erpnext_parent, id_to_name_map, has_children
                )

                if result["success"]:
                    created_count += 1
                    # Store mapping
                    if cc_id:
                        id_to_name_map[cc_id] = result["name"]
                elif result.get("exists"):
                    skipped_count += 1
                    # Still store mapping for existing cost centers
                    if cc_id:
                        id_to_name_map[cc_id] = result["name"]
                else:
                    cc_info = f"Code: {cc_data.get('code', 'N/A')}, Name: {cc_data.get('name', 'N/A')}, ID: {cc_data.get('id', 'N/A')}"
                    errors.append(f"{cc_info}: {result.get('error', 'Unknown error')}")

            except Exception as e:
                cc_info = f"Code: {cc_data.get('code', 'N/A')}, Name: {cc_data.get('name', 'N/A')}, ID: {cc_data.get('id', 'N/A')}"
                errors.append(f"{cc_info}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "created": created_count,
            "skipped": skipped_count,
            "errors": errors,
            "total": len(cost_centers_data),
            "message": f"Created {created_count} cost centers, skipped {skipped_count}",
        }

    except Exception as e:
        frappe.log_error(f"Cost center migration error: {str(e)}", "E-Boekhouden")
        return {"success": False, "error": str(e)}


def create_cost_center_safe(cc_data, company, parent_cc, id_map, has_children=None):
    """
    Create a single cost center with guaranteed valid parent
    """
    if has_children is None:
        has_children = set()
    try:
        cc_code = str(cc_data.get("code", "")).strip()
        cc_name = cc_data.get("name", "").strip()
        cc_description = cc_data.get("description", "").strip()
        cc_id = cc_data.get("id", "")

        # Try to use name, then description, then create from ID
        if not cc_name:
            if cc_description:
                cc_name = cc_description
            elif cc_id:
                cc_name = f"Cost Center {cc_id}"
            else:
                return {"success": False, "error": "No cost center name, description, or ID"}

        # Create full name with code if available
        if cc_code:
            full_cc_name = f"{cc_code} - {cc_name}"
        else:
            full_cc_name = cc_name

        # Check if already exists
        existing = frappe.db.get_value(
            "Cost Center",
            {"cost_center_name": full_cc_name, "company": company},
            ["name", "is_group"],
            as_dict=True,
        )

        if existing:
            # Check if this existing cost center needs to be updated to a group
            cc_id = cc_data.get("id")
            if cc_id and cc_id in has_children and not existing.is_group:
                # Update to group
                try:
                    frappe.db.set_value("Cost Center", existing.name, "is_group", 1)
                    frappe.db.commit()
                    frappe.logger().info(f"Updated cost center {existing.name} to group")
                except Exception as e:
                    frappe.logger().error(f"Failed to update cost center {existing.name} to group: {str(e)}")

            return {"success": False, "exists": True, "name": existing.name}

        # Ensure parent exists and is valid
        if parent_cc:
            parent_exists = frappe.db.exists("Cost Center", parent_cc)
            if not parent_exists:
                frappe.logger().warning(f"Parent {parent_cc} not found, using root")
                parent_cc = ensure_root_cost_center(company)

        # Create cost center
        cc = frappe.new_doc("Cost Center")
        cc.cost_center_name = full_cc_name
        cc.company = company
        cc.parent_cost_center = parent_cc

        # Check if this cost center has children (is a parent/group)
        cc_id = cc_data.get("id")
        if cc_id and cc_id in has_children:
            cc.is_group = 1  # This is a parent/group cost center
        else:
            cc.is_group = 0  # This is a leaf cost center

        # Add custom field to track e-boekhouden ID
        if hasattr(cc, "eboekhouden_id"):
            cc.eboekhouden_id = cc_data.get("id")

        cc.insert(ignore_permissions=True)

        return {"success": True, "name": cc.name}

    except Exception as e:
        return {"success": False, "error": str(e)}


def ensure_root_cost_center(company):
    """
    Ensure root cost center exists for the company
    """
    # Try to find existing root
    root_cc = frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]}, "name"
    )

    if root_cc:
        return root_cc

    # Try company abbreviation pattern
    abbr = frappe.db.get_value("Company", company, "abbr")
    if abbr:
        pattern_cc = f"{company} - {abbr}"
        if frappe.db.exists("Cost Center", pattern_cc):
            return pattern_cc

    # Try to find a cost center with name equal to company
    company_cc = frappe.db.get_value("Cost Center", {"cost_center_name": company, "company": company}, "name")

    if company_cc:
        return company_cc

    # Create root cost center if not found
    try:
        cc = frappe.new_doc("Cost Center")
        # IMPORTANT: For root cost centers, the name must equal the company name
        # to bypass the parent validation in ERPNext
        cc.cost_center_name = company
        cc.company = company
        cc.is_group = 1
        cc.parent_cost_center = ""

        # Try to insert, if it fails due to duplicate, find the existing one
        try:
            cc.insert(ignore_permissions=True)
            frappe.logger().info(f"Created root cost center for company: {company}")
            return cc.name
        except frappe.DuplicateEntryError:
            # If duplicate, find the existing one
            existing = frappe.db.get_value(
                "Cost Center", {"cost_center_name": company, "company": company}, "name"
            )
            if existing:
                return existing
            raise

    except Exception as e:
        frappe.log_error(f"Could not create root cost center: {str(e)}", "E-Boekhouden")

        # As a last resort, try to find ANY group cost center for this company
        any_group = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 1}, "name", order_by="creation asc"
        )

        if any_group:
            frappe.logger().warning(f"Using existing group cost center {any_group} as root for {company}")
            return any_group

        return None


@frappe.whitelist()
def add_eboekhouden_id_field():
    """Add custom field to track e-boekhouden cost center IDs"""
    if not frappe.db.has_column("Cost Center", "eboekhouden_id"):
        custom_field = frappe.new_doc("Custom Field")
        custom_field.dt = "Cost Center"
        custom_field.label = "E-Boekhouden ID"
        custom_field.fieldname = "eboekhouden_id"
        custom_field.fieldtype = "Data"
        custom_field.insert_after = "disabled"
        custom_field.insert(ignore_permissions=True)
        return {"success": True, "message": "Field added"}
    return {"success": True, "message": "Field already exists"}


@frappe.whitelist()
def fix_cost_center_groups(company):
    """
    Fix cost centers that should be groups based on having children
    """
    try:
        # Find all cost centers that have children but are not marked as groups
        non_group_parents = frappe.db.sql(
            """
            SELECT DISTINCT parent.name, parent.cost_center_name
            FROM `tabCost Center` parent
            INNER JOIN `tabCost Center` child ON child.parent_cost_center = parent.name
            WHERE parent.company = %s
            AND parent.is_group = 0
        """,
            company,
            as_dict=True,
        )

        fixed_count = 0
        for cc in non_group_parents:
            try:
                frappe.db.set_value("Cost Center", cc.name, "is_group", 1)
                frappe.logger().info(f"Fixed cost center {cc.name} ({cc.cost_center_name}) - set as group")
                fixed_count += 1
            except Exception as e:
                frappe.logger().error(f"Failed to fix cost center {cc.name}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "fixed": fixed_count,
            "message": f"Fixed {fixed_count} cost centers to be groups",
        }

    except Exception as e:
        frappe.log_error(f"Error fixing cost center groups: {str(e)}", "E-Boekhouden")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_cost_centers(company):
    """
    Clean up cost centers with missing parent references
    """
    try:
        # First ensure we have a proper root cost center
        root_cc = ensure_root_cost_center(company)
        if not root_cc:
            return {"success": False, "error": "Could not create root cost center"}

        # Find all cost centers with empty parent_cost_center (excluding the root)
        orphaned_ccs = frappe.db.get_all(
            "Cost Center",
            filters={"company": company, "parent_cost_center": ["in", ["", None]], "name": ["!=", root_cc]},
            fields=["name", "cost_center_name"],
        )

        fixed_count = 0
        errors = []

        for cc in orphaned_ccs:
            try:
                # Set the root as parent for orphaned cost centers
                frappe.db.set_value("Cost Center", cc.name, "parent_cost_center", root_cc)
                fixed_count += 1
                frappe.logger().info(f"Fixed orphaned cost center: {cc.cost_center_name}")
            except Exception as e:
                errors.append(f"{cc.cost_center_name}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "fixed": fixed_count,
            "errors": errors,
            "message": f"Fixed {fixed_count} orphaned cost centers",
        }

    except Exception as e:
        frappe.log_error(f"Cost center cleanup error: {str(e)}", "E-Boekhouden")
        return {"success": False, "error": str(e)}
