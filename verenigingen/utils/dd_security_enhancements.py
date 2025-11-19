"""
SEPA Direct Debit Security Enhancements
Comprehensive security framework for DD batch processing with focus on:
- Member identity validation and duplicate detection
- Bank account sharing validation
- Fraud detection and prevention
- Enhanced audit logging
"""

import difflib
import re
from typing import Dict, List

import frappe
from frappe.utils import now_datetime, today


class MemberIdentityValidator:
    """Advanced member identity validation to prevent confusion and fraud"""

    def __init__(self):
        self.similarity_threshold = 0.8  # 80% similarity threshold
        self.phonetic_threshold = 0.9  # 90% phonetic similarity

    def detect_potential_duplicates(self, member_data: Dict) -> Dict:
        """
        Detect potential duplicate members using multiple algorithms

        Args:
            member_data: Dict containing member information

        Returns:
            Dict with potential duplicates and confidence scores
        """
        results = {"potential_duplicates": [], "high_risk_matches": [], "recommendations": []}

        try:
            # Get all active members for comparison
            existing_members = frappe.get_all(
                "Member",
                filters={"status": ["in", ["Active", "Pending"]]},
                fields=["name", "first_name", "last_name", "email", "iban", "birth_date", "address_display"],
            )

            new_full_name = f"{member_data.get('first_name', '')} {member_data.get('last_name', '')}".strip()
            new_email = member_data.get("email", "").lower()
            new_iban = self._normalize_iban(member_data.get("iban", ""))

            for member in existing_members:
                if member.name == member_data.get("name"):
                    continue  # Skip self if updating existing member

                existing_full_name = f"{member.first_name or ''} {member.last_name or ''}".strip()

                # Name similarity check
                name_similarity = self._calculate_name_similarity(new_full_name, existing_full_name)

                # Email similarity check
                email_similarity = 0
                if member.email and new_email:
                    email_similarity = difflib.SequenceMatcher(None, new_email, member.email.lower()).ratio()

                # IBAN exact match check
                iban_match = False
                if member.iban and new_iban:
                    existing_iban = self._normalize_iban(member.iban)
                    iban_match = new_iban == existing_iban

                # Calculate overall risk score
                risk_score = self._calculate_risk_score(
                    {
                        "name_similarity": name_similarity,
                        "email_similarity": email_similarity,
                        "iban_match": iban_match,
                        "birth_date_match": member.birth_date == member_data.get("birth_date"),
                    }
                )

                if risk_score > 0.5:  # 50% risk threshold
                    duplicate_info = {
                        "existing_member": member.name,
                        "existing_name": existing_full_name,
                        "existing_email": member.email,
                        "existing_iban": member.iban,
                        "risk_score": risk_score,
                        "name_similarity": name_similarity,
                        "email_similarity": email_similarity,
                        "iban_match": iban_match,
                        "match_reasons": self._get_match_reasons(
                            name_similarity, email_similarity, iban_match
                        ),
                    }

                    if risk_score > 0.8:  # High risk threshold
                        results["high_risk_matches"].append(duplicate_info)
                    else:
                        results["potential_duplicates"].append(duplicate_info)

            # Generate recommendations
            results["recommendations"] = self._generate_recommendations(results)

            return results

        except Exception as e:
            frappe.log_error(f"Error in duplicate detection: {str(e)}", "Member Identity Validation Error")
            return {"error": str(e)}

    def validate_unique_bank_account(self, iban: str, member_id: str = None) -> Dict:
        """
        Validate that IBAN is not inappropriately shared across members

        Args:
            iban: IBAN to validate
            member_id: Current member ID (for updates)

        Returns:
            Dict with validation results and recommendations
        """
        normalized_iban = self._normalize_iban(iban)
        if not normalized_iban:
            return {"valid": False, "error": "Invalid IBAN format"}

        # Find all members using this IBAN
        filters = {"iban": normalized_iban}
        if member_id:
            filters["name"] = ["!=", member_id]

        existing_users = frappe.get_all(
            "Member",
            filters=filters,
            fields=["name", "first_name", "last_name", "email", "status", "member_since"],
        )

        if not existing_users:
            return {"valid": True, "message": "IBAN is unique"}

        # Analyze the sharing pattern
        analysis = self._analyze_iban_sharing(existing_users, member_id)

        return {
            "valid": analysis["allowed"],
            "existing_users": existing_users,
            "sharing_analysis": analysis,
            "recommendations": analysis["recommendations"],
        }

    def detect_payment_anomalies(self, batch_data: List[Dict]) -> Dict:
        """
        Detect unusual payment patterns that might indicate fraud or errors

        Args:
            batch_data: List of payment records

        Returns:
            Dict with anomaly analysis
        """
        anomalies = {
            "suspicious_patterns": [],
            "warnings": [],
            "blocked_transactions": [],
            "recommendations": [],
        }

        try:
            # Group by IBAN for analysis
            iban_groups = {}
            for payment in batch_data:
                iban = self._normalize_iban(payment.get("iban", ""))
                if iban not in iban_groups:
                    iban_groups[iban] = []
                iban_groups[iban].append(payment)

            # Analyze each IBAN group
            for iban, payments in iban_groups.items():
                if len(payments) > 1:
                    # Multiple payments from same account
                    analysis = self._analyze_multiple_payments(iban, payments)
                    if analysis["risk_level"] > 0.5:
                        anomalies["suspicious_patterns"].append(analysis)

                # Check individual payment amounts
                for payment in payments:
                    amount_analysis = self._analyze_payment_amount(payment)
                    if amount_analysis["anomaly"]:
                        anomalies["warnings"].append(amount_analysis)

            # Generate blocking recommendations
            anomalies["blocked_transactions"] = self._identify_blocked_transactions(anomalies)
            anomalies["recommendations"] = self._generate_anomaly_recommendations(anomalies)

            return anomalies

        except Exception as e:
            frappe.log_error(f"Error in anomaly detection: {str(e)}", "Payment Anomaly Detection Error")
            return {"error": str(e)}

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate name similarity using multiple algorithms"""
        if not name1 or not name2:
            return 0.0

        name1 = name1.lower().strip()
        name2 = name2.lower().strip()

        # Exact match
        if name1 == name2:
            return 1.0

        # Sequence similarity
        seq_similarity = difflib.SequenceMatcher(None, name1, name2).ratio()

        # Word-level similarity (handles different ordering)
        words1 = set(name1.split())
        words2 = set(name2.split())
        word_similarity = len(words1.intersection(words2)) / max(len(words1), len(words2))

        # Take the maximum of both approaches
        return max(seq_similarity, word_similarity)

    def _normalize_iban(self, iban: str) -> str:
        """Normalize IBAN format for comparison"""
        if not iban:
            return ""
        return re.sub(r"[^A-Z0-9]", "", iban.upper())

    def _calculate_risk_score(self, factors: Dict) -> float:
        """Calculate overall risk score from multiple factors"""
        weights = {
            "name_similarity": 0.4,
            "email_similarity": 0.3,
            "iban_match": 0.2,
            "birth_date_match": 0.1,
        }

        score = 0.0
        for factor, value in factors.items():
            if factor in weights:
                if isinstance(value, bool):
                    value = 1.0 if value else 0.0
                score += weights[factor] * value

        return min(score, 1.0)

    def _get_match_reasons(self, name_sim: float, email_sim: float, iban_match: bool) -> List[str]:
        """Generate list of match reasons for human review"""
        reasons = []

        if name_sim > 0.8:
            reasons.append(f"Very similar names ({name_sim:.1%} similarity)")
        elif name_sim > 0.6:
            reasons.append(f"Similar names ({name_sim:.1%} similarity)")

        if email_sim > 0.8:
            reasons.append(f"Very similar emails ({email_sim:.1%} similarity)")
        elif email_sim > 0.6:
            reasons.append(f"Similar emails ({email_sim:.1%} similarity)")

        if iban_match:
            reasons.append("Identical IBAN (same bank account)")

        return reasons

    def _analyze_iban_sharing(self, existing_users: List[Dict], current_member: str = None) -> Dict:
        """Analyze IBAN sharing pattern to determine if it's legitimate"""
        analysis = {"pattern": "single_user", "allowed": True, "risk_level": 0.0, "recommendations": []}

        if len(existing_users) == 0:
            return analysis

        if len(existing_users) == 1:
            analysis["pattern"] = "shared_account"
            analysis["risk_level"] = 0.3
            analysis["recommendations"].append("Review if shared account is appropriate (family/business)")

        elif len(existing_users) >= 2:
            # Check if they might be family members (same last name)
            last_names = [user.get("last_name", "").lower() for user in existing_users]
            unique_last_names = set(filter(None, last_names))

            if len(unique_last_names) <= 1:
                analysis["pattern"] = "family_account"
                analysis["risk_level"] = 0.2
                analysis["recommendations"].append("Likely family account - verify relationship")
            else:
                analysis["pattern"] = "suspicious_sharing"
                analysis["risk_level"] = 0.8
                analysis["allowed"] = False
                analysis["recommendations"].append(
                    "Multiple unrelated members using same account - manual review required"
                )

        return analysis

    def _analyze_multiple_payments(self, iban: str, payments: List[Dict]) -> Dict:
        """Analyze multiple payments from same IBAN"""
        total_amount = sum(payment.get("amount", 0) for payment in payments)
        member_names = [payment.get("member_name", "") for payment in payments]

        analysis = {
            "iban": iban,
            "payment_count": len(payments),
            "total_amount": total_amount,
            "member_names": member_names,
            "risk_level": 0.0,
            "issues": [],
        }

        # Check for unusual amount patterns
        if total_amount > 1000:  # Large total amount
            analysis["risk_level"] += 0.3
            analysis["issues"].append(f"Large total amount: {total_amount}")

        # Check for too many payments
        if len(payments) > 3:
            analysis["risk_level"] += 0.4
            analysis["issues"].append(f"Many payments from same account: {len(payments)}")

        return analysis

    def _analyze_payment_amount(self, payment: Dict) -> Dict:
        """Analyze individual payment amount for anomalies"""
        amount = payment.get("amount", 0)
        payment.get("member_name", "")

        analysis = {"payment": payment, "anomaly": False, "reasons": []}

        # Check for unusual amounts
        if amount <= 0:
            analysis["anomaly"] = True
            analysis["reasons"].append("Zero or negative amount")

        if amount > 500:  # Unusually high membership fee
            analysis["anomaly"] = True
            analysis["reasons"].append(f"Unusually high amount: {amount}")

        if amount < 10:  # Unusually low membership fee
            analysis["anomaly"] = True
            analysis["reasons"].append(f"Unusually low amount: {amount}")

        return analysis

    def _generate_recommendations(self, results: Dict) -> List[str]:
        """Generate recommendations based on duplicate detection results"""
        recommendations = []

        if results["high_risk_matches"]:
            recommendations.append(
                "🚨 High risk duplicates detected - manual review required before proceeding"
            )
            recommendations.append("Consider contacting members to verify identity")

        if results["potential_duplicates"]:
            recommendations.append("⚠️ Potential duplicates found - review for data quality")
            recommendations.append("Consider merging duplicate records if confirmed")

        if not results["potential_duplicates"] and not results["high_risk_matches"]:
            recommendations.append("✅ No significant duplicates detected")

        return recommendations

    def _identify_blocked_transactions(self, anomalies: Dict) -> List[Dict]:
        """Identify transactions that should be blocked"""
        blocked = []

        for pattern in anomalies["suspicious_patterns"]:
            if pattern["risk_level"] > 0.7:
                blocked.extend(pattern.get("payments", []))

        return blocked

    def _generate_anomaly_recommendations(self, anomalies: Dict) -> List[str]:
        """Generate recommendations for handling anomalies"""
        recommendations = []

        if anomalies["blocked_transactions"]:
            recommendations.append("🛑 Some transactions should be blocked pending review")

        if anomalies["suspicious_patterns"]:
            recommendations.append("🔍 Suspicious patterns detected - investigate before processing")

        if anomalies["warnings"]:
            recommendations.append("⚠️ Unusual amounts detected - verify with members")

        return recommendations


class DDSecurityAuditLogger:
    """Enhanced audit logging for SEPA Direct Debit operations"""

    def log_batch_action(self, action: str, batch_id: str, user: str = None, details: Dict = None):
        """Log batch-related actions with comprehensive context"""
        try:
            log_entry = frappe.new_doc("DD Security Audit Log")
            log_entry.timestamp = now_datetime()
            log_entry.action = action
            log_entry.batch_id = batch_id
            log_entry.user = user or frappe.session.user
            log_entry.ip_address = frappe.local.request.environ.get("REMOTE_ADDR", "Unknown")
            log_entry.user_agent = frappe.local.request.environ.get("HTTP_USER_AGENT", "Unknown")
            log_entry.session_id = frappe.session.sid

            if details:
                log_entry.details = frappe.as_json(details)

            log_entry.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(f"Error logging audit entry: {str(e)}", "Audit Logging Error")

    def log_security_event(self, event_type: str, severity: str, description: str, details: Dict = None):
        """Log security-related events"""
        try:
            event = frappe.new_doc("DD Security Event Log")
            event.timestamp = now_datetime()
            event.event_type = event_type
            event.severity = severity
            event.description = description
            event.user = frappe.session.user
            event.ip_address = frappe.local.request.environ.get("REMOTE_ADDR", "Unknown")

            if details:
                event.details = frappe.as_json(details)

            event.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(f"Error logging security event: {str(e)}", "Security Logging Error")


class DDConflictResolutionManager:
    """Manager for resolving member identity and payment conflicts"""

    def create_conflict_report(self, conflicts: Dict, batch_id: str = None) -> str:
        """Create a detailed conflict report for manual review"""
        try:
            report = frappe.new_doc("DD Conflict Report")
            report.batch_id = batch_id
            report.report_date = today()
            report.conflict_data = frappe.as_json(conflicts)
            report.status = "Open"
            report.created_by = frappe.session.user

            # Generate human-readable summary
            summary = self._generate_conflict_summary(conflicts)
            report.summary = summary

            report.insert()
            return report.name

        except Exception as e:
            frappe.log_error(f"Error creating conflict report: {str(e)}", "Conflict Resolution Error")
            return None

    def auto_resolve_conflicts(self, conflicts: Dict, resolution_rules: Dict = None) -> Dict:
        """Apply automatic resolution rules where possible"""
        if not resolution_rules:
            resolution_rules = self._get_default_resolution_rules()

        resolved = []
        unresolved = []

        for conflict in conflicts.get("potential_duplicates", []):
            if self._can_auto_resolve(conflict, resolution_rules):
                resolution = self._apply_resolution(conflict, resolution_rules)
                resolved.append(resolution)
            else:
                unresolved.append(conflict)

        return {"resolved": resolved, "unresolved": unresolved, "requires_manual_review": len(unresolved) > 0}

    def _generate_conflict_summary(self, conflicts: Dict) -> str:
        """Generate human-readable summary of conflicts"""
        summary_parts = []

        high_risk = len(conflicts.get("high_risk_matches", []))
        potential = len(conflicts.get("potential_duplicates", []))

        if high_risk > 0:
            summary_parts.append(f"🚨 {high_risk} high-risk duplicate(s) detected")

        if potential > 0:
            summary_parts.append("⚠️ {potential} potential duplicate(s) found")

        if not summary_parts:
            summary_parts.append("✅ No significant conflicts detected")

        return " | ".join(summary_parts)

    def _get_default_resolution_rules(self) -> Dict:
        """Get default automatic resolution rules"""
        return {
            "auto_resolve_low_risk": True,
            "max_auto_resolve_score": 0.6,
            "require_manual_review_above": 0.8,
            "allow_family_account_sharing": True,
        }

    def _can_auto_resolve(self, conflict: Dict, rules: Dict) -> bool:
        """Determine if conflict can be automatically resolved"""
        risk_score = conflict.get("risk_score", 1.0)

        if risk_score > rules.get("require_manual_review_above", 0.8):
            return False

        if risk_score < rules.get("max_auto_resolve_score", 0.6):
            return True

        return False

    def _apply_resolution(self, conflict: Dict, rules: Dict) -> Dict:
        """Apply resolution to a conflict"""
        return {
            "conflict": conflict,
            "resolution": "auto_approved",
            "reason": "Risk score below auto-resolution threshold",
            "timestamp": now_datetime(),
        }


# API Functions for frontend integration


@frappe.whitelist()
def validate_member_identity(member_data):
    """API endpoint for member identity validation"""
    try:
        validator = MemberIdentityValidator()

        if isinstance(member_data, str):
            import json

            member_data = json.loads(member_data)

        results = validator.detect_potential_duplicates(member_data)

        # Log the validation attempt
        logger = DDSecurityAuditLogger()
        logger.log_security_event(
            "member_identity_validation",
            "info",
            "Identity validation performed for member",
            {"validation_results": results},
        )

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(f"Error in member identity validation: {str(e)}", "Member Identity API Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def validate_bank_account_sharing(iban, member_id=None):
    """API endpoint for bank account sharing validation"""
    try:
        validator = MemberIdentityValidator()
        results = validator.validate_unique_bank_account(iban, member_id)

        # Log the validation
        logger = DDSecurityAuditLogger()
        logger.log_security_event(
            "bank_account_validation",
            "info" if results.get("valid") else "warning",
            "Bank account sharing validation for IBAN: {iban[:8]}***",
            {"validation_results": results},
        )

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(f"Error in bank account validation: {str(e)}", "Bank Account API Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_batch_anomalies(batch_data):
    """API endpoint for batch anomaly analysis"""
    try:
        validator = MemberIdentityValidator()

        if isinstance(batch_data, str):
            import json

            batch_data = json.loads(batch_data)

        results = validator.detect_payment_anomalies(batch_data)

        # Log the analysis
        logger = DDSecurityAuditLogger()
        logger.log_security_event(
            "batch_anomaly_analysis",
            "info",
            "Anomaly analysis performed for batch with {len(batch_data)} payments",
            {"analysis_results": results},
        )

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(f"Error in batch anomaly analysis: {str(e)}", "Batch Anomaly API Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_conflict_resolution_report(conflicts, batch_id=None):
    """API endpoint for creating conflict resolution reports"""
    try:
        manager = DDConflictResolutionManager()

        if isinstance(conflicts, str):
            import json

            conflicts = json.loads(conflicts)

        report_id = manager.create_conflict_report(conflicts, batch_id)

        return {"success": True, "report_id": report_id}

    except Exception as e:
        frappe.log_error(f"Error creating conflict report: {str(e)}", "Conflict Resolution API Error")
        return {"success": False, "error": str(e)}
