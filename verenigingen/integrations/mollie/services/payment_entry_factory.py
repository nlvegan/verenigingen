"""
Generic Payment Entry Factory

Creates Payment Entries for different payment types without being tied to specific doctypes.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

from .payment_context_resolver import PaymentContext


def get_appropriate_cost_center_for_context(context: PaymentContext, company: str) -> str:
    """
    Get appropriate cost center based on payment context instead of random selection.

    Args:
        context: PaymentContext with payment details
        company: Company name

    Returns:
        str: Cost center name
    """
    # Default fallback cost center
    default_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

    # Try to get donation from context if available
    donation = None
    if hasattr(context, "source_doc") and context.source_doc:
        if getattr(context.source_doc, "doctype", None) == "Donation":
            donation = context.source_doc

    if not donation:
        # Look for a general cost center for non-donation payments
        general_cost_center = frappe.db.get_value(
            "Cost Center",
            {
                "company": company,
                "is_group": 0,
                "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
            },
            "name",
        )
        return general_cost_center or default_cost_center

    # Check donation purpose type
    purpose_type = getattr(donation, "donation_purpose_type", None)

    if purpose_type == "Chapter" and hasattr(donation, "chapter_reference"):
        # Try to get chapter-specific cost center
        chapter_cost_center = frappe.db.get_value(
            "Cost Center",
            {
                "company": company,
                "cost_center_name": ["like", f"%{donation.chapter_reference}%"],
                "is_group": 0,
            },
            "name",
        )
        if chapter_cost_center:
            return chapter_cost_center

    # For General Fund or any other purpose, use a general cost center
    general_cost_center = frappe.db.get_value(
        "Cost Center",
        {
            "company": company,
            "is_group": 0,
            "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
        },
        "name",
    )

    return general_cost_center or default_cost_center


if TYPE_CHECKING:
    from frappe import Document


class PaymentEntryFactory:
    """
    Generic factory for creating Payment Entries for any payment type.

    This factory creates Payment Entries based on payment context without
    hardcoding specific payment type logic.
    """

    def __init__(self):
        self.logger = frappe.logger()

    def create_payment_entry(
        self, context: PaymentContext, mollie_data: Dict[str, Any], customer: str = None, title: str = None
    ) -> Optional["Document"]:
        """
        Create a generic Payment Entry for any payment type.

        Args:
            context: Payment context information
            mollie_data: Extracted Mollie payment data
            customer: Customer for the payment entry (if None, will be resolved)
            title: Custom title for the payment entry (if None, will be generated)

        Returns:
            Payment Entry document or None if creation fails
        """
        try:
            # Resolve customer if not provided
            if not customer:
                customer = self._resolve_customer_for_context(context)
                if not customer:
                    self.logger.error(f"Could not resolve customer for context: {context}")
                    return None

            # Get company and accounts
            company = self._get_company()
            accounts = self._get_accounts(company, context.payment_type)

            if not accounts["receivable_account"] or not accounts["bank_account"]:
                self.logger.error(f"Missing required accounts for company {company}")
                return None

            # Validate Mode of Payment exists
            if not DocumentExistenceValidator.check_document_exists("Mode of Payment", "Mollie"):
                self.logger.error("Mollie Mode of Payment not configured")
                return None

            # Generate title if not provided
            if not title:
                title = self._generate_payment_title(context, mollie_data, customer)

            # Get appropriate cost center based on payment context
            cost_center = get_appropriate_cost_center_for_context(context, company)

            # Create Payment Entry
            pe = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "paid_amount": float(mollie_data["amount"]),
                    "received_amount": float(mollie_data["amount"]),
                    "reference_no": mollie_data["payment_id"],
                    "reference_date": frappe.utils.getdate(),
                    "company": company,
                    "paid_from": accounts["receivable_account"],
                    "paid_to": accounts["bank_account"],
                    # "mode_of_payment": "Mollie",  # Temporarily commented out to fix cancel button issue
                    "cost_center": cost_center,
                    "title": title,
                    "remarks": self._generate_remarks(context, mollie_data),
                }
            )

            # Insert and submit
            pe.insert()
            pe.submit()

            self.logger.info(f"Created Payment Entry: {pe.name} for {context.payment_type}")
            return pe

        except Exception as e:
            self.logger.error(f"Failed to create Payment Entry for {context}: {e}")
            frappe.log_error(
                f"Payment Entry creation failed for {context}: {str(e)}", "Payment Entry Factory"
            )
            return None

    def _resolve_customer_for_context(self, context: PaymentContext) -> Optional[str]:
        """Resolve customer based on payment context"""
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
        """Get the company for payment entries"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return settings.donation_company or frappe.defaults.get_global_default("company")
        except:
            return frappe.defaults.get_global_default("company") or "Verenigingen"

    def _get_accounts(self, company: str, payment_type: str) -> Dict[str, str]:
        """Get appropriate accounts based on payment type"""
        accounts = {"receivable_account": None, "bank_account": None}

        try:
            # Get receivable account
            if payment_type == "donation":
                settings = frappe.get_single("Verenigingen Settings")
                accounts["receivable_account"] = settings.donation_receivable_account or frappe.get_value(
                    "Company", company, "default_receivable_account"
                )
            else:
                # For memberships and other types, use default receivable account
                accounts["receivable_account"] = frappe.get_value(
                    "Company", company, "default_receivable_account"
                )

            # Get Mollie bank account
            accounts["bank_account"] = frappe.get_value(
                "Account", {"company": company, "account_name": "Mollie"}, "name"
            )

            # Fallback to default bank account
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
            from verenigingen.integrations.mollie.api.payment_webhook import _create_customer_for_donor

            return _create_customer_for_donor(donor_doc)
        except Exception as e:
            self.logger.error(f"Failed to create customer for donor {donor_doc.name}: {e}")
            return None

    def _create_customer_for_member(self, member_doc) -> Optional[str]:
        """Create Customer for Member"""
        try:
            # Get company
            company = self._get_company()

            # Customer group and territory setup
            customer_group = "Individual"
            territory = "Netherlands"

            # Validate customer group exists
            if not frappe.db.exists("Customer Group", customer_group):
                fallback_group = frappe.get_value("Customer Group", {"is_group": 0}, "name")
                customer_group = fallback_group or "All Customer Groups"

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

            customer_doc.flags.ignore_permissions = True
            customer_doc.insert()

            # Link customer back to member
            member_doc.customer = customer_doc.name
            member_doc.flags.ignore_permissions = True
            member_doc.save()

            self.logger.info(f"Created customer {customer_doc.name} for member {member_doc.name}")
            return customer_doc.name

        except Exception as e:
            self.logger.error(f"Failed to create customer for member {member_doc.name}: {e}")
            return None
