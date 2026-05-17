"""
Compliance Metrics Service

Provides compliance monitoring, regulatory tracking, and audit metrics
for the monitoring dashboard.

This service consolidates compliance-related logic that was previously
scattered across portal controllers.
"""

from typing import Any, Dict, List

import frappe
from frappe.utils import add_to_date, now

from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class ComplianceMetricsService:
    """
    Service for collecting and aggregating compliance metrics.

    This service provides:
    - SEPA compliance rate calculations
    - Audit trail completeness assessment
    - Regulatory violation tracking
    - Data retention compliance checking
    - Analytics summary for compliance dashboard
    """

    def get_compliance_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive compliance metrics for dashboard.

        Returns:
            Dict containing compliance scores, gaps, and status indicators.
        """
        try:
            return {
                "sepa_compliance_rate": self.get_sepa_compliance_rate(),
                "audit_completeness": self.calculate_audit_completeness(),
                "regulatory_violations": len(self.get_regulatory_violations()),
                "data_retention_status": self.check_data_retention_compliance(),
                "last_assessment": now(),
            }
        except Exception as e:
            frappe.log_error(f"Error getting compliance metrics: {str(e)}")
            return {"error": str(e)}

    def get_sepa_compliance_rate(self) -> float:
        """
        Calculate SEPA compliance rate.

        Returns:
            Compliance rate as a percentage (0-100).
        """
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                return 0.0

            total_mandates = frappe.db.count("SEPA Mandate")
            if total_mandates == 0:
                return 100.0  # No mandates = 100% compliance

            audited_mandates = frappe.db.count(
                "SEPA Audit Log",
                {"process_type": "Mandate Creation"},
            )

            return round((audited_mandates / total_mandates) * 100, 2)
        except Exception as e:
            frappe.log_error(f"Error calculating SEPA compliance rate: {str(e)}")
            return 0.0

    def calculate_audit_completeness(self) -> float:
        """
        Calculate audit trail completeness.

        Returns:
            Completeness percentage (0-100).
        """
        try:
            # Check key business processes for audit coverage
            processes = {
                "member_creation": frappe.db.count("Member"),
                "sepa_mandate_creation": frappe.db.count("SEPA Mandate"),
                "payment_processing": frappe.db.count("Payment Entry", {"docstatus": 1}),
            }

            # Count audit entries
            if DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                audit_entries = frappe.db.count("SEPA Audit Log")
            else:
                audit_entries = 0

            total_processes = sum(processes.values())
            if total_processes == 0:
                return 100.0

            coverage = min(100, (audit_entries / total_processes) * 100)
            return round(coverage, 2)
        except Exception as e:
            frappe.log_error(f"Error calculating audit completeness: {str(e)}")
            return 0.0

    def get_regulatory_violations(self) -> List[Dict[str, Any]]:
        """
        Get list of regulatory violations.

        Returns:
            List of violation records with type, count, and severity.
        """
        try:
            violations = []

            # Check for SEPA compliance violations
            if DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                failed_sepa = frappe.db.count(
                    "SEPA Audit Log",
                    {
                        "compliance_status": "Failed",
                        "timestamp": (">=", add_to_date(now(), days=-30)),
                    },
                )

                if failed_sepa > 0:
                    violations.append(
                        {
                            "type": "SEPA_COMPLIANCE",
                            "count": failed_sepa,
                            "severity": "high" if failed_sepa > 10 else "medium",
                        }
                    )

            return violations
        except Exception as e:
            frappe.log_error(f"Error getting regulatory violations: {str(e)}")
            return []

    def check_data_retention_compliance(self) -> str:
        """
        Check data retention compliance status.

        Returns:
            Status string: "compliant", "review_required", or "unknown".
        """
        try:
            # Check for very old error logs that might indicate retention policy issues
            old_error_logs = frappe.db.count(
                "Error Log",
                {"creation": ("<=", add_to_date(now(), years=-2))},
            )

            if old_error_logs > 1000:
                return "review_required"
            return "compliant"

        except Exception as e:
            frappe.log_error(f"Error checking data retention: {str(e)}")
            return "unknown"

    def get_unified_security_summary(self) -> Dict[str, Any]:
        """
        Get unified security summary combining security monitoring with SEPA security.

        Returns:
            Dict with unified security score and component breakdowns.
        """
        try:
            from verenigingen.api.security_monitoring_dashboard import get_security_dashboard_data
            from verenigingen.utils.security.security_monitoring import get_security_monitor

            # Get security monitoring data
            security_monitor = get_security_monitor()
            dashboard_data = security_monitor.get_security_dashboard()

            current_metrics = dashboard_data.get("current_metrics", {})
            base_score = current_metrics.get("security_score", 85.0) if current_metrics else 85.0

            # Get SEPA-specific security metrics
            sepa_security = self._get_sepa_security_metrics()

            # Calculate unified security score
            if sepa_security["mandate_validation_failures"] > 5:
                base_score -= 10
            if sepa_security["payment_security_events"] > 0:
                base_score -= 15

            unified_score = max(0, base_score)

            # Get framework health
            security_data = get_security_dashboard_data(hours_back=1)
            framework_health = {}
            if security_data.get("success"):
                framework_health = security_data.get("data", {}).get("framework_health", {})

            return {
                "unified_security_score": unified_score,
                "sepa_security": sepa_security,
                "framework_health": framework_health,
                "overall_status": (
                    "HEALTHY" if unified_score >= 80 else "DEGRADED" if unified_score >= 60 else "CRITICAL"
                ),
                "generated_at": now(),
            }

        except Exception as e:
            frappe.log_error(f"Error getting unified security summary: {str(e)}")
            return {
                "unified_security_score": 70.0,
                "sepa_security": {},
                "framework_health": {},
                "overall_status": "ERROR",
                "generated_at": now(),
                "error": str(e),
            }

    def _get_sepa_security_metrics(self) -> Dict[str, int]:
        """
        Get SEPA-specific security metrics.

        Returns:
            Dict with mandate validation failures and payment security events.
        """
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                return {"mandate_validation_failures": 0, "payment_security_events": 0}

            mandate_failures = frappe.db.count(
                "SEPA Audit Log",
                {
                    "process_type": "mandate_validation",
                    "compliance_status": ["in", ["FAILED", "ERROR"]],
                    "creation": (">=", add_to_date(now(), hours=-24)),
                },
            )

            payment_events = frappe.db.count(
                "SEPA Audit Log",
                {
                    "process_type": ["in", ["payment_processing", "batch_creation"]],
                    "compliance_status": ["in", ["FAILED", "ERROR"]],
                    "creation": (">=", add_to_date(now(), hours=-24)),
                },
            )

            return {
                "mandate_validation_failures": mandate_failures,
                "payment_security_events": payment_events,
            }
        except Exception:
            return {"mandate_validation_failures": 0, "payment_security_events": 0}
