"""
Field Synchronization Service
==============================

General-purpose bidirectional field synchronization service for maintaining
data consistency across related DocTypes.

This service provides a declarative configuration system for defining field
mappings between related DocTypes, with automatic synchronization on document
updates. It handles common challenges like infinite loop prevention, missing
records, and permission management.

Architecture:
    - Declarative field mapping configuration
    - Bidirectional synchronization support
    - Automatic infinite loop prevention
    - Relationship resolution (direct links and lookups)
    - Comprehensive error handling and logging

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
Testing utility returns OperationResult[Dict] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- test_sync_relationship: Returns OperationResult[Dict] (sync test results)

Migration Status: ✅ COMPLETE (2025-11-24)
- Test utility migrated from dict-based to OperationResult pattern
- Type-safe error handling with comprehensive test result metadata

Usage:
    This service is automatically invoked via hooks configuration.
    Field mappings are defined in FIELD_SYNC_CONFIG below.

    To add a new sync relationship:
    1. Define the mapping in FIELD_SYNC_CONFIG
    2. Register hooks in hooks.py using sync_fields()
    3. Test bidirectional sync behavior

Example:
    # In hooks.py
    doc_events = {
        "Member": {
            "on_update": "verenigingen.services.field_sync_service.sync_fields"
        },
        "User": {
            "on_update": "verenigingen.services.field_sync_service.sync_fields"
        }
    }

See: docs/patterns/OPERATION_RESULT_PATTERN.md

Author: Verenigingen Development Team
"""

from typing import Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult

# ==================== CONFIGURATION ====================

FIELD_SYNC_CONFIG = {
    "Member": {
        "User": {
            # Relationship configuration
            "link_field": "user",  # Field on Member that links to User
            "reverse_lookup": {
                "name": "{source_name}"
            },  # How to find Member from User (User.name is the primary key)
            # Field mappings: source_field -> target_field
            # NOTE: Email is excluded from Member -> User sync because User.email is
            # immutable (it's the username/primary key). Email changes on User should
            # be managed through User administration, not Member updates.
            "field_mappings": {
                "image": "user_image",
                "first_name": "first_name",
                "last_name": "last_name",
            },
            # Sync flag to prevent infinite loops
            "sync_flag": "syncing_member_user_fields",
        }
    },
    "User": {
        "Member": {
            # Reverse relationship
            "lookup_method": lambda doc: frappe.db.get_value("Member", {"user": doc.name}, "name"),
            # Field mappings: source_field -> target_field
            "field_mappings": {
                "user_image": "image",
                "email": "email",
                "first_name": "first_name",
                "last_name": "last_name",
            },
            # Sync flag (same as forward sync)
            "sync_flag": "syncing_member_user_fields",
        }
    },
    # Future mappings can be added here:
    # "Donor": {
    #     "Customer": { ... }
    # },
}


# ==================== CORE SERVICE ====================


def sync_fields(doc, method=None):
    """
    Main entry point for field synchronization.

    This function is called by document hooks and automatically syncs
    configured fields to related DocTypes.

    Args:
        doc: Source document being saved/updated
        method: Hook method name (not used)
    """
    source_doctype = doc.doctype

    # Check if this DocType has any sync configurations
    if source_doctype not in FIELD_SYNC_CONFIG:
        return

    # Process each target DocType configured for this source
    for target_doctype, config in FIELD_SYNC_CONFIG[source_doctype].items():
        try:
            _sync_to_target(doc, target_doctype, config)
        except Exception as e:
            # Log error but don't block the source document save
            frappe.log_error(
                f"Failed to sync {source_doctype} -> {target_doctype}: {str(e)}", "Field Sync Error"
            )


def _sync_to_target(source_doc, target_doctype: str, config: Dict):
    """
    Sync fields from source document to target document.

    Args:
        source_doc: Source document
        target_doctype: Target DocType name
        config: Sync configuration for this relationship
    """
    sync_flag = config.get("sync_flag")

    # Prevent infinite loops
    if sync_flag and frappe.flags.get(sync_flag):
        return

    # Find target document
    target_name = _find_target_document(source_doc, target_doctype, config)
    if not target_name:
        # No related record found - this is normal
        return

    # Check if any configured fields have changed
    changed_fields = _get_changed_fields(source_doc, config["field_mappings"])
    if not changed_fields:
        # No relevant fields changed
        return

    # Perform the sync
    try:
        # Set sync flag to prevent infinite loops
        if sync_flag:
            frappe.flags[sync_flag] = True

        # Get target document
        target_doc = frappe.get_doc(target_doctype, target_name)

        # Update fields
        for source_field, target_field in changed_fields.items():
            source_value = getattr(source_doc, source_field, None)
            setattr(target_doc, target_field, source_value)

        # Save target document
        target_doc.save(ignore_permissions=True)

        # Log success
        field_names = ", ".join(changed_fields.keys())
        frappe.logger().info(
            f"Synced fields [{field_names}] from {source_doc.doctype} {source_doc.name} "
            f"to {target_doctype} {target_name}"
        )

    finally:
        # Always clear sync flag
        if sync_flag:
            frappe.flags[sync_flag] = False


def _find_target_document(source_doc, target_doctype: str, config: Dict) -> Optional[str]:
    """
    Find the related target document name.

    Supports three methods:
    1. Direct link field on source document
    2. Reverse lookup using filters
    3. Custom lookup method

    Args:
        source_doc: Source document
        target_doctype: Target DocType name
        config: Sync configuration

    Returns:
        Target document name or None if not found
    """
    # Method 1: Direct link field
    if "link_field" in config:
        link_field = config["link_field"]
        target_name = getattr(source_doc, link_field, None)
        if target_name:
            return target_name

    # Method 2: Reverse lookup with filters
    if "reverse_lookup" in config:
        filters = config["reverse_lookup"].copy()
        # Replace {source_name} placeholder with actual name
        for key, value in filters.items():
            if isinstance(value, str) and "{source_name}" in value:
                filters[key] = value.replace("{source_name}", source_doc.name)

        target_name = frappe.db.get_value(target_doctype, filters, "name")
        if target_name:
            return target_name

    # Method 3: Custom lookup method
    if "lookup_method" in config:
        lookup_fn = config["lookup_method"]
        if callable(lookup_fn):
            target_name = lookup_fn(source_doc)
            if target_name:
                return target_name

    return None


def _get_changed_fields(doc, field_mappings: Dict[str, str]) -> Dict[str, str]:
    """
    Get only the fields that have actually changed.

    Args:
        doc: Document being saved
        field_mappings: Dictionary of source_field -> target_field mappings

    Returns:
        Dictionary of changed source_field -> target_field mappings
    """
    changed = {}

    for source_field, target_field in field_mappings.items():
        # Check if field exists on document
        if not hasattr(doc, source_field):
            continue

        # Check if field has changed
        if hasattr(doc, "has_value_changed") and doc.has_value_changed(source_field):
            changed[source_field] = target_field

    return changed


# ==================== UTILITY FUNCTIONS ====================


def get_sync_config(source_doctype: str, target_doctype: str) -> Optional[Dict]:
    """
    Get sync configuration for a specific DocType pair.

    Args:
        source_doctype: Source DocType name
        target_doctype: Target DocType name

    Returns:
        Configuration dictionary or None
    """
    return FIELD_SYNC_CONFIG.get(source_doctype, {}).get(target_doctype)


def is_sync_configured(source_doctype: str, target_doctype: str) -> bool:
    """
    Check if sync is configured for a DocType pair.

    Args:
        source_doctype: Source DocType name
        target_doctype: Target DocType name

    Returns:
        True if sync is configured
    """
    return get_sync_config(source_doctype, target_doctype) is not None


def add_sync_config(source_doctype: str, target_doctype: str, config: Dict):
    """
    Dynamically add sync configuration at runtime.

    Args:
        source_doctype: Source DocType name
        target_doctype: Target DocType name
        config: Sync configuration dictionary
    """
    if source_doctype not in FIELD_SYNC_CONFIG:
        FIELD_SYNC_CONFIG[source_doctype] = {}

    FIELD_SYNC_CONFIG[source_doctype][target_doctype] = config

    frappe.logger().info(f"Added sync configuration: {source_doctype} -> {target_doctype}")


# ==================== TESTING UTILITIES ====================


def test_sync_relationship(
    source_doctype: str, source_name: str, target_doctype: str, field_to_test: str, test_value: str
) -> OperationResult[Dict]:
    """
    Test a sync relationship by updating a field and verifying sync.

    Args:
        source_doctype: Source DocType name
        source_name: Source document name
        target_doctype: Target DocType name
        field_to_test: Field name to test sync on
        test_value: Test value to set

    Returns:
        OperationResult[Dict]: Test results with metadata:
            - source_field: Field tested on source
            - target_field: Corresponding field on target
            - test_value: Value set for testing
            - actual_value: Actual value found on target
            - target_document: Target document name

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - All errors logged and returned as OperationResult.fail()
    """
    try:
        # Get config
        config = get_sync_config(source_doctype, target_doctype)
        if not config:
            return OperationResult.fail(
                f"No sync config for {source_doctype} -> {target_doctype}",
                errors=["Missing sync configuration"],
                source_doctype=source_doctype,
                target_doctype=target_doctype,
            )

        # Get source document
        source_doc = frappe.get_doc(source_doctype, source_name)

        # Find target document
        target_name = _find_target_document(source_doc, target_doctype, config)
        if not target_name:
            return OperationResult.fail(
                f"No related {target_doctype} found for {source_doctype} {source_name}",
                errors=["Target document not found"],
                source_doctype=source_doctype,
                source_name=source_name,
                target_doctype=target_doctype,
            )

        # Update field
        setattr(source_doc, field_to_test, test_value)
        source_doc.save()
        frappe.db.commit()

        # Check if target was updated
        target_doc = frappe.get_doc(target_doctype, target_name)
        target_field = config["field_mappings"].get(field_to_test)
        target_value = getattr(target_doc, target_field, None)

        sync_success = target_value == test_value
        result_data = {
            "source_field": field_to_test,
            "target_field": target_field,
            "test_value": test_value,
            "actual_value": target_value,
            "target_document": target_name,
        }

        if sync_success:
            return OperationResult.ok(
                result_data, message=f"Sync test passed: {field_to_test} = {test_value}"
            )
        else:
            return OperationResult.fail(
                f"Sync test failed: expected {test_value}, got {target_value}",
                errors=["Value mismatch after sync"],
                **result_data,
            )

    except Exception as e:
        return OperationResult.fail(
            f"Error testing sync relationship: {str(e)}",
            errors=[str(e)],
            source_doctype=source_doctype,
            source_name=source_name,
            target_doctype=target_doctype,
        )
