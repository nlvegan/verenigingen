# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

"""
Account Hierarchy Service

Provides functionality for reorganizing ERPNext account hierarchy based on
eBoekhouden group type mappings. Handles both account type classification
and taxonomical grouping (parent-child relationships).
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def derive_group_code(account_number):
    """Derive the group code from an account number.

    E-Boekhouden accounts use a hierarchical numbering system where
    the first 3 digits typically represent the group.

    Examples:
        "0060" -> "006"
        "10460" -> "104"
        "8000" -> "800"
        "55" -> "055" (padded)

    Args:
        account_number: The account number string

    Returns:
        str: The 3-digit group code, or None if cannot be derived
    """
    if not account_number:
        return None

    # Clean up the account number
    account_number = str(account_number).strip()

    # Remove any non-numeric characters
    numeric_only = "".join(c for c in account_number if c.isdigit())

    if not numeric_only:
        return None

    # Take first 3 digits, padding with zeros if needed
    if len(numeric_only) < 3:
        return numeric_only.zfill(3)

    return numeric_only[:3]


def get_group_type_mappings_dict(settings=None):
    """Get group type mappings as a dict from settings.

    Args:
        settings: E-Boekhouden Settings doc. If None, will fetch from database.

    Returns:
        dict: {group_code: {"group_name": str, "root_type": str, "account_type": str}}
    """
    if settings is None:
        settings = frappe.get_single("E-Boekhouden Settings")

    mappings = {}
    for row in settings.get("group_type_mappings", []):
        if row.group_code and row.group_name and row.root_type:
            mappings[row.group_code] = {
                "group_name": row.group_name,
                "root_type": row.root_type,
                "account_type": row.account_type or "",
            }
    return mappings


def find_or_create_group_account(
    group_code, group_name, root_type, company, dry_run=False,
    created_groups=None, groups_created=None
):
    """Find or create a group account for the given group code.

    Args:
        group_code: The group code (e.g., "001")
        group_name: The group name (e.g., "Vaste activa")
        root_type: The root type (Asset, Liability, etc.)
        company: The company name
        dry_run: If True, don't actually create
        created_groups: Dict to track already created groups (cache)
        groups_created: List to append created group info

    Returns:
        The account name of the group account, or None if not found/created.
    """
    if created_groups is None:
        created_groups = {}
    if groups_created is None:
        groups_created = []

    # Check cache first
    cache_key = f"{group_code}_{root_type}"
    if cache_key in created_groups:
        return created_groups[cache_key]

    # Check if group account already exists
    existing_group = frappe.db.get_value(
        "Account",
        {"account_name": group_name, "company": company, "is_group": 1, "root_type": root_type},
        "name",
    )

    if existing_group:
        created_groups[cache_key] = existing_group
        return existing_group

    # Find the root account to be parent
    # Use SQL query because ORM doesn't handle NULL parent_account well
    root_parent = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE company = %s AND root_type = %s AND is_group = 1
        AND (parent_account IS NULL OR parent_account = '')
        LIMIT 1
        """,
        (company, root_type),
        as_dict=False,
    )
    root_parent = root_parent[0][0] if root_parent else None

    if not root_parent:
        return None

    if dry_run:
        # In dry run, return a placeholder name
        placeholder_name = f"{group_name} - {company}"
        created_groups[cache_key] = placeholder_name
        groups_created.append({
            "group_code": group_code,
            "group_name": group_name,
            "root_type": root_type,
            "parent": root_parent,
            "status": "would_create",
        })
        return placeholder_name

    # Actually create the group account
    try:
        group_account = frappe.get_doc({
            "doctype": "Account",
            "account_name": group_name,
            "company": company,
            "root_type": root_type,
            "is_group": 1,
            "parent_account": root_parent,
            "disabled": 0,
        })
        group_account.insert(ignore_permissions=True)

        created_groups[cache_key] = group_account.name
        groups_created.append({
            "group_code": group_code,
            "group_name": group_name,
            "root_type": root_type,
            "parent": root_parent,
            "account_id": group_account.name,
            "status": "created",
        })

        return group_account.name

    except Exception as e:
        frappe.logger().error(f"Error creating group account {group_code}: {e}")
        return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reorganize_account_hierarchy(dry_run=True):
    """Reorganize existing accounts into proper group hierarchy based on group_type_mappings.

    For each account with an account_number:
    1. Derives the group code from the account number (first 3 digits)
    2. Looks up the group mapping to get group_name and root_type
    3. Finds or creates the group parent account
    4. Moves the account under the correct parent if needed

    Args:
        dry_run: If True, returns preview of changes without applying them.
                 If False, actually updates the account hierarchy.

    Returns:
        dict: {
            "success": True/False,
            "dry_run": bool,
            "total_accounts": int,
            "would_move" or "moved": int,
            "groups_created": int,
            "skipped": int,
            "changes": [...],
            "groups": [...]
        }
    """
    try:
        # Convert string "true"/"false" to boolean (from JS)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() != "false"

        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured in E-Boekhouden Settings"}

        company = settings.default_company

        # Get the group type mappings (need root_type for hierarchy)
        group_type_mappings = get_group_type_mappings_dict(settings)

        if not group_type_mappings:
            return {"success": False, "error": "No group type mappings configured. Please configure mappings first using 'Parse & Suggest Types'."}

        # Get all non-group accounts with account numbers
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 0,
                "account_number": ["is", "set"],
            },
            fields=["name", "account_name", "account_number", "parent_account", "root_type"],
        )

        changes = []
        groups_created = []
        moved_count = 0
        skipped_count = 0

        # Track created groups to avoid duplicates
        created_groups = {}

        for account in accounts:
            account_number = account.account_number or ""
            group_code = derive_group_code(account_number)

            if not group_code:
                skipped_count += 1
                continue

            # Check if we have a mapping for this group
            if group_code not in group_type_mappings:
                skipped_count += 1
                continue

            mapping = group_type_mappings[group_code]
            group_name = mapping["group_name"]
            group_root_type = mapping["root_type"]

            # Find or create the group parent account
            group_account_name = find_or_create_group_account(
                group_code=group_code,
                group_name=group_name,
                root_type=group_root_type,
                company=company,
                dry_run=dry_run,
                created_groups=created_groups,
                groups_created=groups_created,
            )

            if not group_account_name:
                skipped_count += 1
                changes.append({
                    "account": account.account_number,
                    "account_name": account.account_name,
                    "group_code": group_code,
                    "status": "skipped",
                    "reason": f"Could not find/create group account for {group_code}",
                })
                continue

            # Check if account is already under the correct parent
            if account.parent_account == group_account_name:
                skipped_count += 1
                continue

            change_record = {
                "account": account.account_number,
                "account_name": account.account_name,
                "group_code": group_code,
                "old_parent": account.parent_account,
                "new_parent": group_account_name,
                "new_parent_name": group_name,
            }

            if dry_run:
                change_record["status"] = "would_move"
                moved_count += 1
            else:
                # Actually move the account
                try:
                    frappe.db.set_value(
                        "Account",
                        account.name,
                        "parent_account",
                        group_account_name,
                        update_modified=False,
                    )
                    change_record["status"] = "moved"
                    moved_count += 1
                except Exception as e:
                    change_record["status"] = "error"
                    change_record["error"] = str(e)
                    skipped_count += 1

            changes.append(change_record)

        if not dry_run:
            # Rebuild the account tree to fix lft/rgt values
            frappe.db.commit()
            try:
                from frappe.utils.nestedset import rebuild_tree
                rebuild_tree("Account", "parent_account")
            except Exception as e:
                frappe.logger().warning(f"Could not rebuild account tree: {e}")

        result_key = "would_move" if dry_run else "moved"

        return {
            "success": True,
            "dry_run": dry_run,
            "total_accounts": len(accounts),
            result_key: moved_count,
            "groups_created": len(groups_created),
            "skipped": skipped_count,
            "changes": changes,
            "groups": groups_created,
            "mappings_used": len(group_type_mappings),
        }

    except Exception as e:
        frappe.log_error(f"Error reorganizing account hierarchy: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reclassify_accounts_by_group_mappings(dry_run=True):
    """Re-classify existing ERPNext accounts based on configured group type mappings.

    Derives the group code from the account number (first 3 digits) and applies
    the configured group_type_mappings to update account_type and root_type.

    Args:
        dry_run: If True, returns preview of changes without applying them.
                 If False, actually updates the accounts.

    Returns:
        dict with success status and changes made/previewed.
    """
    try:
        # Convert string "true"/"false" to boolean (from JS)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() != "false"

        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured in E-Boekhouden Settings"}

        # Get the group type mappings
        group_type_mappings = get_group_type_mappings_dict(settings)

        if not group_type_mappings:
            return {"success": False, "error": "No group type mappings configured. Please configure mappings first using 'Parse & Suggest Types'."}

        # Get all non-group accounts with account numbers
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": settings.default_company,
                "is_group": 0,
                "account_number": ["is", "set"],
            },
            fields=["name", "account_name", "account_number", "account_type", "root_type"],
        )

        changes = []
        updated_count = 0
        skipped_count = 0

        for account in accounts:
            account_number = account.account_number or ""
            group_code = derive_group_code(account_number)

            if not group_code:
                skipped_count += 1
                continue

            # Check if we have a mapping for this group
            if group_code not in group_type_mappings:
                skipped_count += 1
                changes.append({
                    "account": account.account_number,
                    "account_name": account.account_name,
                    "group_code": group_code,
                    "old_root_type": account.root_type,
                    "old_account_type": account.account_type,
                    "new_root_type": None,
                    "new_account_type": None,
                    "status": "skipped",
                    "reason": f"No mapping for group {group_code}",
                })
                continue

            mapping = group_type_mappings[group_code]
            new_root_type = mapping.get("root_type")
            new_account_type = mapping.get("account_type", "")

            # Check if anything would change
            if account.root_type == new_root_type and account.account_type == new_account_type:
                skipped_count += 1
                continue

            change_record = {
                "account": account.account_number,
                "account_name": account.account_name,
                "group_code": group_code,
                "old_root_type": account.root_type,
                "old_account_type": account.account_type,
                "new_root_type": new_root_type,
                "new_account_type": new_account_type,
            }

            if dry_run:
                change_record["status"] = "would_update"
                updated_count += 1
            else:
                # Actually update the account
                try:
                    frappe.db.set_value(
                        "Account",
                        account.name,
                        {
                            "root_type": new_root_type,
                            "account_type": new_account_type,
                        },
                        update_modified=False,
                    )
                    change_record["status"] = "updated"
                    updated_count += 1
                except Exception as e:
                    change_record["status"] = "error"
                    change_record["error"] = str(e)
                    skipped_count += 1

            changes.append(change_record)

        if not dry_run:
            frappe.db.commit()

        result_key = "would_update" if dry_run else "updated"

        return {
            "success": True,
            "dry_run": dry_run,
            "total_accounts": len(accounts),
            result_key: updated_count,
            "skipped": skipped_count,
            "changes": changes,
            "mappings_used": len(group_type_mappings),
        }

    except Exception as e:
        frappe.log_error(f"Error reclassifying accounts: {str(e)}")
        return {"success": False, "error": str(e)}
