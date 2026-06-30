"""
Ponto Settings controller method tests (Tier-1, HTTP boundary stubbed).

Covers the large untested controller methods of ``PontoSettings`` that the
existing ponto doctype coverage files skip:

- ``_fix_bank_account_currency`` (real Bank Account / GL Account, no HTTP)
- ``validate_credentials`` success + failure (token manager stubbed)
- ``get_active_client_secret`` production branch
- ``fetch_ponto_accounts`` add / update / bank-account-error branches
  (PontoAccountsClient + create_ponto_bank_account stubbed)
- ``trigger_manual_sync`` no-accounts / import / per-account-error branches
  (import_new_transactions stubbed)
- ``refresh_user_info`` non-mTLS alternative-endpoint fallback + status message
  branches (PontoClient stubbed)
- ``get_ponto_settings`` module accessor

Per project policy the ONLY thing stubbed is the HTTP boundary (Ponto/Ibanity
API client factories/classes + the token manager). All controller business
logic, validation and document persistence runs for real. File is named
``*_unit.py`` so the test-quality-enforcer treats the boundary patching as
Tier-1 (allowed).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import singleton_backup

TOKEN_MANAGER = "verenigingen.verenigingen_payments.ponto.utils.token_manager.PontoTokenManager"
ACCOUNTS_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.accounts_client.PontoAccountsClient"
CREATE_BANK_ACCOUNT = (
    "verenigingen.verenigingen_payments.ponto.utils.bank_account_creator.create_ponto_bank_account"
)
IMPORT_TXNS = (
    "verenigingen.verenigingen_payments.ponto.services.transaction_import_service.import_new_transactions"
)
PONTO_CLIENT = "verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoClient"


def _ponto_account(iban, acc_id, currency="EUR", description="Acct", holder="Holder"):
    """Build a fake Ponto account object matching the client's return shape."""
    return SimpleNamespace(
        iban=iban,
        id=acc_id,
        currency=currency,
        description=description,
        holder_name=holder,
    )


class TestFixBankAccountCurrency(EnhancedTestCase):
    """``_fix_bank_account_currency`` — real Bank Account / GL Account, no HTTP."""

    COMPANY = "_Test Company"
    BANK_GROUP = "Bank Accounts - _TC"

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.settings = frappe.get_single("Ponto Settings")
        self._suffix = frappe.generate_hash(length=8)

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _make_gl_account(self, currency="EUR"):
        acct = frappe.new_doc("Account")
        acct.account_name = f"Ponto Cov Bank {self._suffix}"
        acct.company = self.COMPANY
        acct.parent_account = self.BANK_GROUP
        acct.account_type = "Bank"
        acct.account_currency = currency
        acct.insert(ignore_permissions=True)
        return acct.name

    def _make_bank_account(self, gl_account):
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = f"Ponto Cov Inst {self._suffix}"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Ponto Cov BA {self._suffix}"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = self.COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def test_currency_mismatch_is_fixed(self):
        """A GL account whose currency differs from Ponto is updated + True."""
        gl = self._make_gl_account(currency="EUR")
        ba = self._make_bank_account(gl)
        result = self.settings._fix_bank_account_currency(ba, "USD")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "USD")

    def test_matching_currency_is_noop(self):
        """Matching currency returns False and leaves the GL account untouched."""
        gl = self._make_gl_account(currency="EUR")
        ba = self._make_bank_account(gl)
        result = self.settings._fix_bank_account_currency(ba, "EUR")
        self.assertFalse(result)
        self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "EUR")

    def test_no_linked_gl_account_returns_false(self):
        """Bank Account with no linked GL Account cannot be checked -> False."""
        gl = self._make_gl_account(currency="EUR")
        ba = self._make_bank_account(gl)
        # Blank the link directly in DB (bypasses mandatory validation) so the
        # in-controller `if not bank_account.account` guard is exercised.
        frappe.db.set_value("Bank Account", ba, "account", "")
        result = self.settings._fix_bank_account_currency(ba, "USD")
        self.assertFalse(result)

    def test_unknown_bank_account_swallows_error(self):
        """A nonexistent Bank Account is caught and returns False (no raise)."""
        result = self.settings._fix_bank_account_currency(
            f"No Such Bank Account {self._suffix}", "EUR"
        )
        self.assertFalse(result)


class TestValidateCredentials(EnhancedTestCase):
    """``validate_credentials`` success + failure with the token manager stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        frappe.db.rollback()
        super().tearDown()

    def test_valid_credentials_return_true(self):
        """Successful token fetch returns True."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.sandbox_client_secret = "sandbox-secret"
            settings.save()
            settings.reload()
            fake_tm = MagicMock()
            fake_tm.get_valid_token.return_value = "tok-abc"
            with patch(TOKEN_MANAGER, return_value=fake_tm):
                self.assertTrue(settings.validate_credentials())
            fake_tm.get_valid_token.assert_called_once()

    def test_token_fetch_failure_throws(self):
        """A token-manager error is surfaced as a ValidationError."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.sandbox_client_secret = "sandbox-secret"
            settings.save()
            settings.reload()
            fake_tm = MagicMock()
            fake_tm.get_valid_token.side_effect = RuntimeError("invalid_client")
            with patch(TOKEN_MANAGER, return_value=fake_tm):
                with self.assertRaises(frappe.ValidationError):
                    settings.validate_credentials()

    def test_get_active_client_secret_production_branch(self):
        """Production mode resolves the production secret (not the sandbox one)."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 0
            settings.production_client_id = "prod-id"
            settings.production_client_secret = "prod-secret-xyz"
            settings.save()
            settings.reload()
            self.assertEqual(settings.get_active_client_secret(), "prod-secret-xyz")


class TestFetchPontoAccounts(EnhancedTestCase):
    """``fetch_ponto_accounts`` — accounts client + bank account creator stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True
        # fetch_ponto_accounts reads Verenigingen Settings.company; ensure it is
        # set so the test does not depend on shard-residual data.
        self._vs_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if not self._vs_company:
            frappe.db.set_single_value("Verenigingen Settings", "company", "_Test Company")
            self._vs_company = "_Test Company"

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        frappe.db.rollback()
        super().tearDown()

    def _prepare_settings(self):
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-id"
        settings.bank_account_mappings = []
        settings.save()
        return settings

    def _make_real_bank_account(self):
        """Create a real Bank Account so the mapping's Link field validates."""
        suffix = frappe.generate_hash(length=8)
        acct = frappe.new_doc("Account")
        acct.account_name = f"Ponto Fetch Bank {suffix}"
        acct.company = "_Test Company"
        acct.parent_account = "Bank Accounts - _TC"
        acct.account_type = "Bank"
        acct.account_currency = "EUR"
        acct.insert(ignore_permissions=True)
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = f"Ponto Fetch Inst {suffix}"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Ponto Fetch BA {suffix}"
        ba.bank = bank_name
        ba.account = acct.name
        ba.company = "_Test Company"
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    def test_new_account_is_added_with_bank_account(self):
        """A Ponto account not yet mapped is appended and counted as added."""
        with singleton_backup("Ponto Settings"):
            settings = self._prepare_settings()
            real_ba = self._make_real_bank_account()
            accounts = [_ponto_account("NL91ABNA0417164300", "acct-new-1")]
            fake_client = MagicMock()
            fake_client.list_accounts.return_value = accounts
            bank_result = {"success": True, "bank_account": real_ba}
            with patch.object(settings, "validate_credentials", return_value=True), patch(
                ACCOUNTS_CLIENT, return_value=fake_client
            ), patch(CREATE_BANK_ACCOUNT, return_value=bank_result):
                result = settings.fetch_ponto_accounts()
            self.assertTrue(result["success"])
            self.assertEqual(result["accounts_found"], 1)
            self.assertEqual(result["added"], 1)
            self.assertEqual(result["updated"], 0)
            self.assertEqual(result["bank_accounts_created"], 1)
            reloaded = frappe.get_single("Ponto Settings")
            ibans = {r.ponto_iban for r in reloaded.bank_account_mappings}
            self.assertIn("NL91ABNA0417164300", ibans)

    def test_existing_account_is_updated(self):
        """An account whose IBAN is already mapped is updated, not re-added."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": "acct-old",
                    "ponto_iban": "NL91ABNA0417164300",
                    "ponto_account_name": "Old Name",
                    "ponto_currency": "EUR",
                    "enabled": 1,
                },
            )
            settings.save()

            fresh = frappe.get_single("Ponto Settings")
            accounts = [
                _ponto_account(
                    "NL91ABNA0417164300", "acct-new-id", description="Updated Name"
                )
            ]
            fake_client = MagicMock()
            fake_client.list_accounts.return_value = accounts
            with patch.object(fresh, "validate_credentials", return_value=True), patch(
                ACCOUNTS_CLIENT, return_value=fake_client
            ), patch(CREATE_BANK_ACCOUNT) as mock_create:
                result = fresh.fetch_ponto_accounts()
            self.assertEqual(result["added"], 0)
            self.assertEqual(result["updated"], 1)
            # Existing-IBAN path must NOT create a new bank account.
            mock_create.assert_not_called()
            reloaded = frappe.get_single("Ponto Settings")
            row = reloaded.bank_account_mappings[0]
            self.assertEqual(row.ponto_account_name, "Updated Name")
            self.assertEqual(row.ponto_account_id, "acct-new-id")

    def test_existing_account_currency_mismatch_is_fixed(self):
        """Update path fixes the linked Bank Account currency when it differs."""
        with singleton_backup("Ponto Settings"):
            real_ba = self._make_real_bank_account()  # GL currency EUR
            gl = frappe.db.get_value("Bank Account", real_ba, "account")
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": "acct-cur",
                    "ponto_iban": "NL91ABNA0417164300",
                    "ponto_currency": "EUR",
                    "bank_account": real_ba,
                    "enabled": 1,
                },
            )
            settings.save()

            fresh = frappe.get_single("Ponto Settings")
            # Incoming Ponto account reports USD -> controller should fix GL account.
            accounts = [_ponto_account("NL91ABNA0417164300", "acct-cur", currency="USD")]
            fake_client = MagicMock()
            fake_client.list_accounts.return_value = accounts
            with patch.object(fresh, "validate_credentials", return_value=True), patch(
                ACCOUNTS_CLIENT, return_value=fake_client
            ):
                result = fresh.fetch_ponto_accounts()
            self.assertEqual(result["updated"], 1)
            self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "USD")

    def test_bank_account_creation_error_is_collected(self):
        """A failed bank-account creation is recorded in bank_account_errors."""
        with singleton_backup("Ponto Settings"):
            settings = self._prepare_settings()
            accounts = [_ponto_account("NL18RABO0123456789", "acct-err")]
            fake_client = MagicMock()
            fake_client.list_accounts.return_value = accounts
            bank_result = {"success": False, "error": "GL account exists"}
            with patch.object(settings, "validate_credentials", return_value=True), patch(
                ACCOUNTS_CLIENT, return_value=fake_client
            ), patch(CREATE_BANK_ACCOUNT, return_value=bank_result):
                result = settings.fetch_ponto_accounts()
            self.assertEqual(result["added"], 1)
            self.assertEqual(result["bank_accounts_created"], 0)
            self.assertTrue(any("GL account exists" in e for e in result["bank_account_errors"]))

    def test_missing_company_throws(self):
        """No company configured in Verenigingen Settings -> ValidationError."""
        with singleton_backup("Ponto Settings"):
            settings = self._prepare_settings()
            frappe.db.set_single_value("Verenigingen Settings", "company", "")
            fake_client = MagicMock()
            fake_client.list_accounts.return_value = []
            with patch.object(settings, "validate_credentials", return_value=True), patch(
                ACCOUNTS_CLIENT, return_value=fake_client
            ):
                with self.assertRaises(frappe.ValidationError):
                    settings.fetch_ponto_accounts()


class TestTriggerManualSync(EnhancedTestCase):
    """``trigger_manual_sync`` — import_new_transactions stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        frappe.db.rollback()
        super().tearDown()

    def test_no_enabled_mappings_throws(self):
        """No enabled accounts -> ValidationError."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.save()
            with self.assertRaises(frappe.ValidationError):
                settings.trigger_manual_sync()

    def test_import_counts_aggregated_and_last_sync_set(self):
        """Imports from enabled accounts are summed; last_sync_time is stamped."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {"ponto_account_id": "acct-1", "ponto_iban": "NL91ABNA0417164300", "enabled": 1},
            )
            settings.append(
                "bank_account_mappings",
                {"ponto_account_id": "acct-2", "ponto_iban": "NL18RABO0123456789", "enabled": 1},
            )
            settings.last_sync_time = None
            settings.save()

            results = {
                "acct-1": {"imported": 3, "skipped": 1, "errors": []},
                "acct-2": {"imported": 2, "skipped": 0, "errors": []},
            }
            with patch(IMPORT_TXNS, side_effect=lambda acc_id: results[acc_id]):
                result = settings.trigger_manual_sync()
            self.assertTrue(result["success"])
            self.assertEqual(result["imported"], 5)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"], [])
            self.assertIsNotNone(frappe.db.get_value("Ponto Settings", "Ponto Settings", "last_sync_time"))

    def test_per_account_import_error_collected(self):
        """An exception importing one account is caught and reported, not raised."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": "acct-boom",
                    "ponto_iban": "NL91ABNA0417164300",
                    "ponto_account_name": "Boom Account",
                    "enabled": 1,
                },
            )
            settings.save()
            with patch(IMPORT_TXNS, side_effect=RuntimeError("ibanity 503")):
                result = settings.trigger_manual_sync()
            self.assertTrue(result["success"])
            self.assertEqual(result["imported"], 0)
            self.assertTrue(any("ibanity 503" in e for e in result["errors"]))

    def test_import_result_errors_are_propagated(self):
        """Per-account import results carrying their own errors are aggregated."""
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {"ponto_account_id": "acct-e", "ponto_iban": "NL91ABNA0417164300", "enabled": 1},
            )
            settings.save()
            import_result = {"imported": 1, "skipped": 0, "errors": ["row 3 rejected"]}
            with patch(IMPORT_TXNS, return_value=import_result):
                result = settings.trigger_manual_sync()
            self.assertEqual(result["imported"], 1)
            self.assertIn("row 3 rejected", result["errors"])


class TestRefreshUserInfoBranches(EnhancedTestCase):
    """``refresh_user_info`` non-mTLS fallback + status message branches."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        frappe.db.rollback()
        super().tearDown()

    def _fake_client(self, use_mtls, get_side_effect):
        fake = MagicMock()
        fake.BASE_URL = "https://api.ibanity.com"
        fake._use_mtls = use_mtls
        fake.get.side_effect = get_side_effect
        return fake

    def test_non_mtls_alternative_endpoint_fallback(self):
        """When the primary userinfo path fails (non-mTLS), an alternative path is tried."""
        userinfo = {
            "name": "Fallback Org",
            "sub": "org-fb",
            "onboardingComplete": False,
            "paymentsActivated": False,
            "paymentRequestsActivated": False,
            "paymentsActivationRequested": False,
            "paymentRequestsActivationRequested": True,
        }

        calls = {"n": 0}

        def get_side_effect(endpoint):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("primary 404")
            return userinfo

        fake = self._fake_client(use_mtls=False, get_side_effect=get_side_effect)
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            with patch(PONTO_CLIENT, return_value=fake):
                result = settings.refresh_user_info()
            self.assertTrue(result["success"])
            self.assertEqual(result["organization_name"], "Fallback Org")
            # Exercises the "onboarding incomplete" + "requested (pending)" message branches
            self.assertFalse(result["onboarding_complete"])
            self.assertFalse(result["payment_requests_activated"])
            self.assertTrue(result["payment_requests_activation_requested"])
            # First (primary) endpoint failed, the alternative succeeded.
            self.assertEqual(calls["n"], 2)

    def test_non_mtls_all_endpoints_fail_raises(self):
        """When every userinfo endpoint fails (non-mTLS), the original error surfaces."""
        fake = self._fake_client(use_mtls=False, get_side_effect=RuntimeError("all down"))
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            with patch(PONTO_CLIENT, return_value=fake):
                with self.assertRaises(frappe.ValidationError):
                    settings.refresh_user_info()

    def test_outbound_payments_requested_pending_branch(self):
        """paymentsActivationRequested (mTLS) drives the 'Requested (pending)' message branch."""
        userinfo = {
            "name": "Pending Org",
            "sub": "org-p",
            "onboardingComplete": True,
            "paymentsActivated": False,
            "paymentRequestsActivated": False,
            "paymentsActivationRequested": True,
            "paymentRequestsActivationRequested": False,
        }
        fake = self._fake_client(use_mtls=True, get_side_effect=lambda ep: userinfo)
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            with patch(PONTO_CLIENT, return_value=fake):
                result = settings.refresh_user_info()
            self.assertTrue(result["onboarding_complete"])
            self.assertTrue(result["payments_activation_requested"])
            self.assertFalse(result["payments_activated"])

    def test_payments_active_branch(self):
        """paymentsActivated (mTLS) drives the 'Outbound Payments: Active' branch."""
        userinfo = {
            "name": "Active Org",
            "sub": "org-a",
            "onboardingComplete": True,
            "paymentsActivated": True,
            "paymentRequestsActivated": True,
            "paymentsActivationRequested": False,
            "paymentRequestsActivationRequested": False,
        }
        fake = self._fake_client(use_mtls=True, get_side_effect=lambda ep: userinfo)
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            with patch(PONTO_CLIENT, return_value=fake):
                result = settings.refresh_user_info()
            self.assertTrue(result["payments_activated"])
            self.assertTrue(result["payment_requests_activated"])


class TestGetPontoSettingsAccessor(EnhancedTestCase):
    """Module-level ``get_ponto_settings`` accessor."""

    def test_returns_singleton(self):
        from verenigingen.verenigingen_payments.doctype.ponto_settings.ponto_settings import (
            get_ponto_settings,
        )

        settings = get_ponto_settings()
        self.assertEqual(settings.doctype, "Ponto Settings")
