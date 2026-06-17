"""
Mollie Configuration Service

Centralized service for accessing Mollie Settings with caching and validation.
Eliminates duplicate settings access code across 28+ files.

Usage:
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        get_mollie_config
    )

    config = get_mollie_config()
    clearing_account = config.get_clearing_account()
    bank_account_gl = config.get_bank_account_gl()

Note: API keys are NOT cached for security reasons. Use Mollie Settings
      directly for API key access: frappe.get_single("Mollie Settings").get_active_api_key()
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.constants import Roles


class MollieConfigurationService:
    """
    Centralized Mollie Settings access with caching and validation.

    Provides cached access to Mollie Settings with automatic validation
    and consistent error handling. Uses Frappe's cache system for thread-safe
    multi-worker support.
    """

    CACHE_KEY = "mollie_settings_cache"

    # Roles allowed to access Mollie Settings (matches DocType permissions)
    # Using role-based check instead of frappe.has_permission() because
    # has_permission() doesn't work correctly for service accounts
    # See: webhook_security.py comments for details
    ALLOWED_ROLES = {
        Roles.SYSTEM_MANAGER,
        Roles.VERENIGINGEN_ADMIN,
        "Verenigingen Webhook User",
    }
    CACHE_TTL_SECONDS = 300  # 5 minutes

    @classmethod
    def _load_settings_from_db(cls) -> Dict[str, Any]:
        """
        Load settings from database.

        Only caches non-sensitive configuration fields. Password fields
        (API keys) must be retrieved separately for security.
        """
        settings = frappe.get_single("Mollie Settings")

        # Only cache non-Password fields (per security best practices)
        return {
            "mollie_clearing_account": getattr(settings, "mollie_clearing_account", None),
            "mollie_bank_account": getattr(settings, "mollie_bank_account", None),
            "payment_processing_fees_account": getattr(settings, "payment_processing_fees_account", None),
            "test_mode": getattr(settings, "test_mode", True),
            "enable_subscriptions": getattr(settings, "enable_subscriptions", False),
            "enable_backend_api": getattr(settings, "enable_backend_api", False),
            "dues_payment_creation_mode": getattr(settings, "dues_payment_creation_mode", "Bank Transaction"),
        }

    @classmethod
    def clear_cache(cls):
        """
        Manually clear the settings cache.

        Called automatically when Mollie Settings are updated (via on_update hook).
        Can also be called manually when needed.
        """
        frappe.cache().delete_value(cls.CACHE_KEY)
        frappe.logger().info("Cleared Mollie Settings cache")

    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        """
        Get cached Mollie settings (thread-safe with security validation).

        Uses Frappe's cache system which is safe across multiple workers.
        Validates permissions and logs access for financial compliance.

        Security:
            - Validates user permissions before cache access
            - Logs all configuration access for audit trails
            - Returns immutable copy to prevent cache poisoning

        Returns:
            Dict with Mollie Settings fields (immutable copy)

        Raises:
            frappe.PermissionError: If user lacks read permission

        Note: Returns a copy to prevent cache mutation. If you only need
              a single field, use specific getters (get_clearing_account(), etc.)
              for better performance.

        Example:
            settings = MollieConfigurationService.get_settings()
            test_mode = settings.get("test_mode")
        """
        # SECURITY: Validate user has permission to access financial configuration
        # Using role-based check instead of frappe.has_permission() because
        # has_permission() doesn't work correctly for service accounts (webhook users)
        user_roles = set(frappe.get_roles())
        if not user_roles.intersection(cls.ALLOWED_ROLES):
            frappe.logger().warning(
                f"Unauthorized Mollie configuration access attempt by {frappe.session.user} "
                f"(roles: {user_roles})"
            )
            frappe.throw(_("Insufficient permissions to access Mollie configuration"), frappe.PermissionError)

        cache = frappe.cache()
        settings = cache.get_value(cls.CACHE_KEY)

        if not settings:
            settings = cls._load_settings_from_db()
            cache.set_value(cls.CACHE_KEY, settings, expires_in_sec=cls.CACHE_TTL_SECONDS)

            # AUDIT: Log cache miss for security monitoring
            frappe.logger().info(
                f"Mollie configuration loaded by {frappe.session.user} "
                f"(cache miss, TTL: {cls.CACHE_TTL_SECONDS}s)"
            )
        else:
            # AUDIT: Log cache access for compliance tracking (debug level to avoid log spam)
            frappe.logger().debug(f"Mollie configuration accessed by {frappe.session.user} (cache hit)")

        return settings.copy()

    @classmethod
    def get_clearing_account(cls) -> str:
        """
        Get Mollie clearing account (GL Account) with validation.

        The clearing account is where Mollie payments are deposited before
        settlement to the physical bank account.

        Returns:
            GL Account name (e.g., "10460 - Mollie - NVV")

        Raises:
            frappe.ValidationError: If clearing account not configured

        Example:
            clearing_account = get_mollie_config().get_clearing_account()
        """
        settings = cls.get_settings()
        account = settings.get("mollie_clearing_account")

        if not account:
            frappe.throw(
                _(
                    "Mollie Clearing Account not configured in Mollie Settings. "
                    "Please configure it to track payments awaiting settlement."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def get_bank_account_gl(cls) -> str:
        """
        Get Mollie physical bank account (GL Account) with validation.

        The bank account is where settlement payouts from Mollie are deposited
        (typically Triodos account).

        Returns:
            GL Account name (e.g., "10440 - Triodos - NVV")

        Raises:
            frappe.ValidationError: If bank account not configured

        Example:
            bank_account = get_mollie_config().get_bank_account_gl()
        """
        settings = cls.get_settings()
        account = settings.get("mollie_bank_account")

        if not account:
            frappe.throw(
                _(
                    "Mollie Bank Account not configured in Mollie Settings. "
                    "Please configure it to specify where settlement deposits are received."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def get_fees_account_optional(cls) -> Optional[str]:
        """
        Get payment processing fees account (GL Account) without validation.

        Returns:
            GL Account name if configured, None otherwise

        Example:
            fees_account = get_mollie_config().get_fees_account_optional()
            if fees_account:
                # Create fee journal entry
        """
        settings = cls.get_settings()
        return settings.get("payment_processing_fees_account")

    @classmethod
    def get_fees_account(cls) -> str:
        """
        Get payment processing fees account (GL Account) with validation.

        Returns:
            GL Account name

        Raises:
            frappe.ValidationError: If fees account not configured

        Example:
            # Use this when fees account is required
            fees_account = get_mollie_config().get_fees_account()
        """
        settings = cls.get_settings()
        account = settings.get("payment_processing_fees_account")

        if not account:
            frappe.throw(
                _(
                    "Payment Processing Fees Account not configured in Mollie Settings. "
                    "Please configure it to enable fee accounting."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def is_test_mode(cls) -> bool:
        """
        Check if Mollie is in test mode.

        Returns:
            True if test mode enabled, False for live mode

        Example:
            if get_mollie_config().is_test_mode():
                # Using test API
        """
        settings = cls.get_settings()
        return bool(settings.get("test_mode", True))

    @classmethod
    def is_subscriptions_enabled(cls) -> bool:
        """
        Check if Mollie subscriptions are enabled.

        Returns:
            True if subscriptions enabled, False otherwise

        Example:
            if get_mollie_config().is_subscriptions_enabled():
                # Process subscription
        """
        settings = cls.get_settings()
        return bool(settings.get("enable_subscriptions", False))

    @classmethod
    def get_dues_payment_creation_mode(cls) -> str:
        """
        Get dues payment creation mode.

        DEPRECATED: "Payment Entry" mode has been disabled due to GL entry issues
        when invoices are linked after PE submission. All payments now use
        "Bank Transaction" mode for proper reconciliation workflow.

        Returns:
            "Bank Transaction" (always - legacy mode disabled)
        """
        settings = cls.get_settings()
        configured_mode = settings.get("dues_payment_creation_mode", "Bank Transaction")

        if configured_mode == "Payment Entry":
            import frappe

            frappe.logger().warning(
                "[Mollie] DEPRECATED: 'Payment Entry' dues_payment_creation_mode is disabled. "
                "Using 'Bank Transaction' mode instead. Please update Mollie Settings."
            )

        # Always return Bank Transaction - legacy mode disabled
        return "Bank Transaction"

    @classmethod
    def validate_configuration(cls) -> Dict[str, Any]:
        """
        Validate Mollie configuration completeness.

        Returns:
            Dict with validation results:
            {
                "valid": bool,
                "missing_fields": list,
                "warnings": list
            }

        Note: API key validation requires separate check via
              frappe.get_single("Mollie Settings").get_active_api_key()
              as password fields are not cached.

        Example:
            validation = get_mollie_config().validate_configuration()
            if not validation["valid"]:
                frappe.msgprint(f"Missing fields: {validation['missing_fields']}")
        """
        settings = cls.get_settings()
        missing_fields = []
        warnings = []

        # Check required fields (excluding API key - requires password field access)
        if not settings.get("mollie_clearing_account"):
            missing_fields.append("mollie_clearing_account")

        if not settings.get("mollie_bank_account"):
            missing_fields.append("mollie_bank_account")

        # Check optional but recommended fields
        if not settings.get("payment_processing_fees_account"):
            warnings.append("payment_processing_fees_account not configured - fee accounting disabled")

        return {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "warnings": warnings,
        }

    @classmethod
    def is_backend_api_enabled(cls) -> bool:
        """
        Check if Mollie Backend API (organization token) is enabled.

        The Backend API provides access to advanced features like:
        - Balance monitoring
        - Settlement tracking
        - Transaction details

        Returns:
            bool: True if backend API is enabled

        Example:
            if get_mollie_config().is_backend_api_enabled():
                # Use BalancesClient, SettlementsClient, etc.
                balances = BalancesClient().list_balances()
        """
        settings = cls.get_settings()
        return bool(settings.get("enable_backend_api", False))

    @classmethod
    def validate_gl_account(
        cls,
        account_name: str,
        account_type: Optional[str] = None,
        company: Optional[str] = None,
        allow_frozen: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate GL account exists and meets requirements.

        Performs comprehensive validation of General Ledger accounts including:
        - Existence check
        - Account type validation
        - Company ownership validation
        - Frozen status check
        - Group account validation

        Args:
            account_name: GL Account name to validate (e.g., "10460 - Mollie - NVV")
            account_type: Expected account type ("Asset", "Liability", "Expense", etc.)
            company: Company name (validates account belongs to company)
            allow_frozen: Whether to allow frozen accounts (default: False)

        Returns:
            Dict with validation result and account details:
            {
                "valid": True,
                "account_name": "10460 - Mollie - NVV",
                "account_type": "Asset",
                "company": "Vegan Netwerk Nederland",
                "is_group": False,
                "frozen": False
            }

        Raises:
            frappe.ValidationError: If account invalid with specific reason

        Example:
            # Validate clearing account is Asset type
            result = get_mollie_config().validate_gl_account(
                "10460 - Mollie - NVV",
                account_type="Asset"
            )

            # Validate with company check
            result = get_mollie_config().validate_gl_account(
                "10460 - Mollie - NVV",
                account_type="Asset",
                company="Vegan Netwerk Nederland"
            )
        """
        if not account_name:
            frappe.throw(_("Account name is required for validation"), frappe.ValidationError)

        # Check account exists
        if not frappe.db.exists("Account", account_name):
            frappe.throw(
                _("GL Account '{0}' does not exist. Please check Mollie Settings configuration.").format(
                    account_name
                ),
                title=_("Account Not Found"),
                exc=frappe.ValidationError,
            )

        # Fetch account details in single query for performance
        account_details = frappe.db.get_value(
            "Account",
            account_name,
            ["account_type", "company", "is_group", "disabled"],
            as_dict=True,
        )

        # Validate account type if specified
        if account_type and account_details.get("account_type") != account_type:
            frappe.throw(
                _(
                    "GL Account '{0}' is type '{1}' but '{2}' was expected. "
                    "Please update Mollie Settings with correct account."
                ).format(account_name, account_details.get("account_type"), account_type),
                title=_("Account Type Mismatch"),
                exc=frappe.ValidationError,
            )

        # Validate company ownership if specified
        if company and account_details.get("company") != company:
            frappe.throw(
                _(
                    "GL Account '{0}' belongs to company '{1}' but '{2}' was expected. "
                    "Please use accounts from the correct company."
                ).format(account_name, account_details.get("company"), company),
                title=_("Company Mismatch"),
                exc=frappe.ValidationError,
            )

        # Check if account is frozen/disabled
        if not allow_frozen and account_details.get("disabled"):
            frappe.throw(
                _("GL Account '{0}' is disabled and cannot be used for transactions.").format(account_name),
                title=_("Account Disabled"),
                exc=frappe.ValidationError,
            )

        # Warn if group account (should use leaf accounts)
        if account_details.get("is_group"):
            frappe.msgprint(
                _(
                    "Warning: GL Account '{0}' is a group account. "
                    "It's recommended to use leaf accounts for transactions."
                ).format(account_name),
                indicator="orange",
                alert=True,
            )

        return {
            "valid": True,
            "account_name": account_name,
            "account_type": account_details.get("account_type"),
            "company": account_details.get("company"),
            "is_group": bool(account_details.get("is_group", False)),
            "frozen": bool(account_details.get("disabled", False)),
        }

    @classmethod
    def get_all_mollie_accounts(cls, validate: bool = True) -> Dict[str, str]:
        """
        Get all configured Mollie GL accounts with optional validation.

        Retrieves all Mollie-related GL accounts from configuration. Optionally
        validates that each account exists and is properly configured.

        Args:
            validate: Whether to validate accounts exist and are valid (default: True)

        Returns:
            Dict mapping account purpose to account name:
            {
                "clearing_account": "10460 - Mollie - NVV",
                "bank_account": "10500 - Triodos Bank - NVV",
                "fees_account": "70100 - Payment Fees - NVV"  # May be None
            }

        Raises:
            frappe.ValidationError: If validation enabled and any account invalid

        Example:
            # Get all accounts with validation
            accounts = get_mollie_config().get_all_mollie_accounts()
            clearing = accounts["clearing_account"]

            # Get accounts without validation (faster, for display purposes)
            accounts = get_mollie_config().get_all_mollie_accounts(validate=False)
        """
        settings = cls.get_settings()

        accounts = {
            "clearing_account": settings.get("mollie_clearing_account"),
            "bank_account": settings.get("mollie_bank_account"),
            "fees_account": settings.get("payment_processing_fees_account"),  # Optional
        }

        # Validate accounts if requested
        if validate:
            for account_purpose, account_name in accounts.items():
                if account_name:  # Skip optional accounts like fees_account
                    try:
                        cls.validate_gl_account(account_name)
                    except frappe.ValidationError as e:
                        frappe.throw(
                            _(
                                "Mollie {0} validation failed: {1}. "
                                "Please check Mollie Settings configuration."
                            ).format(account_purpose.replace("_", " ").title(), str(e)),
                            title=_("GL Account Validation Failed"),
                            exc=frappe.ValidationError,
                        )

        return accounts

    @classmethod
    def validate_all_mollie_accounts(
        cls, raise_on_error: bool = True, skip_settlement_account: bool = False
    ) -> Dict[str, Any]:
        """
        Validate all Mollie GL accounts configuration comprehensively.

        Performs validation of all configured Mollie GL accounts and returns
        detailed results. Useful for initialization checks and configuration
        validation in admin tools.

        Args:
            raise_on_error: Whether to raise exception on validation failure (default: True)
            skip_settlement_account: Skip validation of settlement bank account (default: False).
                                   Set to True when processing virtual account payments, as
                                   settlement account is only relevant for payout processing.

        Returns:
            Dict with validation results:
            {
                "valid": True,
                "accounts": {
                    "clearing_account": {
                        "valid": True,
                        "account_name": "10460 - Mollie - NVV",
                        "account_type": "Asset",
                        ...
                    },
                    "bank_account": {"valid": True, ...},
                    "fees_account": {"valid": False, "error": "Account not configured"}
                },
                "errors": [],
                "warnings": ["Fees account not configured - fee accounting disabled"]
            }

        Example:
            # Use in __init__ methods to validate configuration
            validation = get_mollie_config().validate_all_mollie_accounts(raise_on_error=False)
            if not validation["valid"]:
                frappe.log_error(
                    message=f"GL Account validation failed: {validation['errors']}",
                    title="Mollie Configuration",
                )

            # Strict validation that raises on error
            get_mollie_config().validate_all_mollie_accounts()  # Raises if any account invalid

            # Skip settlement account validation for virtual account payments
            validation = get_mollie_config().validate_all_mollie_accounts(
                raise_on_error=False,
                skip_settlement_account=True
            )
        """
        settings = cls.get_settings()
        accounts_to_validate = {
            "clearing_account": {
                "name": settings.get("mollie_clearing_account"),
                "required": True,
                "account_type": "Bank",  # Mollie accounts are typically Bank type in ERPNext
            },
            "bank_account": {
                "name": settings.get("mollie_bank_account"),
                "required": not skip_settlement_account,  # Optional if skipping settlement validation
                "account_type": "Bank",  # Physical bank accounts are Bank type
            },
            "fees_account": {
                "name": settings.get("payment_processing_fees_account"),
                "required": False,
                "account_type": None,  # Don't validate type for fees (can be "Expense" or "Expense Account")
            },
        }

        validation_results = {}
        errors = []
        warnings = []

        for account_purpose, account_config in accounts_to_validate.items():
            account_name = account_config["name"]
            account_type = account_config["account_type"]
            required = account_config["required"]

            if not account_name:
                if required:
                    error_msg = f"{account_purpose.replace('_', ' ').title()} not configured"
                    errors.append(error_msg)
                    validation_results[account_purpose] = {"valid": False, "error": error_msg}
                else:
                    warning_msg = f"{account_purpose.replace('_', ' ').title()} not configured - optional feature disabled"
                    warnings.append(warning_msg)
                    validation_results[account_purpose] = {
                        "valid": True,
                        "configured": False,
                        "warning": warning_msg,
                    }
                continue

            try:
                result = cls.validate_gl_account(account_name, account_type=account_type)
                validation_results[account_purpose] = result
            except frappe.ValidationError as e:
                error_msg = f"{account_purpose.replace('_', ' ').title()}: {str(e)}"
                errors.append(error_msg)
                validation_results[account_purpose] = {"valid": False, "error": str(e)}

        overall_valid = len(errors) == 0

        result = {
            "valid": overall_valid,
            "accounts": validation_results,
            "errors": errors,
            "warnings": warnings,
        }

        if not overall_valid and raise_on_error:
            frappe.throw(
                _(
                    "Mollie GL Account validation failed:\n{0}\n\n"
                    "Please check Mollie Settings and configure valid GL accounts."
                ).format("\n".join(errors)),
                title=_("Configuration Validation Failed"),
                exc=frappe.ValidationError,
            )

        return result

    # ===== Company Validation Methods (Phase 3.3) =====

    @classmethod
    def validate_company(cls, company: str) -> Dict[str, Any]:
        """
        Validate company exists and is active.

        Performs comprehensive company validation including:
        - Existence check
        - Active/disabled status
        - Basic company information

        Args:
            company: Company name to validate

        Returns:
            Dict with validation result:
            {
                "valid": True,
                "company_name": "Vegan Netwerk Nederland",
                "abbr": "NVN",
                "is_group": False
            }

        Raises:
            frappe.ValidationError: If company invalid with specific reason

        Example:
            result = get_mollie_config().validate_company("Vegan Netwerk Nederland")
            if result["valid"]:
                print(f"Company {result['company_name']} is active")
        """
        if not company or not company.strip():
            frappe.throw(_("Company name is required for validation"), frappe.ValidationError)

        # Check if company exists
        if not frappe.db.exists("Company", company):
            frappe.throw(
                _("Company '{0}' does not exist. Please check the company name.").format(company),
                frappe.ValidationError,
            )

        # Get company details
        # Note: Company DocType doesn't have a 'disabled' field in ERPNext v15
        company_details = frappe.db.get_value("Company", company, ["name", "abbr", "is_group"], as_dict=True)

        if not company_details:
            frappe.throw(
                _("Could not retrieve details for Company '{0}'.").format(company), frappe.ValidationError
            )

        # Warn if company is a group
        is_group = bool(company_details.get("is_group", False))
        if is_group:
            frappe.logger().warning(
                f"Company '{company}' is a group company. "
                f"Ensure this is intentional for financial transactions."
            )

        return {
            "valid": True,
            "company_name": company_details.get("name"),
            "abbr": company_details.get("abbr"),
            "is_group": is_group,
        }

    @classmethod
    def get_default_company(cls) -> str:
        """
        Get default company with sensible fallback logic.

        Priority order:
        1. company from Verenigingen Settings (primary organization company)
        2. Global Defaults company (system-wide default from Global Defaults DocType)
        3. User default Company (user-specific preference)

        Note: This returns the organization's primary company for all operations
        (memberships, donations, SEPA, etc.). Most organizations have a single
        legal entity handling all operations.

        Returns:
            str: Company name

        Raises:
            frappe.ValidationError: If no company configured or company invalid

        Example:
            company = get_mollie_config().get_default_company()
            print(f"Using company: {company}")
        """
        company = None

        # Priority 1: company from Verenigingen Settings (primary company)
        try:
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            if hasattr(verenigingen_settings, "company") and verenigingen_settings.company:
                company = verenigingen_settings.company
                frappe.logger().info(f"Using company from Verenigingen Settings: {company}")
        except Exception as e:
            frappe.logger().warning(f"Could not get company from Verenigingen Settings: {e}")

        # Priority 2: Global Defaults company (system-wide default)
        if not company:
            company = frappe.defaults.get_global_default("company")
            if company:
                frappe.logger().info(f"Using global default company: {company}")

        # Priority 3: User default Company (user-specific override)
        if not company:
            company = frappe.defaults.get_user_default("Company")
            if company:
                frappe.logger().info(f"Using user default Company: {company}")

        # If still no company found, raise error - don't use arbitrary fallbacks
        if not company:
            frappe.throw(
                _(
                    "No company configured. "
                    "Please set company in Verenigingen Settings or configure a default company in Global Defaults."
                ),
                frappe.ValidationError,
            )

        # Validate the company we found
        cls.validate_company(company)

        return company

    @classmethod
    def get_default_company_validated(cls) -> Dict[str, Any]:
        """
        Get default company with full validation details.

        This is a convenience method that combines get_default_company()
        and validate_company() into a single call.

        Returns:
            Dict with company details and validation:
            {
                "company_name": "Vegan Netwerk Nederland",
                "abbr": "NVN",
                "valid": True,
                "is_group": False,
                "disabled": False
            }

        Raises:
            frappe.ValidationError: If no company found or invalid

        Example:
            company_info = get_mollie_config().get_default_company_validated()
            print(f"Using {company_info['company_name']} ({company_info['abbr']})")
        """
        company = cls.get_default_company()
        validation = cls.validate_company(company)
        return validation


def get_mollie_config() -> MollieConfigurationService:
    """
    Factory function to get MollieConfigurationService singleton.

    Returns:
        MollieConfigurationService instance

    Example:
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config
        )

        config = get_mollie_config()
        clearing_account = config.get_clearing_account()
    """
    return MollieConfigurationService
