# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Settings DocType Controller

Manages configuration for Ponto banking integration including:
- Separate OAuth2 credentials for sandbox and production
- Bank account mapping (multiple Ponto accounts to ERPNext Bank Accounts)
- Webhook configuration
- Synchronization settings
"""

from typing import List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class PontoSettings(Document):
    """Controller for Ponto Settings singleton DocType."""

    def validate(self):
        """Validate settings before save."""
        self.validate_credentials_configured()
        self.validate_no_test_credentials()
        self.validate_sync_interval()
        self.update_webhook_url()

    def before_save(self):
        """
        Protect OAuth2 token fields from being deleted during save.

        Frappe's _save_passwords() deletes Password fields from __Auth when
        they appear empty in the document. Since we store tokens directly via
        set_encrypted_password() (not through document fields), they appear
        empty and get deleted on any save().

        This hook tells Frappe to ignore these specific fields.
        """
        # Initialize if not already a list
        if not isinstance(self.flags.ignore_save_passwords, list):
            self.flags.ignore_save_passwords = []

        # Protect OAuth2 token fields
        token_fields = ["ibanity_refresh_token", "ibanity_access_token"]
        for field in token_fields:
            if field not in self.flags.ignore_save_passwords:
                self.flags.ignore_save_passwords.append(field)

    def on_update(self):
        """Actions after settings are saved."""
        # Clear configuration cache
        self.clear_configuration_cache()
        # Clear token cache (credentials may have changed)
        self.clear_token_cache()

    def validate_credentials_configured(self):
        """Ensure credentials are configured for the active environment."""
        if self.sandbox_mode:
            if not self.sandbox_client_id:
                frappe.throw(
                    _("Sandbox Client ID is required when Sandbox Mode is enabled"),
                    title=_("Missing Credentials"),
                )
        else:
            if not self.production_client_id:
                frappe.throw(
                    _("Production Client ID is required when Sandbox Mode is disabled"),
                    title=_("Missing Credentials"),
                )

    def validate_no_test_credentials(self):
        """
        Prevent test credentials from being saved in non-test environments.

        This catches accidental leakage of test settings from unit tests into
        the database, which can cause OAuth failures that are hard to diagnose.
        """
        # Skip validation in test mode
        if frappe.flags.in_test:
            return

        # Patterns that indicate test credentials
        test_patterns = [
            "test_client",
            "test_secret",
            "mock_",
            "fake_",
            "dummy_",
            "placeholder",
        ]

        # Check all client_id fields
        client_id_fields = [
            ("sandbox_client_id", self.sandbox_client_id),
            ("production_client_id", self.production_client_id),
            ("ibanity_client_id", self.ibanity_client_id),
        ]

        for field_name, value in client_id_fields:
            if value:
                value_lower = value.lower()
                for pattern in test_patterns:
                    if pattern in value_lower:
                        frappe.throw(
                            _(
                                "Invalid {0}: '{1}' appears to be a test credential. "
                                "Test credentials should not be saved outside of test mode. "
                                "This may indicate a test leaked settings into the database."
                            ).format(field_name, value),
                            title=_("Test Credentials Detected"),
                        )

    def validate_sync_interval(self):
        """Ensure sync interval is reasonable."""
        if self.auto_sync_enabled and self.sync_interval_hours:
            if self.sync_interval_hours < 1:
                frappe.throw(
                    _("Sync interval must be at least 1 hour"),
                    title=_("Invalid Sync Interval"),
                )
            if self.sync_interval_hours > 168:  # 1 week
                frappe.throw(
                    _("Sync interval cannot exceed 168 hours (1 week)"),
                    title=_("Invalid Sync Interval"),
                )

    def update_webhook_url(self):
        """Auto-generate webhook URL based on site URL."""
        if self.enable_webhooks:
            base_url = get_url()
            self.webhook_url = (
                f"{base_url}/api/method/verenigingen.verenigingen_payments"
                f".ponto.api.webhook.handle_ponto_webhook"
            )

    def clear_configuration_cache(self):
        """Clear the configuration service cache."""
        frappe.cache().delete_value("ponto_settings_cache")
        frappe.logger().info("Cleared Ponto Settings cache")

    def clear_token_cache(self):
        """Clear the OAuth2 token cache."""
        from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager

        PontoTokenManager.clear_cache()

    def get_active_client_id(self) -> str:
        """
        Get the active client ID based on sandbox mode.

        Returns:
            str: Client ID for the current environment
        """
        if self.sandbox_mode:
            return self.sandbox_client_id or ""
        return self.production_client_id or ""

    def get_active_client_secret(self) -> str:
        """
        Get the active client secret based on sandbox mode.

        Returns:
            str: Decrypted client secret for the current environment
        """
        if self.sandbox_mode:
            return self.get_password("sandbox_client_secret", raise_exception=False) or ""
        return self.get_password("production_client_secret", raise_exception=False) or ""

    def get_webhook_application_id(self) -> str:
        """
        Get the application ID for webhook JWT verification.

        The webhook application ID (from Ibanity developer console) may differ
        from the OAuth client_id. Falls back to client_id if not set.

        Returns:
            str: Application ID for webhook verification
        """
        if self.webhook_application_id:
            return self.webhook_application_id
        # Fall back to client_id for backwards compatibility
        return self.get_active_client_id()

    def validate_credentials(self) -> bool:
        """
        Test Ponto API credentials by attempting token fetch.

        Returns:
            bool: True if credentials are valid

        Raises:
            frappe.ValidationError: If credentials are invalid
        """
        client_id = self.get_active_client_id()
        client_secret = self.get_active_client_secret()

        if not client_id or not client_secret:
            env = "Sandbox" if self.sandbox_mode else "Production"
            frappe.throw(
                _(f"{env} Client ID and Client Secret are required"),
                title=_("Missing Credentials"),
            )

        try:
            from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager

            token_manager = PontoTokenManager(
                client_id=client_id,
                client_secret=client_secret,
            )
            token_manager.get_valid_token()
            env = "Sandbox" if self.sandbox_mode else "Production"
            frappe.msgprint(
                _(f"Ponto {env} credentials validated successfully"),
                indicator="green",
                alert=True,
            )
            return True
        except Exception as e:
            frappe.throw(
                _("Failed to validate Ponto credentials: {0}").format(str(e)),
                title=_("Credential Validation Failed"),
            )

    def cleanup_duplicate_mappings(self) -> int:
        """
        Remove duplicate bank account mappings, keeping the first entry for each IBAN.

        Returns:
            int: Number of duplicates removed
        """
        seen_ibans = set()
        duplicates_to_remove = []

        for i, row in enumerate(self.bank_account_mappings or []):
            if row.ponto_iban in seen_ibans:
                duplicates_to_remove.append(i)
            else:
                seen_ibans.add(row.ponto_iban)

        # Remove duplicates in reverse order to preserve indices
        removed = 0
        for idx in reversed(duplicates_to_remove):
            self.bank_account_mappings.pop(idx)
            removed += 1

        if removed:
            frappe.logger().info(f"Removed {removed} duplicate bank account mappings")

        return removed

    def _fix_bank_account_currency(self, bank_account_name: str, correct_currency: str) -> bool:
        """
        Fix Bank Account currency if it doesn't match.

        Args:
            bank_account_name: Name of the Bank Account to check/fix
            correct_currency: The correct currency from Ponto

        Returns:
            True if currency was fixed, False if already correct or not fixable
        """
        try:
            bank_account = frappe.get_doc("Bank Account", bank_account_name)

            # Bank Account currency comes from the linked GL Account
            if not bank_account.account:
                frappe.logger().warning(
                    f"Bank Account {bank_account_name} has no linked GL Account - cannot check currency"
                )
                return False

            gl_account = frappe.get_doc("Account", bank_account.account)
            current_currency = gl_account.account_currency or "EUR"

            if current_currency != correct_currency:
                frappe.logger().warning(
                    f"Fixing GL Account {bank_account.account} currency: "
                    f"{current_currency} -> {correct_currency}"
                )
                gl_account.account_currency = correct_currency
                gl_account.save(ignore_permissions=True)
                return True

            return False

        except Exception as e:
            frappe.logger().error(f"Error fixing Bank Account currency: {e}")
            return False

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def fetch_ponto_accounts(self):
        """
        Fetch accounts from Ponto API and populate the mappings table.

        Called from UI button. Updates existing mappings or adds new ones.
        Creates GL Accounts, Bank records, and Bank Accounts for new Ponto accounts.
        Does not remove existing mappings that are no longer in Ponto.

        Returns:
            dict: Result with accounts found/added/updated counts
        """
        try:
            from verenigingen.verenigingen_payments.ponto.clients.accounts_client import PontoAccountsClient
            from verenigingen.verenigingen_payments.ponto.utils.bank_account_creator import (
                create_ponto_bank_account,
            )

            # Clean up any existing duplicates first (by IBAN)
            duplicates_removed = self.cleanup_duplicate_mappings()
            if duplicates_removed:
                self.save(ignore_permissions=True)
                frappe.db.commit()

            # Get company from Verenigingen Settings
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            company = verenigingen_settings.company
            if not company:
                frappe.throw(
                    _("Company not configured in Verenigingen Settings"),
                    title=_("Configuration Error"),
                )

            # Validate credentials first (this may update access_token_expiry)
            self.validate_credentials()

            # Fetch accounts from Ponto
            client = PontoAccountsClient()
            ponto_accounts = client.list_accounts()

            # Get fresh settings after all API calls are done
            settings = frappe.get_single("Ponto Settings")

            # Build lookup of existing mappings from database (atomic check)
            # This prevents race conditions when button is clicked multiple times
            # Use IBAN as the unique identifier (more stable than Ponto account UUID)
            existing_in_db = frappe.get_all(
                "Ponto Bank Account Mapping",
                filters={"parent": "Ponto Settings"},
                fields=["name", "ponto_account_id", "ponto_iban"],
            )
            existing_ibans = {row.ponto_iban for row in existing_in_db if row.ponto_iban}

            # Also build in-memory lookup for updates (by IBAN)
            existing_mappings = {
                row.ponto_iban: row for row in settings.bank_account_mappings if row.ponto_iban
            }

            added = 0
            updated = 0
            bank_accounts_created = 0
            bank_account_errors = []

            currency_fixes = 0
            for account in ponto_accounts:
                if account.iban in existing_ibans:
                    # Already exists in database - update if we have it in memory
                    if account.iban in existing_mappings:
                        row = existing_mappings[account.iban]
                        row.ponto_account_name = account.description or account.holder_name
                        row.ponto_account_id = account.id  # Update Ponto ID in case it changed
                        row.ponto_currency = account.currency or "EUR"

                        # Fix linked Bank Account currency if mismatched
                        if row.bank_account:
                            fixed = self._fix_bank_account_currency(
                                row.bank_account, account.currency or "EUR"
                            )
                            if fixed:
                                currency_fixes += 1
                    updated += 1
                else:
                    # Create GL Account, Bank, and Bank Account for new Ponto account
                    bank_result = create_ponto_bank_account(
                        ponto_account=account,
                        company=company,
                    )

                    bank_account_name = None
                    if bank_result.get("success"):
                        bank_account_name = bank_result.get("bank_account")
                        bank_accounts_created += 1
                        frappe.logger().info(
                            f"Created Bank Account {bank_account_name} for Ponto account {account.id}"
                        )
                    else:
                        error_msg = bank_result.get("error", "Unknown error")
                        bank_account_errors.append(f"{account.iban}: {error_msg}")
                        frappe.logger().warning(
                            f"Failed to create Bank Account for Ponto account {account.id}: {error_msg}"
                        )

                    # Add new mapping with auto-linked Bank Account
                    settings.append(
                        "bank_account_mappings",
                        {
                            "enabled": 1,
                            "ponto_account_id": account.id,
                            "ponto_account_name": account.description or account.holder_name,
                            "ponto_iban": account.iban,
                            "ponto_currency": account.currency or "EUR",
                            "bank_account": bank_account_name,
                        },
                    )
                    added += 1

            # Sync modified timestamp with DB to avoid version conflict
            # (token refresh may have saved the doc during validate_credentials)
            settings.modified = frappe.db.get_value("Ponto Settings", "Ponto Settings", "modified")
            settings.save()

            # Build message
            message_parts = [
                _("Found {0} accounts.").format(len(ponto_accounts)),
                _("Added {0} new, updated {1} existing.").format(added, updated),
            ]
            if bank_accounts_created:
                message_parts.append(_("Created {0} Bank Accounts.").format(bank_accounts_created))
            if currency_fixes:
                message_parts.append(_("Fixed {0} Bank Account currencies.").format(currency_fixes))

            message = " ".join(message_parts)

            if bank_account_errors:
                error_list = "<br>".join(bank_account_errors[:5])  # Show first 5 errors
                if len(bank_account_errors) > 5:
                    error_list += f"<br>... and {len(bank_account_errors) - 5} more"
                frappe.msgprint(
                    _("Some Bank Accounts could not be created:<br>{0}").format(error_list),
                    indicator="orange",
                    title=_("Bank Account Creation Warnings"),
                )

            frappe.msgprint(message, indicator="green", alert=True)

            return {
                "success": True,
                "message": message,
                "accounts_found": len(ponto_accounts),
                "added": added,
                "updated": updated,
                "bank_accounts_created": bank_accounts_created,
                "bank_account_errors": bank_account_errors,
            }

        except Exception as e:
            frappe.log_error(
                title="Ponto fetch accounts failed",
                message=f"Failed to fetch Ponto accounts: {e}",
            )
            frappe.throw(
                _("Failed to fetch Ponto accounts: {0}").format(str(e)),
                title=_("API Error"),
            )

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def test_connection(self):
        """
        Test Ponto API connection (called from UI button).

        Returns:
            dict: Connection test result
        """
        try:
            self.validate_credentials()
            from verenigingen.verenigingen_payments.ponto.clients.accounts_client import PontoAccountsClient

            client = PontoAccountsClient()
            accounts = client.list_accounts()
            env = "Sandbox" if self.sandbox_mode else "Production"
            return {
                "success": True,
                "message": _(f"Connection to Ponto {env} successful"),
                "accounts_found": len(accounts),
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
            }

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def trigger_manual_sync(self):
        """
        Import transactions from Ponto for all enabled accounts.

        Note: We don't trigger bank-to-Ponto sync via API because Ponto
        requires user presence for manual sync (regulatory requirement).
        Ponto auto-syncs accounts 4x daily. This just imports what's available.

        Returns:
            dict: Import result with transaction counts
        """
        from frappe.utils import now_datetime

        try:
            from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                import_new_transactions,
            )

            # Get enabled account mappings
            enabled_mappings = self.get_enabled_account_mappings()

            if not enabled_mappings:
                frappe.throw(
                    _("No enabled Ponto accounts configured"),
                    title=_("No Accounts"),
                )

            total_imported = 0
            total_skipped = 0
            errors = []

            for mapping in enabled_mappings:
                account_id = mapping.ponto_account_id
                account_name = mapping.ponto_account_name or mapping.ponto_iban

                frappe.publish_realtime(
                    "ponto_sync_progress",
                    {"message": _("Importing from {0}...").format(account_name)},
                    user=frappe.session.user,
                )

                try:
                    # Import transactions from Ponto (uses what Ponto has already synced)
                    import_result = import_new_transactions(account_id)

                    if import_result:
                        total_imported += import_result.get("imported", 0)
                        total_skipped += import_result.get("skipped", 0)
                        if import_result.get("errors"):
                            errors.extend(import_result["errors"])

                except Exception as e:
                    error_msg = f"{account_name}: {str(e)}"
                    errors.append(error_msg)
                    frappe.logger().error(f"Ponto sync failed for {account_id}: {e}")

            # Update last sync time
            self.last_sync_time = now_datetime()
            self.save()

            # Build result message
            message = _("Sync complete. Imported {0} transactions, skipped {1} duplicates.").format(
                total_imported, total_skipped
            )

            if errors:
                frappe.msgprint(
                    _("Sync completed with errors:<br>{0}").format("<br>".join(errors[:5])),
                    indicator="orange",
                    title=_("Sync Warnings"),
                )
            else:
                frappe.msgprint(message, indicator="green", alert=True)

            return {
                "success": True,
                "message": message,
                "imported": total_imported,
                "skipped": total_skipped,
                "errors": errors,
            }

        except Exception as e:
            frappe.log_error(
                title="Ponto manual sync failed",
                message=str(e),
            )
            frappe.throw(
                _("Sync failed: {0}").format(str(e)),
                title=_("Sync Error"),
            )

    def get_enabled_account_mappings(self) -> List:
        """
        Get list of enabled bank account mappings.

        Returns:
            List of enabled Ponto Bank Account Mapping rows
        """
        return [row for row in self.bank_account_mappings if row.enabled]

    def get_mapping_for_ponto_account(self, ponto_account_id: str) -> Optional[object]:
        """
        Get the mapping for a specific Ponto account ID.

        Args:
            ponto_account_id: Ponto account UUID

        Returns:
            Ponto Bank Account Mapping row or None
        """
        for row in self.bank_account_mappings:
            if row.ponto_account_id == ponto_account_id:
                return row
        return None

    def get_bank_account_for_ponto_account(self, ponto_account_id: str) -> Optional[str]:
        """
        Get the ERPNext Bank Account for a Ponto account.

        Args:
            ponto_account_id: Ponto account UUID

        Returns:
            Bank Account name or None if not mapped
        """
        mapping = self.get_mapping_for_ponto_account(ponto_account_id)
        if mapping and mapping.enabled:
            return mapping.bank_account
        return None

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def refresh_user_info(self):
        """
        Fetch user/organization info from Ponto API and update activation status fields.

        Calls the /userinfo endpoint to get:
        - Organization name
        - Onboarding status
        - Payment activation status (outbound payments)
        - Payment requests activation status (incoming payments/betaalverzoeken)

        Returns:
            dict: Result with user info and activation status
        """
        from frappe.utils import now_datetime

        try:
            from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

            # Use PontoClient which handles mTLS if configured
            client = PontoClient()

            # The userinfo endpoint path
            # PontoClient.BASE_URL already includes /ponto-connect when mTLS is enabled,
            # so we just use /userinfo in both cases
            userinfo_endpoint = "/userinfo"

            try:
                user_info = client.get(userinfo_endpoint)
                frappe.logger().info(f"Ponto userinfo successful from: {client.BASE_URL}{userinfo_endpoint}")
            except Exception as e:
                # If mTLS is not enabled, try alternative endpoints
                if not client._use_mtls:
                    alternative_endpoints = ["/oauth2/userinfo"]
                    for alt_endpoint in alternative_endpoints:
                        try:
                            user_info = client.get(alt_endpoint)
                            frappe.logger().info(
                                f"Ponto userinfo successful from: {client.BASE_URL}{alt_endpoint}"
                            )
                            break
                        except Exception:
                            continue
                    else:
                        raise e
                else:
                    raise

            # Update fields from response
            self.organization_name = user_info.get("name", "")
            self.organization_id = user_info.get("sub", self.organization_id)
            self.onboarding_complete = 1 if user_info.get("onboardingComplete") else 0
            self.payments_activated = 1 if user_info.get("paymentsActivated") else 0
            self.payment_requests_activated = 1 if user_info.get("paymentRequestsActivated") else 0
            self.payments_activation_requested = 1 if user_info.get("paymentsActivationRequested") else 0
            self.payment_requests_activation_requested = (
                1 if user_info.get("paymentRequestsActivationRequested") else 0
            )
            self.last_status_refresh = now_datetime()

            self.save()

            # Build status message
            env = "Sandbox" if self.sandbox_mode else "Production"
            status_parts = [_("Organization: {0}").format(self.organization_name or "Unknown")]

            if self.onboarding_complete:
                status_parts.append(_("Onboarding complete"))
            else:
                status_parts.append(_("Onboarding incomplete"))

            if self.payment_requests_activated:
                status_parts.append(_("Payment Requests: Active"))
            elif self.payment_requests_activation_requested:
                status_parts.append(_("Payment Requests: Requested (pending)"))
            else:
                status_parts.append(_("Payment Requests: Not activated"))

            if self.payments_activated:
                status_parts.append(_("Outbound Payments: Active"))
            elif self.payments_activation_requested:
                status_parts.append(_("Outbound Payments: Requested (pending)"))
            else:
                status_parts.append(_("Outbound Payments: Not activated"))

            message = "<br>".join(status_parts)
            frappe.msgprint(
                message,
                indicator="green" if self.payment_requests_activated else "orange",
                title=_("Ponto {0} Status").format(env),
            )

            return {
                "success": True,
                "organization_name": self.organization_name,
                "organization_id": self.organization_id,
                "onboarding_complete": bool(self.onboarding_complete),
                "payments_activated": bool(self.payments_activated),
                "payment_requests_activated": bool(self.payment_requests_activated),
                "payments_activation_requested": bool(self.payments_activation_requested),
                "payment_requests_activation_requested": bool(self.payment_requests_activation_requested),
            }

        except Exception as e:
            frappe.log_error(
                title="Ponto refresh user info failed",
                message=str(e)[:140],  # Truncate to avoid Error Log length issues
            )
            frappe.throw(
                _("Failed to refresh Ponto status: {0}").format(str(e)),
                title=_("API Error"),
            )


def get_ponto_settings() -> PontoSettings:
    """
    Get Ponto Settings singleton document.

    Returns:
        PontoSettings: The settings document

    Raises:
        frappe.DoesNotExistError: If settings not configured
    """
    return frappe.get_single("Ponto Settings")
