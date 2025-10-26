# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Service for generating membership dues invoices.

Extracted from MembershipDuesSchedule to reduce complexity and improve testability.
This service handles invoice construction and financial configuration.
"""

from datetime import date
from typing import Any, Dict, Optional, Tuple

import frappe
from frappe.utils import add_days, today


class InvoiceGenerationResult:
    """
    Result object for invoice generation operations.

    Attributes:
        success: Whether invoice generation succeeded
        invoice: Sales Invoice document if successful, None otherwise
        error: Error message if failed, None otherwise
        metadata: Additional context about the operation

    Common metadata keys:
        - submitted (bool): Whether invoice was auto-submitted (not just created as draft)
        - coverage_tracked (bool): Whether coverage period was recorded on invoice
        - payment_method (str): Payment method configured (SEPA Direct Debit, Bank Transfer)
        - fallback_used (str): Which fallback account was used (if any)
    """

    def __init__(
        self, success: bool, invoice: Optional[Any] = None, error: Optional[str] = None, **metadata: Any
    ) -> None:
        self.success: bool = success
        self.invoice: Optional[Any] = invoice
        self.error: Optional[str] = error
        self.metadata: Dict[str, Any] = metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        result: Dict[str, Any] = {
            "success": self.success,
            "invoice": self.invoice.name if self.invoice else None,
            "error": self.error,
        }
        result.update(self.metadata)
        return result

    def __repr__(self) -> str:
        if self.success:
            return f"InvoiceGenerationResult(success=True, invoice={self.invoice.name if self.invoice else None})"
        return f"InvoiceGenerationResult(success=False, error='{self.error}')"


class MembershipDuesItemManager:
    """Manages membership dues item creation and lookups"""

    @staticmethod
    def get_item_name(billing_frequency: str, custom_settings: Optional[Dict[str, Any]] = None) -> str:
        """
        Get item name for billing frequency.

        Args:
            billing_frequency: Billing frequency (Daily, Weekly, Monthly, etc.)
            custom_settings: For Custom frequency, dict with 'number' and 'unit' keys

        Returns:
            Item name string
        """
        if billing_frequency == "Custom" and custom_settings:
            frequency_number = custom_settings.get("number", 1)
            frequency_unit = custom_settings.get("unit", "Months")
            frequency_desc = f"Every {frequency_number} {frequency_unit}"
            return f"Membership Dues - Custom ({frequency_desc})"
        else:
            return f"Membership Dues - {billing_frequency}"

    @staticmethod
    def ensure_item_exists(
        item_name: str,
        company: str,
        income_account: Optional[str] = None,
        expense_account: Optional[str] = None,
    ) -> None:
        """
        Create membership dues item if it doesn't exist.

        Handles race condition where multiple processes try to create the same item concurrently.

        Args:
            item_name: Name of the item
            company: Company name
            income_account: Default income account
            expense_account: Default expense account
        """
        # Check if item already exists
        if frappe.db.exists("Item", item_name):
            return  # Item already exists

        # Create new item with race condition handling
        try:
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services"
            item.is_sales_item = 1

            # Set default accounts if provided
            if income_account:
                item.income_account = income_account

            if expense_account:
                item.expense_account = expense_account

            item.insert()
            frappe.logger().info(f"Created membership dues item: {item_name}")

        except frappe.DuplicateEntryError:
            # Another process created the item concurrently - that's fine
            frappe.logger().info(f"Item {item_name} already exists (created by concurrent process)")
            # Verify it actually exists now
            if not frappe.db.exists("Item", item_name):
                # Should never happen, but if it does, raise the original error
                raise


class InvoiceDescriptionBuilder:
    """Builds invoice descriptions based on billing frequency"""

    @staticmethod
    def build_description(
        member_name: str,
        membership_type: str,
        billing_frequency: str,
        period_start: date,
        period_end: date,
    ) -> str:
        """
        Generate formatted invoice description.

        Args:
            member_name: Display name of member
            membership_type: Type of membership
            billing_frequency: Billing frequency
            period_start: Coverage period start date
            period_end: Coverage period end date

        Returns:
            Formatted description string
        """
        if billing_frequency == "Daily":
            return f"Membership dues for {member_name} ({membership_type}) - Daily fee for {period_start}"
        elif billing_frequency in ["Monthly", "Quarterly", "Semi-Annual", "Annual"]:
            return f"Membership dues for {member_name} ({membership_type}) - {billing_frequency} period: {period_start} to {period_end}"
        else:
            return f"Membership dues for {member_name} ({membership_type}) - Period: {period_start} to {period_end}"


class InvoiceGenerator:
    """
    Service for generating membership dues invoices.

    Handles:
    - Sales invoice document creation
    - Account and cost center configuration
    - Item management (membership dues items)
    - Payment method configuration (SEPA, bank transfer)
    - Auto-submit logic based on settings
    """

    # Validation constants for coverage period limits
    MAX_COVERAGE_PERIOD_YEARS = 5  # Maximum allowed coverage period
    MAX_PAST_DATE_YEARS = 10  # How far back we accept coverage start dates
    MAX_FUTURE_DATE_YEARS = 5  # How far forward we accept coverage start dates

    def __init__(self, schedule_doc: Any) -> None:
        """
        Initialize generator with schedule context.

        Args:
            schedule_doc: MembershipDuesSchedule document instance
        """
        self.schedule: Any = schedule_doc
        self.member_name: str = schedule_doc.member
        self.billing_frequency: str = schedule_doc.billing_frequency
        self.dues_rate: float = schedule_doc.dues_rate
        self.schedule_name: str = schedule_doc.name
        self.membership_type: str = getattr(schedule_doc, "membership_type", "Unknown")
        self.member_display_name: str = getattr(schedule_doc, "member_name", "Unknown Member")

    def generate_invoice(
        self, coverage_start: date, coverage_end: date, member_doc: Any
    ) -> InvoiceGenerationResult:
        """
        Generate a sales invoice for membership dues.

        This method executes a multi-phase pipeline to ensure financial correctness:

        Phase 0: Authorization - Verify user has permission to generate invoices
        Phase 1: Input Validation - Validate coverage dates and member document
        Phase 2: Prerequisites - Check member has customer, company configured
        Phase 3: Account Configuration - Get income/expense accounts with fallbacks
        Phase 4: Item Management - Ensure membership dues item exists
        Phase 5: Payment Configuration - Determine payment method (SEPA vs bank transfer)
        Phase 6: Invoice Construction - Build invoice document with all fields
        Phase 7: Submission - Submit invoice based on auto-submit settings

        Args:
            coverage_start: Start date of coverage period
            coverage_end: End date of coverage period
            member_doc: Member document (pre-fetched by caller)

        Returns:
            InvoiceGenerationResult with success status and invoice

        Raises:
            No exceptions raised - all errors returned in result object
        """
        try:
            # Phase 0: Authorization validation
            auth_error = self._validate_authorization()
            if auth_error:
                return InvoiceGenerationResult(success=False, error=auth_error)

            # Phase 1: Input validation
            input_error = self._validate_inputs(coverage_start, coverage_end, member_doc)
            if input_error:
                return InvoiceGenerationResult(success=False, error=input_error)

            # Phase 2: Validate prerequisites
            validation_error = self._validate_prerequisites(member_doc)
            if validation_error:
                return InvoiceGenerationResult(success=False, error=validation_error)

            # Phase 3: Account configuration - Get invoice accounts with fallbacks
            income_account, expense_account, cost_center = self._get_invoice_accounts()
            if not income_account:
                return InvoiceGenerationResult(
                    success=False,
                    error="Income account not configured. Check Verenigingen Settings and Company defaults.",
                )

            # Phase 4: Item management - Ensure membership dues item exists
            item_code = self._create_membership_dues_item(income_account, expense_account)

            # Phase 5: Payment configuration - Get payment method and SEPA mandate
            payment_config = self._get_payment_configuration(member_doc)

            # Phase 6: Invoice construction - Build invoice document
            invoice = self._build_invoice_document(
                member_doc=member_doc,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                income_account=income_account,
                expense_account=expense_account,
                cost_center=cost_center,
                item_code=item_code,
                payment_config=payment_config,
            )

            # Phase 7: Submission - Submit invoice based on auto-submit settings
            return self._submit_invoice(invoice)

        except Exception as e:
            error_msg = f"Invoice generation failed: {str(e)}"
            frappe.log_error(
                f"{error_msg}\nSchedule: {self.schedule_name}\nMember: {self.member_name}\nTraceback: {frappe.get_traceback()}",
                "Invoice Generation Error",
            )
            return InvoiceGenerationResult(success=False, error=error_msg)

    def _validate_inputs(self, coverage_start: date, coverage_end: date, member_doc: Any) -> Optional[str]:
        """
        Validate input parameters for invoice generation.

        Args:
            coverage_start: Start date of coverage period
            coverage_end: End date of coverage period
            member_doc: Member document

        Returns:
            Error message if validation fails, None if validation passes
        """
        # Validate coverage dates are provided
        if not coverage_start or not coverage_end:
            return "Coverage start and end dates are required"

        # Validate coverage start is not after coverage end
        # Note: start == end is allowed for daily billing schedules
        if coverage_start > coverage_end:
            return f"Invalid coverage period: start date {coverage_start} must not be after end date {coverage_end}"

        # Validate coverage period is reasonable
        from datetime import timedelta

        max_period = timedelta(days=365 * self.MAX_COVERAGE_PERIOD_YEARS)
        if (coverage_end - coverage_start) > max_period:
            return (
                f"Coverage period exceeds maximum allowed duration of {self.MAX_COVERAGE_PERIOD_YEARS} years"
            )

        # Validate coverage dates are not too far in the past
        today_date = date.today()
        max_past = timedelta(days=365 * self.MAX_PAST_DATE_YEARS)
        if (today_date - coverage_start) > max_past:
            return f"Coverage start date {coverage_start} is more than {self.MAX_PAST_DATE_YEARS} years in the past"

        # Validate coverage dates are not too far in the future
        max_future = timedelta(days=365 * self.MAX_FUTURE_DATE_YEARS)
        if (coverage_start - today_date) > max_future:
            return f"Coverage start date {coverage_start} is more than {self.MAX_FUTURE_DATE_YEARS} years in the future"

        # Validate member_doc matches schedule
        if member_doc.name != self.member_name:
            return f"Member document mismatch: expected {self.member_name}, got {member_doc.name}"

        # Validate dues rate is positive (financial correctness)
        if self.dues_rate <= 0:
            return f"Invalid dues rate on schedule: {self.dues_rate}"

        return None  # Validation passed

    def _validate_authorization(self) -> Optional[str]:
        """
        Validate that the current user has permission to generate invoices.

        Returns:
            Error message if authorization fails, None if authorized
        """
        # Check if user has permission to create Sales Invoices
        if not frappe.has_permission("Sales Invoice", "create"):
            return f"User {frappe.session.user} does not have permission to create Sales Invoices"

        # Check if user has permission to read the Member
        if not frappe.has_permission("Member", "read", self.member_name):
            return f"User {frappe.session.user} does not have permission to access member {self.member_name}"

        # Check if user has permission to read the Schedule
        if not frappe.has_permission("Membership Dues Schedule", "read", self.schedule_name):
            return (
                f"User {frappe.session.user} does not have permission to access schedule {self.schedule_name}"
            )

        return None  # Authorization passed

    def _validate_prerequisites(self, member_doc: Any) -> Optional[str]:
        """
        Validate that prerequisites for invoice generation are met.

        Args:
            member_doc: Member document

        Returns:
            Error message if validation fails, None if validation passes
        """
        # Check member has customer
        if not member_doc.customer:
            return f"Member {self.member_name} does not have a customer record"

        # Check company is configured
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.company:
            return "Company not configured in Verenigingen Settings"

        return None  # Validation passed

    def _get_invoice_accounts(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get income account, expense account, and cost center with fallback logic.

        Returns:
            Tuple of (income_account, expense_account, cost_center)
        """
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company

        # Get income account with fallback
        income_account = self._get_income_account(settings, company)

        # Get expense account with fallback
        expense_account = self._get_expense_account(company)

        # Get cost center with fallback
        cost_center = self._get_cost_center(company)

        return income_account, expense_account, cost_center

    def _get_income_account(self, settings: Any, company: str) -> Optional[str]:
        """Get income account with fallback logic"""
        # Primary: Verenigingen Settings dues_income_account
        income_account = settings.dues_income_account
        if income_account and frappe.db.exists("Account", income_account):
            return income_account

        if income_account:
            frappe.logger().warning(
                f"Configured dues_income_account '{income_account}' does not exist, using company default"
            )

        # Fallback: Company default income account
        try:
            company_doc = frappe.get_cached_doc("Company", company)
            income_account = company_doc.default_income_account
            if income_account and frappe.db.exists("Account", income_account):
                return income_account

            if income_account:
                frappe.logger().warning(f"Company default_income_account '{income_account}' does not exist")
        except frappe.DoesNotExistError:
            frappe.log_error(f"Company '{company}' does not exist", "Invoice Account Configuration")
        except AttributeError:
            frappe.logger().warning(f"Company '{company}' has no default_income_account field")
        except Exception as e:
            # Unexpected error - log with full traceback
            frappe.log_error(
                f"Unexpected error accessing company income account: {str(e)}\\n{frappe.get_traceback()}",
                "Invoice Account Configuration",
            )

        return None

    def _get_expense_account(self, company: str) -> Optional[str]:
        """Get expense account from company defaults"""
        try:
            company_doc = frappe.get_cached_doc("Company", company)
            expense_account = company_doc.default_expense_account
            if expense_account and frappe.db.exists("Account", expense_account):
                return expense_account

            if expense_account:
                frappe.logger().warning(f"Company default_expense_account '{expense_account}' does not exist")
        except frappe.DoesNotExistError:
            frappe.log_error(f"Company '{company}' does not exist", "Invoice Account Configuration")
        except AttributeError:
            frappe.logger().warning(f"Company '{company}' has no default_expense_account field")
        except Exception as e:
            # Unexpected error - log with full traceback
            frappe.log_error(
                f"Unexpected error accessing company expense account: {str(e)}\\n{frappe.get_traceback()}",
                "Invoice Account Configuration",
            )

        return None

    def _get_cost_center(self, company: str) -> Optional[str]:
        """Get cost center with fallback logic"""
        # Try Main - [Company Abbreviation]
        main_cost_center = f"Main - {company.split()[-1] if len(company.split()) > 1 else 'NVV'}"

        if frappe.db.exists("Cost Center", main_cost_center):
            return main_cost_center

        # Fallback: Search for any Main cost center for this company
        cost_centers = frappe.get_all(
            "Cost Center", filters={"company": company, "cost_center_name": "Main"}, limit=1
        )
        if cost_centers:
            return cost_centers[0]["name"]

        frappe.logger().warning(f"Could not find Main cost center for company {company}")
        return None

    def _create_membership_dues_item(
        self, income_account: Optional[str], expense_account: Optional[str]
    ) -> str:
        """
        Ensure membership dues item exists and return item code.

        Args:
            income_account: Default income account
            expense_account: Default expense account

        Returns:
            Item code string
        """
        # Get custom frequency settings if applicable
        custom_settings = None
        if self.billing_frequency == "Custom":
            custom_settings = {
                "number": getattr(self.schedule, "custom_frequency_number", 1),
                "unit": getattr(self.schedule, "custom_frequency_unit", "Months"),
            }

        item_name = MembershipDuesItemManager.get_item_name(self.billing_frequency, custom_settings)

        settings = frappe.get_single("Verenigingen Settings")
        MembershipDuesItemManager.ensure_item_exists(
            item_name=item_name,
            company=settings.company,
            income_account=income_account,
            expense_account=expense_account,
        )

        return item_name

    def _get_payment_configuration(self, member_doc: Any) -> Dict[str, Any]:
        """
        Get payment method and configuration with enhanced SEPA validation.

        Args:
            member_doc: Member document

        Returns:
            Dict with payment_method, sepa_mandate_id, payment_terms
        """
        config = {
            "payment_method": "Bank Transfer",  # Default
            "sepa_mandate_id": None,
            "payment_terms": getattr(self.schedule, "payment_terms_template", None),
        }

        # Check for active SEPA mandate with enhanced validation
        active_mandate_name = frappe.db.get_value(
            "SEPA Mandate",
            {
                "member": self.member_name,
                "status": "Active",
                "is_active": 1,
                "used_for_memberships": 1,
            },
            "name",
        )

        if active_mandate_name:
            # Validate the mandate thoroughly before using it
            mandate_validation = self._validate_sepa_mandate(active_mandate_name, member_doc)
            if mandate_validation:
                # Validation failed - log warning and fall back to bank transfer
                frappe.logger().warning(
                    f"SEPA mandate {active_mandate_name} validation failed: {mandate_validation}. "
                    f"Falling back to Bank Transfer for member {self.member_name}"
                )
            else:
                # Validation passed - use SEPA
                config["payment_method"] = "SEPA Direct Debit"
                config["sepa_mandate_id"] = active_mandate_name

        return config

    def _validate_sepa_mandate(self, mandate_name: str, member_doc: Any) -> Optional[str]:
        """
        Validate SEPA mandate is suitable for use.

        Args:
            mandate_name: Name of SEPA Mandate to validate
            member_doc: Member document

        Returns:
            Error message if validation fails, None if valid
        """
        try:
            mandate = frappe.get_doc("SEPA Mandate", mandate_name)

            # Validate mandate member matches (SEPA Mandate has member field, not customer)
            if mandate.member != member_doc.name:
                return f"Mandate member {mandate.member} does not match member {member_doc.name}"

            # Validate mandate has sign date
            if not mandate.sign_date:
                return "Mandate has no sign date"

            # Validate sign date is not in the future
            from datetime import date

            if mandate.sign_date > date.today():
                return f"Mandate sign date {mandate.sign_date} is in the future"

            # Validate mandate has expiry_date if applicable
            if mandate.expiry_date:
                if mandate.expiry_date < date.today():
                    return f"Mandate expired on {mandate.expiry_date}"

            # Validate mandate has IBAN
            if not mandate.iban:
                return "Mandate has no IBAN"

            # Validate IBAN format using existing validator
            from verenigingen.utils.validation.iban_validator import validate_iban

            iban_validation = validate_iban(mandate.iban)
            if not iban_validation["valid"]:
                return f"Invalid IBAN format: {iban_validation['message']}"

            return None  # Validation passed

        except Exception as e:
            return f"Failed to validate mandate: {str(e)}"

    def _build_invoice_document(
        self,
        member_doc: Any,
        coverage_start: date,
        coverage_end: date,
        income_account: Optional[str],
        expense_account: Optional[str],
        cost_center: Optional[str],
        item_code: str,
        payment_config: Dict[str, Any],
    ) -> Any:
        """
        Build the sales invoice document with all fields.

        Args:
            member_doc: Member document
            coverage_start: Coverage period start
            coverage_end: Coverage period end
            income_account: Income account
            expense_account: Expense account
            cost_center: Cost center
            item_code: Membership dues item code
            payment_config: Payment configuration dict

        Returns:
            Sales Invoice document (not yet submitted)
        """
        settings = frappe.get_single("Verenigingen Settings")

        # Create invoice document
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = settings.company
        invoice.customer = member_doc.customer
        invoice.posting_date = today()

        # Set coverage dates
        invoice.custom_coverage_start_date = coverage_start
        invoice.custom_coverage_end_date = coverage_end

        # Set descriptive title for list view (instead of just customer name)
        # Format: "Membership Dues - CustomerName - YYYY-MM"
        from frappe.utils import formatdate

        period_label = formatdate(coverage_start, "yyyy-MM")
        # Get customer_name from Customer record (not Member)
        customer_name = frappe.get_cached_value("Customer", member_doc.customer, "customer_name")
        invoice.title = f"Membership Dues - {customer_name} - {period_label}"

        # Set membership-related fields
        invoice.is_membership_invoice = 1
        invoice.membership_dues_schedule_display = self.schedule_name
        invoice.custom_contribution_mode = getattr(self.schedule, "contribution_mode", "Regular")

        # Link to member and membership
        invoice.member = self.member_name
        if member_doc.current_membership_plan:
            invoice.membership = member_doc.current_membership_plan

        # Set payment terms or default due date
        if payment_config["payment_terms"]:
            invoice.payment_terms_template = payment_config["payment_terms"]
        else:
            invoice.due_date = add_days(today(), 30)

        # Set SEPA mandate if applicable
        if payment_config["sepa_mandate_id"]:
            invoice.sepa_mandate_id = payment_config["sepa_mandate_id"]

        # Add invoice item
        invoice.append(
            "items",
            {
                "item_code": item_code,
                "qty": 1,
                "rate": self.dues_rate,
                "description": InvoiceDescriptionBuilder.build_description(
                    member_name=self.member_display_name,
                    membership_type=self.membership_type,
                    billing_frequency=self.billing_frequency,
                    period_start=coverage_start,
                    period_end=coverage_end,
                ),
                "cost_center": cost_center,
                "income_account": income_account,
                "expense_account": expense_account,
            },
        )

        # Set remarks
        invoice.remarks = (
            f"Generated from Membership Dues Schedule: {self.schedule_name}\n"
            f"Coverage period: {coverage_start} to {coverage_end}"
        )

        # Insert invoice with minimal logging
        invoice.flags.ignore_version = True
        invoice.flags.ignore_links = True
        invoice.insert()

        return invoice

    def _submit_invoice(self, invoice: Any) -> InvoiceGenerationResult:
        """
        Submit invoice based on auto-submit settings.

        Args:
            invoice: Sales Invoice document (already inserted)

        Returns:
            InvoiceGenerationResult
        """
        submitted = False

        # Get auto-submit setting (default to True for backwards compatibility)
        try:
            auto_submit = frappe.db.get_single_value(
                "Verenigingen Settings", "auto_submit_membership_invoices"
            )
            # If setting doesn't exist or is None, default to True (historical behavior)
            if auto_submit is None:
                auto_submit = True
                frappe.logger().info("auto_submit_membership_invoices not configured, defaulting to True")
        except Exception as e:
            # If we can't read the setting, default to True and log warning
            frappe.logger().warning(f"Failed to read auto_submit setting: {str(e)}, defaulting to True")
            auto_submit = True

        # Submit invoice if configured
        if auto_submit:
            # Retry logic for database deadlocks
            max_retries = 3
            retry_delay = 0.1  # Start with 100ms

            for attempt in range(max_retries):
                try:
                    invoice.flags.ignore_version = True
                    invoice.flags.ignore_links = True
                    invoice.submit()
                    submitted = True
                    if attempt > 0:
                        frappe.logger().info(f"Invoice {invoice.name} auto-submitted after {attempt} retries")
                    else:
                        frappe.logger().info(f"Invoice {invoice.name} auto-submitted")
                    break  # Success - exit retry loop

                except frappe.QueryDeadlockError as deadlock_error:
                    if attempt < max_retries - 1:
                        # Retry with exponential backoff
                        import time

                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        frappe.logger().warning(
                            f"Deadlock on invoice {invoice.name} submission (attempt {attempt + 1}/{max_retries}), retrying..."
                        )
                        continue
                    else:
                        # Final attempt failed - return error
                        error_msg = f"Invoice created but submission failed after {max_retries} retries: {str(deadlock_error)}"
                        frappe.log_error(
                            f"{error_msg}\\nInvoice: {invoice.name}\\nTraceback: {frappe.get_traceback()}",
                            "Invoice Auto-Submit Failed - Deadlock",
                        )
                        return InvoiceGenerationResult(
                            success=False, error=error_msg, invoice=invoice, submitted=False
                        )

                except Exception as submit_error:
                    # Non-deadlock submission failure is a critical error - don't retry
                    error_msg = f"Invoice created but submission failed: {str(submit_error)}"
                    frappe.log_error(
                        f"{error_msg}\\nInvoice: {invoice.name}\\nTraceback: {frappe.get_traceback()}",
                        "Invoice Auto-Submit Failed",
                    )
                    return InvoiceGenerationResult(
                        success=False, error=error_msg, invoice=invoice, submitted=False
                    )
        else:
            # Auto-submit disabled - keep as draft
            frappe.logger().info(f"Invoice {invoice.name} kept as draft per settings")

        return InvoiceGenerationResult(
            success=True, invoice=invoice, submitted=submitted, coverage_tracked=True
        )
