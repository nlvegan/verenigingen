"""
Membership and Dues Schedule Handler for CSV Import

Handles creation of Membership records and Membership Dues Schedules during CSV import.
Extracted from MijnroodCSVImport to improve testability and separation of concerns.
"""

from datetime import date
from typing import Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class MembershipDuesHandler:
    """
    Handles creation of Membership and Dues Schedule records during CSV import.

    Features:
    - Maps Dutch payment periods to billing frequencies
    - Creates Membership records with proper type and dates
    - Creates Membership Dues Schedules with custom amounts
    - Calculates next invoice dates based on billing frequency
    - Determines membership types from payment period or settings
    """

    # Payment period mapping (Dutch → English)
    PAYMENT_PERIOD_MAPPING = {
        "maandelijks": "Monthly",
        "monthly": "Monthly",
        "per maand": "Monthly",
        "kwartaal": "Quarterly",
        "quarterly": "Quarterly",
        "per kwartaal": "Quarterly",
        "driemaandelijks": "Quarterly",
        "halfjaar": "Semi-Annual",
        "halfjaarlijks": "Semi-Annual",
        "semi-annual": "Semi-Annual",
        "per halfjaar": "Semi-Annual",
        "jaar": "Annual",
        "jaarlijks": "Annual",
        "annual": "Annual",
        "per jaar": "Annual",
    }

    def create_dues_schedule(
        self, member_doc: Document, dues_data: dict, row_data: dict = None
    ) -> Optional[str]:
        """
        Create a membership dues schedule from CSV import data.

        Args:
            member_doc: Member document
            dues_data: Dictionary with dues_rate and payment_period
            row_data: Full row data for membership type determination

        Returns:
            Dues schedule name if created, None if failed

        Raises:
            Exception: Logged but not raised to prevent import failure
        """
        try:
            # Map payment period to billing frequency
            billing_frequency = self.map_payment_period_to_frequency(dues_data.get("payment_period"))

            # Create dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = member_doc.name
            member_full_name = member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}"
            dues_schedule.member_name = member_full_name

            # Generate schedule name: member name + sequence number
            existing_count = frappe.db.count("Membership Dues Schedule", {"member": member_doc.name})
            sequence_number = existing_count + 1
            dues_schedule.schedule_name = f"{member_full_name} - {sequence_number}"

            # Get membership type from the row data context
            membership_type_name = self.determine_membership_type(row_data)

            # Validate membership type exists before creating schedule
            if not frappe.db.exists("Membership Type", membership_type_name):
                frappe.logger().error(
                    "Membership type %s does not exist, cannot create dues schedule for %s",
                    membership_type_name,
                    member_doc.name,
                )
                return None

            dues_schedule.membership_type = membership_type_name
            dues_schedule.dues_rate = dues_data["dues_rate"]
            dues_schedule.billing_frequency = billing_frequency
            dues_schedule.status = "Active"
            dues_schedule.is_active = 1
            dues_schedule.uses_custom_amount = 1
            # Provide a default reason if none was given
            dues_schedule.custom_amount_reason = (
                dues_data.get("override_reason") or "Imported from CSV with custom rate"
            )
            dues_schedule.custom_amount_approved = 1
            dues_schedule.custom_amount_approved_by = frappe.session.user
            dues_schedule.custom_amount_approved_date = today()

            # Set next invoice date based on member_since date and billing frequency
            if member_doc.member_since:
                dues_schedule.next_invoice_date = self.calculate_next_invoice_date(
                    getdate(member_doc.member_since), billing_frequency
                )
            else:
                dues_schedule.next_invoice_date = today()

            # Set CSV import flags
            dues_schedule._csv_import = True
            dues_schedule.flags.ignore_workflow = True

            dues_schedule.insert()

            frappe.logger().info(
                "Created dues schedule %s for member %s", dues_schedule.name, member_doc.name
            )

            return dues_schedule.name

        except frappe.DoesNotExistError as e:
            # Expected: Missing Membership Type or related record
            frappe.logger().warning("Skipping dues schedule for %s: %s", member_doc.name, str(e))
            return None
        except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
            # Expected: Business rule violation
            frappe.logger().warning("Cannot create dues schedule for %s: %s", member_doc.name, str(e))
            return None
        except Exception as e:
            # Unexpected: Configuration error or bug - should surface during development
            frappe.logger().error(
                "UNEXPECTED failure creating dues schedule for %s: %s", member_doc.name, str(e)
            )
            frappe.log_error(frappe.get_traceback(), "Dues Schedule Creation Failed")
            return None

    def create_membership(self, member_doc: Document, row_data: dict) -> Optional[str]:
        """
        Create a membership record from CSV import data.

        Args:
            member_doc: Member document
            row_data: CSV row data with member_since and payment info

        Returns:
            Membership name if created, None if failed

        Raises:
            Exception: Logged but not raised to prevent import failure
        """
        try:
            frappe.log_error(
                f"Step 1: Starting membership creation for {member_doc.name}",
                "DEBUG - Membership Creation Step 1",
            )

            # Determine membership type from payment period or existing membership_type
            membership_type_name = self.determine_membership_type(row_data)

            frappe.log_error(
                f"Step 2: Determined membership type: {membership_type_name}",
                "DEBUG - Membership Creation Step 2",
            )

            # Validate membership type exists before creating membership
            exists = frappe.db.exists("Membership Type", membership_type_name)
            frappe.log_error(
                f"Step 3: Membership type '{membership_type_name}' exists: {exists}",
                "DEBUG - Membership Creation Step 3",
            )

            if not exists:
                frappe.logger().error(
                    "Membership type %s does not exist, cannot create membership for %s",
                    membership_type_name,
                    member_doc.name,
                )
                return None

            frappe.log_error(
                f"Step 4: Creating new Membership doc for {member_doc.name}",
                "DEBUG - Membership Creation Step 4",
            )

            # Create membership record
            membership = frappe.new_doc("Membership")
            membership.member = member_doc.name
            membership.member_name = member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}"
            membership.membership_type = membership_type_name
            membership.start_date = row_data.get("member_since") or today()
            membership.status = "Active"

            frappe.log_error(
                f"Step 5: Set basic fields, start_date={membership.start_date}",
                "DEBUG - Membership Creation Step 5",
            )

            # Set end date based on membership type billing period
            if membership_type_name:
                membership_type_doc = frappe.get_doc("Membership Type", membership_type_name)
                if (
                    hasattr(membership_type_doc, "billing_period_in_months")
                    and membership_type_doc.billing_period_in_months
                ):
                    from dateutil.relativedelta import relativedelta

                    start_date = getdate(membership.start_date)
                    membership.renewal_date = start_date + relativedelta(
                        months=membership_type_doc.billing_period_in_months
                    )

                    frappe.log_error(
                        f"Step 6: Set renewal_date={membership.renewal_date}",
                        "DEBUG - Membership Creation Step 6",
                    )

            # Set CSV import flag
            membership._csv_import = True
            membership.flags.ignore_workflow = True

            frappe.log_error("Step 7: Calling membership.insert()", "DEBUG - Membership Creation Step 7")

            membership.insert()

            frappe.log_error(
                f"Step 8: Insert successful, name={membership.name}, calling submit()",
                "DEBUG - Membership Creation Step 8",
            )

            membership.submit()

            frappe.log_error(
                f"Step 9: Submit successful, returning {membership.name}",
                "DEBUG - Membership Creation Step 9",
            )

            frappe.logger().info("Created membership %s for member %s", membership.name, member_doc.name)

            return membership.name

        except frappe.DoesNotExistError as e:
            # Expected: Missing Membership Type or related record
            frappe.log_error(
                f"DoesNotExistError for {member_doc.name}: {str(e)}",
                "DEBUG - Membership Creation DoesNotExistError",
            )
            frappe.logger().warning("Skipping membership for %s: %s", member_doc.name, str(e))
            return None
        except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
            # Expected: Business rule violation
            frappe.log_error(
                f"ValidationError for {member_doc.name}: {str(e)}",
                "DEBUG - Membership Creation ValidationError",
            )
            frappe.logger().warning("Cannot create membership for %s: %s", member_doc.name, str(e))
            return None
        except Exception as e:
            # Unexpected: Configuration error or bug - should surface during development
            frappe.log_error(
                f"UNEXPECTED error for {member_doc.name}: {str(e)}\n{frappe.get_traceback()}",
                "DEBUG - Membership Creation UNEXPECTED",
            )
            frappe.logger().error(
                "UNEXPECTED failure creating membership for %s: %s", member_doc.name, str(e)
            )
            frappe.log_error(frappe.get_traceback(), "Membership Creation Failed")
            return None

    def map_payment_period_to_frequency(self, payment_period: str) -> str:
        """
        Map Dutch payment period terms to billing frequencies.

        Args:
            payment_period: Dutch payment period string

        Returns:
            Billing frequency (Monthly, Quarterly, Semi-Annual, Annual)
            Defaults to Annual if not found
        """
        if not payment_period:
            return "Annual"

        # Normalize and lookup
        normalized = payment_period.lower().strip()
        return self.PAYMENT_PERIOD_MAPPING.get(normalized, "Annual")

    def determine_membership_type(self, row_data: dict) -> str:
        """
        Determine membership type from payment period or settings default.

        NOTE: CSV's membership_type column maps to Member.status, NOT Membership Type.
        This method determines the Verenigingen Membership Type for billing purposes.

        Args:
            row_data: CSV row data with payment_period

        Returns:
            Membership type name

        Priority:
        1. Map payment_period to membership type (Monthly/Quarterly/Annual)
        2. Settings default
        3. Fallback: First available membership type
        """
        # Priority 1: Map payment period to membership type from settings
        if row_data and row_data.get("payment_period"):
            payment_period = row_data["payment_period"].lower().strip()
            settings = frappe.get_single("Verenigingen Settings")

            if payment_period in ["maandelijks", "monthly", "per maand"]:
                if settings.csv_monthly_membership_type:
                    return settings.csv_monthly_membership_type
                else:
                    frappe.throw(
                        "Payment period is 'Maandelijks' but no CSV Monthly Membership Type is configured in Verenigingen Settings. "
                        "Please set the 'CSV Monthly Membership Type' field."
                    )
            elif payment_period in ["kwartaal", "quarterly", "per kwartaal", "driemaandelijks"]:
                if settings.csv_quarterly_membership_type:
                    return settings.csv_quarterly_membership_type
                else:
                    frappe.throw(
                        "Payment period is 'Kwartaal' but no CSV Quarterly Membership Type is configured in Verenigingen Settings. "
                        "Please set the 'CSV Quarterly Membership Type' field."
                    )
            elif payment_period in ["halfjaar", "halfjaarlijks", "semi-annual", "per halfjaar"]:
                frappe.throw(
                    f"Payment period '{payment_period}' maps to Semi-Annual membership, "
                    "but there is no CSV Semi-Annual Membership Type setting. "
                    "Please add this field to Verenigingen Settings or change the payment period."
                )
            elif payment_period in ["jaar", "jaarlijks", "annual", "per jaar"]:
                if settings.csv_annual_membership_type:
                    return settings.csv_annual_membership_type
                else:
                    frappe.throw(
                        "Payment period is 'Jaarlijks' but no CSV Annual Membership Type is configured in Verenigingen Settings. "
                        "Please set the 'CSV Annual Membership Type' field."
                    )

        # Priority 2: Get default from settings
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if settings and settings.default_membership_type:
                if not frappe.db.exists("Membership Type", settings.default_membership_type):
                    frappe.throw(
                        f"Default membership type '{settings.default_membership_type}' from settings does not exist"
                    )
                return settings.default_membership_type
        except Exception as e:
            frappe.logger().warning("Could not get default membership type from settings: %s", str(e))

        # NO FALLBACK - fail loudly with member context
        member_id = row_data.get("member_id", "") if row_data else ""
        payment_period_value = row_data.get("payment_period") if row_data else None
        frappe.throw(
            f"Cannot determine membership type for member {member_id}. "
            f"Payment period: '{payment_period_value}', no default membership type configured. "
            f"Either provide a valid payment period in CSV or set a default membership type in Verenigingen Settings."
        )

    def calculate_next_invoice_date(self, start_date: date, billing_frequency: str) -> str:
        """
        Calculate next invoice date based on start date and billing frequency.

        Args:
            start_date: Starting date for calculation
            billing_frequency: Monthly, Quarterly, Semi-Annual, or Annual

        Returns:
            Next invoice date in YYYY-MM-DD format
        """
        from dateutil.relativedelta import relativedelta

        if billing_frequency == "Monthly":
            next_date = start_date + relativedelta(months=1)
        elif billing_frequency == "Quarterly":
            next_date = start_date + relativedelta(months=3)
        elif billing_frequency == "Semi-Annual":
            next_date = start_date + relativedelta(months=6)
        elif billing_frequency == "Annual":
            next_date = start_date + relativedelta(months=12)
        else:
            # Default to annual
            next_date = start_date + relativedelta(months=12)

        return next_date.strftime("%Y-%m-%d")
