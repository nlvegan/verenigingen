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

from collections import Counter
from typing import List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url, now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    IMPORT_REFUSED,
    PontoConfigurationService,
)
from verenigingen.verenigingen_payments.ponto.utils.bank_account_creator import (
    _normalise_iban,
    mapping_pause_reason,
    resolve_bank_account_for_ponto_account,
)


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
        Remove duplicate bank account mappings, keeping the first row per Ponto account ID.

        The Ponto account ID is the identity (#2125). IBAN is not: accounts without an
        IBAN, or sharing one, are different accounts.

        Returns:
            int: Number of duplicates removed
        """
        seen_ids = set()
        duplicates_to_remove = []

        for i, row in enumerate(self.bank_account_mappings or []):
            if row.ponto_account_id in seen_ids:
                duplicates_to_remove.append(i)
            else:
                seen_ids.add(row.ponto_account_id)

        # Remove duplicates in reverse order to preserve indices
        removed = 0
        for idx in reversed(duplicates_to_remove):
            self.bank_account_mappings.pop(idx)
            removed += 1

        if removed:
            frappe.logger().info(f"Removed {removed} duplicate bank account mappings")

        return removed

    @staticmethod
    def _iban_holders(ponto_accounts, mappings) -> dict:
        """Map each non-empty IBAN to the set of Ponto account IDs that carry it."""
        holders = {}
        pairs = [(a.iban, a.id) for a in ponto_accounts] + [
            (r.ponto_iban, r.ponto_account_id) for r in mappings
        ]
        for iban, account_id in pairs:
            if _normalise_iban(iban):
                holders.setdefault(_normalise_iban(iban), set()).add(account_id)
        return holders

    @staticmethod
    def _pause_row(row, reason: str):
        """Pause a mapping: nothing is imported, and the reason stays visible on the row."""
        row.enabled = 0
        row.sync_status = "Paused"
        row.last_sync_error = reason
        row.last_sync_failure_time = now_datetime()

    @staticmethod
    def _respect_concurrent_pauses(settings):
        """Carry pauses written to the database since `settings` was loaded into the rows
        about to be saved, so the save cannot un-pause them (pause_mapping does not bump
        `modified`, so the timestamp check cannot catch it)."""
        for row in settings.bank_account_mappings:
            if row.sync_status == "Paused" or not row.name:
                continue
            # FOR UPDATE: under REPEATABLE READ a plain read answers from this transaction's
            # snapshot and never sees a pause another connection committed since.
            db = frappe.db.get_value(
                "Ponto Bank Account Mapping",
                row.name,
                ["enabled", "sync_status", "last_sync_error", "last_sync_failure_time"],
                as_dict=True,
                for_update=True,
            )
            if db and db.sync_status == "Paused":
                row.enabled, row.sync_status = db.enabled, "Paused"
                row.last_sync_error, row.last_sync_failure_time = (
                    db.last_sync_error,
                    db.last_sync_failure_time,
                )

    def _audit_mappings(self, settings) -> list:
        """
        Pause every mapping whose Bank Account is shared or in the wrong currency; resume
        those WE paused whose Bank Account is now fine. Never rewrites a GL Account.

        Returns:
            list of (account label, reason) for every paused mapping.
        """
        rows = settings.bank_account_mappings
        links = Counter(row.bank_account for row in rows if row.bank_account)
        for row in rows:
            if not row.bank_account:
                continue
            reason = mapping_pause_reason(row.bank_account, row.ponto_currency, links[row.bank_account])
            if reason:
                self._pause_row(row, reason)
            elif row.sync_status == "Paused" and not (row.last_sync_error or "").startswith(IMPORT_REFUSED):
                # Only a pause THIS audit set may lift itself. An import refusal needs a person.
                row.enabled, row.sync_status, row.last_sync_error = 1, "OK", None
        return [
            (row.ponto_account_name or row.ponto_account_id, row.last_sync_error)
            for row in rows
            if row.sync_status == "Paused"
        ]

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

            # Get fresh settings after all API calls are done. Every write below goes through
            # THIS copy and the final save, so it is loaded last, and the duplicate cleanup
            # runs on it instead of saving the caller's possibly stale `self` (#2125).
            settings = frappe.get_single("Ponto Settings")
            settings.cleanup_duplicate_mappings()

            by_id = {row.ponto_account_id: row for row in settings.bank_account_mappings}
            iban_holders = self._iban_holders(ponto_accounts, settings.bank_account_mappings)
            claimed = {row.bank_account for row in settings.bank_account_mappings if row.bank_account}

            added = 0
            updated = 0
            bank_accounts_created = 0
            for account in ponto_accounts:
                row = by_id.get(account.id)
                if row:
                    updated += 1
                else:
                    row = settings.append(
                        "bank_account_mappings", {"enabled": 1, "ponto_account_id": account.id}
                    )
                    by_id[account.id] = row
                    added += 1
                row.ponto_account_name = account.description or account.holder_name
                row.ponto_iban = account.iban
                row.ponto_currency = account.currency or "EUR"

                if not row.bank_account:
                    outcome = resolve_bank_account_for_ponto_account(
                        account,
                        company,
                        shared_iban=len(iban_holders.get(_normalise_iban(account.iban), ())) > 1,
                        claimed=claimed,
                    )
                    if outcome.get("bank_account"):
                        row.bank_account = outcome["bank_account"]
                        claimed.add(row.bank_account)
                        bank_accounts_created += 1 if outcome["created"] else 0
                    else:
                        self._pause_row(row, outcome["pause_reason"])

            self._respect_concurrent_pauses(settings)
            paused = self._audit_mappings(settings)
            bank_account_errors = [f"{name}: {reason}" for name, reason in paused]

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
            if paused:
                message_parts.append(_("Paused {0} accounts.").format(len(paused)))

            message = " ".join(message_parts)

            if bank_account_errors:
                error_list = "<br>".join(bank_account_errors[:5])  # Show first 5 errors
                if len(bank_account_errors) > 5:
                    error_list += f"<br>... and {len(bank_account_errors) - 5} more"
                frappe.msgprint(
                    _("These Ponto accounts are paused and import nothing until fixed:<br>{0}").format(
                        error_list
                    ),
                    indicator="orange",
                    title=_("Ponto Accounts Paused"),
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
                "paused": len(paused),
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
        # Validate BEFORE the try: an ordinary "nothing configured" answer must reach the
        # user as is, not re-wrapped as "Sync failed" with an Error Log row.
        enabled_mappings = self.get_enabled_account_mappings()
        paused = [row for row in self.bank_account_mappings if row.sync_status == "Paused"]
        if not enabled_mappings:
            frappe.throw(
                _("No enabled Ponto accounts configured.") + self._paused_summary_html(paused),
                title=_("No Accounts"),
            )

        try:
            from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                import_new_transactions,
            )

            total_imported = 0
            total_skipped = 0
            errors = []
            paused_lines = [(r.ponto_account_name or r.ponto_iban, r.last_sync_error) for r in paused]

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

                    if import_result and import_result.get("paused"):
                        paused_lines.append((account_name, "; ".join(import_result.get("errors") or [])))
                    elif import_result:
                        total_imported += import_result.get("imported", 0)
                        total_skipped += import_result.get("skipped", 0)
                        if import_result.get("errors"):
                            errors.extend(import_result["errors"])

                except Exception as e:
                    error_msg = f"{account_name}: {str(e)}"
                    errors.append(error_msg)
                    frappe.logger().error(f"Ponto sync failed for {account_id}: {e}")

            # Update last sync time. A direct write: self.save() would write this stale
            # in-memory copy of the mappings over a pause set during the import.
            frappe.db.set_value("Ponto Settings", "Ponto Settings", "last_sync_time", now_datetime())
            PontoConfigurationService.clear_cache()

            # Build result message
            message = _("Sync complete. Imported {0} transactions, skipped {1} duplicates.").format(
                total_imported, total_skipped
            )

            if errors or paused_lines:
                details = self._paused_summary_html_from(paused_lines)
                if errors:
                    details += _("Sync completed with errors:<br>{0}").format("<br>".join(errors[:5]))
                frappe.msgprint(f"{message}<br>{details}", indicator="orange", title=_("Sync Warnings"))
            else:
                frappe.msgprint(message, indicator="green", alert=True)

            return {
                "success": True,
                "message": message,
                "imported": total_imported,
                "skipped": total_skipped,
                "errors": errors,
                "paused": [{"account": n, "reason": r} for n, r in paused_lines],
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

    @staticmethod
    def _paused_summary_html(paused_rows) -> str:
        return PontoSettings._paused_summary_html_from(
            [(r.ponto_account_name or r.ponto_iban, r.last_sync_error) for r in paused_rows]
        )

    @staticmethod
    def _paused_summary_html_from(paused_lines) -> str:
        """One block naming every paused account and why."""
        if not paused_lines:
            return ""
        lines = "<br>".join(f"{name}: {reason}" for name, reason in paused_lines)
        return "<br>" + _("Paused accounts (nothing is imported into them):") + f"<br>{lines}<br>"

    def get_enabled_account_mappings(self) -> List:
        """
        Get list of enabled bank account mappings.

        Returns:
            List of enabled Ponto Bank Account Mapping rows
        """
        return [row for row in self.bank_account_mappings if PontoConfigurationService.is_active(row)]

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
        if mapping and PontoConfigurationService.is_usable(mapping):
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

            # Direct write of just these fields: self.save() would write this possibly stale
            # copy of the mappings over a pause set meanwhile (#2125).
            frappe.db.set_value(
                "Ponto Settings",
                "Ponto Settings",
                {
                    field: self.get(field)
                    for field in (
                        "organization_name",
                        "organization_id",
                        "onboarding_complete",
                        "payments_activated",
                        "payment_requests_activated",
                        "payments_activation_requested",
                        "payment_requests_activation_requested",
                        "last_status_refresh",
                    )
                },
            )
            PontoConfigurationService.clear_cache()

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
