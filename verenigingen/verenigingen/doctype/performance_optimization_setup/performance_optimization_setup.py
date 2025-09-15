# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Performance Optimization Setup
==============================

Handles database indexing and caching setup for optimal performance.
Integrates with app installation process to ensure optimizations are
applied automatically during setup.
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class PerformanceOptimizationSetup(Document):
    def validate(self):
        """Validate optimization settings"""
        pass

    def on_submit(self):
        """Apply performance optimizations with rollback on failure"""
        try:
            # Track what we've done for rollback
            self._created_indexes = []

            if self.enable_database_indexing:
                index_result = self.setup_database_indexes()
                if not index_result or index_result.get("failed", 0) > 0:
                    frappe.throw(_("Database indexing failed - see logs for details"))

            if self.enable_caching_layer:
                cache_result = self.setup_caching_layer()
                if not cache_result.get("success"):
                    frappe.logger().warning(f"Caching setup failed: {cache_result.get('error')}")
                    # Don't fail the whole process for caching issues

            self.log_optimization_completion()

        except Exception as e:
            frappe.logger().error(f"Performance optimization failed: {str(e)}")
            # Attempt rollback
            self._rollback_changes()
            raise

    def setup_database_indexes(self):
        """Create optimal database indexes for query performance"""

        try:
            # Define indexes based on our N+1 optimization analysis
            indexes_to_create = [
                # Chapter Member optimizations - Critical for all reports
                {
                    "table": "tabChapter Member",
                    "name": "idx_member_status_creation",
                    "columns": "(member, status, creation DESC)",
                    "rationale": "Optimizes member chapter lookups with status filtering and chronological ordering",
                },
                {
                    "table": "tabChapter Member",
                    "name": "idx_parent_status_enabled",
                    "columns": "(parent, status, enabled)",
                    "rationale": "Optimizes chapter-to-member queries with status filtering",
                },
                # Payment Entry optimizations - High impact
                {
                    "table": "tabPayment Entry",
                    "name": "idx_party_type_party_docstatus",
                    "columns": "(party_type, party, docstatus)",
                    "rationale": "Optimizes customer payment lookups",
                },
                {
                    "table": "tabPayment Entry",
                    "name": "idx_party_posting_date_desc",
                    "columns": "(party, posting_date DESC)",
                    "rationale": "Optimizes last payment date queries",
                },
                # Member optimizations
                {
                    "table": "tabMember",
                    "name": "idx_customer_docstatus",
                    "columns": "(customer, docstatus)",
                    "rationale": "Optimizes member-customer relationship queries",
                },
                {
                    "table": "tabMember",
                    "name": "idx_status_member_since",
                    "columns": "(status, member_since)",
                    "rationale": "Optimizes member status and date-based filtering",
                },
                # Membership optimizations
                {
                    "table": "tabMembership",
                    "name": "idx_member_status_start_date",
                    "columns": "(member, status, start_date)",
                    "rationale": "Optimizes membership queries by member with status and chronological ordering",
                },
                {
                    "table": "tabMembership",
                    "name": "idx_member_creation_desc",
                    "columns": "(member, creation DESC)",
                    "rationale": "Optimizes latest membership lookups",
                },
                # Sales Invoice optimizations
                {
                    "table": "tabSales Invoice",
                    "name": "idx_customer_status_due_date",
                    "columns": "(customer, status, due_date)",
                    "rationale": "Optimizes overdue invoice calculations",
                },
                {
                    "table": "tabSales Invoice",
                    "name": "idx_status_docstatus_posting",
                    "columns": "(status, docstatus, posting_date)",
                    "rationale": "Optimizes invoice status and date filtering",
                },
                # Membership Dues Schedule optimizations
                {
                    "table": "tabMembership Dues Schedule",
                    "name": "idx_member_status_next_invoice",
                    "columns": "(member, status, next_invoice_date)",
                    "rationale": "Optimizes dues schedule queries",
                },
            ]

            optimization_results = []

            for idx_config in indexes_to_create:
                result = self.create_index_if_not_exists(
                    idx_config["table"], idx_config["name"], idx_config["columns"], idx_config["rationale"]
                )
                optimization_results.append(result)

            # Log results
            successful_indexes = [r for r in optimization_results if r["success"]]
            failed_indexes = [r for r in optimization_results if not r["success"]]

            frappe.logger().info(
                f"Database indexing complete: {len(successful_indexes)} successful, {len(failed_indexes)} failed"
            )

            if failed_indexes:
                for failed in failed_indexes:
                    frappe.logger().warning(f"Index creation failed: {failed['name']} - {failed['error']}")

            return {
                "successful": len(successful_indexes),
                "failed": len(failed_indexes),
                "details": optimization_results,
            }

        except Exception as e:
            frappe.logger().error(f"Database indexing setup failed: {str(e)}")
            frappe.throw(_("Failed to set up database indexes: {0}").format(str(e)))

    def create_index_if_not_exists(self, table_name, index_name, columns, rationale):
        """Create database index if it doesn't already exist - SECURE VERSION"""

        try:
            # SECURITY: Validate table name exists in database to prevent injection
            if not self._validate_table_exists(table_name):
                return {
                    "success": False,
                    "name": index_name,
                    "table": table_name,
                    "action": "failed",
                    "error": f"Table {table_name} does not exist",
                }

            # SECURITY: Validate index name contains only safe characters
            if not self._validate_index_name(index_name):
                return {
                    "success": False,
                    "name": index_name,
                    "table": table_name,
                    "action": "failed",
                    "error": "Invalid index name format",
                }

            # Check if index already exists using parameterized query
            existing_indexes = frappe.db.sql(
                """
                SELECT INDEX_NAME
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = %s
                AND INDEX_NAME = %s
            """,
                (table_name.replace("`", ""), index_name),
            )

            if existing_indexes:
                return {
                    "success": True,
                    "name": index_name,
                    "table": table_name,
                    "action": "skipped",
                    "reason": "Index already exists",
                }

            # SECURITY: Use whitelisted column patterns only
            if not self._validate_column_pattern(columns):
                return {
                    "success": False,
                    "name": index_name,
                    "table": table_name,
                    "action": "failed",
                    "error": "Invalid column pattern",
                }

            # Create the index using DDL with validated components
            # Note: Index creation cannot use parameter binding, so we validate all inputs
            create_sql = f"ALTER TABLE `{table_name}` ADD INDEX {index_name} {columns}"

            frappe.db.sql(create_sql)
            frappe.db.commit()

            frappe.logger().info(f"Created index {index_name} on {table_name}: {rationale}")

            # Track created index for rollback
            if not hasattr(self, "_created_indexes"):
                self._created_indexes = []
            self._created_indexes.append({"name": index_name, "table": table_name})

            return {
                "success": True,
                "name": index_name,
                "table": table_name,
                "action": "created",
                "rationale": rationale,
            }

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Failed to create index {index_name} on {table_name}: {error_msg}")

            return {
                "success": False,
                "name": index_name,
                "table": table_name,
                "action": "failed",
                "error": error_msg,
            }

    def _validate_table_exists(self, table_name: str) -> bool:
        """Validate that table exists in database"""
        try:
            # Remove backticks for validation
            clean_table_name = table_name.replace("`", "")

            # Check if table exists in current database
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = %s
            """,
                (clean_table_name,),
            )

            return result[0][0] > 0 if result else False

        except Exception:
            return False

    def _validate_index_name(self, index_name: str) -> bool:
        """Validate index name contains only safe characters"""
        # Allow only alphanumeric characters and underscores
        return bool(re.match(r"^[a-zA-Z0-9_]+$", index_name))

    def _validate_column_pattern(self, columns: str) -> bool:
        """Validate column pattern is safe"""
        # Check for common SQL injection patterns
        dangerous_patterns = ["--", ";", "/*", "*/", "DROP", "DELETE", "INSERT", "UPDATE"]
        columns_upper = columns.upper()

        for pattern in dangerous_patterns:
            if pattern in columns_upper:
                return False

        # Ensure it starts with parentheses (valid index column definition)
        if not columns.strip().startswith("(") or not columns.strip().endswith(")"):
            return False

        return True

    def _verify_cache_backend(self) -> bool:
        """Verify cache backend is available and working"""
        try:
            cache = frappe.cache()
            # Test cache operations
            test_key = "perf_opt_test"
            cache.set_value(test_key, "test", 1)
            result = cache.get_value(test_key)
            cache.delete_value(test_key)
            return result == "test"
        except Exception:
            return False

    def setup_caching_layer(self):
        """Set up caching layer for performance optimization - FIXED VERSION"""

        try:
            # FIXED: Store cache configuration in the document itself, not System Settings
            caching_config = {
                "chapter_access_cache_ttl": 900,  # 15 minutes
                "member_info_cache_ttl": 600,  # 10 minutes
                "report_cache_ttl": 300,  # 5 minutes
                "permission_cache_ttl": 1800,  # 30 minutes
                "settings_cache_ttl": 3600,  # 1 hour
            }

            # Store configuration in this document for reference
            self.caching_details = json.dumps(caching_config, indent=2)

            # Verify Redis is available and working
            if not self._verify_cache_backend():
                frappe.logger().warning("Redis cache not available - caching disabled")
                return {"success": False, "error": "Redis cache backend not available"}

            frappe.logger().info("Caching layer configuration completed")

            return {"success": True, "config": caching_config}

        except Exception as e:
            frappe.logger().error(f"Caching setup failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def _validate_optimizations_working(self):
        """Simple validation that optimizations are working"""
        try:
            # Test that indexes exist on critical tables
            critical_tables = ["tabChapter Member", "tabPayment Entry", "tabMember"]

            for table in critical_tables:
                if self._validate_table_exists(table):
                    # Use INFORMATION_SCHEMA for safety instead of SHOW INDEX
                    indexes = frappe.db.sql(
                        """
                        SELECT INDEX_NAME as Key_name, COUNT(*) as index_count
                        FROM INFORMATION_SCHEMA.STATISTICS
                        WHERE TABLE_SCHEMA = DATABASE()
                        AND TABLE_NAME = %s
                        GROUP BY INDEX_NAME
                    """,
                        (table.replace("`", ""),),
                        as_dict=True,
                    )
                    index_count = len([idx for idx in indexes if idx.get("Key_name", "").startswith("idx_")])
                    frappe.logger().info(f"Performance validation: {table} has {index_count} custom indexes")

            # Test cache is working if enabled
            if self.enable_caching_layer and self._verify_cache_backend():
                frappe.logger().info("Performance validation: Cache backend is working")

        except Exception as e:
            frappe.logger().warning(f"Performance validation failed: {str(e)}")

    def _rollback_changes(self):
        """Rollback any changes made during failed optimization"""
        try:
            frappe.logger().info("Attempting to rollback performance optimization changes")

            # Remove any indexes we created
            if hasattr(self, "_created_indexes"):
                for index_info in self._created_indexes:
                    try:
                        table_name = index_info.get("table")
                        index_name = index_info.get("name")

                        if (
                            table_name
                            and index_name
                            and self._validate_table_exists(table_name)
                            and self._validate_index_name(index_name)
                        ):
                            # Safe DDL construction with validated inputs
                            drop_sql = f"ALTER TABLE `{table_name}` DROP INDEX {index_name}"
                            frappe.db.sql(drop_sql)
                            frappe.logger().info(f"Rolled back index {index_name} on {table_name}")

                    except Exception as rollback_error:
                        frappe.logger().warning(f"Could not rollback index {index_name}: {rollback_error}")

            # Clear cache if it was being set up
            try:
                from verenigingen.utils.performance_cache import PerformanceCache

                cache = PerformanceCache()
                if cache.enabled:
                    # Clear any test cache entries
                    cache.invalidate("lookup")
                    frappe.logger().info("Cleared cache entries during rollback")
            except Exception:
                pass  # Cache rollback is not critical

            frappe.logger().info("Performance optimization rollback completed")

        except Exception as e:
            frappe.logger().error(f"Rollback failed: {str(e)}")

    @frappe.whitelist()
    def remove_optimizations(self):
        """Manually remove performance optimizations"""
        if not frappe.has_permission(self.doctype, "write"):
            frappe.throw(_("Insufficient permissions to remove optimizations"))

        try:
            # This would remove all our custom indexes
            # Implementation would query for indexes starting with 'idx_' and remove them
            frappe.logger().info("Manual optimization removal not yet implemented")
            frappe.msgprint("Manual optimization removal will be implemented in future version")

        except Exception as e:
            frappe.logger().error(f"Failed to remove optimizations: {str(e)}")
            frappe.throw(_("Failed to remove optimizations: {0}").format(str(e)))

    def log_optimization_completion(self):
        """Log completion of optimization setup"""

        frappe.logger().info("Performance Optimization Setup completed successfully")

        # ADDED: Store optimization details for monitoring
        optimization_summary = {
            "database_indexing": self.enable_database_indexing,
            "caching_layer": self.enable_caching_layer,
            "completion_time": frappe.utils.now(),
            "indexes_created": getattr(self, "_indexes_created", 0),
            "cache_backend_verified": getattr(self, "_cache_verified", False),
        }

        self.indexing_details = json.dumps(optimization_summary, indent=2)

        # Update this document with completion status
        self.optimization_status = "Completed"
        self.optimization_completion_date = frappe.utils.now()
        self.save()

        # ADDED: Simple performance validation
        self._validate_optimizations_working()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def run_performance_optimization():
    """Run performance optimization setup - FIXED with proper error handling"""

    try:
        # FIXED: Check if DocType exists before trying to use it
        if not frappe.db.exists("DocType", "Performance Optimization Setup"):
            frappe.logger().warning(
                "Performance Optimization Setup DocType not found - skipping optimization"
            )
            return {"success": False, "message": "Performance Optimization Setup not installed yet"}

        # Create or get existing optimization document
        if frappe.db.exists("Performance Optimization Setup", "default"):
            doc = frappe.get_doc("Performance Optimization Setup", "default")
            if doc.docstatus == 1:  # Already submitted
                return {"success": True, "message": "Performance optimizations already applied"}
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "Performance Optimization Setup",
                    "name": "default",
                    "optimization_name": "Default Performance Optimization",
                    "enable_database_indexing": 1,
                    "enable_caching_layer": 1,
                    "optimization_status": "Pending",
                }
            )
            doc.insert(ignore_permissions=True)  # System setup needs to bypass permissions

        # Run optimizations
        doc.submit()

        return {"success": True, "message": "Performance optimizations applied successfully"}

    except Exception as e:
        frappe.logger().error(f"Performance optimization failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def get_optimization_status():
    """Get current optimization status for monitoring"""

    try:
        if frappe.db.exists("Performance Optimization Setup", "default"):
            doc = frappe.get_doc("Performance Optimization Setup", "default")
            return {
                "applied": True,
                "status": doc.optimization_status,
                "completion_date": doc.optimization_completion_date,
            }
        else:
            return {"applied": False, "status": "Not Applied"}

    except Exception as e:
        return {"applied": False, "error": str(e)}
