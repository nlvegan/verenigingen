"""
Real-DB coverage tests for the Donor DocType controller
(``verenigingen/verenigingen/doctype/donor/donor.py``).

The existing ``test_donor.py`` covers BSN/RSIN validation + encryption roundtrip.
This file fills the large uncovered surface:

- permlevel access + masked decrypt on onload / get_decrypted_*
- mask_identifier edge cases
- the Customer integration subsystem: sync_with_customer / get_or_create_customer
  / create_customer_from_donor / sync_data_to_customer / Contact creation /
  _get_donor_customer_group / get_customer_info / refresh_customer_sync
- parse_donor_name_for_contact and _calculate_sync_hash change detection

Customer sync is gated behind an in-test opt-in flag
(``enable_customer_sync_in_test``); the factory helper
``create_test_donor_with_sync`` sets it, and ``refresh_customer_sync`` sets it
internally, so the real ERPNext Customer/Contact records get created. No
business logic is mocked.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorCoverage(VereningingenTestCase):
    def _new_donor(self, **kwargs):
        data = {
            "donor_name": f"Cov Donor {frappe.generate_hash(length=6)}",
            "donor_type": "Individual",
            "donor_email": f"covdonor.{frappe.generate_hash(length=8).lower()}@example.com",
        }
        data.update(kwargs)
        donor = frappe.new_doc("Donor")
        donor.update(data)
        return donor

    # ------------------------------------------------------------ mask_identifier

    def test_mask_identifier_masks_all_but_last_four(self):
        donor = self._new_donor()
        self.assertEqual(donor.mask_identifier("123456789"), "*****6789")

    def test_mask_identifier_short_value_unchanged(self):
        donor = self._new_donor()
        # < 4 chars is returned as-is (nothing to mask meaningfully).
        self.assertEqual(donor.mask_identifier("12"), "12")
        self.assertEqual(donor.mask_identifier(""), "")
        self.assertIsNone(donor.mask_identifier(None))

    # ------------------------------------------------------------ permlevel access

    def test_has_permlevel_access_admin_true(self):
        # Running as Administrator (System Manager) grants permlevel access.
        donor = self.create_test_donor()
        self.assertTrue(donor.has_permlevel_access())

    # ------------------------------------------------------------ decrypt helpers

    def test_get_decrypted_bsn_returns_plaintext_for_authorized(self):
        donor = self._new_donor(bsn_citizen_service_number="123456782")  # valid BSN
        donor.insert()
        self.track_doc("Donor", donor.name)
        # After insert the stored value is encrypted; the decrypt accessor returns
        # the original plaintext for an authorized (admin) user.
        reloaded = frappe.get_doc("Donor", donor.name)
        self.assertTrue(reloaded.is_encrypted(reloaded.bsn_citizen_service_number))
        self.assertEqual(reloaded.get_decrypted_bsn(), "123456782")

    def test_get_decrypted_rsin_returns_plaintext_for_authorized(self):
        # 9-digit RSIN that passes eleven-proof (weight +1 on last digit): 123456789
        donor = self._new_donor(donor_type="Organization", rsin_organization_tax_number="123456789")
        donor.insert()
        self.track_doc("Donor", donor.name)
        reloaded = frappe.get_doc("Donor", donor.name)
        self.assertEqual(reloaded.get_decrypted_rsin(), "123456789")

    def test_onload_masks_encrypted_bsn_for_display(self):
        donor = self._new_donor(bsn_citizen_service_number="123456782")
        donor.insert()
        self.track_doc("Donor", donor.name)
        reloaded = frappe.get_doc("Donor", donor.name)
        # onload (authorized) decrypts then masks for display: only last 4 shown.
        reloaded.onload()
        self.assertTrue(reloaded.bsn_citizen_service_number.endswith("6782"))
        self.assertIn("*", reloaded.bsn_citizen_service_number)

    # ------------------------------------------------------------ name parsing

    def test_parse_donor_name_two_parts(self):
        donor = self._new_donor(donor_name="Jan de Vries")
        first, last = donor.parse_donor_name_for_contact()
        self.assertEqual(first, "Jan de")
        self.assertEqual(last, "Vries")

    def test_parse_donor_name_single_part(self):
        donor = self._new_donor(donor_name="Cher")
        first, last = donor.parse_donor_name_for_contact()
        self.assertEqual(first, "Cher")
        self.assertEqual(last, "")

    def test_parse_donor_name_empty(self):
        donor = self._new_donor(donor_name="")
        self.assertEqual(donor.parse_donor_name_for_contact(), ("", ""))

    # ------------------------------------------------------------ sync hash

    def test_calculate_sync_hash_changes_with_email(self):
        donor = self._new_donor(donor_email="a@example.com")
        h1 = donor._calculate_sync_hash()
        donor.donor_email = "b@example.com"
        h2 = donor._calculate_sync_hash()
        self.assertNotEqual(h1, h2)

    # ------------------------------------------------------------ customer group

    def test_get_donor_customer_group_creates_donors_group(self):
        donor = self.create_test_donor()
        group = donor._get_donor_customer_group()
        self.assertTrue(group)
        # The resolved group must be a leaf (is_group == 0) so Customer.insert accepts it.
        self.assertEqual(frappe.db.get_value("Customer Group", group, "is_group"), 0)

    # ------------------------------------------------------------ full customer sync

    def test_create_test_donor_with_sync_links_customer(self):
        donor = self.create_test_donor_with_sync()
        self.assertTrue(donor.customer, "sync should create + link a Customer")
        self.assertTrue(frappe.db.exists("Customer", donor.customer))
        # The Customer carries the donor back-reference.
        self.assertEqual(frappe.db.get_value("Customer", donor.customer, "donor"), donor.name)

    def test_get_or_create_customer_idempotent(self):
        donor = self.create_test_donor_with_sync()
        existing = donor.customer
        # Re-resolving must return the already-linked customer, not create a new one.
        self.assertEqual(donor.get_or_create_customer(), existing)

    def test_sync_data_to_customer_propagates_name_change(self):
        donor = self.create_test_donor_with_sync()
        customer = donor.customer
        new_name = f"Renamed Donor {frappe.generate_hash(length=6)}"
        donor.donor_name = new_name
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_data_to_customer(customer)
        frappe.db.commit()
        self.assertEqual(frappe.db.get_value("Customer", customer, "customer_name"), new_name)

    def test_get_customer_info_returns_data_when_linked(self):
        donor = self.create_test_donor_with_sync()
        info = donor.get_customer_info()
        self.assertEqual(info["name"], donor.customer)
        self.assertIn("outstanding_amount", info)

    def test_get_customer_info_empty_when_unlinked(self):
        donor = self.create_test_donor()  # no customer link
        self.assertEqual(donor.get_customer_info(), {})

    def test_refresh_customer_sync_creates_and_links(self):
        # A donor created WITHOUT sync has no customer; refresh_customer_sync
        # forces the in-test opt-in, runs the sync, saves and reloads.
        donor = self.create_test_donor()
        self.assertFalse(donor.customer)
        result = donor.refresh_customer_sync()
        self.assertIn("refreshed", result["message"])
        donor.reload()
        self.assertTrue(donor.customer, "refresh must create + persist a customer link")
        self.track_doc("Customer", donor.customer)

    def test_sync_with_customer_skipped_when_ignore_flag_set(self):
        donor = self.create_test_donor()
        donor.flags.ignore_customer_sync = True
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_with_customer()
        # Skipped entirely: no customer link established.
        self.assertFalse(donor.customer)

    def test_sync_with_customer_skipped_in_test_without_optin(self):
        donor = self.create_test_donor()
        # in_test is set during the run and no opt-in flag -> sync is a no-op.
        donor.sync_with_customer()
        self.assertFalse(donor.customer)

    # ------------------------------------------------------------ sync failures must not read "Synced"

    # `customer_sync_status` is a read-only Select (Synced/Pending/Error/Auto-Created)
    # reported on by get_sync_status_summary and donor_customer_management. Every sync
    # sub-step used to log-and-swallow its failure, so control fell through to
    # `customer_sync_status = "Synced"` for a sync that did not happen (#666). The donor
    # save must still succeed -- an external Customer sync failing is not grounds to
    # refuse the donor -- but the status has to read "Error", which sync_with_customer
    # already writes and which nothing could reach.

    def _run_sync_hook(self, donor, as_user=None, **changes):
        """Drive the real on_update hook, which is what persists the status.

        The document is re-fetched rather than reloaded: sync_with_customer dedupes on
        `_sync_already_done` / `_last_sync_hash`, which are plain instance attributes and
        survive doc.reload(). Re-running the hook on the same object after a successful
        sync is a no-op, which would leave every assertion below satisfied by the FIRST
        sync's result instead of the one under test.
        """
        from verenigingen.services.member.donor import donor_customer_sync as dcs

        fresh = frappe.get_doc("Donor", donor.name)
        for field, value in changes.items():
            setattr(fresh, field, value)
        fresh.flags.enable_customer_sync_in_test = True
        if as_user is None:
            dcs.sync_donor_to_customer(fresh)
            return fresh
        original_user = frappe.session.user
        frappe.set_user(as_user)
        try:
            dcs.sync_donor_to_customer(fresh)
        finally:
            frappe.set_user(original_user)
        return fresh

    def _user_without_customer_permission(self):
        """An actor who may not create a Customer and cannot request system escalation.

        Only a User row is created, and the harness deletes it -- no shared master data is
        touched, which is the whole point (see the note in the creation test below).
        """
        user = frappe.new_doc("User")
        user.email = f"nocust.{frappe.generate_hash(length=8).lower()}@example.invalid"
        user.first_name = "No Customer Perm"
        user.send_welcome_email = 0
        user.append("roles", {"role": "Verenigingen Member"})
        # Plain insert: the suite runs as Administrator, so no permission bypass is needed.
        user.insert()
        self.track_doc("User", user.name)
        return user.name

    def _persisted_status(self, donor):
        return frappe.db.get_value("Donor", donor.name, "customer_sync_status")

    # Every Error Log title the sync writes on a failure, listed rather than matched by
    # a loose substring: "Donor" used to match only because the fixture's Customer is
    # named "Test Donor <hash>" and that name appears in secure_operations' row -- five
    # of these tests passed VERENIGINGEN_FAIL_ON_ERROR_LOG=1 by fixture-name coincidence,
    # and the sixth (whose Customer has no name yet at insert) failed.
    _SYNC_FAILURE_LOG_TITLES = (
        "Secure Operation Failed",
        "Donor Customer Creation Error",
        "Donor-Customer Data Sync Error",
        "Donor-Customer Contact Sync Error",
        "Donor Customer Contact Creation Error",
        "Customer Contact Creation Error",
        "Customer Contact Link Error",
        "Donor-Customer Sync Error",
        "Donor-Customer Sync Hook Error",
        # sanitize_customer_links logs every broken link it repairs; the
        # unresolvable-contact test creates one deliberately.
        "Link Sanitization - Auto-Cleared",
        # _get_donor_customer_group's fallback chain, reached from
        # create_customer_from_donor. Neither fires on a site that already resolves a
        # donor customer group, which is exactly why they are listed rather than
        # discovered: on a fresh CI site the group must be auto-created first.
        "Donor Customer Group Configuration Error",
        "Customer Group Auto-Creation Error",
    )

    def _expect_sync_failure_logs(self):
        self.expectErrorLog(*self._SYNC_FAILURE_LOG_TITLES)

    def test_successful_sync_persists_synced(self):
        """CONTROL for the failure tests below: an unbroken sync still records "Synced".
        Without it, a fix that wrote "Error" unconditionally would pass every one of
        them."""
        donor = self.create_test_donor_with_sync()
        with self.assertNoErrorLog():
            self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Synced")

    def test_failed_customer_update_persists_error_not_synced(self):
        """donor.py sync_data_to_customer: the Customer save fails, so the sync did not
        happen -- the row must not claim it did.

        The Customer is given a Link value that does not resolve, so its save fails
        exactly as it would in production; sanitize_customer_links only clears
        member/contact/address links, so customer_group survives to the save.
        """
        donor = self.create_test_donor_with_sync()
        frappe.db.set_value(
            "Customer", donor.customer, "customer_group", "__no_such_group__", update_modified=False
        )
        self._expect_sync_failure_logs()
        self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Error")

    def test_sync_failure_error_log_preserves_diagnostic_message(self):
        """#711: sync_with_customer's own except-Exception handler -- the last stop
        before a sync failure is recorded as "Error" -- called frappe.log_error with
        (message, title) reversed from the real (title, message) signature. Since the
        message argument never contains a newline, frappe's swap-heuristic
        (frappe/utils/error.py) never rescues it: the diagnostic lands in the 140-char
        `method` column (truncated) and the traceback column holds only the literal
        label "Donor-Customer Sync Error" -- recording no usable diagnostic for
        exactly the failure #711 needs surfaced (an escalation to a nonexistent
        creation_user reaches this same handler). Reuses the real breakage from
        test_failed_customer_update_persists_error_not_synced -- the exception is a
        genuine Customer.save() failure, not mocked -- and checks where its content
        landed rather than just that *some* status flipped to "Error".
        """
        donor = self.create_test_donor_with_sync()
        frappe.db.set_value(
            "Customer", donor.customer, "customer_group", "__no_such_group__", update_modified=False
        )
        self._expect_sync_failure_logs()
        marker = frappe.utils.now_datetime()
        self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Error")

        rows = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", marker]},
            fields=["method", "error"],
            order_by="creation desc",
        )
        candidates = [r for r in rows if "__no_such_group__" in f"{r.method}\n{r.error}"]
        self.assertTrue(candidates, f"no Error Log row mentions the injected failure; rows={rows}")
        row = candidates[0]
        self.assertEqual(
            row.method,
            "Donor-Customer Sync Error",
            "title column must stay the short constant label, not the (mis-swapped) diagnostic",
        )
        self.assertIn(
            "__no_such_group__",
            row.error or "",
            "the actual failure detail must land in the traceback column, not be replaced "
            "by the literal label",
        )

    def test_failed_customer_creation_persists_error(self):
        """donor.py create_customer_from_donor: the Customer insert fails, so
        get_or_create_customer yielded nothing and sync_with_customer skipped its whole
        status block -- leaving whatever the row held before. Must be "Error"."""
        donor = self.create_test_donor()
        self._expect_sync_failure_logs()
        # The failure is a permission denial -- the case #666 names -- driven by an actor
        # who may not create a Customer and holds no role in ESCALATION_ALLOWED_ROLES.
        # Note what does NOT follow: secure_document_operation raises
        # frappe.PermissionError internally but converts it to success=False, and the
        # caller re-throws that with frappe.throw, so what arrives at the recorder is a
        # ValidationError. This test does not discriminate the bare `raise` from
        # `except frappe.ValidationError: raise`; measured, none of these tests does.
        #
        # Nothing shared is poisoned to get here. An earlier version pointed
        # Selling Settings.territory at a missing Territory; sync_data_to_customer
        # commits while frappe.flags.in_test is set, so the poison outlived the test and
        # the restore -- registered with addCleanup -- was itself undone by the harness
        # rollback that runs after it. It broke every later test in the module and had to
        # be repaired by hand on two sites.
        self._run_sync_hook(donor, as_user=self._user_without_customer_permission())
        self.assertEqual(self._persisted_status(donor), "Error")

    def test_failed_contact_update_persists_error_not_synced(self):
        """donor.py sync_donor_to_customer_contact: the Contact save fails, so the donor's
        new email never reached the Customer -- yet the Customer save that follows still
        succeeded and the row said "Synced".

        The break has to live in the value being COPIED, not on the stored Contact:
        saving the Customer re-saves its primary Contact, so a Contact that is broken in
        the database fails the Customer save too and the assertion is then satisfied by
        sync_data_to_customer instead. Here the stored Contact stays valid and only the
        incoming address is bad, which isolates this handler -- confirmed by mutation:
        reverting only this `raise` reddens this test.
        """
        donor = self.create_test_donor_with_sync()
        contact = frappe.db.get_value("Customer", donor.customer, "customer_primary_contact")
        self.assertTrue(contact, "sync must have produced a primary Contact for this test to mean anything")
        frappe.db.set_value("Donor", donor.name, "donor_email", "not an email", update_modified=False)
        self._expect_sync_failure_logs()
        self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Error")

    def test_unresolvable_contact_persists_error(self):
        """donor.py get_or_create_customer_contact: a Customer whose primary-contact link
        points at a deleted Contact cannot be resolved, so no contact data syncs.

        This handler is one layer below the four #666 lists: its try body contains no
        literal frappe.throw, so the AST predicate misses it -- but it swallows the one
        create_new_customer_contact re-raises, which would nullify that fix on this path.
        """
        donor = self.create_test_donor_with_sync()
        frappe.db.set_value(
            "Customer",
            donor.customer,
            "customer_primary_contact",
            "__no_such_contact__",
            update_modified=False,
        )
        self._expect_sync_failure_logs()
        self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Error")

    def test_failed_contact_creation_persists_error(self):
        """donor.py create_new_customer_contact: all retries exhausted. The Contact
        carries the donor's email, so an address the Contact schema rejects fails every
        attempt -- and the Customer was still created, so the sync used to report success
        for a donor whose email reached nothing.

        The bad address is written straight to the row because Donor.validate rejects it.
        """
        donor = self.create_test_donor()
        frappe.db.set_value("Donor", donor.name, "donor_email", "not an email", update_modified=False)
        self._expect_sync_failure_logs()
        self._run_sync_hook(donor)
        self.assertEqual(self._persisted_status(donor), "Error")

    def test_failed_primary_contact_link_save_persists_error(self):
        """donor.py refresh_customer_from_contact: it saves the Customer on the caller's
        behalf and the caller then sets `_contact_triggered_customer_save`, which
        suppresses sync_data_to_customer's own save. So a failure swallowed here is not
        merely lost -- it also cancels the only retry, leaving an unsaved Customer
        reported as "Synced".

        Not one of the four #666 lists (no literal frappe.throw in its try body). The
        Customer is broken and the donor renamed so the Contact needs saving: that is
        what routes the Customer save through this method instead of the caller's own.
        """
        donor = self.create_test_donor_with_sync()
        frappe.db.set_value(
            "Customer", donor.customer, "customer_group", "__no_such_group__", update_modified=False
        )
        self._expect_sync_failure_logs()
        self._run_sync_hook(donor, donor_name=f"Renamed {frappe.generate_hash(length=6)}")
        self.assertEqual(self._persisted_status(donor), "Error")
