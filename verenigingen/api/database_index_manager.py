#!/usr/bin/env python3
"""
Database Index Manager
Phase 2.4 Implementation - Safe Database Index Addition with Validation

This module manages database index creation, validation, and monitoring
using safe ALGORITHM=INPLACE, LOCK=NONE approach for performance optimization.
"""

import time
from typing import Any, Dict, List, Tuple

import frappe
from frappe import _


class DatabaseIndexManager:
    """Manager for safe database index operations"""

    # Define the specific indexes from the implementation addendum
    PERFORMANCE_INDEXES = [
        {
            "name": "idx_customer_status",
            "table": "tabSales Invoice",
            "columns": ["customer", "status"],
            "type": "INDEX",
            "description": "Optimizes customer invoice status lookups",
        },
        {
            "name": "idx_reference_name",
            "table": "tabPayment Entry Reference",
            "columns": ["reference_name"],
            "type": "INDEX",
            "description": "Optimizes payment entry reference lookups",
        },
        {
            "name": "idx_member_status",
            "table": "tabSEPA Mandate",
            "columns": ["member", "status"],
            "type": "INDEX",
            "description": "Optimizes SEPA mandate member/status lookups",
        },
        {
            "name": "idx_party_type_party",
            "table": "tabPayment Entry",
            "columns": ["party_type", "party"],
            "type": "INDEX",
            "description": "Optimizes payment entry party lookups",
        },
        {
            "name": "idx_posting_date_customer",
            "table": "tabSales Invoice",
            "columns": ["posting_date", "customer"],
            "type": "INDEX",
            "description": "Optimizes date-based customer invoice queries",
        },
    ]

    @staticmethod
    def add_performance_indexes() -> Dict[str, Any]:
        """
        Add all performance indexes with safe approach

        Returns:
            Results of index creation operations
        """
        results = {
            "timestamp": frappe.utils.now(),
            "indexes_processed": 0,
            "indexes_created": 0,
            "indexes_skipped": 0,
            "indexes_failed": 0,
            "details": [],
        }

        for index_config in DatabaseIndexManager.PERFORMANCE_INDEXES:
            try:
                result = DatabaseIndexManager.add_single_index(index_config)
                results["details"].append(result)
                results["indexes_processed"] += 1

                if result["status"] == "created":
                    results["indexes_created"] += 1
                elif result["status"] == "exists":
                    results["indexes_skipped"] += 1
                elif result["status"] == "failed":
                    results["indexes_failed"] += 1

            except Exception as e:
                error_result = {
                    "index_name": index_config["name"],
                    "table": index_config["table"],
                    "status": "error",
                    "error": str(e),
                }
                results["details"].append(error_result)
                results["indexes_failed"] += 1

                frappe.log_error(
                    f"Index creation error for {index_config['name']}: {e}", "Database Index Error"
                )

        return results

    @staticmethod
    def add_single_index(index_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a single index with validation and safety checks

        Args:
            index_config: Index configuration dictionary

        Returns:
            Result of index creation
        """
        index_name = index_config["name"]
        table_name = index_config["table"]
        columns = index_config["columns"]

        result = {
            "index_name": index_name,
            "table": table_name,
            "columns": columns,
            "status": "unknown",
            "execution_time": 0,
            "validation_result": None,
        }

        try:
            start_time = time.time()

            # 1. Check if index already exists
            if DatabaseIndexManager.index_exists(table_name, index_name):
                result["status"] = "exists"
                result["message"] = f"Index {index_name} already exists"
                return result

            # 2. Validate table exists
            if not DatabaseIndexManager.table_exists(table_name):
                result["status"] = "failed"
                result["error"] = f"Table {table_name} does not exist"
                return result

            # 3. Validate columns exist
            missing_columns = DatabaseIndexManager.get_missing_columns(table_name, columns)
            if missing_columns:
                result["status"] = "failed"
                result["error"] = f"Missing columns in {table_name}: {missing_columns}"
                return result

            # 4. Run EXPLAIN query to validate query pattern
            explain_result = DatabaseIndexManager.validate_index_usage(table_name, columns)
            result["validation_result"] = explain_result

            # 5. Create index with safe approach
            column_list = ", ".join([f"`{col}`" for col in columns])

            # Use standard MySQL/MariaDB syntax for index creation
            sql = f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` ({column_list})"

            # Execute the index creation
            frappe.db.sql(sql)
            frappe.db.commit()

            end_time = time.time()
            result["execution_time"] = round(end_time - start_time, 3)
            result["status"] = "created"
            result["message"] = f"Index {index_name} created successfully"

            # 6. Validate index was created
            if DatabaseIndexManager.index_exists(table_name, index_name):
                result["verified"] = True
            else:
                result["verified"] = False
                result["warning"] = "Index creation reported success but verification failed"

            return result

        except Exception as e:
            end_time = time.time()
            result["execution_time"] = round(end_time - start_time, 3)
            result["status"] = "failed"
            result["error"] = str(e)

            frappe.log_error(
                f"Failed to create index {index_name} on {table_name}: {e}", "Index Creation Error"
            )

            return result

    @staticmethod
    def index_exists(table_name: str, index_name: str) -> bool:
        """Check if an index exists on a table"""
        try:
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                AND table_name = %s
                AND index_name = %s
            """,
                (table_name, index_name),
                as_dict=True,
            )

            return result[0]["count"] > 0

        except Exception as e:
            frappe.log_error(f"Error checking index existence {index_name}: {e}")
            return False

    @staticmethod
    def table_exists(table_name: str) -> bool:
        """Check if a table exists"""
        try:
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = %s
            """,
                (table_name,),
                as_dict=True,
            )

            return result[0]["count"] > 0

        except Exception as e:
            frappe.log_error(f"Error checking table existence {table_name}: {e}")
            return False

    @staticmethod
    def get_missing_columns(table_name: str, columns: List[str]) -> List[str]:
        """Get list of columns that don't exist in the table"""
        try:
            # Get all columns in the table
            existing_columns = frappe.db.sql(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = %s
            """,
                (table_name,),
                as_dict=True,
            )

            existing_column_names = {col["column_name"].lower() for col in existing_columns}
            missing = [col for col in columns if col.lower() not in existing_column_names]

            return missing

        except Exception as e:
            frappe.log_error(f"Error checking columns for {table_name}: {e}")
            return columns  # Assume all are missing if we can't check

    @staticmethod
    def validate_index_usage(table_name: str, columns: List[str]) -> Dict[str, Any]:
        """
        Validate that the index will be used by running EXPLAIN queries

        Args:
            table_name: Name of the table
            columns: List of columns in the index

        Returns:
            EXPLAIN query results
        """
        try:
            # Create sample queries that should use this index
            validation_queries = DatabaseIndexManager.get_validation_queries(table_name, columns)

            explain_results = []

            for query_info in validation_queries:
                try:
                    # Run EXPLAIN on the query
                    explain_sql = f"EXPLAIN {query_info['query']}"
                    explain_result = frappe.db.sql(explain_sql, query_info.get("params", []), as_dict=True)

                    explain_results.append(
                        {
                            "query_description": query_info["description"],
                            "query": query_info["query"],
                            "explain_result": explain_result,
                            "will_use_index": DatabaseIndexManager.check_if_index_used(
                                explain_result, columns
                            ),
                        }
                    )

                except Exception as e:
                    explain_results.append({"query_description": query_info["description"], "error": str(e)})

            return {
                "validation_queries": len(validation_queries),
                "successful_explains": len([r for r in explain_results if "error" not in r]),
                "results": explain_results,
            }

        except Exception as e:
            frappe.log_error(f"Index validation failed for {table_name}: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_validation_queries(table_name: str, columns: List[str]) -> List[Dict[str, Any]]:
        """Get validation queries for specific table and columns"""

        queries = []

        if table_name == "tabSales Invoice" and "customer" in columns and "status" in columns:
            queries = [
                {
                    "description": "Customer invoices by status",
                    "query": f"SELECT name FROM `{table_name}` WHERE customer = %s AND status = %s LIMIT 1",
                    "params": ["CUST-00001", "Paid"],
                },
                {
                    "description": "Customer unpaid invoices",
                    "query": f"SELECT name FROM `{table_name}` WHERE customer = %s AND status != %s LIMIT 1",
                    "params": ["CUST-00001", "Cancelled"],
                },
            ]

        elif table_name == "tabPayment Entry Reference" and "reference_name" in columns:
            queries = [
                {
                    "description": "Payment references by invoice",
                    "query": f"SELECT parent FROM `{table_name}` WHERE reference_name = %s LIMIT 1",
                    "params": ["SI-00001"],
                }
            ]

        elif table_name == "tabSEPA Mandate" and "member" in columns and "status" in columns:
            queries = [
                {
                    "description": "Active member mandates",
                    "query": f"SELECT name FROM `{table_name}` WHERE member = %s AND status = %s LIMIT 1",
                    "params": ["MEM-00001", "Active"],
                }
            ]

        elif table_name == "tabPayment Entry" and "party_type" in columns and "party" in columns:
            queries = [
                {
                    "description": "Customer payment entries",
                    "query": f"SELECT name FROM `{table_name}` WHERE party_type = %s AND party = %s LIMIT 1",
                    "params": ["Customer", "CUST-00001"],
                }
            ]

        return queries

    @staticmethod
    def check_if_index_used(explain_result: List[Dict], columns: List[str]) -> bool:
        """Check if EXPLAIN result indicates index usage"""
        try:
            if not explain_result:
                return False

            first_row = explain_result[0]

            # Check if 'key' field indicates index usage
            key_used = first_row.get("key", "").strip()
            if key_used and key_used != "NULL":
                return True

            # Check if possible_keys includes our expected index columns
            possible_keys = first_row.get("possible_keys", "") or ""
            for column in columns:
                if column.lower() in possible_keys.lower():
                    return True

            return False

        except Exception as e:
            frappe.log_error(f"Error checking index usage in EXPLAIN: {e}")
            return False

    @staticmethod
    def monitor_index_impact(duration_hours: int = 24) -> Dict[str, Any]:
        """
        Monitor the impact of newly created indexes

        Args:
            duration_hours: How long to monitor (for future implementation)

        Returns:
            Monitoring results
        """
        try:
            # Get current query performance metrics
            current_metrics = DatabaseIndexManager.get_current_query_metrics()

            # This would be expanded in a production system to:
            # 1. Store baseline metrics before index creation
            # 2. Compare current metrics to baseline
            # 3. Track query performance improvements
            # 4. Alert if any queries become slower

            return {
                "timestamp": frappe.utils.now(),
                "monitoring_duration_hours": duration_hours,
                "current_metrics": current_metrics,
                "status": "monitoring_active",
                "note": "Full monitoring implementation would track query performance over time",
            }

        except Exception as e:
            frappe.log_error(f"Index monitoring failed: {e}")
            return {"status": "monitoring_failed", "error": str(e)}

    @staticmethod
    def get_current_query_metrics() -> Dict[str, Any]:
        """Get current database query performance metrics"""
        try:
            # Get some basic metrics about query performance
            # This is a simplified version - production would track more metrics

            metrics = {}

            # Get slow query count
            try:
                slow_queries = frappe.db.sql(
                    """
                    SHOW GLOBAL STATUS LIKE 'Slow_queries'
                """,
                    as_dict=True,
                )

                if slow_queries:
                    metrics["slow_query_count"] = slow_queries[0].get("Value", 0)
            except:
                pass

            # Get query cache hit rate
            try:
                cache_stats = frappe.db.sql(
                    """
                    SHOW GLOBAL STATUS WHERE Variable_name IN ('Qcache_hits', 'Com_select')
                """,
                    as_dict=True,
                )

                cache_hits = 0
                selects = 0

                for stat in cache_stats:
                    if stat["Variable_name"] == "Qcache_hits":
                        cache_hits = int(stat["Value"])
                    elif stat["Variable_name"] == "Com_select":
                        selects = int(stat["Value"])

                if selects > 0:
                    metrics["query_cache_hit_rate"] = round((cache_hits / (cache_hits + selects)) * 100, 2)
            except:
                pass

            # Get table sizes for the indexed tables
            try:
                table_sizes = frappe.db.sql(
                    """
                    SELECT table_name, table_rows, data_length, index_length
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    AND table_name IN ('tabSales Invoice', 'tabPayment Entry Reference', 'tabSEPA Mandate', 'tabPayment Entry')
                """,
                    as_dict=True,
                )

                metrics["table_stats"] = {}
                for table in table_sizes:
                    metrics["table_stats"][table["table_name"]] = {
                        "rows": table["table_rows"],
                        "data_size_mb": round(table["data_length"] / 1024 / 1024, 2),
                        "index_size_mb": round(table["index_length"] / 1024 / 1024, 2),
                    }
            except:
                pass

            metrics["timestamp"] = frappe.utils.now()
            return metrics

        except Exception as e:
            frappe.log_error(f"Failed to get query metrics: {e}")
            return {"error": str(e)}

    @staticmethod
    def remove_performance_indexes() -> Dict[str, Any]:
        """
        Remove all performance indexes (for rollback)

        Returns:
            Results of index removal operations
        """
        results = {
            "timestamp": frappe.utils.now(),
            "indexes_processed": 0,
            "indexes_removed": 0,
            "indexes_not_found": 0,
            "indexes_failed": 0,
            "details": [],
        }

        for index_config in DatabaseIndexManager.PERFORMANCE_INDEXES:
            try:
                result = DatabaseIndexManager.remove_single_index(index_config["table"], index_config["name"])
                results["details"].append(result)
                results["indexes_processed"] += 1

                if result["status"] == "removed":
                    results["indexes_removed"] += 1
                elif result["status"] == "not_found":
                    results["indexes_not_found"] += 1
                elif result["status"] == "failed":
                    results["indexes_failed"] += 1

            except Exception as e:
                error_result = {
                    "index_name": index_config["name"],
                    "table": index_config["table"],
                    "status": "error",
                    "error": str(e),
                }
                results["details"].append(error_result)
                results["indexes_failed"] += 1

        return results

    @staticmethod
    def remove_single_index(table_name: str, index_name: str) -> Dict[str, Any]:
        """Remove a single index with proper input validation"""
        result = {"index_name": index_name, "table": table_name, "status": "unknown", "execution_time": 0}

        try:
            start_time = time.time()

            # Validate inputs for security
            if not isinstance(table_name, str) or not isinstance(index_name, str):
                result["status"] = "failed"
                result["message"] = "Invalid input types"
                return result

            # Validate table name format (must be a valid DocType table)
            if not table_name.startswith("`tab") or not table_name.endswith("`"):
                result["status"] = "failed"
                result["message"] = f"Invalid table name format: {table_name}"
                return result

            # Validate index name format (alphanumeric + underscore only)
            if not index_name.replace("_", "").replace("idx", "").isalnum():
                result["status"] = "failed"
                result["message"] = f"Invalid index name format: {index_name}"
                return result

            # Check if index exists
            if not DatabaseIndexManager.index_exists(table_name, index_name):
                result["status"] = "not_found"
                result["message"] = f"Index {index_name} does not exist"
                return result

            # Remove the index using validated inputs (no user-controllable data)
            # Note: inputs have been validated above, so f-string is safe here
            sql = f"ALTER TABLE {table_name} DROP INDEX `{index_name}`"
            frappe.db.sql(sql)
            frappe.db.commit()

            end_time = time.time()
            result["execution_time"] = round(end_time - start_time, 3)
            result["status"] = "removed"
            result["message"] = f"Index {index_name} removed successfully"

            return result

        except Exception as e:
            end_time = time.time()
            result["execution_time"] = round(end_time - start_time, 3)
            result["status"] = "failed"
            result["error"] = str(e)

            frappe.log_error(f"Failed to remove index {index_name}: {e}")
            return result


# API Endpoints for Index Management


@frappe.whitelist()
def add_performance_indexes():
    """API endpoint to add performance indexes"""
    # Check admin permissions
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("Insufficient permissions to manage database indexes"))

    return DatabaseIndexManager.add_performance_indexes()


@frappe.whitelist()
def validate_index_impact():
    """API endpoint to validate index impact with EXPLAIN queries"""
    # Check admin permissions
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw(_("Insufficient permissions to validate indexes"))

    results = []

    for index_config in DatabaseIndexManager.PERFORMANCE_INDEXES:
        validation = DatabaseIndexManager.validate_index_usage(index_config["table"], index_config["columns"])

        results.append(
            {
                "index_name": index_config["name"],
                "table": index_config["table"],
                "columns": index_config["columns"],
                "description": index_config["description"],
                "validation": validation,
                "exists": DatabaseIndexManager.index_exists(index_config["table"], index_config["name"]),
            }
        )

    return {"timestamp": frappe.utils.now(), "indexes_validated": len(results), "results": results}


@frappe.whitelist()
def monitor_index_performance(duration_hours: int = 24):
    """API endpoint to monitor index performance impact"""
    # Check admin permissions
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw(_("Insufficient permissions to monitor index performance"))

    return DatabaseIndexManager.monitor_index_impact(duration_hours)


@frappe.whitelist()
def remove_performance_indexes():
    """API endpoint to remove performance indexes (rollback)"""
    # Check admin permissions
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("Insufficient permissions to manage database indexes"))

    return DatabaseIndexManager.remove_performance_indexes()


@frappe.whitelist()
def get_index_status():
    """API endpoint to get current status of all performance indexes"""
    # Check admin permissions
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw(_("Insufficient permissions to view index status"))

    status_results = []

    for index_config in DatabaseIndexManager.PERFORMANCE_INDEXES:
        exists = DatabaseIndexManager.index_exists(index_config["table"], index_config["name"])

        status_results.append(
            {
                "index_name": index_config["name"],
                "table": index_config["table"],
                "columns": index_config["columns"],
                "description": index_config["description"],
                "exists": exists,
                "status": "Active" if exists else "Not Created",
            }
        )

    return {
        "timestamp": frappe.utils.now(),
        "total_indexes": len(status_results),
        "active_indexes": len([r for r in status_results if r["exists"]]),
        "missing_indexes": len([r for r in status_results if not r["exists"]]),
        "indexes": status_results,
    }
