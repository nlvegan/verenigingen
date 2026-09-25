"""
Ponto DocType Coverage — Extra (integration, no HTTP)

Extends ``test_ponto_doctype_coverage.py`` with the pure validation /
transition / helper branches that don't make outbound Ponto API calls:

- Ponto Settings: client secret resolution, webhook application id fallback,
  bank-account-for-ponto-account lookup, before_save token protection,
  on_update cache clearing, validate_credentials missing-creds throw.
- Ponto Payment Link: format_description placeholder substitution,
  set_defaults_from_settings, on_cancel non-pending branch,
  validate_periodic_settings, process_payment_received early returns.
- Ponto Payment Request: set_ponto_account_name from settings mapping,
  on_cancel branches, create_payment_entry no-bank-account guard.

HTTP-calling branches live in ``test_ponto_doctype_unit.py``.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPontoSettingsExtra(EnhancedTestCase):
    """Helper / accessor branches of Ponto Settings that need no API call."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._original_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._original_in_test
        super().tearDown()

    def test_get_active_client_secret_sandbox_empty(self):
        """Sandbox secret resolution returns '' when not set (no raise).

        Ponto Settings is a singleton shared across the whole suite; a sibling
        test class may have persisted a sandbox secret. Establish our own empty
        state (under singleton backup so it is restored) so the unset-secret
        branch is exercised deterministically on a fresh / polluted site alike.
        """
        from verenigingen.tests.fixtures.singleton_backup import singleton_backup

        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            # validate_credentials_configured requires a sandbox client id when
            # sandbox_mode is on; set it so save() doesn't depend on a sibling test
            # having left credentials behind (order-independence).
            settings.sandbox_client_id = "sandbox-test-client-id"
            settings.sandbox_client_secret = ""
            settings.save()
            settings.reload()
            # get_password(raise_exception=False) on unset field -> "" via `or ""`
            self.assertEqual(settings.get_active_client_secret(), "")

    def test_get_webhook_application_id_explicit(self):
        """Explicit webhook_application_id is returned verbatim."""
        settings = frappe.get_single("Ponto Settings")
        settings.webhook_application_id = "app-explicit-123"
        self.assertEqual(settings.get_webhook_application_id(), "app-explicit-123")

    def test_get_webhook_application_id_falls_back_to_client_id(self):
        """Falls back to active client id when no webhook app id set."""
        settings = frappe.get_single("Ponto Settings")
        settings.webhook_application_id = ""
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-fallback-id"
        self.assertEqual(settings.get_webhook_application_id(), "sandbox-fallback-id")

    def test_get_mapping_for_known_account(self):
        """Lookup returns the matching mapping row by Ponto account id."""
        settings = frappe.get_single("Ponto Settings")
        original = list(settings.bank_account_mappings or [])
        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {"ponto_account_id": "acct-known", "ponto_iban": "NL91ABNA0417164300", "enabled": 1},
        )
        row = settings.get_mapping_for_ponto_account("acct-known")
        self.assertIsNotNone(row)
        self.assertEqual(row.ponto_account_id, "acct-known")
        settings.bank_account_mappings = original

    def test_get_bank_account_for_ponto_account_enabled(self):
        """Returns mapped bank account when mapping is enabled."""
        settings = frappe.get_single("Ponto Settings")
        original = list(settings.bank_account_mappings or [])
        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": "acct-x",
                "ponto_iban": "NL91ABNA0417164300",
                "enabled": 1,
                "bank_account": "Some Bank Account - X",
            },
        )
        self.assertEqual(
            settings.get_bank_account_for_ponto_account("acct-x"),
            "Some Bank Account - X",
        )
        settings.bank_account_mappings = original

    def test_get_bank_account_for_ponto_account_disabled_returns_none(self):
        """Disabled mapping yields None even if a bank account is set."""
        settings = frappe.get_single("Ponto Settings")
        original = list(settings.bank_account_mappings or [])
        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": "acct-off",
                "ponto_iban": "NL91ABNA0417164300",
                "enabled": 0,
                "bank_account": "Some Bank Account - X",
            },
        )
        self.assertIsNone(settings.get_bank_account_for_ponto_account("acct-off"))
        settings.bank_account_mappings = original

    def test_get_bank_account_for_unknown_account_returns_none(self):
        """Unknown Ponto account id yields None."""
        settings = frappe.get_single("Ponto Settings")
        self.assertIsNone(settings.get_bank_account_for_ponto_account("does-not-exist"))

    def test_before_save_protects_token_fields(self):
        """before_save adds OAuth token fields to ignore_save_passwords."""
        settings = frappe.get_single("Ponto Settings")
        settings.flags.ignore_save_passwords = None  # exercise the init branch
        settings.before_save()
        self.assertIn("ibanity_refresh_token", settings.flags.ignore_save_passwords)
        self.assertIn("ibanity_access_token", settings.flags.ignore_save_passwords)

    def test_before_save_idempotent(self):
        """Calling before_save twice does not duplicate the protected fields."""
        settings = frappe.get_single("Ponto Settings")
        settings.flags.ignore_save_passwords = []
        settings.before_save()
        settings.before_save()
        self.assertEqual(settings.flags.ignore_save_passwords.count("ibanity_access_token"), 1)

    def test_clear_configuration_cache(self):
        """clear_configuration_cache removes the cached settings value."""
        settings = frappe.get_single("Ponto Settings")
        frappe.cache().set_value("ponto_settings_cache", {"x": 1})
        settings.clear_configuration_cache()
        self.assertIsNone(frappe.cache().get_value("ponto_settings_cache"))

    def test_on_update_clears_caches(self):
        """on_update should clear configuration and token caches without error."""
        settings = frappe.get_single("Ponto Settings")
        frappe.cache().set_value("ponto_settings_cache", {"x": 1})
        settings.on_update()
        self.assertIsNone(frappe.cache().get_value("ponto_settings_cache"))

    def test_validate_credentials_missing_throws(self):
        """validate_credentials throws before any API call when creds missing."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = ""
        with self.assertRaises(frappe.ValidationError):
            settings.validate_credentials()

    def test_cleanup_duplicate_mappings_no_duplicates(self):
        """cleanup with all-unique IBANs removes nothing."""
        settings = frappe.get_single("Ponto Settings")
        original = list(settings.bank_account_mappings or [])
        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {"ponto_iban": "NL91ABNA0417164300", "enabled": 1, "ponto_account_id": "a1"},
        )
        settings.append(
            "bank_account_mappings",
            {"ponto_iban": "NL53RABO0123456789", "enabled": 1, "ponto_account_id": "b1"},
        )
        self.assertEqual(settings.cleanup_duplicate_mappings(), 0)
        settings.bank_account_mappings = original


class TestPontoPaymentLinkExtra(EnhancedTestCase):
    """Validation / transition / formatting branches that make no API call."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_link(self, **kwargs):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = kwargs.pop("payment_type", "One-Time")
        doc.amount = kwargs.pop("amount", 25.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.description = kwargs.pop("description", "Test payment")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Association")
        doc.creditor_iban = kwargs.pop("creditor_iban", "NL91ABNA0417164300")
        doc.update(kwargs)
        return doc

    def test_format_description_with_explicit_template(self):
        """Placeholders are substituted; unknown ones blanked but text kept."""
        link = self._create_link()
        link.insert()
        result = link.format_description("Hello MEMBER_NAME (MEMBER_ID)")
        # No member set -> name blank, id blank. The interior double-space from
        # the blank MEMBER_NAME remains (only ends are stripped).
        self.assertEqual(result, "Hello  ()")

    def test_format_description_with_member(self):
        """MEMBER_NAME / MEMBER_ID resolved from linked Member."""
        member = self.create_test_member(
            first_name="Ponto", last_name="Tester", email="ponto.tester@example.com"
        )
        link = self._create_link(member=member.name)
        link.insert()
        result = link.format_description("Dues for MEMBER_NAME")
        self.assertIn("Ponto", result)

    def test_format_description_default_template_used(self):
        """When no template passed and no settings template, default is used."""
        link = self._create_link()
        link.insert()
        result = link.format_description(None)
        # Default template references coverage dates and member fields
        self.assertIsInstance(result, str)
        self.assertNotIn("MEMBER_NAME", result)
        self.assertNotIn("MEMBER_ID", result)

    def test_set_defaults_from_settings_keeps_explicit_creditor(self):
        """Explicit creditor fields are not overwritten by settings defaults."""
        link = self._create_link(creditor_name="Explicit Org", creditor_iban="NL91ABNA0417164300")
        link.set_defaults_from_settings()
        self.assertEqual(link.creditor_name, "Explicit Org")

    def test_on_cancel_non_pending_sets_cancelled_without_api(self):
        """on_cancel for a non-pending link just sets status to Cancelled."""
        link = self._create_link()
        link.insert()
        link.status = "Draft"
        link.ponto_request_id = None
        link.on_cancel()
        self.assertEqual(link.status, "Cancelled")

    def test_cancel_ponto_request_no_id_noop(self):
        """cancel_ponto_request returns silently when no request id."""
        link = self._create_link()
        link.insert()
        link.ponto_request_id = None
        # Should not raise and not attempt an API call
        link.cancel_ponto_request()

    def test_process_payment_received_already_processed(self):
        """process_payment_received returns early if payment_entry already set."""
        link = self._create_link()
        link.insert()
        link.payment_entry = "PE-EXISTING"
        # Early return — no Payment Entry creation attempted
        link.process_payment_received()
        self.assertEqual(link.payment_entry, "PE-EXISTING")

    def test_validate_periodic_settings_one_time_ok(self):
        """One-Time payment passes the periodic guard."""
        link = self._create_link(payment_type="One-Time")
        link.validate_periodic_settings()  # should not raise

    def test_update_status_from_webhook_no_change(self):
        """Webhook with same status performs no update."""
        link = self._create_link()
        link.insert()
        current = link.status
        link.update_status_from_webhook(current)
        self.assertEqual(link.status, current)


class TestPontoPaymentRequestExtra(EnhancedTestCase):
    """Validation / transition branches of Ponto Payment Request (no API)."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_request(self, **kwargs):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = kwargs.pop("ponto_account", "test-account-uuid")
        doc.amount = kwargs.pop("amount", 50.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Supplier")
        doc.creditor_iban = kwargs.pop("creditor_iban", "DE89370400440532013000")
        doc.remittance_info = kwargs.pop("remittance_info", "Invoice payment")
        doc.update(kwargs)
        return doc

    def test_set_ponto_account_name_from_mapping(self):
        """ponto_account_name is filled from the matching settings mapping.

        set_ponto_account_name() re-loads the Ponto Settings singleton from the
        DB, so the mapping must be persisted (not just appended in memory). We
        run inside frappe.flags.in_test so the test-credential guard is skipped,
        and restore the original mappings afterwards.
        """
        from verenigingen.tests.fixtures.singleton_backup import singleton_backup

        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id-for-test"
            settings.bank_account_mappings = []
            settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": "acct-named",
                    "ponto_iban": "NL91ABNA0417164300",
                    "ponto_account_name": "Main Business Account",
                    "enabled": 1,
                },
            )
            settings.save()

            req = self._create_request(ponto_account="acct-named")
            req.ponto_account_name = None
            req.set_ponto_account_name()
            self.assertEqual(req.ponto_account_name, "Main Business Account")

    def test_set_ponto_account_name_no_match_unchanged(self):
        """No matching mapping leaves ponto_account_name unset."""
        req = self._create_request(ponto_account="acct-unmapped")
        req.ponto_account_name = None
        req.set_ponto_account_name()
        self.assertIsNone(req.ponto_account_name)

    def test_on_cancel_non_pending_sets_cancelled(self):
        """on_cancel without a pending API payment just marks Cancelled."""
        req = self._create_request()
        req.insert()
        req.status = "Draft"
        req.ponto_payment_id = None
        req.on_cancel()
        self.assertEqual(req.status, "Cancelled")

    def test_cancel_ponto_payment_no_id_noop(self):
        """cancel_ponto_payment returns silently when no payment id."""
        req = self._create_request()
        req.insert()
        req.ponto_payment_id = None
        req.cancel_ponto_payment()

    def test_create_payment_entry_already_created(self):
        """create_payment_entry returns early when payment_entry already set."""
        req = self._create_request()
        req.insert()
        req.payment_entry = "PE-EXISTING"
        req.create_payment_entry()
        self.assertEqual(req.payment_entry, "PE-EXISTING")

    def test_create_payment_entry_no_bank_account_guard(self):
        """No mapped bank account -> create_payment_entry RAISES (#1323 review:
        a plain return here silently released the caller's atomic-transition
        savepoint, committing "Executed" with no Payment Entry and no trail)."""
        req = self._create_request(ponto_account="acct-with-no-mapping")
        req.insert()
        # No mapping for this account -> bank_account stays None -> must raise
        with self.assertRaises(frappe.ValidationError):
            req.create_payment_entry()
        self.assertFalse(req.payment_entry)

    def _mapped_bank_account(self, ponto_account_id, bank_account):
        """Point a Ponto Settings mapping at `bank_account`, restored on exit.

        `validate_credentials_configured()` throws "Sandbox Client ID is
        required when Sandbox Mode is enabled" when sandbox_mode is truthy and
        sandbox_client_id is empty - and sandbox_mode's JSON default is "1"
        with no default for sandbox_client_id, so a site whose singleton has
        never had a sandbox client id set (e.g. test_site_7) ERRORs here before
        create_payment_entry is ever reached. A site that happens to carry a
        leftover sandbox_client_id from another test masks this - test_site_2
        did. Set both explicitly (same pattern as
        TestPontoSettingsExtra.test_get_active_client_secret_sandbox_empty)
        instead of depending on whatever a sibling test left behind.
        """
        from verenigingen.tests.fixtures.singleton_backup import singleton_backup

        ctx = singleton_backup("Ponto Settings")
        ctx.__enter__()
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-test-client-id"
        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": ponto_account_id,
                "ponto_iban": "NL91ABNA0417164300",
                "bank_account": bank_account,
                "enabled": 1,
            },
        )
        settings.save()
        return ctx

    def test_create_payment_entry_with_supplier_posts_balanced_pe(self):
        """A mapped bank account + Supplier reference produces a correctly
        accounted, submitted Payment Entry.

        #1200: this construction never set paid_from/paid_to/paid_to's party
        account at all, so insert() always failed the same #906 way ("Source
        Exchange Rate is mandatory" - set_exchange_rate() cannot resolve a
        currency without paid_from being set). Asserts on GL Entry rows, not
        just docstatus (verenigingen-test-harness skill): a submit() failure
        can leave docstatus=1 behind a half-posted ledger.
        """
        from verenigingen.tests.support.sepa_test_company import (
            get_eur_bank_account,
            get_eur_test_company,
        )

        company = get_eur_test_company()
        bank_account = get_eur_bank_account(company)
        bank_gl_account = frappe.db.get_value("Bank Account", bank_account, "account")

        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = f"Ponto Test Supplier {frappe.generate_hash(length=6)}"
        supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
        supplier.save()
        self.track_doc("Supplier", supplier.name)

        ctx = self._mapped_bank_account("acct-with-supplier", bank_account)
        try:
            req = self._create_request(
                ponto_account="acct-with-supplier",
                reference_doctype="Supplier",
                reference_name=supplier.name,
            )
            req.insert()
            # Priority 6: drains before the Supplier (default priority 0),
            # mirroring DRAIN_PRIORITY_BY_DOCTYPE's "Payment Entry" tier - both
            # this doc and the Payment Entry below reference the Supplier, so
            # deleting it first breaks cancel/delete with "Could not find Party".
            self.factory.track_document("Ponto Payment Request", req.name, priority=6)

            with self.assertNoErrorLog():
                req.create_payment_entry()
        finally:
            ctx.__exit__(None, None, None)

        req.reload()
        self.assertTrue(
            req.payment_entry, "create_payment_entry should have created and linked a Payment Entry"
        )

        pe = frappe.get_doc("Payment Entry", req.payment_entry)
        self.factory.track_document("Payment Entry", pe.name, priority=6)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.company, company)
        self.assertEqual(pe.party_type, "Supplier")
        self.assertEqual(pe.party, supplier.name)
        self.assertEqual(pe.paid_from, bank_gl_account)
        expected_paid_to = frappe.get_cached_value("Company", company, "default_payable_account")
        self.assertEqual(pe.paid_to, expected_paid_to)

        gl_rows = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
            fields=["account", "debit", "credit"],
        )
        self.assertEqual(len(gl_rows), 2, "a Pay entry with a party posts exactly two GL rows")
        total_debit = sum(r.debit for r in gl_rows)
        total_credit = sum(r.credit for r in gl_rows)
        self.assertEqual(total_debit, total_credit, "GL rows must balance")
        self.assertEqual(total_debit, req.amount)

    def test_create_payment_entry_no_party_guard(self):
        """No reference Supplier/Employee -> refuses rather than posting with a
        guessed paid_to account (#1200 self-review: fail closed, not open).

        "Fail closed" now means RAISE, not silently return (#1323 review): a
        plain return here silently released the caller's atomic-transition
        savepoint, committing "Executed" with no Payment Entry and no trail --
        exactly the bug #1200's own comment says this guard exists to avoid.
        """
        from verenigingen.tests.support.sepa_test_company import (
            get_eur_bank_account,
            get_eur_test_company,
        )

        company = get_eur_test_company()
        bank_account = get_eur_bank_account(company)

        ctx = self._mapped_bank_account("acct-no-party", bank_account)
        try:
            req = self._create_request(ponto_account="acct-no-party")
            req.insert()
            self.track_doc("Ponto Payment Request", req.name)
            with self.assertRaises(frappe.ValidationError):
                req.create_payment_entry()
        finally:
            ctx.__exit__(None, None, None)

        self.assertFalse(req.payment_entry)

    def test_update_status_from_webhook_no_change(self):
        """Webhook with unchanged status performs no update."""
        req = self._create_request()
        req.insert()
        current = req.status
        req.update_status_from_webhook(current)
        self.assertEqual(req.status, current)
