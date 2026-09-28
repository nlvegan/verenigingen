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
from frappe.utils import add_days, add_months, get_datetime, getdate, now_datetime, today

from verenigingen.tests.support.termination_request import execute_real_termination
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

    def test_get_linked_donations_same_name_stranger_not_attached(self):
        """#1356 review: there is no name-based tier at all, so a donor whose
        donor_name EXACTLY equals this member's full_name -- a real
        possibility for a common Dutch name -- must never be attached
        without a link or matching e-mail to back it up."""
        member_doc = frappe.get_doc("Member", self.member.name)
        self.create_test_donor(donor_name=member_doc.full_name, donor_email=None)
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])

    def test_get_linked_donations_does_not_substring_match_a_strangers_donor(self):
        """#1356: a stranger's donor whose name merely CONTAINS this member's
        full_name as a substring must never be attached to this member -- the
        old `LIKE f"%{full_name}%"` query with no ambiguity guard did exactly
        that.
        """
        member_doc = frappe.get_doc("Member", self.member.name)
        self.create_test_donor(
            donor_name=f"{member_doc.full_name} (a completely unrelated donor)", donor_email=None
        )
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])

    def test_get_linked_donations_ambiguous_member_link_never_falls_through_to_email(self):
        """Regression for the #1356 review finding: an ambiguous match at the
        (stronger) member-link tier must refuse immediately, not fall through
        to the (weaker) e-mail tier. Without that guard, this scenario
        resolved to the THIRD donor below -- an unrelated donor that merely
        happens to share this member's e-mail address."""
        member_doc = frappe.get_doc("Member", self.member.name)
        self.create_test_donor(member=self.member.name, donor_email=None)
        self.create_test_donor(member=self.member.name, donor_email=None)
        self.create_test_donor(donor_email=member_doc.email)
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])

    def test_get_linked_donations_ambiguous_email_refuses(self):
        """Two donors sharing this member's exact e-mail must refuse rather
        than silently picking the first one. Asserts the ambiguity message
        specifically -- e-mail is the last tier, so an ambiguous match and a
        plain not-found both give success=False; a bare `assertFalse` would
        stay green even if the ambiguity check on this tier were deleted,
        since both paths fall through to a success=False result."""
        member_doc = frappe.get_doc("Member", self.member.name)
        self.create_test_donor(donor_email=member_doc.email)
        self.create_test_donor(donor_email=member_doc.email)
        result = mu.get_linked_donations(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("Multiple donor records", result["message"])

    def test_get_linked_donations_member_link_takes_priority(self):
        """The authoritative Donor.member link resolves the donor even when
        donor_name/donor_email do not match the member at all."""
        donor = self.create_test_donor(
            donor_name="Someone Else Entirely", donor_email="unrelated@test.invalid", member=self.member.name
        )
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

    # -------------------------------------------- #1544/#1548: hook scoping by member_since

    def _insert_executed_termination(self, member_name, termination_date, execution_date=None,
                                      termination_type="Voluntary"):
        """A real (not mocked) Membership Termination Request row already in
        the "Executed" state -- the hook under test only ever reads this via
        `frappe.get_all(..., filters={"status": "Executed"})`, regardless of
        docstatus, so a direct insert at that status is a faithful fixture
        for exercising the hook in isolation from the full execution service
        (that service itself is covered by test_termination_execution_service.py)."""
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member_name,
                "termination_type": termination_type,
                "termination_reason": "Test: #1544/#1548 hook scoping",
                "termination_date": termination_date,
                "execution_date": execution_date or termination_date,
                "requested_by": frappe.session.user,
                "request_date": termination_date,
                "status": "Executed",
                "executed_by": frappe.session.user,
            }
        )
        request.insert()
        self.track_doc("Membership Termination Request", request.name)
        return request

    def test_update_termination_status_display_normal_termination_still_applies(self):
        """Regression guard: the ordinary case (termination AFTER member_since,
        no rejoin) must still force the terminal status -- #1548's fix must
        not weaken this, only the superseded-by-rejoin case."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        self._insert_executed_termination(member_doc.name, add_months(today(), -12))

        member_doc.reload()
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Quit")

    def test_update_termination_status_display_future_termination_date_still_applies(self):
        """A termination_date in the future is still AFTER member_since, so it
        is not "superseded" by the boundary this fix adds -- unaffected,
        matching pre-existing behaviour (this function has never checked
        whether the date has actually arrived yet)."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -6)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        self._insert_executed_termination(member_doc.name, add_months(today(), 3))

        member_doc.reload()
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Quit")

    def test_update_termination_status_display_null_member_since_still_applies(self):
        """A missing member_since (data gap, e.g. an old import) is NOT
        treated as evidence of supersession -- the fix must fail closed
        (still reflect a real Executed termination) rather than silently
        leaving a terminated member's status untouched."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = None
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        self._insert_executed_termination(member_doc.name, add_months(today(), -1))

        member_doc.reload()
        self.assertIsNone(member_doc.member_since)
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Quit")

    def test_update_termination_status_display_backdated_termination_still_applies(self):
        """A termination recorded today but backdated to an earlier effective
        date (termination_date < execution_date) -- ordinary practice, e.g.
        "processed today, effective as of the member's actual resignation
        date" -- must still apply as long as that effective date is after
        member_since. Only a termination whose date predates member_since
        entirely is treated as belonging to a prior, superseded membership."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        self._insert_executed_termination(
            member_doc.name,
            termination_date=add_months(today(), -12),
            execution_date=today(),
        )

        member_doc.reload()
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Quit")

    def test_update_termination_status_display_skips_when_termination_predates_member_since(self):
        """The core #1548 fix: a real reapproval resets member_since to the
        rejoin date, and the OLD termination (necessarily dated before that)
        must no longer force a terminal status. Also clears the stale
        member_end_date it left behind, for the same reason #1544 scopes its
        own exclusion by member_since -- membership_analytics.py's retention
        queries read member_end_date the same way."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        old_termination_date = add_months(today(), -12)
        self._insert_executed_termination(member_doc.name, old_termination_date)

        member_doc.reload()
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Quit")
        # Raw member_end_date, not getdate(member_end_date) -- see the sibling
        # misfire test's comment: getdate(None) returns today, not None.
        self.assertEqual(member_doc.member_end_date, getdate(old_termination_date))

        # Real rejoin: member_since resets to AFTER the old termination.
        member_doc.member_since = today()
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        mu.update_termination_status_display(member_doc)
        self.assertEqual(
            member_doc.status,
            "Active",
            "A termination predating the current member_since must not force Quit",
        )
        self.assertIsNone(
            member_doc.member_end_date,
            "The stale member_end_date from the superseded termination must be cleared",
        )

    def test_update_termination_status_display_manual_member_since_edit_also_supersedes(self):
        """An admin manually correcting member_since forward past an old
        termination (without going through the reapplication API) is treated
        the same way -- the boundary is on the DATA, not on which code path
        produced it."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        self._insert_executed_termination(member_doc.name, add_months(today(), -12))

        member_doc.reload()
        # Manual correction: bump member_since forward past the termination,
        # exactly as an admin editing the field in the Desk UI would.
        member_doc.member_since = today()
        member_doc.status = "Active"
        mu.update_termination_status_display(member_doc)
        self.assertEqual(member_doc.status, "Active")

    def test_update_termination_status_display_skips_while_reapplication_pending(self):
        """While a reapplication is Pending (member_since not yet reset --
        that happens at approval), forcing a terminal status would drop the
        applicant from get_pending_applications() (status='Pending' filter),
        hiding a legitimate rejoin from reviewers. application_date is set to
        AFTER the termination -- exactly what update_member_from_reapplication
        does -- which is the positive signal that distinguishes this from the
        Select-default misfire covered below."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        old_termination_date = add_months(today(), -12)
        self._insert_executed_termination(member_doc.name, old_termination_date)

        member_doc.reload()
        # Reapplication in progress: status set to Pending, member_since NOT
        # yet reset (matches update_member_from_reapplication's own order),
        # application_date set to now (also matches that function).
        member_doc.status = "Pending"
        member_doc.application_status = "Pending"
        member_doc.application_date = now_datetime()
        mu.update_termination_status_display(member_doc)
        self.assertEqual(
            member_doc.status,
            "Pending",
            "A Pending reapplication must not be reverted to Quit before it is reviewed",
        )

    def test_update_termination_status_display_same_day_reapplication_still_skips(self):
        """Boundary: application_date on the SAME calendar day as the
        termination's own effective date must still count as "the
        reapplication postdates the termination". application_date is a
        Datetime and the termination's date a Date, so a same-day
        reapplication (processed hours after the termination, same calendar
        day) has application_date > termination_date at the TIME level but
        their DATE parts are equal -- getdate() truncates both to the date
        part before comparing, so this collapses to an equality, not a
        `>`. A reapplication can never actually precede the termination it
        responds to, so this equality must still count: `>=` is required,
        `>` would wrongly force Quit over the in-progress Pending status."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -24)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()
        termination_date = add_months(today(), -12)
        self._insert_executed_termination(member_doc.name, termination_date)

        member_doc.reload()
        member_doc.status = "Pending"
        member_doc.application_status = "Pending"
        # Same calendar day as termination_date, processed later that day.
        member_doc.application_date = get_datetime(f"{termination_date} 23:59:59")
        mu.update_termination_status_display(member_doc)
        self.assertEqual(
            member_doc.status,
            "Pending",
            "A same-day reapplication must still count as postdating the termination "
            "(the `>=` boundary, not `>`)",
        )

    def test_update_termination_status_display_default_application_status_does_not_misfire(self):
        """Regression (2nd independent review round, 2026-09-28): Member.
        application_status is a Select with NO default, so Frappe auto-fills
        its FIRST option, "Pending", for every member where it was never
        explicitly written -- CSV/Mijnrood imports, and every test member made
        by create_test_member() without passing application_status (as
        self.member here is). That must not be misread as "a reapplication is
        in progress": an ordinary, unrelated save on a member who was really
        terminated long ago (and never rejoined) must not clear
        member_end_date or leave status un-forced, just because
        application_status happens to still read the Select default.

        Drives a REAL termination via TerminationExecutionService (not a
        hand-set status) -- matches the reviewer's own reproduction and
        #1532/#1540's discipline."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_days(today(), -1000)
        # application_status deliberately left UNSET.
        member_doc.status = "Active"
        member_doc.save()
        member_doc.reload()
        self.assertEqual(
            member_doc.application_status,
            "Pending",
            "precondition: an unwritten Select auto-fills its first option",
        )

        termination_date = add_days(today(), -400)
        execute_real_termination(self, member_doc.name, termination_date)
        member_doc.reload()
        self.assertEqual(member_doc.status, "Quit")
        # Compare the RAW member_end_date, not getdate(member_end_date):
        # frappe.utils.getdate(None) returns TODAY, not None, so wrapping the
        # actual value in getdate() would silently turn "member_end_date was
        # never set / got cleared" into a same-shaped date mismatch instead of
        # an obvious None -- exactly what masked the real failure reason in
        # this test's own history (independent review, round 2).
        self.assertEqual(member_doc.member_end_date, getdate(termination_date))

        # An unrelated save (e.g. an admin editing an unrelated field) must
        # NOT clear member_end_date or un-force status, just because
        # application_status merely defaults to "Pending".
        member_doc.notes = "Unrelated edit, not a reapplication"
        member_doc.save()
        member_doc.reload()
        self.assertEqual(member_doc.status, "Quit")
        self.assertEqual(
            member_doc.member_end_date,
            getdate(termination_date),
            "member_end_date must survive an unrelated save on a member whose "
            "application_status merely defaults to 'Pending'",
        )

    def test_update_termination_status_display_clears_member_end_date_with_no_termination_request(self):
        """#1554: member_end_date can be written by a path that never creates
        a Membership Termination Request at all -- a raw `frappe.db.set_value`
        (e.g. `mollie_debug_service._sync_single_member_end_date`) does not
        depend on one existing. #1548's clearing logic sits entirely inside
        `if executed_termination:`, so a member with NO termination request
        of any kind never reached it, regardless of rejoin -- the stale value
        stayed forever. member_since advancing past a stale member_end_date
        must clear it on its own, independent of whether any termination
        request backs that value.

        Calls the hook directly (`mu.update_termination_status_display`),
        matching every sibling test in this section -- the hook is a pure
        function of doc state, not itself gated on request context. The
        `frappe.db.set_value` write below stands in for the Mollie writer's
        own bypass of before_save (see #1554); it is that writer's exact
        mechanism, not a hand-rolled shortcut."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.member_since = add_months(today(), -6)
        member_doc.application_status = "Approved"
        member_doc.status = "Active"
        member_doc.save()

        # The writer's own raw overwrite -- no Membership Termination
        # Request exists for this member at all.
        stale_end_date = add_months(today(), -3)
        frappe.db.set_value(
            "Member", member_doc.name, "member_end_date", stale_end_date, update_modified=False
        )
        member_doc.reload()
        self.assertEqual(member_doc.member_end_date, getdate(stale_end_date))
        self.assertEqual(
            frappe.db.count("Membership Termination Request", {"member": member_doc.name}),
            0,
            "precondition: no termination request exists for this scenario",
        )

        # Real rejoin: member_since resets to AFTER the stale end date.
        member_doc.member_since = today()
        member_doc.status = "Active"
        mu.update_termination_status_display(member_doc)
        self.assertIsNone(
            member_doc.member_end_date,
            "A stale member_end_date with no termination request behind it must "
            "still be cleared once member_since advances past it (#1554)",
        )

    def test_update_termination_status_display_quit_member_survives_unrelated_save_when_member_since_is_later(
        self,
    ):
        """#1554 round 2 (independent review): reproduces a REAL veg11 row
        (Assoc-Member-2026-01-33238: status Quit, member_since AFTER
        member_end_date, zero Membership Termination Requests) that a
        status-blind version of the #1554 fix (member_end_date <=
        member_since, on ANY status) silently wiped on an unrelated save --
        making a genuinely terminated member read as retained by
        membership_analytics.py (its queries treat a NULL member_end_date as
        "still a member"). member_since being later than member_end_date is
        NOT evidence of a rejoin by itself: an import writer can move
        member_since (or populate it for the first time) without the member
        ever rejoining -- see the member_since writer table in the PR
        description. Only `status == "Active"` (what the real
        rejoin/approval flow actually sets) is the positive signal.

        Hand-sets status="Quit" directly (a probe shortcut, disclosed): it
        stands in for the production row's OWN observed shape (read-only
        SELECT against veg11), not a hypothetical -- the point under test is
        the hook's behaviour given that DB state, regardless of which
        writer produced it."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.status = "Quit"
        member_doc.member_end_date = add_months(today(), -6)
        member_doc.member_since = add_months(today(), -2)  # AFTER the end date
        member_doc.save()
        self.assertEqual(
            frappe.db.count("Membership Termination Request", {"member": member_doc.name}),
            0,
            "precondition: no termination request exists for this scenario (matches the veg11 row)",
        )

        # An unrelated save must not touch member_end_date.
        member_doc.reload()
        member_doc.notes = "Unrelated edit, not a rejoin"
        member_doc.save()
        member_doc.reload()
        self.assertEqual(
            member_doc.member_end_date,
            getdate(add_months(today(), -6)),
            "A Quit member's own end date must survive regardless of member_since "
            "ordering -- member_since alone is not evidence of a rejoin (#1554 round 2)",
        )

    def test_update_termination_status_display_active_member_non_stale_end_date_survives(self):
        """Control (#1554 round 2): an Active member whose member_end_date is
        AFTER member_since (i.e. NOT stale -- e.g. a Mollie subscription
        cancellation recorded mid-membership, before any formal termination
        has actually been executed) must survive an unrelated save.
        Distinguishes the real fix's date comparison from a plausible wrong
        fix that clears whenever `status == "Active"` alone, ignoring
        whether the date is actually stale."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.status = "Active"
        member_doc.member_since = add_months(today(), -12)
        member_doc.member_end_date = add_months(today(), -1)  # AFTER member_since
        member_doc.save()

        member_doc.reload()
        member_doc.notes = "Unrelated edit"
        member_doc.save()
        member_doc.reload()
        self.assertEqual(
            member_doc.member_end_date,
            getdate(add_months(today(), -1)),
            "An Active member's own, non-stale member_end_date must survive (#1554 round 2 control)",
        )

    def test_update_termination_status_display_clears_when_member_since_populated_for_first_time_past_end_date(
        self,
    ):
        """#1554 round 2: a member_since IMPORT writer can populate
        member_since for the FIRST TIME (it was previously NULL) on a
        member who already carries a member_end_date, landing the new
        member_since after that end date -- without the member ever
        rejoining. services/csv_import/member_import_service.py's
        `_set_member_since_date` does exactly this in its `else` branch
        (`member_doc.member_since = new_member_since`, used when
        `member_doc.member_since` was falsy) whenever the CSV membership
        type maps to a non-Active status (e.g. "opgezegd" -> Quit, per
        MemberImportService.STATUS_MAP) -- status is set from the SAME row
        in the SAME update_member_fields() call, so this scenario keeps the
        member Quit throughout, matching the real writer's own behaviour.

        Reproduced here as a direct field write (disclosed) standing in for
        that writer's mechanism -- invoking the full CSV import service
        would additionally require its lookup-strategy and membership/dues
        scaffolding, which is orthogonal to what is under test here (the
        hook's response to this DB state). Status is never hand-set to
        anything the writer itself would not also set for this row shape."""
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.status = "Quit"
        member_doc.member_since = None
        member_doc.member_end_date = add_months(today(), -6)
        member_doc.save()
        member_doc.reload()
        self.assertIsNone(member_doc.member_since, "precondition: member_since starts NULL")

        # The import writer's mechanism: member_since populated for the
        # first time, landing AFTER the existing member_end_date. Status
        # stays "Quit" -- same call, same row, no rejoin involved.
        member_doc.member_since = add_months(today(), -2)
        member_doc.status = "Quit"
        member_doc.save()
        member_doc.reload()
        self.assertEqual(
            member_doc.member_end_date,
            getdate(add_months(today(), -6)),
            "A still-Quit member's end date must survive an import writer populating "
            "member_since for the first time past it (#1554 round 2)",
        )

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

        # find_chapter_by_postal_code is wrapped by
        # @frappe.whitelist(allow_guest=True) + @public_api, whose
        # audit/rate-limit machinery issues a fixed, N-independent number of
        # extra queries. Those are constant overhead, not the N+1 under
        # test, so measure the bare business function (reached via
        # __wrapped__), matching the precedent in
        # tests/sepa/test_sepa_performance_optimization.py.
        business_fn = mu.find_chapter_by_postal_code
        while hasattr(business_fn, "__wrapped__"):
            business_fn = business_fn.__wrapped__

        # 1 query for the bulk Chapter fetch + 1 for the settings check --
        # must NOT scale with the number of chapters (measured: unfixed code
        # issues 172 queries here; see #845 for the before/after numbers).
        with self.assertQueryCount(2):
            result = business_fn("1234")

        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result["matching_chapters"]), 4)
