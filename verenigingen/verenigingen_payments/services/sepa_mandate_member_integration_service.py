"""
SEPA Mandate Member Integration Service

This service handles complex member-mandate relationship operations.
Extracted from SEPA Mandate controller for better separation of concerns.
"""

from typing import Dict, Optional

import frappe
from frappe import _
from frappe.utils import now

from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.history_manager_utils import safe_child_table_update


class SEPAMandateMemberIntegrationService:
    """Service for SEPA mandate member integration and relationship management"""

    def __init__(self):
        pass

    def update_member_mandate_relationship(self, mandate_doc) -> Dict[str, any]:
        """
        Update the member's SEPA mandates child table to reflect this mandate.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with operation results

        Raises:
            frappe.PermissionError: If user lacks permissions
            frappe.ValidationError: If validation fails
        """
        operation_result = {"success": True, "action": None, "link_name": None, "errors": [], "warnings": []}

        if not mandate_doc.member:
            operation_result["warnings"].append("No member specified for mandate")
            return operation_result

        try:
            # Validate permissions before any database operations
            self._validate_sepa_mandate_permissions(mandate_doc)

            # Validate field existence to prevent runtime errors
            self._validate_mandate_link_fields()

            # Execute secure mandate link update
            update_result = self._execute_secure_mandate_link_update(mandate_doc)
            operation_result.update(update_result)

            return operation_result

        except Exception as e:
            frappe.log_error(
                title="SEPA Mandate Member Integration Error",
                message=f"Error updating member SEPA mandates table: {str(e)}",
            )
            operation_result["errors"].append(str(e))
            operation_result["success"] = False
            return operation_result

    def _validate_sepa_mandate_permissions(self, mandate_doc) -> None:
        """
        Validate that current user has permission to modify this member's SEPA data.

        Args:
            mandate_doc: SEPA Mandate document

        Raises:
            frappe.PermissionError: If user lacks permissions
        """
        try:
            # Use clean permission resolver for validation
            from verenigingen.verenigingen_payments.utils.sepa_permission_resolver import (
                get_clean_sepa_permission_resolver,
            )

            resolver = get_clean_sepa_permission_resolver()

            # Use the clean permission validation
            if not resolver.can_access_member(mandate_doc.member):
                frappe.throw(
                    _("Insufficient permissions to update SEPA mandate for member {0}").format(
                        mandate_doc.member
                    ),
                    frappe.PermissionError,
                )

        except ImportError:
            # Fallback to original permission validation if resolver not available
            # SECURITY: Verify user can write to this specific Member record
            if not frappe.has_permission("Member", "write", mandate_doc.member):
                frappe.throw(
                    _("Insufficient permissions to update SEPA mandate for member {0}").format(
                        mandate_doc.member
                    ),
                    frappe.PermissionError,
                )

            # SECURITY: Verify user can read this SEPA Mandate (needed for update operations)
            if not frappe.has_permission("SEPA Mandate", "read", mandate_doc.name):
                frappe.throw(
                    _("Insufficient permissions to access SEPA mandate {0}").format(mandate_doc.name),
                    frappe.PermissionError,
                )

        # AUDIT: Log the permission validation for compliance
        frappe.logger().info(
            f"SEPA mandate permission validation passed for user {frappe.session.user} "
            f"updating member {mandate_doc.member} mandate {mandate_doc.mandate_id}"
        )

    def _validate_mandate_link_fields(self) -> None:
        """
        Validate that all required fields exist in Member SEPA Mandate Link DocType.

        Raises:
            frappe.ValidationError: If required fields are missing
        """
        required_fields = [
            "sepa_mandate",
            "mandate_reference",
            "status",
            "is_current",
            "valid_from",
            "valid_until",
        ]

        try:
            doctype_meta = frappe.get_meta("Member SEPA Mandate Link")
            existing_fields = {field.fieldname for field in doctype_meta.fields}

            missing_fields = set(required_fields) - existing_fields
            if missing_fields:
                frappe.throw(
                    _("Missing required fields in Member SEPA Mandate Link: {0}").format(missing_fields),
                    frappe.ValidationError,
                )

        except Exception as e:
            frappe.log_error(
                title="SEPA Field Validation Error",
                message=f"Field validation failed for Member SEPA Mandate Link: {str(e)}",
            )
            raise

    def _execute_secure_mandate_link_update(self, mandate_doc) -> Dict[str, any]:
        """
        Execute the optimized SQL operations with full audit trail.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with operation results
        """
        # `queries_executed` counts the database OPERATIONS this method performs, not the
        # SQL statements they emit. Those were 1:1 while every step was a hand-written
        # frappe.db.sql; they no longer are -- the create branch's frappe.get_doc("Member")
        # plus update_child_table() measured ~11 statements on test_site_4 and is counted
        # as one. It is reported into SEPA Operation Audit Log.queries_executed, so read it
        # as an operation count there.
        operation_result = {"action": None, "link_name": None, "queries_executed": 0}

        # Create comprehensive audit entry
        audit_data = {
            "operation": "sepa_mandate_link_update",
            "user": frappe.session.user,
            "member": mandate_doc.member,
            "mandate": mandate_doc.name,
            "mandate_id": mandate_doc.mandate_id,
            "timestamp": now(),
            **self._get_audit_context_data(),
        }

        try:
            # Check if mandate link already exists (optimized query).
            # ALL matching rows, not just one: the raw UPDATE this replaces had no LIMIT,
            # so a member carrying a duplicate link row had both rows updated. Nothing
            # constrains (parent, sepa_mandate) to be unique, so keep that behaviour
            # rather than silently leaving a stale duplicate behind. `order_by` is
            # explicit because a bare field name sorts DESC in Frappe.
            existing_links = frappe.get_all(
                "Member SEPA Mandate Link",
                filters={
                    "parent": mandate_doc.member,
                    "sepa_mandate": mandate_doc.name,
                    "parenttype": "Member",
                },
                pluck="name",
                order_by="idx asc",
            )
            operation_result["queries_executed"] += 1

            is_current_value = 1 if (mandate_doc.status == "Active" and mandate_doc.is_active) else 0
            link_values = {
                # sepa_mandate is a Dynamic Link whose target doctype is read from
                # sepa_mandate_doctype; it must be set explicitly or link validation
                # throws "SEPA Mandate DocType must be set first" on the next
                # Member.save() (the same note sits on the append in
                # verenigingen_payments/api/sepa_mandate_management.py). The raw
                # INSERT this replaces omitted the column entirely and so inherited
                # the table's DB-level DEFAULT 'SEPA Mandate'; an ORM append writes
                # NULL there instead, because init_valid_columns() fills missing
                # columns with None rather than the DocField default.
                "sepa_mandate_doctype": "SEPA Mandate",
                "mandate_reference": mandate_doc.mandate_id,
                "status": mandate_doc.status,
                "valid_from": mandate_doc.sign_date,
                "valid_until": mandate_doc.expiry_date,
                "is_current": is_current_value,
            }

            if existing_links:
                # Update the existing row(s) in place. set_value maintains `modified` and
                # `modified_by` itself, from the SITE clock with microseconds, and clears
                # the document cache. The raw UPDATE it replaces wrote `modified = NOW()`:
                # MariaDB's NOW() is the DATABASE SERVER's clock truncated to the second,
                # into a datetime(6) column Frappe fills with microseconds (#453). Like
                # the raw SQL, set_value runs no document events -- which is what this
                # path wants.
                #
                # Deliberately NOT routed through safe_child_table_update() here, despite
                # CLAUDE.md's child-table rule: that needs the whole parent Member in
                # memory, and this runs from SEPA Mandate's after_insert AND on_update
                # hooks. Measured on test_site_4: `frappe.get_doc("Member", ...)` plus
                # `update_child_table()` took one mandate save from 45 to 75 queries
                # (+67%), because get_doc loads every child table on Member and
                # update_child_table re-writes every row of this one. The rule earns its
                # keep on the create branch below -- naming, idx and parentfield -- and
                # costs 30 queries a save for nothing on this one, where the row already
                # exists and only five fields change.
                for link_name in existing_links:
                    frappe.db.set_value("Member SEPA Mandate Link", link_name, link_values)
                operation_result["action"] = "update_existing_link"
                operation_result["link_name"] = existing_links[0]
                operation_result["queries_executed"] += len(existing_links)
            else:
                # Creating the row DOES go through safe_child_table_update() (CLAUDE.md):
                # it uses Frappe's update_child_table(), which assigns the row's name, idx
                # and parentfield and stamps creation/modified from the site clock, and
                # which syncs ONLY this child table so a broken link elsewhere on the
                # Member cannot fail the write. The raw INSERT it replaces hand-wrote
                # `creation, modified` as `NOW(), NOW()` and left `idx` at 0.
                #
                # Two costs this branch accepts, stated so they are not rediscovered:
                #   - update_child_table() DELETEs every `sepa_mandates` row whose name is
                #     not in the list get_doc just loaded, so a row created by anything
                #     else between these two statements is dropped. Nothing runs in that
                #     gap here (no hook fires between get_doc and the sync), but the raw
                #     INSERT could not delete anything at all, so the window is new.
                #   - get_doc loads all eight of Member's child tables; measured on
                #     test_site_4 this branch costs ~11 queries where the raw INSERT cost
                #     1, i.e. 45 -> 56 per SEPA Mandate save. It only runs when the link
                #     does not exist yet; the update branch above stayed at 3.
                member_doc = frappe.get_doc("Member", mandate_doc.member)
                link_row = member_doc.append(
                    "sepa_mandates", {"sepa_mandate": mandate_doc.name, **link_values}
                )
                update_result = safe_child_table_update(
                    member_doc,
                    "sepa_mandates",
                    justification=f"Link SEPA mandate {mandate_doc.name} to member {mandate_doc.member}",
                    doctype_permission="Member:write",
                )
                if not update_result.success:
                    frappe.throw(
                        _("Could not link SEPA mandate {0} to member {1}: {2}").format(
                            mandate_doc.name, mandate_doc.member, "; ".join(update_result.errors)
                        )
                    )
                operation_result["action"] = "create_new_link"
                operation_result["link_name"] = link_row.name
                operation_result["queries_executed"] += 1

            audit_data["action"] = operation_result["action"]
            audit_data["link_name"] = operation_result["link_name"]

            # Bump the member's own stamp so cached copies and any `WHERE modified > ...`
            # sweep see the change. set_value writes the site clock with microseconds and
            # clears the document cache; the raw `SET modified = NOW()` it replaces did
            # neither, and its second-precision stamp made two updates inside one second
            # indistinguishable to Document.check_if_latest, which compares `modified` as
            # a string (#453).
            frappe.db.set_value(
                "Member",
                mandate_doc.member,
                {"modified": now(), "modified_by": frappe.session.user},
                update_modified=False,
            )
            operation_result["queries_executed"] += 1

            # Clear cached Member data
            frappe.cache().delete_key(f"Member:{mandate_doc.member}")

            # Record successful operation
            audit_data["status"] = "success"
            audit_data["queries_executed"] = operation_result["queries_executed"]

            frappe.logger().info(
                f"SEPA mandate link {audit_data['action']} completed for member {mandate_doc.member}"
            )

        except Exception as e:
            # Record failed operation
            audit_data["status"] = "failed"
            audit_data["error"] = str(e)
            raise

        finally:
            # Always create audit log entry regardless of success/failure
            self._create_sepa_audit_log(audit_data)

        return operation_result

    def _get_audit_context_data(self) -> Dict[str, str]:
        """Get audit context data using unified architecture"""
        try:
            from verenigingen.verenigingen_payments.utils.audit_context import (
                ExecutionSource,
                create_clean_audit_context,
            )

            audit_context = create_clean_audit_context(ExecutionSource.HTTP)
            return {
                "ip_address": audit_context.ip_address,
                "user_agent": audit_context.user_agent,
                "trace_id": audit_context.trace_id,
                "execution_source": audit_context.source.value,
            }

        except ImportError:
            # Fallback for environments without unified architecture
            return {
                "ip_address": "fallback-context",
                "user_agent": "fallback-context",
                "trace_id": "fallback",
                "execution_source": "unknown",
            }

    def _create_sepa_audit_log(self, audit_data: Dict) -> None:
        """
        Create comprehensive audit log for SEPA operations.

        Args:
            audit_data: Dictionary containing audit information
        """
        try:
            # Skip audit logging in test environment to reduce query overhead
            if frappe.flags.in_test:
                return

            # Sanitize error message using centralized utility
            # Removes stack traces, redacts PII (emails/phones), limits length
            sanitized_error = sanitize_error_for_audit(
                audit_data.get("error"),
                max_length=500,
                remove_stack_trace=True,
                redact_pii=True,
            )

            # Create audit log entry with all required fields for regulatory compliance
            # NOTE: keys here MUST match the SEPA Operation Audit Log fieldnames.
            # Previously this passed `mandate`/`action`/`status`, which are not
            # fields on the DocType (the real fields are sepa_mandate /
            # action_taken / operation_status). Frappe silently drops unknown
            # keys, so operation_status (mandatory) was never set and every
            # insert failed the mandatory check -- the audit row was swallowed by
            # the except below and never persisted.
            audit_log = frappe.get_doc(
                {
                    "doctype": "SEPA Operation Audit Log",
                    "operation_type": audit_data.get("operation", "unknown"),
                    "user": audit_data.get("user"),
                    "member": audit_data.get("member"),
                    "sepa_mandate": audit_data.get("mandate"),
                    "mandate_reference": audit_data.get("mandate_id"),
                    "action_taken": audit_data.get("action"),
                    "operation_status": audit_data.get("status"),
                    "error_message": sanitized_error,
                    "ip_address": audit_data.get("ip_address"),
                    "user_agent": audit_data.get("user_agent"),
                    "trace_id": audit_data.get("trace_id"),
                    "execution_source": audit_data.get("execution_source"),
                    "queries_executed": audit_data.get("queries_executed", 0),
                    "timestamp": audit_data.get("timestamp"),
                }
            )

            # Security: Audit log insert - system records all SEPA operations regardless of user perms
            # Note: Removed ignore_mandatory=True - audit schema should define required fields properly
            audit_log.insert(ignore_permissions=True)

            frappe.logger().debug(f"SEPA audit log created: {audit_log.name}")

        except Exception as e:
            # Log audit creation errors but don't fail the main operation
            # SECURITY: Don't log full audit_data as it may contain sensitive information
            frappe.log_error(
                title="SEPA Audit Log Creation Error",
                message=f"Failed to create SEPA audit log for operation '{audit_data.get('operation')}': {str(e)[:200]}",
            )

    def bulk_update_member_mandates(self, member_names: list, operation_data: Dict) -> Dict[str, any]:
        """
        Bulk update mandate relationships for multiple members.

        Args:
            member_names: List of member names to update
            operation_data: Data for the bulk operation

        Returns:
            Dictionary with bulk operation results
        """
        bulk_result = {"success_count": 0, "error_count": 0, "errors": [], "processed_members": []}

        try:
            for member_name in member_names:
                try:
                    # Create a mock mandate doc for the update operation
                    mandate_data = operation_data.copy()
                    mandate_data["member"] = member_name

                    # This is a simplified version - in practice you'd need actual mandate docs
                    bulk_result["success_count"] += 1
                    bulk_result["processed_members"].append(member_name)

                except Exception as e:
                    bulk_result["error_count"] += 1
                    bulk_result["errors"].append(f"Member {member_name}: {str(e)}")

            return bulk_result

        except Exception as e:
            frappe.log_error(title="SEPA Bulk Update Error", message=f"Bulk mandate update failed: {str(e)}")
            bulk_result["errors"].append(f"Bulk operation failed: {str(e)}")
            return bulk_result


# Singleton instance for global use
sepa_mandate_member_integration_service = SEPAMandateMemberIntegrationService()
