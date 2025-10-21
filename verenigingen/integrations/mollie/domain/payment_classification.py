"""
Payment Classification Strategy Pattern

Implements explicit business rules for classifying Mollie payments as
membership dues, donations, or unknown types. Provides audit trail and
confidence levels for classification decisions.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

import frappe


# Centralized Payment Description Patterns
class PaymentPatterns:
    """Centralized regex patterns for payment description parsing"""

    # Invoice number pattern: "Bestelling 2025-55986" or "Bestelling 55986"
    INVOICE_NUMBER = re.compile(r"bestelling\s+(\d{4}-\d+|\d+)", re.IGNORECASE)

    @classmethod
    def extract_invoice_number(cls, description: str) -> Optional[str]:
        """
        Extract invoice number from payment description.

        Args:
            description: Payment description text

        Returns:
            Invoice number if found (e.g., "2025-55986"), None otherwise

        Examples:
            >>> PaymentPatterns.extract_invoice_number("Bestelling 2025-55986")
            '2025-55986'
            >>> PaymentPatterns.extract_invoice_number("Bestelling 12345")
            '12345'
            >>> PaymentPatterns.extract_invoice_number("Random payment")
            None
        """
        if not description:
            return None

        match = cls.INVOICE_NUMBER.search(description)
        return match.group(1) if match else None


# Payment type constants (replaces magic strings)
class PaymentType:
    """Constants for payment types"""

    DUES = "dues"
    DONATION = "donation"
    ORDER = "order"  # WooCommerce/shop orders requiring bank reconciliation
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


class DatabaseLookupClassification(PaymentClassificationRule):
    """
    Base class for database lookup classifications.

    Provides reusable logic for checking payment attributes against
    Member/Donor records in database. Eliminates code duplication.
    """

    def _check_member_donor_match(
        self, payment, field_name: str, field_value: str, confidence: str, match_type: str
    ) -> Optional[ClassificationResult]:
        """
        Check if field value matches Member or Donor records.

        Args:
            payment: Mollie payment object
            field_name: Database field to check (e.g., 'mollie_subscription_id', 'mollie_customer_id')
            field_value: Value to look up
            confidence: Confidence level for this match
            match_type: Description of match type (e.g., 'subscription_id', 'customer_id')

        Returns:
            ClassificationResult if match found, None otherwise
        """
        # Check Member records first (membership dues)
        member = frappe.db.get_value("Member", {field_name: field_value}, "name")
        if member:
            frappe.logger().debug(
                f"Payment {payment.id} matched Member {member} via {match_type} {field_value}"
            )
            return ClassificationResult(
                payment_type=PaymentType.DUES,
                confidence=confidence,
                matched_by=f"{match_type}_member_match",
                member_id=member,
            )

        # Check Donor records (donations)
        donor = frappe.db.get_value("Donor", {field_name: field_value}, "name")
        if donor:
            frappe.logger().debug(
                f"Payment {payment.id} matched Donor {donor} via {match_type} {field_value}"
            )
            return ClassificationResult(
                payment_type=PaymentType.DONATION,
                confidence=confidence,
                matched_by=f"{match_type}_donor_match",
                donor_id=donor,
            )

        return None


class SubscriptionBasedClassification(DatabaseLookupClassification):
    """
    Classify payment by subscription_id lookup (highest confidence).

    Checks if subscription ID matches Member or Donor records in database.
    """

    def classify(self, payment) -> Optional[ClassificationResult]:
        subscription_id = getattr(payment, "subscription_id", None)
        if not subscription_id:
            return None

        result = self._check_member_donor_match(
            payment=payment,
            field_name="mollie_subscription_id",
            field_value=subscription_id,
            confidence=ConfidenceLevel.HIGH,
            match_type="subscription_id",
        )

        if not result:
            frappe.logger().warning(
                f"Payment {payment.id} has subscription {subscription_id} but no matching Member/Donor found"
            )

        return result


class CustomerBasedClassification(DatabaseLookupClassification):
    """
    Classify payment by customer_id lookup (medium confidence).

    Checks if customer ID matches Member or Donor records in database.
    Used for payments without subscription_id (e.g., one-time payments,
    balance transactions).
    """

    def classify(self, payment) -> Optional[ClassificationResult]:
        customer_id = getattr(payment, "customer_id", None)
        if not customer_id:
            return None

        return self._check_member_donor_match(
            payment=payment,
            field_name="mollie_customer_id",
            field_value=customer_id,
            confidence=ConfidenceLevel.MEDIUM,
            match_type="customer_id",
        )


class OrderBasedClassification(PaymentClassificationRule):
    """
    Classify payment as order by 'Bestelling' keyword (high confidence).

    Order payments (WooCommerce/shop) are identified by description containing
    "Bestelling" and should be processed via bank reconciliation workflow,
    not direct Payment Entry creation.

    Pattern: "Bestelling YYYY-NNNNN" where NNNNN is the invoice number
    """

    def classify(self, payment) -> Optional[ClassificationResult]:
        description = getattr(payment, "description", "")
        if not description or not isinstance(description, str):
            return None

        # Use centralized pattern matching
        invoice_number = PaymentPatterns.extract_invoice_number(description)

        if invoice_number:
            frappe.logger().debug(
                f"Payment {payment.id} classified as order by 'Bestelling' keyword "
                f"(invoice: {invoice_number})"
            )

            return ClassificationResult(
                payment_type=PaymentType.ORDER,
                confidence=ConfidenceLevel.HIGH,  # High confidence - clear indicator
                matched_by="order_keyword_bestelling",
                # Note: We don't set member_id or donor_id for orders
                # The invoice number is extracted via PaymentPatterns
            )

        return None


class DescriptionKeywordClassification(PaymentClassificationRule):
    """
    Classify payment by description keywords (low confidence).

    Configurable keyword-based classification with support for multiple
    payment types and keywords. Note: "Bestelling" is handled by
    OrderBasedClassification with higher priority.
    """

    # Keyword mappings: payment_type -> list of keywords
    KEYWORD_MAP = {
        PaymentType.DUES: ["contributie"],
        PaymentType.DONATION: ["donation", "donatie"],
        # Note: "bestelling" removed - handled by OrderBasedClassification
    }

    def classify(self, payment) -> Optional[ClassificationResult]:
        description = getattr(payment, "description", "")
        if not description or not isinstance(description, str):
            return None

        description_lower = description.lower()

        # Check each payment type's keywords
        for payment_type, keywords in self.KEYWORD_MAP.items():
            for keyword in keywords:
                if keyword in description_lower:
                    frappe.logger().debug(
                        f"Payment {payment.id} classified as {payment_type} by keyword '{keyword}' in description"
                    )
                    return ClassificationResult(
                        payment_type=payment_type,
                        confidence=ConfidenceLevel.LOW,
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
                OrderBasedClassification(),  # HIGH confidence - WooCommerce orders
                SubscriptionBasedClassification(),  # HIGH confidence - Recurring payments
                CustomerBasedClassification(),  # MEDIUM confidence - One-time payments
                DescriptionKeywordClassification(),  # LOW confidence - Fallback
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

        Optimizes database access by pre-fetching all Member/Donor lookups
        in 2 batch queries instead of 2N queries (where N = number of payments).

        Args:
            payments: List of Mollie payment objects

        Returns:
            List of ClassificationResult objects in same order as input
        """
        if not payments:
            return []

        # Collect all lookup IDs upfront
        subscription_ids = set()
        customer_ids = set()

        for payment in payments:
            sub_id = getattr(payment, "subscription_id", None)
            if sub_id:
                subscription_ids.add(sub_id)

            cust_id = getattr(payment, "customer_id", None)
            if cust_id:
                customer_ids.add(cust_id)

        # Pre-fetch Member lookups in batch (single query)
        member_by_subscription = {}
        member_by_customer = {}

        if subscription_ids or customer_ids:
            filters = []
            if subscription_ids:
                filters.append(["mollie_subscription_id", "in", list(subscription_ids)])
            if customer_ids:
                filters.append(["mollie_customer_id", "in", list(customer_ids)])

            members = frappe.db.get_all(
                "Member",
                filters=filters,
                fields=["name", "mollie_subscription_id", "mollie_customer_id"],
                or_filters=True if len(filters) > 1 else False,
            )

            for member in members:
                if member.mollie_subscription_id:
                    member_by_subscription[member.mollie_subscription_id] = member.name
                if member.mollie_customer_id:
                    member_by_customer[member.mollie_customer_id] = member.name

        # Pre-fetch Donor lookups in batch (single query)
        donor_by_subscription = {}
        donor_by_customer = {}

        if subscription_ids or customer_ids:
            filters = []
            if subscription_ids:
                filters.append(["mollie_subscription_id", "in", list(subscription_ids)])
            if customer_ids:
                filters.append(["mollie_customer_id", "in", list(customer_ids)])

            donors = frappe.db.get_all(
                "Donor",
                filters=filters,
                fields=["name", "mollie_subscription_id", "mollie_customer_id"],
                or_filters=True if len(filters) > 1 else False,
            )

            for donor in donors:
                if donor.mollie_subscription_id:
                    donor_by_subscription[donor.mollie_subscription_id] = donor.name
                if donor.mollie_customer_id:
                    donor_by_customer[donor.mollie_customer_id] = donor.name

        # Now classify each payment using pre-fetched data
        results = []
        for payment in payments:
            result = self._classify_with_cache(
                payment, member_by_subscription, member_by_customer, donor_by_subscription, donor_by_customer
            )
            results.append(result)

        return results

    def _classify_with_cache(
        self,
        payment,
        member_by_subscription: Dict,
        member_by_customer: Dict,
        donor_by_subscription: Dict,
        donor_by_customer: Dict,
    ) -> ClassificationResult:
        """
        Classify payment using pre-fetched lookup caches.

        Args:
            payment: Mollie payment object
            member_by_subscription: Dict mapping subscription_id -> member name
            member_by_customer: Dict mapping customer_id -> member name
            donor_by_subscription: Dict mapping subscription_id -> donor name
            donor_by_customer: Dict mapping customer_id -> donor name

        Returns:
            ClassificationResult
        """
        payment_id = getattr(payment, "id", "unknown")

        # Try subscription-based classification first (HIGH confidence)
        subscription_id = getattr(payment, "subscription_id", None)
        if subscription_id:
            member = member_by_subscription.get(subscription_id)
            if member:
                return ClassificationResult(
                    payment_type=PaymentType.DUES,
                    confidence=ConfidenceLevel.HIGH,
                    matched_by="subscription_id_member_match",
                    member_id=member,
                )

            donor = donor_by_subscription.get(subscription_id)
            if donor:
                return ClassificationResult(
                    payment_type=PaymentType.DONATION,
                    confidence=ConfidenceLevel.HIGH,
                    matched_by="subscription_id_donor_match",
                    donor_id=donor,
                )

        # Try customer-based classification (MEDIUM confidence)
        customer_id = getattr(payment, "customer_id", None)
        if customer_id:
            member = member_by_customer.get(customer_id)
            if member:
                return ClassificationResult(
                    payment_type=PaymentType.DUES,
                    confidence=ConfidenceLevel.MEDIUM,
                    matched_by="customer_id_member_match",
                    member_id=member,
                )

            donor = donor_by_customer.get(customer_id)
            if donor:
                return ClassificationResult(
                    payment_type=PaymentType.DONATION,
                    confidence=ConfidenceLevel.MEDIUM,
                    matched_by="customer_id_donor_match",
                    donor_id=donor,
                )

        # Fall back to single-payment classification for order/keyword rules
        # (These don't benefit from batch caching)
        return self.classify(payment)
