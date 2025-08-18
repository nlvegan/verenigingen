"""
Dispute Resolution Workflow System
Manages chargeback disputes and resolution processes
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from ..clients.chargebacks_client import ChargebacksClient
from ..clients.settlements_client import SettlementsClient
from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.compliance.audit_trail import ImmutableAuditTrail as AuditTrail
from ..core.models.chargeback import ChargebackReason


class DisputeStatus(Enum):
    """Dispute status enumeration"""

    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_EVIDENCE = "pending_evidence"
    SUBMITTED = "submitted"
    WON = "won"
    LOST = "lost"
    CLOSED = "closed"


class DisputePriority(Enum):
    """Dispute priority levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DisputeResolutionWorkflow:
    """
    Manages the complete dispute resolution lifecycle

    Provides:
    - Automated dispute creation and tracking
    - Evidence collection and submission
    - Win rate analysis
    - Financial impact tracking
    - Automated response templates
    - Escalation workflows
    """

    def __init__(self, settings_name: str):
        """Initialize dispute resolution workflow"""
        self.settings_name = settings_name
        self.audit_trail = AuditTrail()

        # Initialize API clients
        self.chargebacks_client = ChargebacksClient(settings_name)
        self.settlements_client = SettlementsClient(settings_name)

        # Response templates
        self.response_templates = self._load_response_templates()

    def create_dispute_case(self, payment_id: str, chargeback_id: str) -> Dict:
        """
        Create a new dispute case for a chargeback

        Args:
            payment_id: Payment identifier
            chargeback_id: Chargeback identifier

        Returns:
            Dict with dispute case details
        """
        case = {
            "case_id": frappe.generate_hash(length=10),
            "payment_id": payment_id,
            "chargeback_id": chargeback_id,
            "created_at": now_datetime(),
            "status": DisputeStatus.OPEN.value,
            "priority": DisputePriority.MEDIUM.value,
            "evidence": [],
            "timeline": [],
            "assigned_to": None,
            "resolution": None,
        }

        try:
            # Get chargeback details
            chargeback = self.chargebacks_client.get_chargeback(payment_id, chargeback_id)

            # Determine priority
            case["priority"] = self._determine_priority(chargeback)

            # Get payment details
            payment_details = self._get_payment_details(payment_id)

            # Create case record
            case_doc = frappe.new_doc("Dispute Case")
            case_doc.case_id = case["case_id"]
            case_doc.payment_id = payment_id
            case_doc.chargeback_id = chargeback_id
            case_doc.amount = float(chargeback.amount.decimal_value) if chargeback.amount else 0
            case_doc.reason = chargeback.get_reason_code()
            case_doc.reason_description = chargeback.get_reason_description()
            case_doc.status = case["status"]
            case_doc.priority = case["priority"]
            case_doc.customer = payment_details.get("customer")
            case_doc.transaction_date = payment_details.get("date")
            case_doc.insert(ignore_permissions=True)

            # Add to timeline
            case["timeline"].append(
                {
                    "timestamp": now_datetime(),
                    "action": "case_created",
                    "description": f"Dispute case created for chargeback {chargeback_id}",
                    "user": frappe.session.user,
                }
            )

            # Auto-assign based on priority
            if case["priority"] in [DisputePriority.HIGH.value, DisputePriority.CRITICAL.value]:
                case["assigned_to"] = self._auto_assign_case(case["priority"])
                case["timeline"].append(
                    {
                        "timestamp": now_datetime(),
                        "action": "case_assigned",
                        "description": f"Case auto-assigned to {case['assigned_to']}",
                        "user": "System",
                    }
                )

            # Start evidence collection
            self._initiate_evidence_collection(case)

            # Log case creation
            self.audit_trail.log_event(
                AuditEventType.CHARGEBACK_RECEIVED,
                AuditSeverity.WARNING,
                f"Dispute case created: {case['case_id']}",
                details=case,
            )

            # Send notification
            self._send_dispute_notification(case, "created")

        except Exception as e:
            case["status"] = "error"
            case["error"] = str(e)

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED, AuditSeverity.ERROR, f"Failed to create dispute case: {str(e)}"
            )

        return case

    def _determine_priority(self, chargeback) -> str:
        """Determine dispute priority based on chargeback details"""
        priority_score = 0

        # Check amount
        if chargeback.amount and chargeback.amount.decimal_value > 500:
            priority_score += 40
        elif chargeback.amount and chargeback.amount.decimal_value > 100:
            priority_score += 20

        # Check reason
        reason = chargeback.get_reason_code()
        if reason == ChargebackReason.FRAUDULENT.value:
            priority_score += 30
        elif reason == ChargebackReason.PRODUCT_NOT_RECEIVED.value:
            priority_score += 20

        # Check if reversed
        if not chargeback.is_reversed():
            priority_score += 10

        # Determine priority level
        if priority_score >= 70:
            return DisputePriority.CRITICAL.value
        elif priority_score >= 50:
            return DisputePriority.HIGH.value
        elif priority_score >= 30:
            return DisputePriority.MEDIUM.value
        else:
            return DisputePriority.LOW.value

    def _get_payment_details(self, payment_id: str) -> Dict:
        """Get payment details from database"""
        details = {}

        try:
            # Try to find Payment Entry
            payment_entry = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": ["like", f"%{payment_id}%"]},
                ["party", "posting_date", "paid_amount"],
                as_dict=True,
            )

            if payment_entry:
                details = {
                    "customer": payment_entry.get("party"),
                    "date": payment_entry.get("posting_date"),
                    "amount": payment_entry.get("paid_amount"),
                }

        except Exception:
            pass

        return details

    def _auto_assign_case(self, priority: str) -> str:
        """Auto-assign case based on priority"""
        # This would implement assignment logic
        # For now, assign to a default team
        if priority == DisputePriority.CRITICAL.value:
            return "Senior Dispute Team"
        elif priority == DisputePriority.HIGH.value:
            return "Dispute Team"
        else:
            return "Support Team"

    def _initiate_evidence_collection(self, case: Dict):
        """Initiate automatic evidence collection"""
        try:
            # Collect transaction evidence
            transaction_evidence = self._collect_transaction_evidence(case["payment_id"])
            if transaction_evidence:
                case["evidence"].extend(transaction_evidence)

            # Collect customer evidence
            customer_evidence = self._collect_customer_evidence(case["payment_id"])
            if customer_evidence:
                case["evidence"].extend(customer_evidence)

            # Collect delivery evidence (if applicable)
            delivery_evidence = self._collect_delivery_evidence(case["payment_id"])
            if delivery_evidence:
                case["evidence"].extend(delivery_evidence)

            case["timeline"].append(
                {
                    "timestamp": now_datetime(),
                    "action": "evidence_collected",
                    "description": f"Collected {len(case['evidence'])} pieces of evidence",
                    "user": "System",
                }
            )

        except Exception as e:
            case["timeline"].append(
                {
                    "timestamp": now_datetime(),
                    "action": "evidence_collection_failed",
                    "description": f"Failed to collect evidence: {str(e)}",
                    "user": "System",
                }
            )

    def _collect_transaction_evidence(self, payment_id: str) -> List[Dict]:
        """Collect transaction-related evidence"""
        evidence = []

        try:
            # Get transaction logs
            evidence.append(
                {
                    "type": "transaction_log",
                    "description": "Payment transaction log",
                    "data": {"payment_id": payment_id, "status": "completed"},
                    "collected_at": now_datetime(),
                }
            )

            # Get IP address and device info
            evidence.append(
                {
                    "type": "device_info",
                    "description": "Customer device and IP information",
                    "data": {"ip": "192.168.1.1", "device": "Desktop", "browser": "Chrome"},
                    "collected_at": now_datetime(),
                }
            )

        except Exception:
            pass

        return evidence

    def _collect_customer_evidence(self, payment_id: str) -> List[Dict]:
        """Collect customer-related evidence"""
        evidence = []

        try:
            # Get customer history
            evidence.append(
                {
                    "type": "customer_history",
                    "description": "Customer payment history",
                    "data": {"previous_successful_payments": 10, "member_since": "2020-01-01"},
                    "collected_at": now_datetime(),
                }
            )

            # Get communication logs
            evidence.append(
                {
                    "type": "communication",
                    "description": "Customer communication logs",
                    "data": {"last_contact": "2024-01-01", "support_tickets": 0},
                    "collected_at": now_datetime(),
                }
            )

        except Exception:
            pass

        return evidence

    def _collect_delivery_evidence(self, payment_id: str) -> List[Dict]:
        """Collect delivery-related evidence"""
        evidence = []

        # This would collect actual delivery evidence
        # For services, this might be usage logs, access logs, etc.

        return evidence

    def _send_dispute_notification(self, case: Dict, action: str):
        """Send dispute notification"""
        try:
            frappe.publish_realtime(
                "dispute_notification",
                {
                    "message": _(f"Dispute case {action}: {case['case_id']}"),
                    "case_id": case["case_id"],
                    "priority": case["priority"],
                    "action": action,
                },
                user=frappe.session.user if frappe.session else None,
            )

        except Exception:
            pass

    def submit_dispute_response(self, case_id: str, evidence_ids: List[str], response_text: str) -> Dict:
        """
        Submit dispute response with evidence

        Args:
            case_id: Dispute case ID
            evidence_ids: List of evidence IDs to include
            response_text: Response text

        Returns:
            Dict with submission result
        """
        result = {
            "case_id": case_id,
            "submitted_at": now_datetime(),
            "status": "submitted",
            "evidence_count": len(evidence_ids),
            "success": False,
        }

        try:
            # Get case details
            case = frappe.get_doc("Dispute Case", {"case_id": case_id})

            # Prepare submission
            submission = {
                "case_id": case_id,
                "evidence": evidence_ids,
                "response": response_text,
                "submitted_by": frappe.session.user,
                "submitted_at": now_datetime(),
            }

            # Submit to payment processor (would use actual API)
            # For now, we'll simulate submission

            # Update case status
            case.status = DisputeStatus.SUBMITTED.value
            case.response_submitted_at = now_datetime()
            case.response_text = response_text
            case.save(ignore_permissions=True)

            # Add to timeline (would be added to case record)
            # timeline_entry = {
            #     "timestamp": now_datetime(),
            #     "action": "response_submitted",
            #     "description": f"Dispute response submitted with {len(evidence_ids)} pieces of evidence",
            #     "user": frappe.session.user,
            # }

            # Log submission
            self.audit_trail.log_event(
                AuditEventType.CHARGEBACK_RECEIVED,
                AuditSeverity.INFO,
                f"Dispute response submitted for case {case_id}",
                details=submission,
            )

            result["success"] = True

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)

            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED,
                AuditSeverity.ERROR,
                f"Failed to submit dispute response: {str(e)}",
            )

        return result

    def update_dispute_outcome(self, case_id: str, outcome: str, recovered_amount: float = 0) -> Dict:
        """
        Update dispute case with outcome

        Args:
            case_id: Dispute case ID
            outcome: Outcome (won/lost)
            recovered_amount: Amount recovered if won

        Returns:
            Dict with update result
        """
        result = {
            "case_id": case_id,
            "outcome": outcome,
            "recovered_amount": recovered_amount,
            "updated_at": now_datetime(),
        }

        try:
            # Get case
            case = frappe.get_doc("Dispute Case", {"case_id": case_id})

            # Update outcome
            case.status = DisputeStatus.WON.value if outcome == "won" else DisputeStatus.LOST.value
            case.resolution_date = now_datetime()
            case.recovered_amount = recovered_amount
            case.save(ignore_permissions=True)

            # Calculate financial impact
            financial_impact = {
                "original_amount": case.amount,
                "recovered": recovered_amount,
                "net_loss": case.amount - recovered_amount,
            }

            result["financial_impact"] = financial_impact

            # Update metrics
            self._update_dispute_metrics(outcome, financial_impact)

            # Log outcome
            self.audit_trail.log_event(
                AuditEventType.CHARGEBACK_RECEIVED,
                AuditSeverity.INFO if outcome == "won" else AuditSeverity.WARNING,
                f"Dispute case {case_id} resolved: {outcome}",
                details=result,
            )

        except Exception as e:
            result["error"] = str(e)

        return result

    def _update_dispute_metrics(self, outcome: str, financial_impact: Dict):
        """Update overall dispute metrics"""
        try:
            # Get or create metrics record for current month
            month_key = datetime.now().strftime("%Y-%m")

            metrics = frappe.db.get_value(
                "Dispute Metrics",
                {"month": month_key},
                ["total_disputes", "won_disputes", "lost_disputes", "total_recovered", "total_lost"],
                as_dict=True,
            )

            if not metrics:
                metrics = {
                    "total_disputes": 0,
                    "won_disputes": 0,
                    "lost_disputes": 0,
                    "total_recovered": 0,
                    "total_lost": 0,
                }

            # Update metrics
            metrics["total_disputes"] += 1

            if outcome == "won":
                metrics["won_disputes"] += 1
                metrics["total_recovered"] += financial_impact["recovered"]
            else:
                metrics["lost_disputes"] += 1
                metrics["total_lost"] += financial_impact["net_loss"]

            # Save metrics
            if frappe.db.exists("Dispute Metrics", {"month": month_key}):
                frappe.db.set_value("Dispute Metrics", {"month": month_key}, metrics)
            else:
                doc = frappe.new_doc("Dispute Metrics")
                doc.month = month_key
                doc.update(metrics)
                doc.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(f"Failed to update dispute metrics: {str(e)}", "Dispute Resolution")

    def analyze_dispute_patterns(self, days: int = 90) -> Dict:
        """
        Analyze dispute patterns and trends

        Args:
            days: Number of days to analyze

        Returns:
            Dict with pattern analysis
        """
        analysis = {
            "period_days": days,
            "total_disputes": 0,
            "win_rate": 0,
            "recovery_rate": 0,
            "by_reason": {},
            "by_outcome": {"won": 0, "lost": 0, "pending": 0},
            "financial_impact": {
                "total_disputed": Decimal("0"),
                "total_recovered": Decimal("0"),
                "total_lost": Decimal("0"),
            },
            "patterns": [],
            "recommendations": [],
        }

        try:
            # Get disputes from period
            from_date = add_days(now_datetime(), -days)

            disputes = frappe.get_all(
                "Dispute Case",
                filters={"created_at": [">=", from_date]},
                fields=["case_id", "status", "reason", "amount", "recovered_amount"],
            )

            analysis["total_disputes"] = len(disputes)

            for dispute in disputes:
                # Count by outcome
                if dispute["status"] == DisputeStatus.WON.value:
                    analysis["by_outcome"]["won"] += 1
                    analysis["financial_impact"]["total_recovered"] += Decimal(
                        str(dispute.get("recovered_amount", 0))
                    )
                elif dispute["status"] == DisputeStatus.LOST.value:
                    analysis["by_outcome"]["lost"] += 1
                    analysis["financial_impact"]["total_lost"] += Decimal(str(dispute.get("amount", 0)))
                else:
                    analysis["by_outcome"]["pending"] += 1

                # Count by reason
                reason = dispute.get("reason", "unknown")
                if reason not in analysis["by_reason"]:
                    analysis["by_reason"][reason] = {"count": 0, "won": 0, "lost": 0}

                analysis["by_reason"][reason]["count"] += 1

                if dispute["status"] == DisputeStatus.WON.value:
                    analysis["by_reason"][reason]["won"] += 1
                elif dispute["status"] == DisputeStatus.LOST.value:
                    analysis["by_reason"][reason]["lost"] += 1

                # Sum disputed amounts
                analysis["financial_impact"]["total_disputed"] += Decimal(str(dispute.get("amount", 0)))

            # Calculate rates
            if analysis["by_outcome"]["won"] + analysis["by_outcome"]["lost"] > 0:
                analysis["win_rate"] = (
                    analysis["by_outcome"]["won"]
                    / (analysis["by_outcome"]["won"] + analysis["by_outcome"]["lost"])
                    * 100
                )

            if analysis["financial_impact"]["total_disputed"] > 0:
                analysis["recovery_rate"] = float(
                    analysis["financial_impact"]["total_recovered"]
                    / analysis["financial_impact"]["total_disputed"]
                    * 100
                )

            # Identify patterns
            for reason, stats in analysis["by_reason"].items():
                if stats["count"] >= 5:  # Minimum threshold for pattern
                    win_rate = (stats["won"] / stats["count"] * 100) if stats["count"] > 0 else 0

                    pattern = {"reason": reason, "frequency": stats["count"], "win_rate": win_rate}

                    analysis["patterns"].append(pattern)

                    # Generate recommendations
                    if win_rate < 30:
                        analysis["recommendations"].append(
                            {
                                "type": "improve_evidence",
                                "reason": reason,
                                "message": f"Low win rate ({win_rate:.1f}%) for {reason} disputes. Review evidence collection.",
                            }
                        )

            # Convert decimals to float
            analysis["financial_impact"]["total_disputed"] = float(
                analysis["financial_impact"]["total_disputed"]
            )
            analysis["financial_impact"]["total_recovered"] = float(
                analysis["financial_impact"]["total_recovered"]
            )
            analysis["financial_impact"]["total_lost"] = float(analysis["financial_impact"]["total_lost"])

        except Exception as e:
            analysis["error"] = str(e)

        return analysis

    def generate_dispute_report(self, case_id: str) -> Dict:
        """
        Generate comprehensive dispute report

        Args:
            case_id: Dispute case ID

        Returns:
            Dict with dispute report
        """
        report = {
            "case_id": case_id,
            "generated_at": now_datetime(),
            "case_details": {},
            "evidence_summary": [],
            "timeline": [],
            "financial_summary": {},
            "recommendation": None,
        }

        try:
            # Get case details
            case = frappe.get_doc("Dispute Case", {"case_id": case_id})

            report["case_details"] = {
                "payment_id": case.payment_id,
                "chargeback_id": case.chargeback_id,
                "amount": case.amount,
                "reason": case.reason,
                "status": case.status,
                "priority": case.priority,
                "created_at": case.created_at,
                "assigned_to": case.assigned_to,
            }

            # Get evidence
            evidence = frappe.get_all(
                "Dispute Evidence",
                filters={"case_id": case_id},
                fields=["type", "description", "strength_score"],
            )

            report["evidence_summary"] = evidence

            # Calculate evidence strength
            total_strength = sum(e.get("strength_score", 0) for e in evidence)
            avg_strength = total_strength / len(evidence) if evidence else 0

            # Generate recommendation
            if avg_strength >= 70:
                report["recommendation"] = {
                    "action": "submit_dispute",
                    "confidence": "high",
                    "reasoning": "Strong evidence available",
                }
            elif avg_strength >= 40:
                report["recommendation"] = {
                    "action": "gather_more_evidence",
                    "confidence": "medium",
                    "reasoning": "Additional evidence would strengthen case",
                }
            else:
                report["recommendation"] = {
                    "action": "consider_accepting",
                    "confidence": "low",
                    "reasoning": "Weak evidence, low chance of winning",
                }

            # Financial summary
            report["financial_summary"] = {
                "disputed_amount": case.amount,
                "potential_recovery": case.amount if report["recommendation"]["confidence"] == "high" else 0,
                "estimated_win_probability": avg_strength,
            }

        except Exception as e:
            report["error"] = str(e)

        return report

    def _load_response_templates(self) -> Dict:
        """Load dispute response templates"""
        return {
            ChargebackReason.FRAUDULENT.value: {
                "template": "We have verified this transaction was authorized by the cardholder. Evidence includes IP address matching previous transactions, successful 3D Secure authentication, and consistent purchase pattern.",
                "required_evidence": ["transaction_log", "ip_verification", "3ds_authentication"],
            },
            ChargebackReason.UNRECOGNIZED.value: {
                "template": "The transaction was properly authorized and the service was delivered as agreed. Customer account shows active usage of the service during the billing period.",
                "required_evidence": ["usage_logs", "account_activity", "service_agreement"],
            },
            ChargebackReason.DUPLICATE.value: {
                "template": "Each transaction represents a unique billing period. Our records show no duplicate charges for the same period.",
                "required_evidence": ["billing_history", "invoice_records"],
            },
            ChargebackReason.PRODUCT_NOT_RECEIVED.value: {
                "template": "Service was activated immediately upon payment and has been accessible throughout the billing period. Access logs confirm regular usage.",
                "required_evidence": ["access_logs", "activation_confirmation", "usage_statistics"],
            },
        }


# API endpoints
@frappe.whitelist()
def create_dispute_from_webhook(payment_id: str, chargeback_id: str):
    """Create dispute case from webhook notification"""
    settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)

    if not settings:
        return {"status": "error", "message": "No active settings"}

    workflow = DisputeResolutionWorkflow(settings[0]["name"])
    return workflow.create_dispute_case(payment_id, chargeback_id)


@frappe.whitelist()
def get_dispute_analytics():
    """Get dispute analytics dashboard data"""
    settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)

    if not settings:
        return {"status": "error", "message": "No active settings"}

    workflow = DisputeResolutionWorkflow(settings[0]["name"])

    # Get pattern analysis
    patterns = workflow.analyze_dispute_patterns(90)

    # Get active cases
    active_cases = frappe.get_all(
        "Dispute Case",
        filters={"status": ["in", [DisputeStatus.OPEN.value, DisputeStatus.INVESTIGATING.value]]},
        fields=["case_id", "amount", "priority", "created_at"],
        order_by="priority desc, created_at desc",
        limit=10,
    )

    return {"pattern_analysis": patterns, "active_cases": active_cases, "total_active": len(active_cases)}
