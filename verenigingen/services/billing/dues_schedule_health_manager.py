"""
Comprehensive Dues Schedule Health Management System

This module provides comprehensive health checking and reconstruction capabilities
for membership dues schedules, ensuring data integrity and synchronization between
Member records, Membership records, and Membership Dues Schedule records.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint


class DuesScheduleHealthManager:
    """
    Central manager for dues schedule health operations including:
    - Data reconstruction from available sources
    - Field synchronization between related DocTypes
    - Missing record creation with proper business logic
    - Integration with error recovery systems
    """

    def __init__(self):
        self.results = {
            "members_processed": 0,
            "memberships_reconstructed": 0,
            "schedules_created": 0,
            "fields_synchronized": 0,
            "errors": [],
            "actions_taken": [],
            "transaction_failures": 0,
            "batch_info": {},
        }

    def get_dues_rate_from_priority_hierarchy(self, member_name):
        """
        Get dues rate using priority hierarchy:
        1. Current dues_rate field on Member
        2. Latest entry in fee_change_history child table
        3. Active dues schedule if exists
        4. application_custom_fee from application details
        5. Membership type minimum amount as fallback
        """
        member_doc = frappe.get_doc("Member", member_name)

        # Priority 1: Current dues_rate field on Member
        if member_doc.dues_rate and member_doc.dues_rate > 0:
            return {
                "dues_rate": member_doc.dues_rate,
                "source": "member_dues_rate_field",
                "confidence": "high",
            }

        # Priority 2: Latest entry in fee_change_history
        if member_doc.fee_change_history:
            latest_fee_change = max(member_doc.fee_change_history, key=lambda x: getdate(x.change_date))
            if latest_fee_change.new_dues_rate and latest_fee_change.new_dues_rate > 0:
                return {
                    "dues_rate": latest_fee_change.new_dues_rate,
                    "source": "fee_change_history",
                    "confidence": "high",
                    "billing_frequency": latest_fee_change.billing_frequency,
                }

        # Priority 3: Active dues schedule if exists
        active_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active", "is_template": 0},
            ["dues_rate", "billing_frequency"],
            as_dict=True,
        )
        if active_schedule and active_schedule.dues_rate and active_schedule.dues_rate > 0:
            return {
                "dues_rate": active_schedule.dues_rate,
                "source": "active_dues_schedule",
                "confidence": "medium",
                "billing_frequency": active_schedule.billing_frequency,
            }

        # Priority 4: application_custom_fee from application details
        if member_doc.application_custom_fee and member_doc.application_custom_fee > 0:
            return {
                "dues_rate": member_doc.application_custom_fee,
                "source": "application_custom_fee",
                "confidence": "medium",
            }

        # Priority 5: Membership type minimum amount as fallback
        membership_type = None
        if member_doc.current_membership_plan:
            membership = frappe.db.get_value(
                "Membership", member_doc.current_membership_plan, "membership_type"
            )
            if membership:
                membership_type = membership
        elif member_doc.selected_membership_type:
            membership_type = member_doc.selected_membership_type

        if membership_type:
            min_amount = frappe.db.get_value("Membership Type", membership_type, "minimum_amount")
            if min_amount and min_amount > 0:
                return {
                    "dues_rate": min_amount,
                    "source": "membership_type_minimum",
                    "confidence": "low",
                    "membership_type": membership_type,
                }

        return {
            "dues_rate": None,
            "source": "none_found",
            "confidence": "none",
            "error": "No dues rate found in any priority source",
        }

    def reconstruct_missing_membership(self, member_name):
        """
        Reconstruct missing membership record from available data
        """
        member_doc = frappe.get_doc("Member", member_name)

        # Check if member already has active membership
        existing_membership = frappe.db.get_value(
            "Membership", {"member": member_name, "status": "Active"}, "name"
        )
        if existing_membership:
            # Update current_membership_plan if not set
            if not member_doc.current_membership_plan:
                frappe.db.set_value("Member", member_name, "current_membership_plan", existing_membership)
                self.results["fields_synchronized"] += 1
                self.results["actions_taken"].append(f"Updated current_membership_plan for {member_name}")
            return existing_membership

        # Determine membership type
        membership_type = None
        if member_doc.selected_membership_type:
            membership_type = member_doc.selected_membership_type
        elif member_doc.current_membership_type:
            membership_type = member_doc.current_membership_type

        if not membership_type:
            self.results["errors"].append(
                f"Cannot reconstruct membership for {member_name}: no membership type found"
            )
            return None

        # Create new membership
        try:
            membership = frappe.new_doc("Membership")
            membership.member = member_name
            membership.membership_type = membership_type
            membership.status = "Active"
            membership.start_date = member_doc.member_since or today()
            # Note: Membership uses autoname format, no naming_series needed

            # Use secure operation
            operation_result = secure_document_operation(
                operation="insert",
                doc=membership,
                justification=f"Reconstruct missing membership for member {member_name} - health check recovery",
                required_permissions=["Membership:create"],
            )

            if operation_result.success:
                # Update member's current_membership_plan
                frappe.db.set_value("Member", member_name, "current_membership_plan", membership.name)

                self.results["memberships_reconstructed"] += 1
                self.results["actions_taken"].append(
                    f"Reconstructed membership {membership.name} for {member_name}"
                )
                return membership.name
            else:
                self.results["errors"].append(
                    f"Failed to create membership for {member_name}: {'; '.join(operation_result.errors)}"
                )
                return None

        except Exception as e:
            self.results["errors"].append(f"Error reconstructing membership for {member_name}: {str(e)}")
            return None

    def reconstruct_dues_schedule(self, member_name):
        """
        Reconstruct missing dues schedule from available data
        """
        # Check if schedule already exists
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "status": "Active", "is_template": 0}, "name"
        )
        if existing_schedule:
            return existing_schedule

        # Get dues rate from priority hierarchy
        dues_data = self.get_dues_rate_from_priority_hierarchy(member_name)
        if not dues_data["dues_rate"]:
            self.results["errors"].append(
                f"Cannot reconstruct dues schedule for {member_name}: {dues_data.get('error', 'no dues rate found')}"
            )
            return None

        # Ensure membership exists
        membership_name = self.reconstruct_missing_membership(member_name)
        if not membership_name:
            return None

        # Get membership type
        membership_type = frappe.db.get_value("Membership", membership_name, "membership_type")
        if not membership_type:
            self.results["errors"].append(
                f"Cannot reconstruct dues schedule for {member_name}: membership has no type"
            )
            return None

        try:
            # Create dues schedule
            from verenigingen.services.billing.dues_schedule_auto_creator import (
                _calculate_next_invoice_date,
            )
            from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

            member_doc = frappe.get_doc("Member", member_name)
            dues_schedule = frappe.new_doc("Membership Dues Schedule")

            dues_schedule.schedule_name = generate_dues_schedule_name(member_name, membership_type)
            dues_schedule.member = member_name
            dues_schedule.member_name = member_doc.full_name
            dues_schedule.membership = membership_name
            dues_schedule.membership_type = membership_type
            dues_schedule.status = "Active"

            # Set billing frequency
            billing_frequency = dues_data.get("billing_frequency", "Monthly")
            dues_schedule.billing_frequency = billing_frequency

            # Set dues rate
            dues_schedule.dues_rate = dues_data["dues_rate"]
            dues_schedule.contribution_mode = "Fixed"
            dues_schedule.auto_generate = 1

            # Set next invoice date. Delegated rather than re-branched here: this
            # was a second copy of the same table and it had already drifted --
            # it was missing Semi-Annual, so a Semi-Annual schedule reconstructed
            # by the health check was billed one MONTH out instead of six.
            dues_schedule.next_invoice_date = _calculate_next_invoice_date(billing_frequency)

            dues_schedule.notes = (
                f"Reconstructed via health check on {today()} from source: {dues_data['source']}"
            )

            # Use secure operation
            operation_result = secure_document_operation(
                operation="insert",
                doc=dues_schedule,
                justification=f"Reconstruct missing dues schedule for member {member_name} - health check recovery",
                required_permissions=["Membership Dues Schedule:create"],
            )

            if operation_result.success:
                # Update member fields
                frappe.db.set_value("Member", member_name, "current_dues_schedule", dues_schedule.name)
                frappe.db.set_value("Member", member_name, "dues_rate", dues_data["dues_rate"])
                frappe.db.set_value(
                    "Member", member_name, "next_invoice_date", dues_schedule.next_invoice_date
                )

                # Add fee change history entry via the canonical writer (dedup,
                # billing-frequency validation, old_dues_rate default, 50-row cap).
                from verenigingen.services.member.history.member_fee_change_history_service import (
                    get_member_fee_change_history_service,
                )

                member_doc = frappe.get_doc("Member", member_name)
                get_member_fee_change_history_service().add_fee_change_to_history(
                    member_doc,
                    {
                        "name": dues_schedule.name,
                        "billing_frequency": billing_frequency,
                        "dues_rate": dues_data["dues_rate"],
                        "change_type": "Schedule Created",
                        "reason": f"Reconstructed from {dues_data['source']}",
                        "changed_by": frappe.session.user,
                    },
                )
                member_doc.save()

                self.results["schedules_created"] += 1
                self.results["actions_taken"].append(
                    f"Reconstructed dues schedule {dues_schedule.name} for {member_name}"
                )
                return dues_schedule.name
            else:
                self.results["errors"].append(
                    f"Failed to create dues schedule for {member_name}: {'; '.join(operation_result.errors)}"
                )
                return None

        except Exception as e:
            self.results["errors"].append(f"Error reconstructing dues schedule for {member_name}: {str(e)}")
            return None

    def sync_member_fields(self, member_name):
        """
        Synchronize member fields with their related records
        """
        try:
            member_doc = frappe.get_doc("Member", member_name)
            changes_made = []

            # Find active membership
            active_membership = frappe.db.get_value(
                "Membership", {"member": member_name, "status": "Active"}, "name"
            )

            if active_membership and member_doc.current_membership_plan != active_membership:
                frappe.db.set_value("Member", member_name, "current_membership_plan", active_membership)
                changes_made.append(f"current_membership_plan -> {active_membership}")

            # Find active dues schedule
            active_schedule_data = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member_name, "status": "Active", "is_template": 0},
                ["name", "dues_rate", "next_invoice_date"],
                as_dict=True,
            )

            if active_schedule_data:
                if member_doc.current_dues_schedule != active_schedule_data.name:
                    frappe.db.set_value(
                        "Member", member_name, "current_dues_schedule", active_schedule_data.name
                    )
                    changes_made.append(f"current_dues_schedule -> {active_schedule_data.name}")

                if member_doc.dues_rate != active_schedule_data.dues_rate:
                    frappe.db.set_value("Member", member_name, "dues_rate", active_schedule_data.dues_rate)
                    changes_made.append(f"dues_rate -> {active_schedule_data.dues_rate}")

                if member_doc.next_invoice_date != active_schedule_data.next_invoice_date:
                    frappe.db.set_value(
                        "Member", member_name, "next_invoice_date", active_schedule_data.next_invoice_date
                    )
                    changes_made.append(f"next_invoice_date -> {active_schedule_data.next_invoice_date}")

            if changes_made:
                self.results["fields_synchronized"] += 1
                self.results["actions_taken"].append(
                    f"Synchronized fields for {member_name}: {', '.join(changes_made)}"
                )

        except Exception as e:
            self.results["errors"].append(f"Error syncing fields for {member_name}: {str(e)}")

    def process_member_with_transaction(self, member_name, fix_issues=True):
        """
        ✅ NEW: Process a single member with full transaction safety

        This ensures either all operations succeed or all are rolled back,
        preventing partial updates that could corrupt data integrity.
        """
        import time

        initial_processed = self.results["members_processed"]
        initial_reconstructed = self.results["memberships_reconstructed"]
        initial_created = self.results["schedules_created"]
        initial_synchronized = self.results["fields_synchronized"]

        # Use an explicit named savepoint rather than the savepoint() context
        # manager: that helper catches Exception and swallows it, which would skip
        # both the failure-dict return and the counter rollback below (the method
        # would silently return None on failure). With an explicit savepoint we
        # roll back to it and let the exception reach our own except handler.
        sp = "health_check_" + frappe.generate_hash(length=10)
        frappe.db.savepoint(sp)
        try:
            # Process this member's health check
            self.results["members_processed"] += 1

            # Always sync fields first
            self.sync_member_fields(member_name)

            if fix_issues:
                # Ensure membership exists
                self.reconstruct_missing_membership(member_name)

                # Ensure dues schedule exists
                self.reconstruct_dues_schedule(member_name)

            frappe.db.release_savepoint(sp)

            return {
                "success": True,
                "member": member_name,
                "operations_completed": {
                    "memberships_reconstructed": self.results["memberships_reconstructed"]
                    - initial_reconstructed,
                    "schedules_created": self.results["schedules_created"] - initial_created,
                    "fields_synchronized": self.results["fields_synchronized"] - initial_synchronized,
                },
            }

        except NON_RESUMABLE_DB_ERRORS:
            # The counter reset below restores this manager's in-memory tally, which is
            # meaningless once the server has thrown the transaction away.
            raise
        except Exception as e:
            rollback_to_savepoint(sp)
            # Savepoint context manager handles rollback automatically
            # Reset counters to pre-transaction state
            self.results["members_processed"] = initial_processed
            self.results["memberships_reconstructed"] = initial_reconstructed
            self.results["schedules_created"] = initial_created
            self.results["fields_synchronized"] = initial_synchronized

            # Record the transaction failure
            self.results["transaction_failures"] += 1
            error_msg = f"Transaction failed for {member_name}: {str(e)}"
            self.results["errors"].append(error_msg)

            # Log for monitoring
            frappe.logger().error(error_msg)

            return {"success": False, "member": member_name, "error": str(e)}

    def validate_custom_rate_preservation(self, member_name, new_dues_rate):
        """
        ✅ NEW: Validate if manually approved custom rates should be preserved

        Per QCE finding: Prevent overriding manually approved custom rates
        """
        try:
            member_doc = frappe.get_doc("Member", member_name)

            # Check if member has any dues schedules with custom amount approved
            custom_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name, "custom_amount_approved": 1, "status": "Active"},
                fields=["name", "dues_rate", "custom_amount_reason", "custom_amount_approved_by"],
            )

            if custom_schedules:
                for schedule in custom_schedules:
                    # If there's a manually approved custom rate that differs from our calculated rate
                    if schedule.dues_rate != new_dues_rate:
                        # Check if it was approved by a human (not system)
                        if (
                            schedule.custom_amount_approved_by != "Administrator"
                            and "auto-created" not in (schedule.custom_amount_reason or "").lower()
                            and "reconstructed" not in (schedule.custom_amount_reason or "").lower()
                        ):
                            return {
                                "should_preserve": True,
                                "reason": f"Preserving manually approved custom rate {schedule.dues_rate} (approved by {schedule.custom_amount_approved_by})",
                                "existing_rate": schedule.dues_rate,
                            }

            return {
                "should_preserve": False,
                "reason": "No manually approved custom rates found",
                "existing_rate": None,
            }

        except Exception as e:
            frappe.log_error(
                f"Error validating custom rate preservation for {member_name}: {str(e)}",
                "Custom Rate Validation Error",
            )
            # Default to preserving existing rate on error
            return {
                "should_preserve": True,
                "reason": f"Error during validation, preserving existing rate: {str(e)}",
                "existing_rate": member_doc.dues_rate if "member_doc" in locals() else None,
            }


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def comprehensive_dues_schedule_health_check(
    member_filter: "str | list | None" = None,
    fix_issues: bool = False,
    batch_size: int = 100,
    continue_on_error: bool = True,
    max_members: int = 50,
):
    """
    ✅ ENHANCED: Comprehensive health check with batch processing and transaction safety

    Args:
        member_filter: Specific member(s) to process, or None for all
        fix_issues: Whether to actually fix issues or just report them
        batch_size: Number of members to process per batch (default 100)
        continue_on_error: Whether to continue processing if individual members fail
        max_members: Maximum number of members to process (useful for testing)
    """
    manager = DuesScheduleHealthManager()

    # ✅ NEW: Batch processing with proper pagination
    if member_filter:
        # Process specific member(s)
        members = [member_filter] if isinstance(member_filter, str) else member_filter
        total_members = len(members)

        manager.results["batch_info"] = {
            "total_members": total_members,
            "batch_size": batch_size,
            "specific_filter": True,
        }

        # Process in batches even for filtered members
        for i in range(0, len(members), batch_size):
            batch = members[i : i + batch_size]
            batch_result = _process_member_batch(
                manager, batch, fix_issues, continue_on_error, i // batch_size + 1
            )

            if not continue_on_error and batch_result["failed_members"]:
                break
    else:
        # ✅ NEW: Safe batch processing for all members
        total_members = frappe.db.count("Member")

        # Apply max_members limit if specified
        if max_members and max_members < total_members:
            total_members = max_members

        manager.results["batch_info"] = {
            "total_members": total_members,
            "batch_size": batch_size,
            "total_batches": (total_members + batch_size - 1) // batch_size,  # Ceiling division
            "specific_filter": False,
        }

        frappe.logger().info(f"Starting health check for {total_members} members in batches of {batch_size}")

        members_processed = 0
        for offset in range(0, total_members, batch_size):
            # ✅ NEW: Get members in safe batches
            batch_limit = min(batch_size, total_members - offset)
            batch_members = frappe.get_all(
                "Member",
                limit=batch_limit,
                start=offset,
                pluck="name",
                order_by="name",  # Consistent ordering for repeatability
            )

            if not batch_members:
                break

            batch_number = (offset // batch_size) + 1
            batch_result = _process_member_batch(
                manager, batch_members, fix_issues, continue_on_error, batch_number
            )

            members_processed += len(batch_members)

            # ✅ NEW: Progress monitoring
            frappe.logger().info(
                f"Completed batch {batch_number}: {len(batch_members)} members, {batch_result['successful_members']} successful, {batch_result['failed_members']} failed"
            )

            # Break if continue_on_error is False and we have failures
            if not continue_on_error and batch_result["failed_members"]:
                frappe.logger().warning("Stopping processing due to batch failures (continue_on_error=False)")
                break

            # ✅ NEW: Memory management - commit periodically
            if batch_number % 10 == 0:  # Every 10 batches
                frappe.db.commit()
                frappe.logger().info(
                    f"Committed progress after {batch_number} batches ({members_processed} members)"
                )

    # ✅ NEW: Enhanced result reporting
    manager.results["processing_summary"] = {
        "success_rate": (manager.results["members_processed"] - manager.results["transaction_failures"])
        / max(manager.results["members_processed"], 1)
        * 100,
        "total_operations": manager.results["memberships_reconstructed"]
        + manager.results["schedules_created"]
        + manager.results["fields_synchronized"],
        "transaction_failure_rate": manager.results["transaction_failures"]
        / max(manager.results["members_processed"], 1)
        * 100,
    }

    return manager.results


def _process_member_batch(manager, batch_members, fix_issues, continue_on_error, batch_number):
    """
    ✅ NEW: Process a batch of members with detailed tracking
    """
    batch_result = {
        "batch_number": batch_number,
        "batch_size": len(batch_members),
        "successful_members": 0,
        "failed_members": 0,
        "batch_errors": [],
    }

    frappe.logger().info(f"Processing batch {batch_number} with {len(batch_members)} members")

    for member_name in batch_members:
        try:
            # ✅ NEW: Use transaction-safe processing
            result = manager.process_member_with_transaction(member_name, fix_issues)

            if result["success"]:
                batch_result["successful_members"] += 1
            else:
                batch_result["failed_members"] += 1
                batch_result["batch_errors"].append(result["error"])

                if not continue_on_error:
                    frappe.logger().warning(f"Stopping batch processing due to failure for {member_name}")
                    break

        except Exception as e:
            # This should not happen due to transaction safety, but catch just in case
            error_msg = f"Unexpected error processing {member_name} in batch {batch_number}: {str(e)}"
            manager.results["errors"].append(error_msg)
            batch_result["failed_members"] += 1
            batch_result["batch_errors"].append(str(e))

            frappe.log_error(error_msg, "Batch Processing Unexpected Error")

            if not continue_on_error:
                break

    return batch_result


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def comprehensive_dues_health_maintenance():
    """
    Main scheduled job for comprehensive dues health maintenance
    """
    results = {
        "field_sync_results": None,
        "missing_membership_results": None,
        "missing_schedule_results": None,
        "stuck_schedule_results": None,
        "total_errors": 0,
        "summary": "",
    }

    try:
        # Step 1: Sync all member fields
        sync_result = sync_all_member_fields()
        results["field_sync_results"] = sync_result

        # Step 2: Reconstruct missing memberships and schedules
        health_result = comprehensive_dues_schedule_health_check()
        results["missing_membership_results"] = health_result

        # Step 3: Process stuck schedules with our enhanced retry system
        from verenigingen.api.fix_stuck_dues_schedule import find_all_stuck_schedules

        stuck_result = find_all_stuck_schedules()
        results["stuck_schedule_results"] = stuck_result

        # Calculate totals
        results["total_errors"] = (
            len(sync_result.get("errors", []))
            + len(health_result.get("errors", []))
            + len(stuck_result.get("errors", []))
        )

        # Generate summary
        summary_parts = []
        if health_result.get("schedules_created", 0) > 0:
            summary_parts.append(f"{health_result['schedules_created']} schedules created")
        if health_result.get("memberships_reconstructed", 0) > 0:
            summary_parts.append(f"{health_result['memberships_reconstructed']} memberships reconstructed")
        if health_result.get("fields_synchronized", 0) > 0:
            summary_parts.append(f"{health_result['fields_synchronized']} members synchronized")
        if stuck_result.get("total_stuck", 0) > 0:
            summary_parts.append(f"{stuck_result['total_stuck']} stuck schedules found")

        results["summary"] = "; ".join(summary_parts) if summary_parts else "No issues found"

        return results

    except Exception as e:
        frappe.log_error(
            f"Error in comprehensive dues health maintenance: {str(e)}", "Dues Health Maintenance Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def sync_all_member_fields(batch_size=100, max_members=None, continue_on_error=True):
    """
    ✅ ENHANCED: Synchronize all member fields with transaction safety and batch processing
    """
    results = {
        "members_processed": 0,
        "fields_synchronized": 0,
        "transaction_failures": 0,
        "errors": [],
        "actions_taken": [],
        "batch_info": {},
        "processing_summary": {},
    }

    # ✅ NEW: Safe batch processing
    total_members = frappe.db.count("Member")
    if max_members and max_members < total_members:
        total_members = max_members

    results["batch_info"] = {
        "total_members": total_members,
        "batch_size": batch_size,
        "total_batches": (total_members + batch_size - 1) // batch_size,
    }

    frappe.logger().info(f"Starting field sync for {total_members} members in batches of {batch_size}")

    members_processed = 0
    for offset in range(0, total_members, batch_size):
        batch_limit = min(batch_size, total_members - offset)
        batch_members = frappe.get_all(
            "Member", limit=batch_limit, start=offset, pluck="name", order_by="name"
        )

        if not batch_members:
            break

        batch_number = (offset // batch_size) + 1
        batch_successful = 0
        batch_failed = 0

        frappe.logger().info(f"Processing sync batch {batch_number} with {len(batch_members)} members")

        for member_name in batch_members:
            # ✅ NEW: Transaction safety for each member
            from frappe.database.database import savepoint

            try:
                with savepoint():
                    manager = DuesScheduleHealthManager()

                    # Sync this member's fields
                    manager.sync_member_fields(member_name)

                    results["members_processed"] += 1
                    results["fields_synchronized"] += manager.results["fields_synchronized"]
                    results["actions_taken"].extend(manager.results["actions_taken"])
                    batch_successful += 1

            except Exception as e:
                # Savepoint context manager handles rollback automatically
                results["transaction_failures"] += 1
                error_msg = f"Transaction failed for member sync {member_name}: {str(e)}"
                results["errors"].append(error_msg)
                batch_failed += 1

                frappe.logger().error(error_msg)

                if not continue_on_error:
                    frappe.logger().warning(f"Stopping sync due to failure for {member_name}")
                    break

        members_processed += len(batch_members)

        frappe.logger().info(
            f"Completed sync batch {batch_number}: {batch_successful} successful, {batch_failed} failed"
        )

        # Break if continue_on_error is False and we have failures
        if not continue_on_error and batch_failed > 0:
            break

        # Periodic commit for memory management
        if batch_number % 10 == 0:
            frappe.db.commit()
            frappe.logger().info(f"Committed sync progress after {batch_number} batches")

    # ✅ NEW: Enhanced summary
    results["processing_summary"] = {
        "success_rate": (results["members_processed"] - results["transaction_failures"])
        / max(results["members_processed"], 1)
        * 100,
        "transaction_failure_rate": results["transaction_failures"]
        / max(results["members_processed"], 1)
        * 100,
        "synchronization_rate": results["fields_synchronized"] / max(results["members_processed"], 1) * 100,
    }

    return results
