"""
Generic Payment Entry Factory

DEPRECATED: This module has been moved to the shared services layer.
Import from verenigingen.verenigingen_payments.mollie.services.shared instead.

This file is kept for backward compatibility and re-exports from the new location.
"""

import warnings
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

from .payment_context_resolver import PaymentContext

# Re-export from shared location for backward compatibility
from .shared.cost_center_resolver import get_cost_center_for_context as _get_cost_center_for_context
from .shared.payment_entry_factory import PaymentEntryFactory as _SharedPaymentEntryFactory


def get_appropriate_cost_center_for_context(context: PaymentContext, company: str) -> str:
    """
    Get appropriate cost center based on payment context instead of random selection.

    DEPRECATED: Use verenigingen.verenigingen_payments.mollie.services.shared.get_cost_center_for_context instead.

    Args:
        context: PaymentContext with payment details
        company: Company name

    Returns:
        str: Cost center name
    """
    warnings.warn(
        "get_appropriate_cost_center_for_context is deprecated. "
        "Use verenigingen.verenigingen_payments.mollie.services.shared.get_cost_center_for_context instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_cost_center_for_context(context, company)


if TYPE_CHECKING:
    from frappe import Document


class PaymentEntryFactory(_SharedPaymentEntryFactory):
    """
    Generic factory for creating Payment Entries for any payment type.

    DEPRECATED: This class has been moved to the shared services layer.
    Import from verenigingen.verenigingen_payments.mollie.services.shared instead.

    This class inherits from the shared implementation for backward compatibility.
    """

    def __init__(self):
        warnings.warn(
            "PaymentEntryFactory from payment_entry_factory is deprecated. "
            "Use verenigingen.verenigingen_payments.mollie.services.shared.PaymentEntryFactory instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__()


# The rest of this file is kept for reference but the actual implementation
# is now in services/shared/payment_entry_factory.py


class _LegacyPaymentEntryFactory:
    """
    ARCHIVED: Original PaymentEntryFactory implementation.
    Kept for reference only - do not use.
    Use PaymentEntryFactory from services/shared/ instead.
    """

    def __init__(self):
        self.logger = frappe.logger()

    def _resolve_customer_for_context_ARCHIVED(self, context: PaymentContext) -> Optional[str]:
        """ARCHIVED: Resolve customer based on payment context"""
        try:
            if context.payment_type == "donation":
                # Get customer from donation -> donor
                donation = frappe.get_doc("Donation", context.target_name)
                if hasattr(donation, "donor") and donation.donor:
                    donor = frappe.get_doc("Donor", donation.donor)
                    if hasattr(donor, "customer") and donor.customer:
                        return donor.customer
                    else:
                        # Create customer for donor if missing
                        return self._create_customer_for_donor(donor)

            elif context.payment_type == "membership":
                # Get customer from member
                member = frappe.get_doc("Member", context.target_name)
                if hasattr(member, "customer") and member.customer:
                    return member.customer
                else:
                    # Create customer for member if missing
                    return self._create_customer_for_member(member)

            return None

        except Exception as e:
            self.logger.error(f"Error resolving customer for context {context}: {e}")
            return None

    def _get_company(self) -> str:
        """
        Get the company for payment entries using centralized configuration service.

        Uses MollieConfigurationService for consistent company resolution with
        proper priority chain (Verenigingen Settings → Global Defaults → User defaults).
        """
        return get_mollie_config().get_default_company()

    def _get_accounts(self, company: str, payment_type: str) -> Dict[str, str]:
        """Get appropriate accounts based on payment type"""
        accounts = {"receivable_account": None, "bank_account": None}

        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Get receivable account
            if payment_type == "donation":
                accounts["receivable_account"] = settings.donation_receivable_account or frappe.get_value(
                    "Company", company, "default_receivable_account"
                )
            else:
                # For memberships and other types, use default receivable account
                accounts["receivable_account"] = frappe.get_value(
                    "Company", company, "default_receivable_account"
                )

            # Get Mollie bank account - prefer settings, fallback to named account, then default
            accounts["bank_account"] = settings.mollie_bank_account
            if not accounts["bank_account"]:
                accounts["bank_account"] = frappe.get_value(
                    "Account", {"company": company, "account_name": "Mollie"}, "name"
                )
            if not accounts["bank_account"]:
                accounts["bank_account"] = frappe.get_value("Company", company, "default_bank_account")

        except Exception as e:
            self.logger.error(f"Error getting accounts for company {company}: {e}")

        return accounts

    def _generate_payment_title(
        self, context: PaymentContext, mollie_data: Dict[str, Any], customer: str
    ) -> str:
        """Generate appropriate title for the payment entry"""
        try:
            # Get customer name
            customer_doc = frappe.get_doc("Customer", customer)
            display_name = customer_doc.customer_name or "Unknown Customer"

            # Extract record reference from Mollie data
            record_reference = self._extract_record_reference(mollie_data, context)

            return f"{display_name} - {record_reference}"

        except Exception as e:
            self.logger.warning(f"Could not generate payment title: {e}")
            return f"Payment - {context.target_name}"

    def _extract_record_reference(self, mollie_data: Dict[str, Any], context: PaymentContext) -> str:
        """Extract record reference for payment title"""
        # Try metadata first
        metadata = mollie_data.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("record_id"):
            return metadata["record_id"]

        # Try description JSON
        description = mollie_data.get("description")
        if description:
            try:
                import json

                desc_data = json.loads(description)
                if isinstance(desc_data, dict) and desc_data.get("record_id"):
                    return desc_data["record_id"]
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback to context target name
        return context.target_name

    def _generate_remarks(self, context: PaymentContext, mollie_data: Dict[str, Any]) -> str:
        """Generate remarks for the payment entry"""
        method = mollie_data.get("method", "Unknown method")
        payment_type = context.payment_type.title()

        return f"{payment_type} payment for {context.target_name} via Mollie ({method})"

    def _create_customer_for_donor(self, donor_doc) -> Optional[str]:
        """Create Customer for Donor (reusing existing logic)"""
        try:
            from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
                _create_customer_for_donor,
            )

            return _create_customer_for_donor(donor_doc)
        except Exception as e:
            self.logger.error(f"Failed to create customer for donor {donor_doc.name}: {e}")
            return None

    def _create_customer_for_member(self, member_doc) -> Optional[str]:
        """Create Customer for Member"""
        try:
            # Get company
            company = self._get_company()

            # Customer group: use the shared resolver so we never pass a
            # group node (e.g. "All Customer Groups") through to the Customer
            # insert; ERPNext's strict-validation branch rejects group nodes
            # and the bad fallback used to land here when "Individual" was
            # missing on a fresh site.
            customer_group = resolve_non_group_customer_group()
            territory = "Netherlands"

            # Validate territory exists
            if not frappe.db.exists("Territory", territory):
                fallback_territory = frappe.get_value("Territory", {"is_group": 0}, "name")
                territory = fallback_territory or "All Territories"

            # Create customer
            customer_doc = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": member_doc.full_name or f"Member {member_doc.name}",
                    "customer_type": "Individual",
                    "customer_group": customer_group,
                    "territory": territory,
                    "company": company,
                    "custom_member": member_doc.name,
                    "email_id": getattr(member_doc, "email", None),
                }
            )

            # Security: Customer creation during authenticated Mollie webhook - system creates customer for payment processing
            customer_doc.flags.ignore_permissions = True
            # Retry on duplicate-name PK collision (two same-named members race on
            # the Customer name). See application_payments.insert_customer_with_duplicate_retry.
            from verenigingen.services.member.approval.application_payments import (
                insert_customer_with_duplicate_retry,
            )

            insert_customer_with_duplicate_retry(customer_doc)

            # Security: Link customer to member during webhook - required for payment flow integrity
            member_doc.customer = customer_doc.name
            member_doc.flags.ignore_permissions = True
            member_doc.save()

            self.logger.info(f"Created customer {customer_doc.name} for member {member_doc.name}")
            return customer_doc.name

        except Exception as e:
            self.logger.error(f"Failed to create customer for member {member_doc.name}: {e}")
            return None
