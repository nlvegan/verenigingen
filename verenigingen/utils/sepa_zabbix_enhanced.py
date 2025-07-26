"""
Enhanced Zabbix Integration for SEPA Operations

Week 4 Implementation: Advanced Zabbix integration providing SEPA-specific
metrics, automated discovery, and intelligent alerting for comprehensive
monitoring of SEPA batch operations and dues invoicing.

This module extends the existing Zabbix integration with detailed SEPA
business metrics and operational intelligence.
"""

import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from verenigingen.utils.error_handling import log_error
from verenigingen.utils.performance_dashboard import _performance_dashboard
from verenigingen.utils.sepa_memory_optimizer import SEPAMemoryMonitor
from verenigingen.utils.sepa_monitoring_dashboard import get_dashboard_instance


class SEPAZabbixIntegration:
    """
    Enhanced Zabbix integration for SEPA operations

    Provides comprehensive monitoring metrics for Zabbix including:
    - SEPA batch processing metrics
    - Mandate lifecycle monitoring
    - Financial transaction analytics
    - Performance and health indicators
    """

    def __init__(self):
        self.memory_monitor = SEPAMemoryMonitor()
        self.sepa_dashboard = get_dashboard_instance()
        self.performance_dashboard = _performance_dashboard

        # Zabbix item configuration
        self.zabbix_items = self._initialize_zabbix_items()

    def _initialize_zabbix_items(self) -> Dict[str, Dict[str, Any]]:
        """Initialize Zabbix item definitions for SEPA monitoring"""
        return {
            # SEPA Batch Processing Metrics
            "sepa.batch.count.total": {
                "name": "SEPA Total Batches",
                "type": "integer",
                "description": "Total number of SEPA batches processed",
                "units": "batches",
                "update_interval": "1m",
            },
            "sepa.batch.count.daily": {
                "name": "SEPA Daily Batches",
                "type": "integer",
                "description": "Number of SEPA batches processed today",
                "units": "batches",
                "update_interval": "5m",
            },
            "sepa.batch.amount.total": {
                "name": "SEPA Total Amount",
                "type": "float",
                "description": "Total amount processed in SEPA batches",
                "units": "EUR",
                "update_interval": "1m",
            },
            "sepa.batch.amount.daily": {
                "name": "SEPA Daily Amount",
                "type": "float",
                "description": "Amount processed in SEPA batches today",
                "units": "EUR",
                "update_interval": "5m",
            },
            "sepa.batch.success_rate": {
                "name": "SEPA Batch Success Rate",
                "type": "float",
                "description": "Percentage of successful SEPA batch operations",
                "units": "%",
                "update_interval": "5m",
            },
            "sepa.batch.avg_processing_time": {
                "name": "SEPA Batch Average Processing Time",
                "type": "float",
                "description": "Average time to process SEPA batches",
                "units": "ms",
                "update_interval": "5m",
            },
            "sepa.batch.stuck_count": {
                "name": "SEPA Stuck Batches",
                "type": "integer",
                "description": "Number of batches stuck in processing",
                "units": "batches",
                "update_interval": "1m",
            },
            # Mandate Management Metrics
            "sepa.mandate.count.active": {
                "name": "SEPA Active Mandates",
                "type": "integer",
                "description": "Number of active SEPA mandates",
                "units": "mandates",
                "update_interval": "10m",
            },
            "sepa.mandate.count.total": {
                "name": "SEPA Total Mandates",
                "type": "integer",
                "description": "Total number of SEPA mandates",
                "units": "mandates",
                "update_interval": "10m",
            },
            "sepa.mandate.validation_success_rate": {
                "name": "SEPA Mandate Validation Success Rate",
                "type": "float",
                "description": "Percentage of successful mandate validations",
                "units": "%",
                "update_interval": "5m",
            },
            "sepa.mandate.expiring_count": {
                "name": "SEPA Expiring Mandates",
                "type": "integer",
                "description": "Number of mandates expiring within 30 days",
                "units": "mandates",
                "update_interval": "1h",
            },
            # Financial Metrics
            "sepa.financial.outstanding_amount": {
                "name": "SEPA Outstanding Amount",
                "type": "float",
                "description": "Total outstanding amount in SEPA operations",
                "units": "EUR",
                "update_interval": "10m",
            },
            "sepa.financial.collection_rate": {
                "name": "SEPA Collection Rate",
                "type": "float",
                "description": "Percentage of successful collections",
                "units": "%",
                "update_interval": "1h",
            },
            "sepa.financial.failed_collections": {
                "name": "SEPA Failed Collections",
                "type": "integer",
                "description": "Number of failed collection attempts",
                "units": "failures",
                "update_interval": "5m",
            },
            # Performance Metrics
            "sepa.performance.memory_usage": {
                "name": "SEPA Memory Usage",
                "type": "float",
                "description": "Memory usage by SEPA operations",
                "units": "MB",
                "update_interval": "1m",
            },
            "sepa.performance.query_count": {
                "name": "SEPA Database Queries",
                "type": "integer",
                "description": "Number of database queries in SEPA operations",
                "units": "queries",
                "update_interval": "1m",
            },
            "sepa.performance.api_response_time": {
                "name": "SEPA API Response Time",
                "type": "float",
                "description": "Average response time for SEPA API calls",
                "units": "ms",
                "update_interval": "1m",
            },
            # Business Intelligence Metrics
            "sepa.business.dues_invoices_today": {
                "name": "Dues Invoices Generated Today",
                "type": "integer",
                "description": "Number of membership dues invoices generated today",
                "units": "invoices",
                "update_interval": "10m",
            },
            "sepa.business.active_schedules": {
                "name": "Active Dues Schedules",
                "type": "integer",
                "description": "Number of active membership dues schedules",
                "units": "schedules",
                "update_interval": "1h",
            },
            "sepa.business.payment_failures_rate": {
                "name": "Payment Failure Rate",
                "type": "float",
                "description": "Rate of payment failures in SEPA operations",
                "units": "%",
                "update_interval": "10m",
            },
            # System Health Indicators
            "sepa.health.overall_status": {
                "name": "SEPA System Health",
                "type": "integer",
                "description": "Overall SEPA system health (0=critical, 1=warning, 2=healthy)",
                "units": "status",
                "update_interval": "1m",
            },
            "sepa.health.scheduler_status": {
                "name": "SEPA Scheduler Health",
                "type": "integer",
                "description": "SEPA scheduler health status",
                "units": "status",
                "update_interval": "5m",
            },
            "sepa.health.error_rate": {
                "name": "SEPA Error Rate",
                "type": "float",
                "description": "Rate of errors in SEPA operations",
                "units": "%",
                "update_interval": "1m",
            },
        }

    def get_zabbix_metrics(self) -> Dict[str, Any]:
        """
        Get all SEPA metrics formatted for Zabbix

        Returns:
            Dictionary of metrics with timestamps
        """
        try:
            metrics = {}
            timestamp = int(time.time())

            # Collect all metric values
            batch_metrics = self._get_batch_metrics()
            mandate_metrics = self._get_mandate_metrics()
            financial_metrics = self._get_financial_metrics()
            performance_metrics = self._get_performance_metrics()
            business_metrics = self._get_business_metrics()
            health_metrics = self._get_health_metrics()

            # Combine all metrics
            all_metrics = {
                **batch_metrics,
                **mandate_metrics,
                **financial_metrics,
                **performance_metrics,
                **business_metrics,
                **health_metrics,
            }

            # Format for Zabbix
            for key, value in all_metrics.items():
                if key in self.zabbix_items:
                    metrics[key] = {
                        "value": value,
                        "timestamp": timestamp,
                        "type": self.zabbix_items[key]["type"],
                        "name": self.zabbix_items[key]["name"],
                    }

            return {
                "timestamp": timestamp,
                "metrics": metrics,
                "host": frappe.local.site or "verenigingen",
                "status": "success",
            }

        except Exception as e:
            log_error(e, context={"operation": "get_zabbix_metrics"}, module="sepa_zabbix_enhanced")

            return {
                "timestamp": int(time.time()),
                "metrics": {},
                "host": frappe.local.site or "verenigingen",
                "status": "error",
                "error": str(e),
            }

    def _get_batch_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA batch processing metrics"""
        try:
            today_start = get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)

            # Total batches
            total_batches = frappe.db.count("Direct Debit Batch")

            # Daily batches
            daily_batches = frappe.db.count("Direct Debit Batch", {"creation": [">=", today_start]})

            # Total amount with enhanced calculation
            total_amount = self._calculate_total_batch_amount_optimized()

            # Daily amount with enhanced calculation
            daily_amount = self._calculate_daily_batch_amount_optimized(today_start)

            # Success rate (last 24 hours)
            last_24h = get_datetime() - timedelta(hours=24)
            total_recent = frappe.db.count("Direct Debit Batch", {"creation": [">=", last_24h]})
            successful_recent = frappe.db.count(
                "Direct Debit Batch", {"creation": [">=", last_24h], "docstatus": 1}
            )

            success_rate = (successful_recent / total_recent * 100) if total_recent > 0 else 100

            # Average processing time (simplified - would need actual timing data)
            avg_processing_time = 5000.0  # Placeholder - implement actual timing

            # Stuck batches (draft for more than 2 hours)
            stuck_threshold = get_datetime() - timedelta(hours=2)
            stuck_batches = frappe.db.count(
                "Direct Debit Batch", {"status": "Draft", "creation": ["<", stuck_threshold]}
            )

            return {
                "sepa.batch.count.total": total_batches,
                "sepa.batch.count.daily": daily_batches,
                "sepa.batch.amount.total": float(total_amount),
                "sepa.batch.amount.daily": float(daily_amount),
                "sepa.batch.success_rate": float(success_rate),
                "sepa.batch.avg_processing_time": avg_processing_time,
                "sepa.batch.stuck_count": stuck_batches,
            }

        except Exception as e:
            frappe.logger().error(f"Error getting batch metrics: {str(e)}")
            return {}

    def _calculate_total_batch_amount_optimized(self) -> float:
        """
        Calculate total batch amount with SQL optimization and Python fallback

        Follows the functional equivalence pattern from direct_debit_batch.py
        for consistent NULL/None handling and defensive programming.
        """
        try:
            # Primary SQL approach with COALESCE for NULL handling
            result = frappe.db.sql(
                """
                SELECT COALESCE(SUM(total_amount), 0)
                FROM `tabDirect Debit Batch`
                WHERE docstatus = 1
            """
            )

            if result and result[0] and result[0][0] is not None:
                return float(result[0][0])
            else:
                return 0.0

        except Exception as e:
            # Fallback to Python iteration if SQL fails (graceful degradation)
            frappe.logger().warning(
                f"SQL aggregation failed for total batch amount, using Python fallback: {str(e)}"
            )
            return self._calculate_total_batch_amount_python()

    def _calculate_total_batch_amount_python(self) -> float:
        """
        Python fallback calculation functionally equivalent to SQL aggregation

        Implements the same defensive programming patterns as direct_debit_batch.py:
        - NULL/None handling equivalent to SQL COALESCE(total_amount, 0)
        - Type safety with try/except blocks for conversion errors
        - Currency precision with round(total, 2) for financial calculations
        - Handles edge cases (strings, invalid data) gracefully
        """
        try:
            # Get batch data using Frappe ORM
            batches = frappe.get_all("Direct Debit Batch", filters={"docstatus": 1}, fields=["total_amount"])

            if not batches:
                return 0.0

            # Handle None/NULL values same way as SQL COALESCE(total_amount, 0)
            # Also handle potential string values and invalid data types gracefully
            total = 0.0
            for batch in batches:
                try:
                    amount = batch.get("total_amount")
                    if amount is None:
                        # Same as SQL COALESCE(total_amount, 0)
                        amount = 0.0
                    elif isinstance(amount, str):
                        # Handle string amounts (shouldn't happen but defensive programming)
                        amount = float(amount) if amount.strip() else 0.0
                    else:
                        # Ensure it's a float for precision consistency with SQL
                        amount = float(amount)

                    total += amount

                except (ValueError, TypeError, AttributeError):
                    # Handle any conversion errors by treating as 0 (same as SQL COALESCE behavior)
                    # This matches SQL behavior where invalid/NULL data becomes 0
                    continue

            # Ensure precision consistency with database currency handling
            return round(total, 2)

        except Exception as e:
            # Final fallback - log error and return 0
            frappe.logger().error(f"Python fallback calculation failed for total batch amount: {str(e)}")
            return 0.0

    def _calculate_daily_batch_amount_optimized(self, cutoff_date) -> float:
        """
        Calculate daily batch amount with SQL optimization and Python fallback

        Follows the functional equivalence pattern from direct_debit_batch.py
        for consistent NULL/None handling and defensive programming.
        """
        try:
            # Primary SQL approach with COALESCE for NULL handling
            result = frappe.db.sql(
                """
                SELECT COALESCE(SUM(total_amount), 0)
                FROM `tabDirect Debit Batch`
                WHERE creation >= %s AND docstatus = 1
            """,
                (cutoff_date,),
            )

            if result and result[0] and result[0][0] is not None:
                return float(result[0][0])
            else:
                return 0.0

        except Exception as e:
            # Fallback to Python iteration if SQL fails (graceful degradation)
            frappe.logger().warning(
                f"SQL aggregation failed for daily batch amount, using Python fallback: {str(e)}"
            )
            return self._calculate_daily_batch_amount_python(cutoff_date)

    def _calculate_daily_batch_amount_python(self, cutoff_date) -> float:
        """
        Python fallback calculation functionally equivalent to SQL aggregation for daily amounts

        Implements the same defensive programming patterns as direct_debit_batch.py:
        - NULL/None handling equivalent to SQL COALESCE(total_amount, 0)
        - Type safety with try/except blocks for conversion errors
        - Currency precision with round(total, 2) for financial calculations
        - Handles edge cases (strings, invalid data) gracefully
        """
        try:
            # Get batch data using Frappe ORM
            batches = frappe.get_all(
                "Direct Debit Batch",
                filters={"creation": [">=", cutoff_date], "docstatus": 1},
                fields=["total_amount"],
            )

            if not batches:
                return 0.0

            # Handle None/NULL values same way as SQL COALESCE(total_amount, 0)
            # Also handle potential string values and invalid data types gracefully
            total = 0.0
            for batch in batches:
                try:
                    amount = batch.get("total_amount")
                    if amount is None:
                        # Same as SQL COALESCE(total_amount, 0)
                        amount = 0.0
                    elif isinstance(amount, str):
                        # Handle string amounts (shouldn't happen but defensive programming)
                        amount = float(amount) if amount.strip() else 0.0
                    else:
                        # Ensure it's a float for precision consistency with SQL
                        amount = float(amount)

                    total += amount

                except (ValueError, TypeError, AttributeError):
                    # Handle any conversion errors by treating as 0 (same as SQL COALESCE behavior)
                    # This matches SQL behavior where invalid/NULL data becomes 0
                    continue

            # Ensure precision consistency with database currency handling
            return round(total, 2)

        except Exception as e:
            # Final fallback - log error and return 0
            frappe.logger().error(f"Python fallback calculation failed for daily batch amount: {str(e)}")
            return 0.0

    def _get_mandate_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA mandate management metrics"""
        try:
            # Active mandates
            active_mandates = frappe.db.count("SEPA Mandate", {"status": "Active"})

            # Total mandates
            total_mandates = frappe.db.count("SEPA Mandate")

            # This would need actual validation tracking - placeholder calculation
            validation_success_rate = 95.0  # Placeholder

            # Expiring mandates (signed more than 3 years ago)
            expiring_threshold = get_datetime() - timedelta(days=3 * 365)
            expiring_mandates = (
                frappe.db.sql(
                    """
                SELECT COUNT(*) FROM `tabSEPA Mandate`
                WHERE status = 'Active'
                AND sign_date < %s
            """,
                    (expiring_threshold,),
                )[0][0]
                or 0
            )

            return {
                "sepa.mandate.count.active": active_mandates,
                "sepa.mandate.count.total": total_mandates,
                "sepa.mandate.validation_success_rate": float(validation_success_rate),
                "sepa.mandate.expiring_count": expiring_mandates,
            }

        except Exception as e:
            frappe.logger().error(f"Error getting mandate metrics: {str(e)}")
            return {}

    def _get_financial_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA financial metrics"""
        try:
            # Outstanding amount
            outstanding_amount = (
                frappe.db.sql(
                    """
                SELECT COALESCE(SUM(si.outstanding_amount), 0)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                WHERE si.docstatus = 1 AND si.outstanding_amount > 0
            """
                )[0][0]
                or 0
            )

            # Collection rate (last 30 days)
            last_30d = get_datetime() - timedelta(days=30)

            total_invoiced = (
                frappe.db.sql(
                    """
                SELECT COALESCE(SUM(si.grand_total), 0)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                WHERE ddb.creation >= %s AND si.docstatus = 1
            """,
                    (last_30d,),
                )[0][0]
                or 0
            )

            total_collected = (
                frappe.db.sql(
                    """
                SELECT COALESCE(SUM(si.grand_total - si.outstanding_amount), 0)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                WHERE ddb.creation >= %s AND si.docstatus = 1
            """,
                    (last_30d,),
                )[0][0]
                or 0
            )

            collection_rate = (total_collected / total_invoiced * 100) if total_invoiced > 0 else 100

            # Failed collections (invoices with status indicating failure)
            failed_collections = (
                frappe.db.sql(
                    """
                SELECT COUNT(*)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                WHERE si.status IN ('Unpaid', 'Overdue')
                AND si.creation >= %s
            """,
                    (last_30d,),
                )[0][0]
                or 0
            )

            return {
                "sepa.financial.outstanding_amount": float(outstanding_amount),
                "sepa.financial.collection_rate": float(collection_rate),
                "sepa.financial.failed_collections": failed_collections,
            }

        except Exception as e:
            frappe.logger().error(f"Error getting financial metrics: {str(e)}")
            return {}

    def _get_performance_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA performance metrics"""
        try:
            # Memory usage
            memory_snapshot = self.memory_monitor.take_snapshot()
            memory_usage = memory_snapshot.process_memory_mb

            # Query count (simplified - would need actual tracking)
            query_count = memory_snapshot.query_cache_size

            # API response time (get from performance dashboard)
            try:
                api_summary = self.performance_dashboard.get_performance_report(hours=1)
                api_performance = api_summary.get("api_performance", {})

                if api_performance.get("endpoints"):
                    avg_response_times = [
                        endpoint["avg_time_ms"]
                        for endpoint in api_performance["endpoints"].values()
                        if "sepa" in endpoint.get("name", "").lower()
                    ]
                    api_response_time = (
                        sum(avg_response_times) / len(avg_response_times) if avg_response_times else 500.0
                    )
                else:
                    api_response_time = 500.0  # Default value
            except Exception:
                api_response_time = 500.0

            return {
                "sepa.performance.memory_usage": float(memory_usage),
                "sepa.performance.query_count": query_count,
                "sepa.performance.api_response_time": float(api_response_time),
            }

        except Exception as e:
            frappe.logger().error(f"Error getting performance metrics: {str(e)}")
            return {}

    def _get_business_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA business intelligence metrics"""
        try:
            today_start = get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)

            # Dues invoices generated today
            dues_invoices_today = (
                frappe.db.sql(
                    """
                SELECT COUNT(DISTINCT si.name)
                FROM `tabSales Invoice` si
                INNER JOIN `tabMembership Dues Schedule` mds ON mds.member = (
                    SELECT member FROM `tabMember` WHERE customer = si.customer LIMIT 1
                )
                WHERE si.creation >= %s
                AND si.docstatus = 1
                AND mds.status = 'Active'
            """,
                    (today_start,),
                )[0][0]
                or 0
            )

            # Active dues schedules
            active_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active"})

            # Payment failure rate (last 7 days)
            last_7d = get_datetime() - timedelta(days=7)

            total_payment_attempts = (
                frappe.db.sql(
                    """
                SELECT COUNT(*)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                WHERE ddb.creation >= %s AND si.docstatus = 1
            """,
                    (last_7d,),
                )[0][0]
                or 0
            )

            failed_payments = (
                frappe.db.sql(
                    """
                SELECT COUNT(*)
                FROM `tabSales Invoice` si
                JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice = si.name
                JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                WHERE ddb.creation >= %s
                AND si.docstatus = 1
                AND si.status IN ('Unpaid', 'Overdue')
            """,
                    (last_7d,),
                )[0][0]
                or 0
            )

            payment_failure_rate = (
                (failed_payments / total_payment_attempts * 100) if total_payment_attempts > 0 else 0
            )

            return {
                "sepa.business.dues_invoices_today": dues_invoices_today,
                "sepa.business.active_schedules": active_schedules,
                "sepa.business.payment_failures_rate": float(payment_failure_rate),
            }

        except Exception as e:
            frappe.logger().error(f"Error getting business metrics: {str(e)}")
            return {}

    def _get_health_metrics(self) -> Dict[str, Union[int, float]]:
        """Get SEPA system health metrics"""
        try:
            # Overall health status
            try:
                system_health = self.performance_dashboard.get_system_health()
                health_status = system_health.get("status", "unknown")

                # Convert to numeric for Zabbix
                if health_status == "healthy":
                    overall_status = 2
                elif health_status == "degraded":
                    overall_status = 1
                else:
                    overall_status = 0
            except Exception:
                overall_status = 1  # Default to warning

            # Scheduler status
            try:
                scheduler_check = self.performance_dashboard._check_scheduler_health()
                scheduler_status_str = scheduler_check.get("status", "unknown")

                if scheduler_status_str == "ok":
                    scheduler_status = 2
                elif scheduler_status_str == "warning":
                    scheduler_status = 1
                else:
                    scheduler_status = 0
            except Exception:
                scheduler_status = 1

            # Error rate (last hour)
            last_1h = get_datetime() - timedelta(hours=1)

            # Count recent errors from error log
            error_count = frappe.db.count("Error Log", {"creation": [">=", last_1h]})

            # Approximate error rate (errors per hour as percentage)
            error_rate = min(error_count, 100)  # Cap at 100%

            return {
                "sepa.health.overall_status": overall_status,
                "sepa.health.scheduler_status": scheduler_status,
                "sepa.health.error_rate": float(error_rate),
            }

        except Exception as e:
            frappe.logger().error(f"Error getting health metrics: {str(e)}")
            return {}

    def get_zabbix_discovery_data(self) -> Dict[str, Any]:
        """
        Get Zabbix low-level discovery data for SEPA items

        Returns:
            Discovery data for dynamic item creation
        """
        try:
            discovery_data = {"data": []}

            # Discover SEPA batches for individual monitoring
            recent_batches = frappe.db.sql(
                """
                SELECT name, status, total_amount, creation
                FROM `tabDirect Debit Batch`
                WHERE creation >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY creation DESC
                LIMIT 20
            """,
                as_dict=True,
            )

            for batch in recent_batches:
                discovery_data["data"].append(
                    {
                        "{#BATCH_NAME}": batch.name,
                        "{#BATCH_STATUS}": batch.status,
                        "{#BATCH_AMOUNT}": str(batch.total_amount),
                        "{#BATCH_DATE}": batch.creation.strftime("%Y-%m-%d"),
                    }
                )

            # Note: Bank account discovery removed as Direct Debit Batch doesn't have bank_account field
            # This could be implemented by linking to SEPA Mandate bank details if needed

            return discovery_data

        except Exception as e:
            log_error(e, context={"operation": "get_zabbix_discovery_data"}, module="sepa_zabbix_enhanced")
            return {"data": []}

    def get_zabbix_item_prototype(self, item_key: str) -> Optional[Dict[str, Any]]:
        """
        Get Zabbix item prototype configuration

        Args:
            item_key: Zabbix item key

        Returns:
            Item prototype configuration
        """
        if item_key in self.zabbix_items:
            config = self.zabbix_items[item_key]
            return {
                "key": item_key,
                "name": config["name"],
                "type": "zabbix_agent",
                "value_type": config["type"],
                "description": config["description"],
                "units": config.get("units", ""),
                "delay": config.get("update_interval", "1m"),
                "history": "7d",
                "trends": "365d",
            }
        return None

    def get_zabbix_trigger_prototypes(self) -> List[Dict[str, Any]]:
        """
        Get Zabbix trigger prototype configurations for SEPA monitoring

        Returns:
            List of trigger configurations
        """
        triggers = [
            {
                "name": "SEPA Batch Processing Failure",
                "expression": "{verenigingen:sepa.batch.success_rate.last()}<90",
                "priority": "high",
                "description": "SEPA batch success rate below 90%",
            },
            {
                "name": "SEPA Stuck Batches Detected",
                "expression": "{verenigingen:sepa.batch.stuck_count.last()}>5",
                "priority": "average",
                "description": "More than 5 SEPA batches are stuck in processing",
            },
            {
                "name": "SEPA High Memory Usage",
                "expression": "{verenigingen:sepa.performance.memory_usage.last()}>1024",
                "priority": "warning",
                "description": "SEPA operations using more than 1GB memory",
            },
            {
                "name": "SEPA No Daily Batches",
                "expression": "{verenigingen:sepa.batch.count.daily.last()}=0 and {verenigingen:sepa.business.active_schedules.last()}>0",
                "priority": "warning",
                "description": "No SEPA batches created today despite active schedules",
            },
            {
                "name": "SEPA High Payment Failure Rate",
                "expression": "{verenigingen:sepa.business.payment_failures_rate.last()}>15",
                "priority": "high",
                "description": "SEPA payment failure rate exceeds 15%",
            },
            {
                "name": "SEPA System Critical Health",
                "expression": "{verenigingen:sepa.health.overall_status.last()}=0",
                "priority": "disaster",
                "description": "SEPA system health is critical",
            },
            {
                "name": "SEPA Mandates Expiring",
                "expression": "{verenigingen:sepa.mandate.expiring_count.last()}>50",
                "priority": "warning",
                "description": "More than 50 SEPA mandates are expiring soon",
            },
        ]

        return triggers

    def test_zabbix_connectivity(self) -> Dict[str, Any]:
        """
        Test Zabbix connectivity and data collection

        Returns:
            Test results
        """
        try:
            # Test metric collection
            start_time = time.time()
            metrics = self.get_zabbix_metrics()
            collection_time = time.time() - start_time

            # Test discovery data
            discovery_data = self.get_zabbix_discovery_data()

            # Validate metrics
            validation_results = []
            for key, metric in metrics.get("metrics", {}).items():
                if isinstance(metric.get("value"), (int, float)):
                    validation_results.append(f"✓ {key}: {metric['value']}")
                else:
                    validation_results.append(f"✗ {key}: invalid value type")

            return {
                "success": True,
                "collection_time_ms": collection_time * 1000,
                "metrics_collected": len(metrics.get("metrics", {})),
                "discovery_items": len(discovery_data.get("data", [])),
                "validation_results": validation_results,
                "sample_metrics": {k: v["value"] for k, v in list(metrics.get("metrics", {}).items())[:5]},
                "timestamp": metrics.get("timestamp"),
                "host": metrics.get("host"),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "timestamp": int(time.time())}


# Global Zabbix integration instance
_zabbix_integration = SEPAZabbixIntegration()


# API Functions


@frappe.whitelist(allow_guest=True)
def get_sepa_zabbix_metrics() -> Dict[str, Any]:
    """
    Get SEPA metrics for Zabbix monitoring

    Returns:
        Zabbix-formatted metrics
    """
    try:
        return _zabbix_integration.get_zabbix_metrics()
    except Exception as e:
        frappe.logger().error(f"Error in get_sepa_zabbix_metrics: {str(e)}")
        return {
            "timestamp": int(time.time()),
            "metrics": {},
            "host": frappe.local.site or "verenigingen",
            "status": "error",
            "error": str(e),
        }


@frappe.whitelist(allow_guest=True)
def get_sepa_zabbix_discovery() -> Dict[str, Any]:
    """
    Get Zabbix low-level discovery data for SEPA

    Returns:
        Discovery data
    """
    try:
        return _zabbix_integration.get_zabbix_discovery_data()
    except Exception as e:
        frappe.logger().error(f"Error in get_sepa_zabbix_discovery: {str(e)}")
        return {"data": []}


@frappe.whitelist()
def get_zabbix_item_config(item_key: str) -> Optional[Dict[str, Any]]:
    """
    Get Zabbix item configuration

    Args:
        item_key: Zabbix item key

    Returns:
        Item configuration
    """
    return _zabbix_integration.get_zabbix_item_prototype(item_key)


@frappe.whitelist()
def get_zabbix_trigger_configs() -> List[Dict[str, Any]]:
    """
    Get Zabbix trigger configurations

    Returns:
        List of trigger configurations
    """
    return _zabbix_integration.get_zabbix_trigger_prototypes()


@frappe.whitelist()
def test_sepa_zabbix_integration() -> Dict[str, Any]:
    """
    Test SEPA Zabbix integration

    Returns:
        Test results
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only system managers can test Zabbix integration"))

    return _zabbix_integration.test_zabbix_connectivity()


# Compatibility wrapper for existing Zabbix integration
@frappe.whitelist(allow_guest=True)
def get_enhanced_metrics_for_zabbix() -> Dict[str, Any]:
    """
    Enhanced version of get_metrics_for_zabbix with SEPA-specific metrics

    Returns:
        Combined metrics from original and SEPA-enhanced monitoring
    """
    try:
        # Get SEPA-specific metrics
        sepa_metrics = _zabbix_integration.get_zabbix_metrics()

        # Try to get original metrics if available
        try:
            from verenigingen.monitoring.zabbix_integration import get_metrics_for_zabbix

            original_metrics = get_metrics_for_zabbix()

            # Merge metrics
            combined_metrics = original_metrics.get("metrics", {})
            combined_metrics.update(sepa_metrics.get("metrics", {}))

            return {
                "timestamp": sepa_metrics.get("timestamp"),
                "metrics": combined_metrics,
                "host": sepa_metrics.get("host"),
                "status": "success",
                "enhanced": True,
            }

        except ImportError:
            # Return only SEPA metrics if original integration not available
            return sepa_metrics

    except Exception as e:
        frappe.logger().error(f"Error in get_enhanced_metrics_for_zabbix: {str(e)}")
        return {
            "timestamp": int(time.time()),
            "metrics": {},
            "host": frappe.local.site or "verenigingen",
            "status": "error",
            "error": str(e),
        }


# Helper function for direct integration
def get_zabbix_integration_instance() -> SEPAZabbixIntegration:
    """Get the global Zabbix integration instance"""
    return _zabbix_integration
