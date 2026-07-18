"""
Donation Donor Management Service

Handles donor creation, management, and relationship operations for donations.
Extracted from the monolithic donation controller for better separation of concerns.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, validate_email_address

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_document_operation,
    secure_user_context,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


def get_donor_by_email(email: str) -> Optional[Any]:
    """
    Get donor by email address.

    This is the canonical way to lookup donors by email across the codebase.
    Replaces ad-hoc frappe.get_all() and frappe.db.get_value() calls.

    Performance Considerations:
    - Caching removed due to stale data risks with ANBI consent and contact updates
    - Single indexed query by email is fast enough without caching complexity
    - Query uses indexed donor_email field with DESC ordering for latest record

    Security:
    - No permission bypass - uses standard Frappe permission system
    - Returns full document (not bypassing row-level security)

    Args:
        email: Email address to search for (case-sensitive)

    Returns:
        Donor document if found, None otherwise

    Example:
        >>> donor = get_donor_by_email("john@example.com")
        >>> if donor:
        ...     print(f"Found donor: {donor.donor_name}")
    """
    if not email:
        return None

    donors = frappe.get_all("Donor", filters={"donor_email": email}, order_by="creation desc", limit=1)

    if donors:
        return frappe.get_doc("Donor", donors[0]["name"])
    return None


class DonationDonorService(StatelessService):
    """Service for handling donor-related operations for donations"""

    def __init__(self, donation_doc):
        super().__init__(service_name="DonationDonorService")
        self.donation = donation_doc

    def ensure_donor_exists(self) -> str:
        """
        Ensure donor exists for the donation, creating if necessary

        Returns:
            Donor name/ID
        """
        if self.donation.donor and DocumentExistenceValidator.check_document_exists(
            "Donor", self.donation.donor
        ):
            return self.donation.donor

        # Check if this is a website user who needs donor auto-creation
        user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
        if user_type == "Website User":
            donor_name = self.create_donor_for_website_user()
            self.donation.donor = donor_name
            return donor_name

        # For non-website users, donor must be explicitly provided
        frappe.throw(_("Please select a Donor"))

    def create_donor_for_website_user(self) -> str:
        """
        Create donor record for website user making donation

        Returns:
            Created donor name
        """
        # Check if donor already exists for this user's email
        user_email = frappe.session.user
        existing_donor = get_donor_by_email(user_email)

        if existing_donor:
            self.logger.info(f"Found existing donor {existing_donor.name} for email {user_email}")
            return existing_donor.name

        # Get user information
        user = frappe.get_doc("User", user_email)

        # Create new donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = user.full_name or user.first_name or "Anonymous"
        donor.donor_email = user_email
        donor.donor_type = self._get_default_donor_type()

        # Set additional fields from user if available
        if hasattr(user, "phone") and user.phone:
            donor.phone = user.phone
        if hasattr(user, "mobile_no") and user.mobile_no:
            donor.phone = user.mobile_no

        # Auto-enable ANBI consent for website users (they can opt-out later)
        donor.anbi_consent = 1
        # Note: privacy_consent field doesn't exist on Donor DocType

        # Use secure document operation instead of permission bypass
        result = secure_document_operation(
            operation="insert",
            doc=donor,
            justification="Website user donor creation for donation processing",
            required_permissions=["Donor:create"],
        )

        if not result.success:
            frappe.throw(_("Failed to create donor: {0}").format("; ".join(result.errors)))

        self.logger.info(f"Created donor {donor.name} for website user {user_email}")
        return donor.name

    def create_donor_from_donation_data(
        self, donor_name: str, email: str, phone: Optional[str] = None, donor_type: Optional[str] = None
    ) -> str:
        """
        Create donor from donation form data

        Args:
            donor_name: Name of the donor
            email: Email address
            phone: Optional phone number
            donor_type: Optional donor type

        Returns:
            Created donor name
        """
        # Validate email format
        if not validate_email_address(email):
            frappe.throw(_("Invalid email address: {0}").format(email))

        # Check if donor already exists
        existing_donor = get_donor_by_email(email)
        if existing_donor:
            # Update existing donor information if needed
            return self._update_existing_donor(existing_donor, donor_name, phone)

        # Create new donor.
        # Set defaults for new donors: anbi_consent=0 (require explicit consent).
        # Note: privacy_consent and donor_status fields don't exist on Donor DocType
        # Privacy is handled through the donation process itself
        donor = self._build_new_donor(
            donor_name=donor_name,
            email=email,
            donor_type=donor_type or self._get_default_donor_type(),
            phone=phone,
            anbi_consent=0,
        )

        donor.insert()

        self.logger.info(f"Created donor {donor.name} from donation data")
        return donor.name

    def _build_new_donor(
        self,
        *,
        donor_name: str,
        email: str,
        donor_type: str,
        phone: Optional[str] = None,
        address: Optional[str] = None,
        contact_person: Optional[str] = None,
        donor_category: Optional[str] = None,
        anbi_consent: Optional[int] = None,
    ):
        """Construct (not insert) a new Donor doc. Each caller passes exactly the
        fields its flow set historically — do not default-fill divergent fields."""
        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_email = email
        donor.donor_type = donor_type
        if phone:
            donor.phone = phone
        if address is not None:
            donor.address = address
        if contact_person is not None:
            donor.contact_person = contact_person
        if donor_category is not None:
            donor.donor_category = donor_category
        if anbi_consent is not None:
            donor.anbi_consent = anbi_consent
        return donor

    def get_or_create_from_public_form(self, form_data):
        """Get existing donor or create one from the public donation web form.

        Returns the donor DOCUMENT (not the name), matching the donate.py contract.
        Uses the public-donation secure_user_context framework for guest writes.
        """
        existing_donor = get_donor_by_email(form_data.donor_email)
        if existing_donor:
            if form_data.get("donor_phone") and not existing_donor.phone:
                existing_donor.phone = form_data.donor_phone
                try:
                    system_user = get_system_user_for_operation("public_donation_donor_update")
                    with secure_user_context(
                        system_user, f"Updating donor phone for public donation: {existing_donor.name}"
                    ):
                        existing_donor.save()
                        frappe.db.commit()
                    frappe.logger().info(
                        f"Updated donor {existing_donor.name} with phone information from public donation form"
                    )
                except Exception as e:
                    frappe.log_error(
                        f"Failed to update donor information: {str(e)}",
                        "Public Donation - Donor Update Error",
                    )
            return existing_donor

        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        if not settings:
            frappe.throw(_("Unable to load system settings"), frappe.ValidationError)
        donor_type = (
            form_data.get("donor_type") or getattr(settings, "default_donor_type", None) or "Individual"
        )

        donor_doc = self._build_new_donor(
            donor_name=form_data.donor_name,
            email=form_data.donor_email,
            donor_type=donor_type,
            phone=form_data.get("donor_phone", ""),
            address=form_data.get("donor_address", ""),
            contact_person=form_data.donor_name,
            donor_category="Regular Donor",
        )
        try:
            system_user = get_system_user_for_operation("public_donation_donor_creation")
            with secure_user_context(
                system_user, f"Creating donor for public donation: {form_data.donor_email}"
            ):
                donor_doc.insert()
                frappe.db.commit()
                frappe.db.set_value("Donor", donor_doc.name, "owner", system_user)
                frappe.db.commit()
            frappe.logger().info(
                f"Created donor record for public donation: {form_data.donor_name} ({form_data.donor_email})"
            )
            return donor_doc
        except Exception as e:
            frappe.log_error(
                f"Failed to create donor record for public donation: {str(e)}",
                "Public Donation - Donor Creation Error",
            )
            frappe.throw(_("Unable to process donation: Failed to create donor record"))

    def update_donor_donation_history(self, donor_name: str) -> None:
        """Update donor's donation history with this donation"""
        try:
            from verenigingen.utils.donation_history_manager import DonationHistoryManager

            DonationHistoryManager.add_donation_entry(donor_name, self.donation)

        except Exception as e:
            self.logger.error(f"Failed to update donor donation history: {str(e)}")
            # Don't fail the entire donation process for history update issues

    def validate_donor_eligibility(self, donor_name: str) -> List[str]:
        """
        Validate donor eligibility for specific donation types

        Args:
            donor_name: Donor to validate

        Returns:
            List of validation warnings/errors
        """
        if not donor_name or not DocumentExistenceValidator.check_document_exists("Donor", donor_name):
            return ["Donor does not exist"]

        donor = frappe.get_doc("Donor", donor_name)
        issues = []

        # Check donor status
        if hasattr(donor, "donor_status") and donor.donor_status != "Active":
            issues.append(f"Donor status is {donor.donor_status}, not Active")

        # Check ANBI consent for ANBI-eligible donations
        if self.donation.get("anbi_eligible") and not getattr(donor, "anbi_consent", False):
            issues.append("ANBI consent required for tax-exempt donations")

        # Check privacy consent
        if not getattr(donor, "privacy_consent", False):
            issues.append("Privacy consent required for donation processing")

        # Check for blacklist status
        if hasattr(donor, "is_blacklisted") and donor.is_blacklisted:
            issues.append("Donor is blacklisted and cannot make donations")

        # Validate recurring donation eligibility.
        # WHY: the Donation DocType has no ``is_recurring`` field — direct
        # attribute access raises AttributeError on a fresh Donation document
        # (and silently differs on a loaded one). Read it defensively, mirroring
        # the getattr() pattern used for the other optional donor/donation
        # attributes above. The Donation's recurring flag is expressed via the
        # ``status`` Select ("Recurring") instead.
        is_recurring = getattr(self.donation, "is_recurring", None) or (
            self.donation.get("status") == "Recurring"
        )
        if is_recurring:
            if not self._validate_recurring_eligibility(donor):
                issues.append("Donor not eligible for recurring donations")

        return issues

    def get_donor_donation_summary(self, donor_name: str) -> Dict[str, Any]:
        """
        Get donation summary for a donor

        Args:
            donor_name: Donor to get summary for

        Returns:
            Donation summary data
        """
        if not donor_name or not DocumentExistenceValidator.check_document_exists("Donor", donor_name):
            return {}

        # Get donation statistics.
        # WHY: the Donation DocType has no ``payment_status`` column — querying
        # it raises an OperationalError (1054 Unknown column). Paid-ness is
        # recorded on the boolean ``paid`` field instead, so we select and
        # filter on that.
        donations = frappe.get_all(
            "Donation",
            filters={"donor": donor_name, "docstatus": 1},
            fields=["name", "amount", "donation_date", "paid", "donation_purpose_type"],
        )

        total_amount = sum(flt(d.amount) for d in donations if d.paid)
        total_count = len(donations)
        paid_count = len([d for d in donations if d.paid])

        # Get purpose breakdown
        purpose_breakdown = {}
        for donation in donations:
            purpose = donation.donation_purpose_type or "General"
            if purpose not in purpose_breakdown:
                purpose_breakdown[purpose] = {"count": 0, "amount": 0}

            purpose_breakdown[purpose]["count"] += 1
            if donation.paid:
                purpose_breakdown[purpose]["amount"] += flt(donation.amount)

        return {
            "total_donations": total_count,
            "paid_donations": paid_count,
            "total_amount": total_amount,
            "average_donation": total_amount / paid_count if paid_count > 0 else 0,
            "purpose_breakdown": purpose_breakdown,
            "first_donation": donations[0].donation_date if donations else None,
            "latest_donation": donations[-1].donation_date if donations else None,
        }

    def link_donor_to_customer(self, donor_name: str) -> Optional[str]:
        """
        Link donor to customer record for accounting integration

        Args:
            donor_name: Donor to link

        Returns:
            Customer name if successful
        """
        if not donor_name:
            return None

        # Check if customer already exists.
        # WHY: the Customer DocType's donor link field is named ``donor`` (see the
        # Donor controller's get_or_create_customer, which filters on the same
        # field). There is no ``donor_reference`` column, so the previous filter
        # raised an OperationalError (1054 Unknown column) the moment this method
        # was reached.
        existing_customer = frappe.db.get_value("Customer", {"donor": donor_name})
        if existing_customer:
            return existing_customer

        donor = frappe.get_doc("Donor", donor_name)

        # Create customer from donor
        customer = frappe.new_doc("Customer")
        customer.customer_name = donor.donor_name
        customer.customer_type = "Individual"
        customer.customer_group = resolve_non_group_customer_group()
        customer.territory = frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"

        # Link to donor via the Customer's ``donor`` link field (matching the
        # lookup filter above and the Donor controller's own customer linking).
        customer.donor = donor_name

        # Copy contact details
        if donor.donor_email:
            customer.email_id = donor.donor_email
        if hasattr(donor, "phone") and donor.phone:
            customer.mobile_no = donor.phone

        try:
            customer.insert()
            self.logger.info(f"Created customer {customer.name} for donor {donor_name}")
            return customer.name
        except Exception as e:
            self.logger.error(f"Failed to create customer for donor {donor_name}: {str(e)}")
            return None

    def _update_existing_donor(self, donor: Any, donor_name: str, phone: Optional[str] = None) -> str:
        """Update existing donor with new information if needed"""
        updated = False

        # Update name if significantly different
        if donor.donor_name != donor_name and len(donor_name) > len(donor.donor_name):
            donor.donor_name = donor_name
            updated = True

        # Update phone if provided and not already set
        if phone and not getattr(donor, "phone", None):
            donor.phone = phone
            updated = True

        if updated:
            donor.save()
            self.logger.info(f"Updated donor {donor.name} information")

        return donor.name

    def _get_default_donor_type(self) -> str:
        """Get default donor type from settings"""
        settings = frappe.get_single("Verenigingen Settings")
        return settings.get("default_donor_type") or "Individual"

    def _validate_recurring_eligibility(self, donor: Any) -> bool:
        """Validate if donor is eligible for recurring donations"""
        # Check minimum requirements for recurring donations
        if not donor.donor_email:
            return False

        # Check if donor has privacy consent
        if not getattr(donor, "privacy_consent", False):
            return False

        # Check donor status
        if hasattr(donor, "donor_status") and donor.donor_status != "Active":
            return False

        return True

    def get_donor_preferences(self, donor_name: str) -> Dict[str, Any]:
        """Get donor preferences for communication and donations"""
        if not donor_name or not DocumentExistenceValidator.check_document_exists("Donor", donor_name):
            return {}

        donor = frappe.get_doc("Donor", donor_name)

        return {
            "communication_method": getattr(donor, "preferred_communication_method", "Email"),
            "anbi_consent": getattr(donor, "anbi_consent", False),
            "privacy_consent": getattr(donor, "privacy_consent", False),
            "marketing_consent": getattr(donor, "marketing_consent", False),
            "anonymous_donations": getattr(donor, "anonymous_donations_preferred", False),
            "tax_receipt_preference": getattr(donor, "tax_receipt_preference", "Email"),
        }


def get_donation_donor_service(donation_doc) -> DonationDonorService:
    """Get instance of DonationDonorService."""
    return DonationDonorService(donation_doc)
