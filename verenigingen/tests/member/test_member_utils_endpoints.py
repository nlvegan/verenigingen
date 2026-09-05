"""
Real-integration tests for the whitelisted endpoints in
``verenigingen/verenigingen/doctype/member/member_utils.py``.

This module is distinct from ``tests/member/test_member_utils.py``, which covers
the *helper* module ``verenigingen.utils.member_utils``. The doctype module here
holds the SEPA/mandate/payment/chapter endpoints exposed to the member form, and
was almost entirely uncovered (~23%).

Tests create real Members, SEPA Mandates, Donors and Chapters via the test
factory (no business-logic mocking) and run as Administrator.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import member_utils as mu

# Valid test-bank IBANs (mod-97 valid, recognised by iban_validator). Their BICs
# are deterministic: TEST->TESTNL2A, MOCK->MOCKNL2A, DEMO->DEMONL2A.
IBAN_TEST = "NL13TEST0123456789"
IBAN_MOCK = "NL82MOCK0123456789"
IBAN_DEMO = "NL93DEMO0123456789"


class TestMemberUtilsEndpoints(VereningingenTestCase):
    """Exercise the member_utils doctype-module endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="MemberUtils",
            last_name="Endpoint",
            email="memberutils.endpoint@test.invalid",
            status="Active",
        )

    # ----------------------------------------------------------------- settings / pure helpers

    def test_get_member_settings_returns_expected_keys(self):
        settings = mu.get_member_settings()
        self.assertIn("mandate_expiry_warning_days", settings)
        self.assertIn("default_mandate_type", settings)
        # Values must be usable as a number / mandate-type string.
        self.assertIsInstance(settings["mandate_expiry_warning_days"], int)
        self.assertTrue(settings["default_mandate_type"])

    def test_get_iban_bank_codes_known_countries(self):
        codes = mu.get_iban_bank_codes()
        self.assertEqual(codes["NL"], (4, 4))
        self.assertEqual(codes["DE"], (4, 8))
        self.assertIn("GB", codes)

    def test_is_chapter_management_enabled_returns_bool(self):
        self.assertIsInstance(mu.is_chapter_management_enabled(), bool)

    def test_get_member_form_settings_shape(self):
        result = mu.get_member_form_settings()
        self.assertIn("show_chapter_field", result)
        self.assertIn("chapter_field_label", result)
        # The label is populated iff chapter management is on.
        if result["show_chapter_field"]:
            self.assertTrue(result["chapter_field_label"])
        else:
            self.assertEqual(result["chapter_field_label"], "")

    # --------------------------------------------------------------------- BIC derivation

    def test_derive_bic_from_iban_test_bank(self):
        self.assertEqual(mu.derive_bic_from_iban(IBAN_TEST), "TESTNL2A")
        self.assertEqual(mu.derive_bic_from_iban(IBAN_MOCK), "MOCKNL2A")

    def test_derive_bic_from_iban_real_dutch_bank(self):
        # RABO bank code -> RABONL2U
        self.assertEqual(mu.derive_bic_from_iban("NL39RABO0300065264"), "RABONL2U")

    def test_derive_bic_from_iban_invalid_returns_none(self):
        self.assertIsNone(mu.derive_bic_from_iban("NL00TEST0123456789"))  # bad checksum
        self.assertIsNone(mu.derive_bic_from_iban(""))

    # --------------------------------------------------------------- mandate reference helpers

    def test_validate_mandate_reference_available_then_taken(self):
        unique = f"MNDREF-{frappe.generate_hash(length=8)}"
        first = mu.validate_mandate_reference(unique)
        self.assertTrue(first["available"])
        self.assertFalse(first["exists"])

        self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST, mandate_id=unique)

        second = mu.validate_mandate_reference(unique)
        self.assertFalse(second["available"])
        self.assertTrue(second["exists"])

    def test_generate_mandate_reference_format(self):
        result = mu.generate_mandate_reference(self.member.name)
        ref = result["mandate_reference"]
        self.assertTrue(ref.startswith("M-"))
        # First mandate of the day for this member -> sequence 001
        self.assertTrue(ref.endswith("-001"), ref)

    def test_need_new_mandate(self):
        # No mandate for this IBAN yet.
        self.assertTrue(mu.need_new_mandate(self.member.name, IBAN_TEST)["need_new"])
        self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST)
        self.assertFalse(mu.need_new_mandate(self.member.name, IBAN_TEST)["need_new"])

    # ------------------------------------------------------------------ SEPA mandate status

    def test_check_sepa_mandate_status_no_mandate(self):
        result = mu.check_sepa_mandate_status(self.member.name)
        self.assertFalse(result["has_active_mandate"])
        self.assertFalse(result["expiring_soon"])

    def test_check_sepa_mandate_status_active_and_expiring(self):
        self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            expiry_date=add_days(today(), 10),  # within the default 30-day warning window
        )
        result = mu.check_sepa_mandate_status(self.member.name)
        self.assertTrue(result["has_active_mandate"])
        self.assertTrue(result["expiring_soon"])

    # ------------------------------------------------------------------ IBAN mismatch popup

    def test_check_mandate_iban_mismatch_missing_params(self):
        result = mu.check_mandate_iban_mismatch(self.member.name, "")
        self.assertFalse(result["show_popup"])
        self.assertIn("error", result)

    def test_check_mandate_iban_mismatch_no_existing(self):
        result = mu.check_mandate_iban_mismatch(self.member.name, IBAN_TEST)
        self.assertTrue(result["show_popup"])
        self.assertEqual(result["reason"], "no_existing_mandates")

    def test_check_mandate_iban_mismatch_matching(self):
        self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST)
        result = mu.check_mandate_iban_mismatch(self.member.name, IBAN_TEST)
        self.assertFalse(result["show_popup"])
        self.assertEqual(result["reason"], "iban_matches")

    def test_check_mandate_iban_mismatch_different(self):
        self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST)
        result = mu.check_mandate_iban_mismatch(self.member.name, IBAN_MOCK)
        self.assertTrue(result["show_popup"])
        self.assertEqual(result["reason"], "iban_mismatch")
        self.assertEqual(result["current_iban"], IBAN_MOCK)

    # ---------------------------------------------------------- check_and_handle_sepa_mandate

    def test_check_and_handle_sepa_mandate_create_new(self):
        result = mu.check_and_handle_sepa_mandate(self.member.name, IBAN_TEST)
        self.assertEqual(result["action"], "create_new")

    def test_check_and_handle_sepa_mandate_use_existing_then_none_needed(self):
        mandate = self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST)
        # The SEPA Mandate after_insert hook links the mandate as current. Flip the
        # existing link to not-current so check_and_handle has to promote it.
        member_doc = frappe.get_doc("Member", self.member.name)
        linked = False
        for link in member_doc.sepa_mandates:
            if link.sepa_mandate == mandate.name:
                link.is_current = 0
                linked = True
        self.assertTrue(linked, "factory after_insert should have linked the mandate to the member")
        member_doc.save()

        result = mu.check_and_handle_sepa_mandate(self.member.name, IBAN_TEST)
        self.assertEqual(result["action"], "use_existing")
        self.assertEqual(result["mandate"], mandate.name)

        # Now the mandate is current -> nothing needed.
        result2 = mu.check_and_handle_sepa_mandate(self.member.name, IBAN_TEST)
        self.assertEqual(result2["action"], "none_needed")

    # ------------------------------------------------------- create_sepa_mandate_from_bank_details

    def test_create_sepa_mandate_from_bank_details_happy(self):
        name = mu.create_sepa_mandate_from_bank_details(
            member=self.member.name,
            iban=IBAN_TEST,
            bic="TESTNL2A",
        )
        self.assertTrue(frappe.db.exists("SEPA Mandate", name))
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.member, self.member.name)
        self.assertEqual(mandate.status, "Active")

        # Member now links the mandate as current.
        member_doc = frappe.get_doc("Member", self.member.name)
        current = [m for m in member_doc.sepa_mandates if m.is_current]
        self.assertTrue(any(m.sepa_mandate == name for m in current))

    def test_create_sepa_mandate_from_bank_details_requires_member_and_iban(self):
        with self.assertRaises(frappe.ValidationError):
            mu.create_sepa_mandate_from_bank_details(member="", iban=IBAN_TEST)
        with self.assertRaises(frappe.ValidationError):
            mu.create_sepa_mandate_from_bank_details(member=self.member.name, iban="")

    # ------------------------------------------------------------------ create_and_link_mandate

    def test_create_and_link_mandate_suspends_previous(self):
        old = self.create_test_sepa_mandate(member=self.member.name, iban=IBAN_TEST, used_for_memberships=1)
        new_name = mu.create_and_link_mandate(
            member=self.member.name,
            iban=IBAN_MOCK,
            used_for_memberships=1,
        )
        self.assertNotEqual(new_name, old.name)
        self.assertTrue(frappe.db.exists("SEPA Mandate", new_name))

        # Old membership mandate suspended; new one active + current.
        old_doc = frappe.get_doc("SEPA Mandate", old.name)
        self.assertEqual(old_doc.status, "Suspended")
        self.assertEqual(old_doc.is_active, 0)

        member_doc = frappe.get_doc("Member", self.member.name)
        current_links = [m for m in member_doc.sepa_mandates if m.is_current]
        self.assertEqual(len(current_links), 1)
        self.assertEqual(current_links[0].sepa_mandate, new_name)

    def test_create_and_link_mandate_suspends_previous_donation_mandate(self):
        old = self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            used_for_memberships=0,
            used_for_donations=1,
        )
        new_name = mu.create_and_link_mandate(
            member=self.member.name,
            iban=IBAN_MOCK,
            used_for_memberships=0,
            used_for_donations=1,
        )
        self.assertNotEqual(new_name, old.name)
        old_doc = frappe.get_doc("SEPA Mandate", old.name)
        self.assertEqual(old_doc.status, "Suspended")
        self.assertEqual(old_doc.is_active, 0)

    # ------------------------------------------------------- add_manual_payment_record happy path

    def test_add_manual_payment_record_happy_path(self):
        # Full financial path: requires a Company with a receivable account and a
        # "Cash" Mode of Payment. Skip cleanly where those masters are absent.
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company or frappe.defaults.get_global_default("company")
        if not company:
            self.skipTest("No default company configured")
        if not frappe.db.exists("Mode of Payment", "Cash"):
            self.skipTest("No 'Cash' Mode of Payment configured")
        if not frappe.get_value("Company", company, "default_receivable_account"):
            self.skipTest("Company has no default receivable account")

        payment_name = mu.add_manual_payment_record(
            member=self.member.name, amount=12.50, notes="unit-test cash donation"
        )
        self.assertTrue(frappe.db.exists("Payment Entry", payment_name))
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.docstatus, 1)  # submitted
        self.assertEqual(float(pe.paid_amount), 12.50)

    # ------------------------------------------------------------------- linked donations

    def test_get_linked_donations_no_member(self):
        result = mu.get_linked_donations("")
        self.assertFalse(result["success"])

    def test_get_linked_donations_none_found(self):
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])

    def test_get_linked_donations_match_by_email(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        donor = self.create_test_donor(donor_email=member_doc.email)
        result = mu.get_linked_donations(self.member.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["donor"], donor.name)

    # ------------------------------------------------------------------ termination status

    def test_get_member_termination_status_none(self):
        result = mu.get_member_termination_status(self.member.name)
        self.assertEqual(result["pending_requests"], [])
        self.assertEqual(result["executed_requests"], [])
        self.assertFalse(result["is_terminated"])

    def test_update_termination_status_display_in_progress_short_circuit(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc._termination_in_progress = True
        member_doc._termination_final_status = "Banned"
        member_doc.status = "Active"
        mu.update_termination_status_display(member_doc)
        # Short-circuit path forces status to the final status without a DB query.
        self.assertEqual(member_doc.status, "Banned")

    def test_update_termination_status_display_no_termination_keeps_status(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.status = "Active"
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Active")

    # ------------------------------------------------------------------ member id counter

    def test_get_next_member_id_preview_shape(self):
        result = mu.get_next_member_id_preview()
        self.assertIn("next_id", result)
        self.assertIn("current_counter", result)
        self.assertEqual(result["next_id"], result["current_counter"] + 1)

    def test_reset_member_id_counter_rejects_nonpositive(self):
        # Guard clauses must fire before touching the shared Redis counter.
        with self.assertRaises(frappe.ValidationError):
            mu.reset_member_id_counter(0)
        with self.assertRaises(frappe.ValidationError):
            mu.reset_member_id_counter(-5)

    # ------------------------------------------------------- payment-history hook early returns

    def test_update_member_payment_history_non_customer_party_returns(self):
        doc = frappe._dict(party_type="Supplier", party="X", name="PE-X")
        # Should return without error for non-customer parties.
        self.assertIsNone(mu.update_member_payment_history(doc))

    def test_update_member_payment_history_from_invoice_ignores_non_invoice(self):
        doc = frappe._dict(doctype="Payment Entry", customer=None, name="X")
        self.assertIsNone(mu.update_member_payment_history_from_invoice(doc))

    # --------------------------------------------------------------- add_manual_payment_record guards

    def test_add_manual_payment_record_requires_member_and_amount(self):
        with self.assertRaises(frappe.ValidationError):
            mu.add_manual_payment_record(member="", amount=10)
        with self.assertRaises(frappe.ValidationError):
            mu.add_manual_payment_record(member=self.member.name, amount=0)

    def test_add_manual_payment_record_requires_customer(self):
        # Clear the customer link so the "must have a customer" guard is reachable.
        frappe.db.set_value("Member", self.member.name, "customer", None)
        with self.assertRaises(frappe.ValidationError):
            mu.add_manual_payment_record(member=self.member.name, amount=10)

    # ------------------------------------------------------------------ counter sync hook

    def test_sync_member_counter_with_settings_ignores_other_doctypes(self):
        doc = frappe._dict(doctype="Member")
        # Non-settings doctype must be a no-op (returns None without error).
        self.assertIsNone(mu.sync_member_counter_with_settings(doc))

    # ----------------------------------------------------------------- payment-history bodies

    def test_update_member_payment_history_customer_path(self):
        # A submitted invoice gives load_payment_history() something to persist, so
        # we can assert a real side effect (not just "did not raise").
        customer = frappe.get_doc("Member", self.member.name).customer
        self.assertTrue(customer, "factory member should have a customer")
        invoice = self.create_test_sales_invoice(member=self.member.name)
        invoice.submit()

        doc = frappe._dict(party_type="Customer", party=customer, name=invoice.name)
        mu.update_member_payment_history(doc)

        member_doc = frappe.get_doc("Member", self.member.name)
        self.assertTrue(
            any(row.invoice == invoice.name for row in member_doc.payment_history),
            "the submitted invoice should be persisted into the member's payment history",
        )

    def test_update_member_payment_history_from_invoice_customer_path(self):
        customer = frappe.get_doc("Member", self.member.name).customer
        invoice = self.create_test_sales_invoice(member=self.member.name)
        invoice.submit()

        doc = frappe._dict(doctype="Sales Invoice", customer=customer, name=invoice.name)
        mu.update_member_payment_history_from_invoice(doc)

        member_doc = frappe.get_doc("Member", self.member.name)
        self.assertTrue(
            any(row.invoice == invoice.name for row in member_doc.payment_history),
            "the submitted invoice should be persisted into the member's payment history",
        )

    # --------------------------------------------------------------- chapter postal-code lookup

    def _enable_chapter_management(self):
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)

    def test_find_chapter_by_postal_code_disabled(self):
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 0)
        result = mu.find_chapter_by_postal_code("1234")
        self.assertFalse(result["success"])

    def test_find_chapter_by_postal_code_requires_postal_code(self):
        self._enable_chapter_management()
        result = mu.find_chapter_by_postal_code("")
        self.assertFalse(result["success"])
        self.assertIn("required", result["message"].lower())

    def test_find_chapter_by_postal_code_match(self):
        self._enable_chapter_management()
        chapter = self.create_test_chapter(
            chapter_name=f"Postal Test {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        result = mu.find_chapter_by_postal_code("1234")
        self.assertTrue(result["success"])
        self.assertTrue(any(c["name"] == chapter.name for c in result["matching_chapters"]))

    def test_debug_postal_code_matching(self):
        self._enable_chapter_management()
        self.create_test_chapter(
            chapter_name=f"Debug Postal {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        result = mu.debug_postal_code_matching("1234")
        self.assertEqual(result["postal_code"], "1234")
        self.assertIn("matching_chapters", result)
        self.assertGreaterEqual(result["total_chapters"], 1)

    def test_debug_postal_code_matching_no_input(self):
        result = mu.debug_postal_code_matching("")
        self.assertIn("error", result)

    def _unwrap(self, fn):
        """Return the undecorated business function.

        ``find_chapter_by_postal_code`` is wrapped by
        ``@frappe.whitelist(allow_guest=True)`` + ``@public_api``, whose
        audit/rate-limit machinery issues a fixed, N-independent number of
        extra queries. Those are constant overhead, not the N+1 under test,
        so the query-count assertion measures the bare business function
        (reached via ``__wrapped__``), matching the precedent in
        ``tests/sepa/test_sepa_performance_optimization.py``.
        """
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn

    def test_find_chapter_by_postal_code_query_count_does_not_scale_with_chapters(self):
        """#845: find_chapter_by_postal_code used to frappe.get_doc() every
        published chapter just to call matches_postal_code() -- a per-row
        Document load (Chapter has 4 child tables) on a guest-reachable
        endpoint. An unauthenticated caller could drive N document loads with
        one request. The fix reads ``postal_codes`` off the bulk
        frappe.get_all() rows already fetched, so the query count must stay
        flat as the number of published chapters grows.
        """
        self._enable_chapter_management()

        # Warm meta / table-column caches so a first-touch introspection
        # query inside the measured window isn't mistaken for the N+1 (a
        # cold `table_columns::tab<DocType>` cache issues an
        # information_schema query the first time a table is touched --
        # see tests/sepa/test_sepa_performance_optimization.py).
        frappe.get_meta("Chapter")
        frappe.db.get_table_columns("Chapter")
        frappe.get_meta("Verenigingen Settings")
        frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management")

        for i in range(8):
            self.create_test_chapter(
                chapter_name=f"Postal Scale {i} {frappe.generate_hash(length=6)}",
                postal_codes="1000-9999" if i % 2 == 0 else "5000-5099",
                published=1,
            )

        business_fn = self._unwrap(mu.find_chapter_by_postal_code)

        # 1 query for the bulk Chapter fetch + 1 for the settings check --
        # must NOT scale with the number of chapters (measured: unfixed code
        # issues 172 queries here; see #845 for the before/after numbers).
        with self.assertQueryCount(2):
            result = business_fn("1234")

        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result["matching_chapters"]), 4)
