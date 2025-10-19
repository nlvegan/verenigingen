"""
Payment Classification Strategy Pattern

Implements explicit business rules for classifying Mollie payments as
membership dues, donations, or unknown types. Provides audit trail and
confidence levels for classification decisions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import frappe


# Payment type constants (replaces magic strings)
class PaymentType:
    """Constants for payment types"""

    DUES = "dues"
    DONATION = "donation"
    UNKNOWN = "unknown"


# Confidence level constants
class ConfidenceLevel:
    """Constants for classification confidence levels"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class ClassificationResult:
    """
    Explicit result of payment classification with audit trail.

    Attributes:
        payment_type: Payment type constant (PaymentType.DUES, PaymentType.DONATION, or PaymentType.UNKNOWN)
        confidence: Confidence level constant (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW, ConfidenceLevel.NONE)
        matched_by: Which rule/method produced this classification
        member_id: Associated Member record (if dues payment)
        donor_id: Associated Donor record (if donation)
    """

    payment_type: str
    confidence: str
    matched_by: str
    member_id: Optional[str] = None
    donor_id: Optional[str] = None


class PaymentClassificationRule(ABC):
    """Base class for payment classification rules"""

    @abstractmethod
    def classify(self, payment) -> Optional[ClassificationResult]:
        """
        Attempt to classify the payment using this rule.

        Args:
            payment: Mollie payment object

        Returns:
            ClassificationResult if this rule matches, None otherwise
        """
        pass


class SubscriptionBasedClassification(PaymentClassificationRule):
    """
    Classify payment by subscription_id lookup (highest confidence).

    Checks if subscription ID matches Member or Donor records in database.
    """

    def classify(self, payment) -> Optional[ClassificationResult]:
        subscription_id = getattr(payment, "subscription_id", None)
        if not subscription_id:
            return None

        # Check Member records first (dues payments)
        member = frappe.db.get_value("Member", {"mollie_subscription_id": subscription_id}, "name")
        if member:
            frappe.logger().debug(
                f"Payment {payment.id} matched Member {member} via subscription {subscription_id}"
            )
            return ClassificationResult(
                payment_type=PaymentType.DUES,
                confidence=ConfidenceLevel.HIGH,
                matched_by="subscription_id_member_match",
                member_id=member,
            )

        # Check Donor records (donations)
        donor = frappe.db.get_value("Donor", {"mollie_subscription_id": subscription_id}, "name")
        if donor:
            frappe.logger().debug(
                f"Payment {payment.id} matched Donor {donor} via subscription {subscription_id}"
            )
            return ClassificationResult(
                payment_type=PaymentType.DONATION,
                confidence=ConfidenceLevel.HIGH,
                matched_by="subscription_id_donor_match",
                donor_id=donor,
            )

        # Subscription ID exists but doesn't match any record
        frappe.logger().warning(
            f"Payment {payment.id} has subscription {subscription_id} but no matching Member/Donor found"
        )
        return None


class DescriptionKeywordClassification(PaymentClassificationRule):
    """
    Classify payment by description keywords (medium confidence).

    Looks for Dutch language keywords in payment description:
    - "contributie" (membership dues/contribution)
    - "donation"/"donatie" (donation)
    """

    DUES_KEYWORDS = ["contributie"]
    DONATION_KEYWORDS = ["donation", "donatie"]

    def classify(self, payment) -> Optional[ClassificationResult]:
        description = getattr(payment, "description", "")
        if not description or not isinstance(description, str):
            return None

        description_lower = description.lower()

        # Check for dues keywords
        for keyword in self.DUES_KEYWORDS:
            if keyword in description_lower:
                frappe.logger().debug(
                    f"Payment {payment.id} classified as dues by keyword '{keyword}' in description"
                )
                return ClassificationResult(
                    payment_type=PaymentType.DUES,
                    confidence=ConfidenceLevel.MEDIUM,
                    matched_by=f"description_keyword_{keyword}",
                )

        # Check for donation keywords
        for keyword in self.DONATION_KEYWORDS:
            if keyword in description_lower:
                frappe.logger().debug(
                    f"Payment {payment.id} classified as donation by keyword '{keyword}' in description"
                )
                return ClassificationResult(
                    payment_type=PaymentType.DONATION,
                    confidence=ConfidenceLevel.MEDIUM,
                    matched_by=f"description_keyword_{keyword}",
                )

        return None


class PaymentClassifier:
    """
    Orchestrates payment classification using chain of responsibility pattern.

    Runs payment through classification rules in priority order (highest
    confidence first). Stops at first successful classification.
    """

    def __init__(self, rules: Optional[List[PaymentClassificationRule]] = None):
        """
        Initialize classifier with rules.

        Args:
            rules: List of classification rules in priority order.
                   If None, uses default rule set.
        """
        if rules is None:
            # Default rules in priority order (highest confidence first)
            self.rules = [
                SubscriptionBasedClassification(),
                DescriptionKeywordClassification(),
                # Easy to add new rules here in future
            ]
        else:
            self.rules = rules

    def classify(self, payment) -> ClassificationResult:
        """
        Run payment through classification rules in priority order.

        Args:
            payment: Mollie payment object

        Returns:
            ClassificationResult with payment type, confidence, and audit info
        """
        payment_id = getattr(payment, "id", "unknown")

        for rule in self.rules:
            result = rule.classify(payment)
            if result:
                frappe.logger().info(
                    f"Payment {payment_id} classified as '{result.payment_type}' "
                    f"by {result.matched_by} (confidence: {result.confidence})"
                )
                return result

        # No rule matched
        frappe.logger().warning(f"Payment {payment_id} could not be classified - no rule matched")
        return ClassificationResult(
            payment_type=PaymentType.UNKNOWN, confidence=ConfidenceLevel.NONE, matched_by="no_rule_matched"
        )

    def classify_batch(self, payments: List) -> List[ClassificationResult]:
        """
        Classify multiple payments efficiently with batch database queries.

        Args:
            payments: List of Mollie payment objects

        Returns:
            List of ClassificationResult objects (same order as input)
        """
        results = []

        # Extract subscription IDs for batch lookup
        subscription_ids = [
            getattr(p, "subscription_id", None)
            for p in payments
            if hasattr(p, "subscription_id") and getattr(p, "subscription_id", None)
        ]

        # Batch query for Members
        members_by_sub = {}
        if subscription_ids:
            member_records = frappe.db.get_all(
                "Member",
                filters={"mollie_subscription_id": ["in", subscription_ids]},
                fields=["mollie_subscription_id", "name"],
            )
            members_by_sub = {m.mollie_subscription_id: m.name for m in member_records}

        # Batch query for Donors
        donors_by_sub = {}
        if subscription_ids:
            donor_records = frappe.db.get_all(
                "Donor",
                filters={"mollie_subscription_id": ["in", subscription_ids]},
                fields=["mollie_subscription_id", "name"],
            )
            donors_by_sub = {d.mollie_subscription_id: d.name for d in donor_records}

        # Classify each payment using pre-loaded data
        for payment in payments:
            subscription_id = getattr(payment, "subscription_id", None)

            # Check subscription match first (highest confidence)
            if subscription_id:
                if subscription_id in members_by_sub:
                    results.append(
                        ClassificationResult(
                            payment_type=PaymentType.DUES,
                            confidence=ConfidenceLevel.HIGH,
                            matched_by="subscription_id_member_match",
                            member_id=members_by_sub[subscription_id],
                        )
                    )
                    continue
                elif subscription_id in donors_by_sub:
                    results.append(
                        ClassificationResult(
                            payment_type=PaymentType.DONATION,
                            confidence=ConfidenceLevel.HIGH,
                            matched_by="subscription_id_donor_match",
                            donor_id=donors_by_sub[subscription_id],
                        )
                    )
                    continue

            # Fallback to other rules
            result = self.classify(payment)
            results.append(result)

        return results
