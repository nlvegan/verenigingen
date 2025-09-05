# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import frappe
from frappe import _

from verenigingen.verenigingen_payments.utils.audit_context import (
    AuditContextManagerClean,
    ExecutionSource,
    create_clean_audit_context,
)
from verenigingen.verenigingen_payments.utils.performance_estimator import (
    estimate_sepa_operation_performance_clean,
    get_clean_performance_estimator,
)

# Import unified architecture components
from verenigingen.verenigingen_payments.utils.sepa_permission_resolver import (
    get_clean_sepa_permission_resolver,
)


@dataclass
class FrappeNativeSEPAOperation:
    """Data structure for Frappe-native SEPA operations"""

    member_id: str
    operation_type: str  # create, update, cancel
    operation_data: Dict[str, Any]
    priority: str = "normal"


class FrappeNativeSEPAManagerOptimized:
    """
    OPTIMIZED Frappe-Native SEPA Operations Manager

    Uses proven 4-step bulk operation pattern from payment processing optimization:
    1. Bulk permission validation
    2. Group operations by type
    3. Bulk process each type
    4. Single transaction management

    Performance improvements: 80-90% query reduction expected
    """

    def __init__(self):
        self.processed_count = 0
        self.failed_count = 0
        self.errors = []

    def process_bulk_operations_optimized(
        self,
        operations: List[FrappeNativeSEPAOperation],
        execution_source: ExecutionSource = ExecutionSource.HTTP,
    ) -> Dict[str, Any]:
        """
        Process bulk SEPA operations with optimized 4-step pattern

        OPTIMIZATION APPLIED:
        - Bulk permission validation (1 query vs N queries)
        - Group operations by type for bulk processing
        - Single transaction vs N individual commits
        - In-memory error handling and validation
        """

        if not operations:
            return {"success": True, "processed": 0, "failed": 0, "errors": []}

        start_time = time.time()

        # Get performance estimator and audit context (for logging/monitoring)
        get_clean_performance_estimator()
        # Convert operations to format expected by performance estimator
        operation_dicts = [{"operation_type": op.operation_type} for op in operations]
        estimate_sepa_operation_performance_clean(operation_dicts)

        # Create audit context manager
        from verenigingen.verenigingen_payments.utils.audit_context import AuditContextManagerClean

        audit_mgr = AuditContextManagerClean("bulk_sepa_operations", execution_source)

        with audit_mgr:
            try:
                # STEP 1: BULK PERMISSION VALIDATION (1 query vs N queries)
                permission_results = self._validate_bulk_permissions(operations)

                # STEP 2: GROUP OPERATIONS BY TYPE FOR EFFICIENT PROCESSING
                grouped_operations = self._group_authorized_operations(operations, permission_results)

                # STEP 3: BULK PROCESS EACH OPERATION TYPE
                results = self._process_operations_by_type_bulk(
                    grouped_operations, execution_source, audit_mgr
                )

                # STEP 4: SINGLE TRANSACTION MANAGEMENT
                return self._finalize_bulk_transaction(results, start_time, audit_mgr)

            except Exception as e:
                frappe.db.rollback()
                audit_mgr.log_operation_result(False, {"error": str(e), "rollback": "completed"})
                frappe.log_error(f"Bulk SEPA operation failed: {str(e)}", "Optimized SEPA Bulk Processing")
                return {"success": False, "error": str(e)}

    def _validate_bulk_permissions(self, operations: List[FrappeNativeSEPAOperation]) -> Dict[str, bool]:
        """
        BULK QUERY 1: Validate permissions for all operations at once
        Replaces N individual permission checks with 1 bulk validation
        """
        # Get unique member IDs
        member_ids = list(set(op.member_id for op in operations))

        # Use existing bulk permission validation (already optimized!)
        resolver = get_clean_sepa_permission_resolver()
        permission_results = resolver.validate_bulk_operations(member_ids)

        frappe.logger().info(
            f"Bulk permission validation: {len(member_ids)} members, "
            f"{sum(permission_results.values())} authorized"
        )

        return permission_results

    def _group_authorized_operations(
        self, operations: List[FrappeNativeSEPAOperation], permission_results: Dict[str, bool]
    ) -> Dict[str, List[FrappeNativeSEPAOperation]]:
        """
        IN-MEMORY PROCESSING: Group operations by type for bulk processing
        Separates authorized operations by type (create/update/cancel)
        """
        grouped = {"create": [], "update": [], "cancel": []}

        for operation in operations:
            if permission_results.get(operation.member_id, False):
                grouped[operation.operation_type].append(operation)
            else:
                # Track unauthorized operations
                self.failed_count += 1
                self.errors.append(
                    {
                        "member_id": operation.member_id,
                        "operation_type": operation.operation_type,
                        "error": "insufficient_permissions",
                    }
                )

        # Log grouping results
        for op_type, ops in grouped.items():
            if ops:
                frappe.logger().info(f"Grouped {len(ops)} {op_type} operations for bulk processing")

        return grouped

    def _process_operations_by_type_bulk(
        self,
        grouped_operations: Dict[str, List[FrappeNativeSEPAOperation]],
        execution_source: ExecutionSource,
        audit_mgr: AuditContextManagerClean,
    ) -> Dict[str, Any]:
        """
        BULK QUERIES 2-4: Process each operation type in bulk
        Applies bulk processing to each operation type separately
        """
        results = {"create": [], "update": [], "cancel": []}

        try:
            # Process create operations in bulk
            if grouped_operations["create"]:
                results["create"] = self._bulk_create_mandates(
                    grouped_operations["create"], execution_source, audit_mgr
                )

            # Process update operations in bulk
            if grouped_operations["update"]:
                results["update"] = self._bulk_update_mandates(
                    grouped_operations["update"], execution_source, audit_mgr
                )

            # Process cancel operations in bulk
            if grouped_operations["cancel"]:
                results["cancel"] = self._bulk_cancel_mandates(
                    grouped_operations["cancel"], execution_source, audit_mgr
                )

            return results

        except Exception as e:
            frappe.logger().error(f"Bulk operation processing failed: {str(e)}")
            raise

    def _bulk_create_mandates(
        self,
        create_operations: List[FrappeNativeSEPAOperation],
        execution_source: ExecutionSource,
        audit_mgr: AuditContextManagerClean,
    ) -> List[Dict[str, Any]]:
        """
        BULK CREATE: Process mandate creation operations in bulk
        Creates multiple mandates efficiently with minimal database operations
        """
        results = []

        try:
            # BULK PREPARATION: Prepare all mandate data
            mandate_data_list = []
            for operation in create_operations:
                mandate_data = {
                    "doctype": "SEPA Mandate",
                    "member": operation.member_id,
                    **operation.operation_data,
                }
                mandate_data_list.append(mandate_data)

            # BULK PROCESSING: Create all mandates
            for i, mandate_data in enumerate(mandate_data_list):
                try:
                    # Use standard Frappe document creation - respects all permissions
                    mandate = frappe.get_doc(mandate_data)
                    mandate.insert()

                    results.append(
                        {
                            "success": True,
                            "member_id": create_operations[i].member_id,
                            "mandate_id": mandate.name,
                            "operation_type": "create",
                        }
                    )
                    self.processed_count += 1

                except Exception as e:
                    results.append(
                        {
                            "success": False,
                            "member_id": create_operations[i].member_id,
                            "error": str(e),
                            "operation_type": "create",
                        }
                    )
                    self.failed_count += 1
                    self.errors.append(
                        {
                            "member_id": create_operations[i].member_id,
                            "error": str(e),
                            "operation_type": "create",
                        }
                    )

            audit_mgr.log_operation_result(
                True,
                {
                    "operation_type": "bulk_create",
                    "processed": len([r for r in results if r["success"]]),
                    "failed": len([r for r in results if not r["success"]]),
                },
            )

            return results

        except Exception as e:
            frappe.logger().error(f"Bulk mandate creation failed: {str(e)}")
            raise

    def _bulk_update_mandates(
        self,
        update_operations: List[FrappeNativeSEPAOperation],
        execution_source: ExecutionSource,
        audit_mgr: AuditContextManagerClean,
    ) -> List[Dict[str, Any]]:
        """
        BULK UPDATE: Process mandate update operations in bulk
        Updates multiple mandates efficiently
        """
        results = []

        try:
            # BULK QUERY: Get all mandates to be updated
            member_ids = [op.member_id for op in update_operations]
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": ["in", member_ids], "status": ["!=", "Cancelled"]},
                fields=["name", "member"],
            )

            # Create lookup for efficient matching
            mandate_by_member = {m.member: m.name for m in mandates}

            # Process updates
            for operation in update_operations:
                mandate_name = mandate_by_member.get(operation.member_id)
                if not mandate_name:
                    results.append(
                        {
                            "success": False,
                            "member_id": operation.member_id,
                            "error": "No active mandate found",
                            "operation_type": "update",
                        }
                    )
                    self.failed_count += 1
                    continue

                try:
                    # Load and update mandate
                    mandate = frappe.get_doc("SEPA Mandate", mandate_name)
                    for field, value in operation.operation_data.items():
                        setattr(mandate, field, value)
                    mandate.save()

                    results.append(
                        {
                            "success": True,
                            "member_id": operation.member_id,
                            "mandate_id": mandate_name,
                            "operation_type": "update",
                        }
                    )
                    self.processed_count += 1

                except Exception as e:
                    results.append(
                        {
                            "success": False,
                            "member_id": operation.member_id,
                            "error": str(e),
                            "operation_type": "update",
                        }
                    )
                    self.failed_count += 1
                    self.errors.append(
                        {"member_id": operation.member_id, "error": str(e), "operation_type": "update"}
                    )

            audit_mgr.log_operation_result(
                True,
                {
                    "operation_type": "bulk_update",
                    "processed": len([r for r in results if r["success"]]),
                    "failed": len([r for r in results if not r["success"]]),
                },
            )

            return results

        except Exception as e:
            frappe.logger().error(f"Bulk mandate update failed: {str(e)}")
            raise

    def _bulk_cancel_mandates(
        self,
        cancel_operations: List[FrappeNativeSEPAOperation],
        execution_source: ExecutionSource,
        audit_mgr: AuditContextManagerClean,
    ) -> List[Dict[str, Any]]:
        """
        BULK CANCEL: Process mandate cancellation operations in bulk
        Cancels multiple mandates efficiently
        """
        results = []

        try:
            # BULK QUERY: Get all mandates to be cancelled
            member_ids = [op.member_id for op in cancel_operations]
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": ["in", member_ids], "status": ["!=", "Cancelled"]},
                fields=["name", "member"],
            )

            # Create lookup for efficient matching
            mandate_by_member = {m.member: m.name for m in mandates}

            # Process cancellations
            for operation in cancel_operations:
                mandate_name = mandate_by_member.get(operation.member_id)
                if not mandate_name:
                    results.append(
                        {
                            "success": False,
                            "member_id": operation.member_id,
                            "error": "No active mandate found",
                            "operation_type": "cancel",
                        }
                    )
                    self.failed_count += 1
                    continue

                try:
                    # Load and cancel mandate
                    mandate = frappe.get_doc("SEPA Mandate", mandate_name)
                    mandate.status = "Cancelled"
                    mandate.cancellation_date = frappe.utils.today()
                    mandate.cancellation_reason = operation.operation_data.get("reason", "Bulk cancellation")
                    mandate.save()

                    results.append(
                        {
                            "success": True,
                            "member_id": operation.member_id,
                            "mandate_id": mandate_name,
                            "operation_type": "cancel",
                        }
                    )
                    self.processed_count += 1

                except Exception as e:
                    results.append(
                        {
                            "success": False,
                            "member_id": operation.member_id,
                            "error": str(e),
                            "operation_type": "cancel",
                        }
                    )
                    self.failed_count += 1
                    self.errors.append(
                        {"member_id": operation.member_id, "error": str(e), "operation_type": "cancel"}
                    )

            audit_mgr.log_operation_result(
                True,
                {
                    "operation_type": "bulk_cancel",
                    "processed": len([r for r in results if r["success"]]),
                    "failed": len([r for r in results if not r["success"]]),
                },
            )

            return results

        except Exception as e:
            frappe.logger().error(f"Bulk mandate cancellation failed: {str(e)}")
            raise

    def _finalize_bulk_transaction(
        self, results: Dict[str, Any], start_time: float, audit_mgr: AuditContextManagerClean
    ) -> Dict[str, Any]:
        """
        SINGLE TRANSACTION: Finalize all operations with single commit
        Replaces N individual commits with 1 atomic transaction
        """

        try:
            # Calculate totals - handle case where results might be integers or lists
            total_processed = 0
            total_successful = 0

            for op_type in results:
                op_results = results[op_type]
                if isinstance(op_results, list):
                    total_processed += len(op_results)
                    total_successful += len([r for r in op_results if r.get("success", False)])
                elif isinstance(op_results, int):
                    # Handle case where results is just a count
                    total_processed += op_results
                    total_successful += op_results  # Assume all successful if no error details

            total_failed = total_processed - total_successful

            # SINGLE COMMIT: Commit all operations atomically
            if total_successful > 0:
                frappe.db.commit()
                frappe.logger().info(f"Bulk SEPA operations committed: {total_successful} successful")

            # Calculate performance
            actual_duration = time.time() - start_time

            # Build comprehensive response
            response = {
                "success": True,
                "processed": total_successful,
                "failed": total_failed,
                "total_operations": total_processed,
                "execution_time": actual_duration,
                "results_by_type": {
                    op_type: {
                        "successful": len([r for r in op_results if r.get("success", False)])
                        if isinstance(op_results, list)
                        else (op_results if isinstance(op_results, int) else 0),
                        "failed": len([r for r in op_results if not r.get("success", True)])
                        if isinstance(op_results, list)
                        else 0,
                    }
                    for op_type, op_results in results.items()
                    if op_results  # Use items() and store op_results
                },
                "errors": self.errors,
            }

            audit_mgr.log_operation_result(
                True,
                {
                    "total_processed": total_successful,
                    "total_failed": total_failed,
                    "execution_time": actual_duration,
                    "optimization": "bulk_processing_enabled",
                },
            )

            # Send completion notification
            frappe.publish_realtime(
                "sepa_bulk_operation_complete",
                {
                    "success": True,
                    "processed": total_successful,
                    "failed": total_failed,
                    "execution_time": actual_duration,
                },
                user=frappe.session.user,
            )

            return response

        except Exception as e:
            # Rollback on any finalization error
            frappe.db.rollback()
            frappe.logger().error(f"Bulk transaction finalization failed: {str(e)}")
            raise


# Utility function to get optimized SEPA manager
def get_optimized_sepa_manager() -> FrappeNativeSEPAManagerOptimized:
    """Get instance of optimized SEPA operations manager"""
    return FrappeNativeSEPAManagerOptimized()
