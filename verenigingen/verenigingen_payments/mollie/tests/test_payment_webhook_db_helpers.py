"""
DB-integration tests (Tier-2) for the LIVE database-backed helpers in
mollie/api/payment_webhook.py.

These helpers are imported by integrations/mollie/__init__.py (public surface),
payment_entry_factory, and the failed-payment path, so they are live. The pure
SDK-normalisation helpers (extract_mollie_payment_data, _determine_recurring_status,
_validate_payment_amount, _extract_record_reference_from_mollie_data) are already
covered in test_payment_webhook_helpers_unit.py; this file covers the helpers that
read/write real DocTypes, exercised against the real database via the Enhanced Test
Factory with NO mocks of the logic under test. The Mollie SDK payment object is the
only boundary, stubbed with types.SimpleNamespace.

Targets:
- get_appropriate_cost_center            (cost-center selection by donation purpose)
- update_donation_with_mollie_data       (metadata persistence)
- update_donation_payment_history        (child-table append + idempotency)
- create_payment_entry_for_donation      (PE creation + idempotency + guest customer)
- check_payment_processing_status_by_id  (idempotency status probe)
- find_member_for_payment                (member matching strategies)
- _get_subscription_failure_count        (atomic failure counting)
- _validate_webhook_signature            (HMAC validation, PermissionError path)
"""

import types

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
    _get_subscription_failure_count,
    _validate_webhook_signature,
    check_payment_processing_status_by_id,
    create_payment_entry_for_donation,
    find_member_for_payment,
    get_appropriate_cost_center,
    update_donation_payment_history,
    update_donation_with_mollie_data,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    mollie_settings_override,
    sign_payload,
)


def _company():
    return frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")


def _make_unsubmitted_donation(test_case, donor_name="Webhook Helper Donor", amount=75.0):
    """Create a docstatus=0 Donation so its child tables can be appended.

    create_test_donation force-submits; we need an open doc to append payment
    rows. Lives at module scope so the insert is a recognised factory pattern.
    """
    donor = test_case.create_test_donor(donor_name=donor_name)
    donation = frappe.get_doc(
        {
            "doctype": "Donation",
            "company": _company(),
            "donor": donor.name,
            "amount": amount,
            "donation_date": getdate(),
            "currency": "EUR",
            "paid": 0,
            "mode_of_payment": "Bank Transfer",
        }
    ).insert()
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Donation", donation.name)
        factory.track_document("Donor", donor.name)
    return donation, donor


class TestGetAppropriateCostCenter(EnhancedTestCase):
    def test_no_donation_returns_a_cost_center(self):
        cc = get_appropriate_cost_center(None, _company())
        self.assertTrue(cc)
        self.assertTrue(frappe.db.exists("Cost Center", cc))

    def test_general_cost_center_preferred(self):
        """A donation with a non-Chapter purpose selects a General/Main cost
        center (the _Test Company has a 'Main' leaf cost center)."""
        donation, _ = _make_unsubmitted_donation(self, donor_name="CostCenter Donor")
        cc = get_appropriate_cost_center(donation, _company())
        self.assertTrue(frappe.db.exists("Cost Center", cc))
        # Must be a leaf cost center of the company (never a group node).
        self.assertEqual(frappe.db.get_value("Cost Center", cc, "is_group"), 0)


class TestUpdateDonationWithMollieData(EnhancedTestCase):
    def test_persists_mollie_ids(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="Metadata Donor")
        mollie_data = {
            "payment_id": "tr_meta_123",
            "customer_id": "cst_meta_123",
            "mandate_id": "mdt_meta_123",
            "subscription_id": "sub_meta_123",
        }
        update_donation_with_mollie_data(donation, mollie_data)

        fresh = frappe.get_doc("Donation", donation.name)
        self.assertEqual(fresh.payment_id, "tr_meta_123")
        self.assertEqual(fresh.mollie_customer_id, "cst_meta_123")
        self.assertEqual(fresh.mollie_mandate_id, "mdt_meta_123")
        self.assertEqual(fresh.mollie_subscription_id, "sub_meta_123")

    def test_no_updates_does_not_crash(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="NoUpdate Donor")
        # Empty mollie_data => no fields to set; should be a no-op, not an error.
        update_donation_with_mollie_data(donation, {})
        self.assertTrue(frappe.db.exists("Donation", donation.name))


class TestUpdateDonationPaymentHistory(EnhancedTestCase):
    def test_appends_history_row(self):
        donation, _ = _make_unsubmitted_donation(self, donor_name="History Donor")
        mollie_data = {"payment_id": "tr_hist_1", "customer_id": "cst_hist_1", "paid_at": None}
        ok = update_donation_payment_history(donation, mollie_data, "PE-HIST-1")
        self.assertTrue(ok)

        fresh = frappe.get_doc("Donation", donation.name)
        rows = [p for p in fresh.payments if p.mollie_payment_id == "tr_hist_1"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payment_status, "Paid")
        self.assertEqual(rows[0].payment_reference, "tr_hist_1")

    def test_idempotent_when_row_exists(self):
        """A second call for the same mollie_payment_id must NOT duplicate the row."""
        donation, _ = _make_unsubmitted_donation(self, donor_name="Idem History Donor")
        mollie_data = {"payment_id": "tr_hist_dup", "paid_at": None}

        self.assertTrue(update_donation_payment_history(donation, mollie_data, "PE-DUP"))
        donation.reload()
        self.assertTrue(update_donation_payment_history(donation, mollie_data, "PE-DUP"))

        fresh = frappe.get_doc("Donation", donation.name)
        rows = [p for p in fresh.payments if p.mollie_payment_id == "tr_hist_dup"]
        self.assertEqual(len(rows), 1, "Duplicate webhook must not create a second history row")


class TestCreatePaymentEntryForDonation(EnhancedTestCase):
    """create_payment_entry_for_donation — guard + idempotency branches.

    The full happy-path (insert+submit) requires a complete PE accounting setup
    (posting_date defaulting, party account currency, etc.) that is environment
    heavy and exercised by the bulk/orchestrator integration suites; here we pin
    the two webhook-specific contract branches that the function owns:
    (1) it returns None (never raises) when a required bank account is unconfigured;
    (2) it is idempotent — when a matching Payment Entry already exists it returns
        that existing PE instead of creating a duplicate.
    """

    def _persist_customer(self, name):
        c = frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_type": "Individual"})
        c.insert(ignore_permissions=True)
        return c

    def _persist_donor_customer_link(self, donor, customer_name):
        donor.customer = customer_name
        donor.save(ignore_permissions=True)

    def _persist_existing_payment_entry(self, customer_name, payment_id, amount):
        """Pre-create a matching (unsubmitted) Payment Entry the same way the
        function's existing-PE lookup finds it: payment_type Receive,
        reference_no == payment_id, party == customer."""
        company = _company()
        receivable = frappe.get_value("Company", company, "default_receivable_account")
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer_name,
                "paid_amount": amount,
                "received_amount": amount,
                "reference_no": payment_id,
                "reference_date": getdate(),
                "company": company,
                "paid_from": receivable,
                "paid_to": receivable,
            }
        )
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True)
        return pe

    def test_returns_none_when_bank_account_missing(self):
        """No bank account configured anywhere => returns None (does NOT raise),
        so the webhook acknowledges and the failure is logged for review."""
        company = _company()
        donation, donor = _make_unsubmitted_donation(self, donor_name="NoBank Donor", amount=10.0)
        self._persist_donor_customer_link(donor, self._persist_customer("NoBank Customer").name)

        if frappe.db.exists("Account", {"company": company, "account_name": "Mollie"}):
            self.skipTest("Site has a 'Mollie' account; bank-missing branch not reproducible")

        # Ensure the bank lookups all fail: no default_bank_account, no 'Mollie'
        # account. (Settings.mollie_bank_account is not a real field -> .get None.)
        # Unset only within this test, with the Company document cache cleared so
        # erpnext's get_cached_value re-reads it, and restored in `finally` --
        # mirroring test_sepa_reconciliation.py's pattern for the same field. Left
        # to tearDown's rollback alone (as before), this write survives any commit
        # `create_payment_entry_for_donation` -- or a future change to it -- makes
        # on a reachable path, permanently stripping the company's bank default for
        # the rest of the shard (#582). Both the null-write and the restore are
        # inside `try`/`finally` so a raise between them still restores.
        original_default = frappe.db.get_value("Company", company, "default_bank_account")
        try:
            frappe.db.set_value("Company", company, "default_bank_account", None)
            frappe.clear_document_cache("Company", company)
            result = create_payment_entry_for_donation(
                donation, {"payment_id": "tr_nobank", "method": "ideal"}
            )
            self.assertIsNone(result)
        finally:
            frappe.db.set_value("Company", company, "default_bank_account", original_default)
            frappe.clear_document_cache("Company", company)
            # Commit the restore only when it actually moved something: this repo's
            # own guard for the same situation (sepa_test_company.py:404-410) --
            # committing unconditionally took a sibling suite's TEST-LEAK count from
            # 3/3/3 to 6/6/4 by prematurely committing this test's other in-flight,
            # not-yet-tracked fixtures. If a commit ever DOES land between the
            # null-write and here (none does today, on any path this test reaches --
            # verified by reading create_payment_entry_for_donation in full), an
            # uncommitted restore is itself undone by the next test's rollback
            # (measured with a simulated intervening commit); when nothing else
            # commits, restoring None to None costs nothing to also skip.
            if original_default is not None:
                frappe.db.commit()

    def test_idempotent_returns_existing_payment_entry(self):
        """When a Payment Entry already exists for (reference_no, party), the
        function returns it rather than creating a second one."""
        donation, donor = _make_unsubmitted_donation(self, donor_name="Idem PE Donor", amount=33.0)
        customer = self._persist_customer("Idem PE Customer")
        self._persist_donor_customer_link(donor, customer.name)

        payment_id = f"tr_idem_pe_{frappe.generate_hash()[:8]}"
        existing = self._persist_existing_payment_entry(customer.name, payment_id, 33.0)

        returned = create_payment_entry_for_donation(donation, {"payment_id": payment_id, "method": "ideal"})
        self.assertIsNotNone(returned)
        self.assertEqual(returned.name, existing.name)

        # No duplicate PE was created for this reference_no + party.
        count = frappe.db.count(
            "Payment Entry",
            {"reference_no": payment_id, "party": customer.name, "payment_type": "Receive"},
        )
        self.assertEqual(count, 1)


class TestCheckPaymentProcessingStatusById(EnhancedTestCase):
    def test_no_donation_for_id_reports_incomplete(self):
        status = check_payment_processing_status_by_id("tr_does_not_exist_999")
        self.assertFalse(status["all_complete"])
        self.assertIn("No donation found", status["message"])


class TestFindMemberForPayment(EnhancedTestCase):
    def test_find_by_customer_id(self):
        member = self.create_test_member(
            first_name="Find", last_name="ByCustomer", email="find.bycustomer@example.com"
        )
        member.mollie_customer_id = f"cst_find_{frappe.generate_hash()[:8]}"
        member.save()

        payment = types.SimpleNamespace(
            id="tr_find_1",
            subscription_id=None,
            customer_id=member.mollie_customer_id,
            metadata={},
        )
        found = find_member_for_payment("tr_find_1", payment)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, member.name)

    def test_no_match_returns_none(self):
        payment = types.SimpleNamespace(
            id="tr_find_none", subscription_id=None, customer_id="cst_nobody", metadata={}
        )
        self.assertIsNone(find_member_for_payment("tr_find_none", payment))


class TestSubscriptionFailureCount(EnhancedTestCase):
    def test_counts_only_matching_cancelled_rows(self):
        member = self.create_test_member(
            first_name="Failure", last_name="Count", email="failure.count@example.com"
        )
        sub_id = f"sub_fc_{frappe.generate_hash()[:8]}"
        self.assertEqual(_get_subscription_failure_count(member.name, sub_id), 0)

        # Add two Cancelled rows that match the production filter
        # (payment_status == "Cancelled" AND notes LIKE "%subscription <id>%").
        for i in range(2):
            member.append(
                "payment_history",
                {
                    "payment_date": getdate(),
                    "amount": 25.0,
                    "payment_method": "Mollie",
                    "payment_status": "Cancelled",
                    "notes": f"Mollie payment tr_fc_{i} (subscription {sub_id}) failed",
                },
            )
        # A non-matching row (Paid) must not be counted.
        member.append(
            "payment_history",
            {
                "payment_date": getdate(),
                "amount": 25.0,
                "payment_method": "Mollie",
                "payment_status": "Paid",
                "notes": f"subscription {sub_id} ok",
            },
        )
        member.save()

        self.assertEqual(_get_subscription_failure_count(member.name, sub_id), 2)


class TestValidateWebhookSignaturePaymentWebhook(EnhancedTestCase):
    """payment_webhook._validate_webhook_signature — strict HMAC path that REQUIRES
    a signature header (distinct from the lenient verify_mollie_webhook_signature)."""

    PAYLOAD = '{"id":"tr_pw_sig_1","status":"paid"}'
    SECRET = "whsec_payment_webhook_sig"

    def test_valid_signature_passes(self):
        with mollie_settings_override(test_mode=True, webhook_secret=self.SECRET):
            sig = sign_payload(self.PAYLOAD, self.SECRET)
            with install_fake_request(self.PAYLOAD, sig):
                # Should not raise.
                _validate_webhook_signature()

    def test_missing_signature_header_raises_permission_error(self):
        with mollie_settings_override(test_mode=True, webhook_secret=self.SECRET):
            with install_fake_request(self.PAYLOAD, None):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_invalid_signature_raises_permission_error(self):
        with mollie_settings_override(test_mode=True, webhook_secret=self.SECRET):
            with install_fake_request(self.PAYLOAD, "sha256=deadbeef"):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()
