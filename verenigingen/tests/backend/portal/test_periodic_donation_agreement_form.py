"""
Regression tests for
verenigingen/verenigingen/web_form/periodic_donation_agreement_form/periodic_donation_agreement_form.py
(#744, #762).

Covers two independent defects:

1. (#744) Periodic Donation Agreement.payment_method is a Select with exactly
   three options ("SEPA Direct Debit", "Bank Transfer", "Other").
   create_agreement_from_form() assigned form_data.get("payment_method")
   straight into that field with no check. This form's own dropdown only
   offers the three valid options, but the endpoint (process_agreement_form,
   @self_service_api) is reachable directly with any string, so the same
   fix applied to the API sibling (periodic_donation_operations.py) is
   applied here too.

2. (#762) create_sepa_mandate_for_agreement() could not work as written: its
   dedupe guard compared an unspaced IBAN against SEPAMandate's
   space-formatted stored value (never matches), it put a Donor name into a
   Member-only Link field, used a non-existent "Pending" status, and set a
   nonexistent "valid_from" field. Reachability check (verified live on
   test_site_1 and veg11): both Verenigingen web forms exist but are
   unpublished (published=0), and zero Periodic Donation Agreement on veg11
   has ever had a sepa_mandate set -- so this path has never actually been
   used in production. Even a spec-compliant, memberless SEPA Mandate would
   still be inert: the SEPA collection pipeline (sepa_batch_processor.py,
   mandate_candidates.py) resolves every mandate by Member, never by Donor,
   so nothing would ever collect on it. Rather than build a mandate the rest
   of the system cannot act on, SEPA Direct Debit is now refused loudly,
   before any donor/agreement side effects run.
"""

import frappe

from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPeriodicDonationAgreementFormPaymentMethodMapping(EnhancedTestCase):
    """REGRESSION (#744): payment_method must be validated/mapped, not
    assigned unchecked into the agreement's 3-option Select."""

    def test_create_agreement_from_form_maps_mollie_to_other(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Mollie",
        }

        agreement = create_agreement_from_form(donor.name, form_data)
        self.track_doc("Periodic Donation Agreement", agreement.name)

        self.assertEqual(agreement.payment_method, "Other")

    def test_create_agreement_from_form_rejects_unrecognized_payment_method(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(donor_type="Individual")
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bitcoin",
        }

        with self.assertRaises(frappe.ValidationError):
            create_agreement_from_form(donor.name, form_data)

        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": donor.name}))

    def test_create_agreement_from_form_accepts_valid_select_option_unchanged(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            create_agreement_from_form,
        )

        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
        }

        agreement = create_agreement_from_form(donor.name, form_data)
        self.track_doc("Periodic Donation Agreement", agreement.name)

        self.assertEqual(agreement.payment_method, "Bank Transfer")


class TestPeriodicDonationAgreementFormSepaRefusal(EnhancedTestCase):
    """REGRESSION (#762): SEPA Direct Debit must be refused loudly, before
    any donor/agreement/mandate side effects, not attempt a broken mandate
    creation."""

    def _sepa_form_data(self, **overrides):
        data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "SEPA Direct Debit",
            "sepa_iban": "NL91 ABNA 0417 1643 00",
            "sepa_account_holder": "Test Donor",
            "accept_five_year_term": 1,
            "accept_terms": 1,
        }
        data.update(overrides)
        return data

    def test_validate_agreement_form_data_rejects_sepa_direct_debit(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            validate_agreement_form_data,
        )

        with self.assertRaises(frappe.ValidationError):
            validate_agreement_form_data(self._sepa_form_data())

    def test_validate_agreement_form_data_still_accepts_bank_transfer(self):
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            validate_agreement_form_data,
        )

        # Must not raise.
        validate_agreement_form_data(self._sepa_form_data(payment_method="Bank Transfer"))

    def test_process_agreement_form_rejects_sepa_with_no_side_effects(self):
        """Full endpoint: a SEPA Direct Debit submission must fail cleanly,
        with no Donor, Agreement, or SEPA Mandate left behind.

        process_agreement_form is @self_service_api(implicit_allowed=True),
        which requires the calling user to resolve to a Member record (see
        self_service_access_controller.get_user_member) -- so the test user
        needs a linked Member, even though the endpoint itself operates on a
        Donor derived separately via get_or_create_donor_for_user().
        """
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        # process_agreement_form's own except-block logs every rejection
        # (including this expected one) via frappe.log_error.
        self.expectErrorLog("Agreement Form Error")

        user_email = f"pda.sepa.test.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        self.create_test_member(email=user_email)

        original_user = frappe.session.user
        try:
            frappe.set_user(user_email)
            result = process_agreement_form(self._sepa_form_data())
        finally:
            frappe.set_user(original_user)

        self.assertFalse(result.get("success"), f"SEPA submission should be rejected: {result}")
        self.assertIn("SEPA Direct Debit", result.get("message", ""))

        # No side effects: validate_agreement_form_data raises before
        # get_or_create_donor_for_user ever runs, so no Donor -- and
        # therefore no Agreement referencing one -- was created for this user.
        self.assertFalse(frappe.db.exists("Donor", {"donor_email": user_email}))


class TestPeriodicDonationAgreementFormDonorResolution(EnhancedTestCase):
    """#1450: get_or_create_donor_for_user() used to resolve the logged-in
    user's Donor with an arbitrary frappe.db.get_value("Donor",
    {"donor_email": ...}) pick, then wrote the submitter's BSN
    (update_donor_bsn) and created a 5-year Periodic Donation Agreement
    against whatever it picked -- the same "silent arbitrary pick"
    anti-pattern as #1356/#1384/#1389/#1392/#1406/#1396, but with a
    higher-severity blast radius because both are real writes.

    Now resolves via the shared, tiered Donor resolution: the authoritative
    Donor.member link wins over a donor_email match (get_donor_for_member),
    and falling back to a plain email match (donor_service.get_donor_by_email)
    only when the user has no linked Member. An ambiguous match at either
    tier refuses -- get_or_create_donor_for_user then falls through to its
    existing create-a-new-unlinked-Donor branch (PROVISIONAL per the #1396
    maintainer ruling, made for a public unauthenticated donation form; this
    endpoint is a logged-in user creating a legal/tax agreement, a
    higher-stakes case the maintainer had not yet separately ruled on when
    this fix was written) rather than ever writing onto an arbitrarily
    picked existing Donor.
    """

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def test_member_linked_donor_wins_over_email_match(self):
        """A Donor.member link must be consulted BEFORE donor_email, even
        when a completely different Donor shares the logged-in user's
        e-mail and would be the only hit for an email-first lookup. Catches
        an "email tier before member tier" regression: with member-tier
        skipped, the single donor_email match below is unambiguous and
        would be returned outright."""
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            get_or_create_donor_for_user,
        )

        user_email = f"pda.memberwins.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        member = self.create_test_member(email=user_email, user=user_email)

        # What an email-first lookup would find: unrelated to this member.
        email_match_donor = self.create_test_donor(
            donor_name="Email Match Donor", donor_email=user_email, donor_type="Individual"
        )
        # The authoritative donor: linked via Donor.member, unrelated e-mail.
        member_linked_donor = self.create_test_donor(
            donor_name="Member Linked Donor",
            donor_email=f"unrelated.{frappe.generate_hash(length=6)}@example.com",
            donor_type="Individual",
            member=member.name,
        )

        with self.as_user(user_email):
            resolved = get_or_create_donor_for_user()

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["name"], member_linked_donor.name)
        self.assertNotEqual(resolved["name"], email_match_donor.name)

    def test_single_email_match_with_no_member_is_used(self):
        """Control: exactly one Donor shares the e-mail and the user has no
        Member at all -- must resolve to that Donor (not create a new,
        redundant one)."""
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            get_or_create_donor_for_user,
        )

        user_email = f"pda.singlematch.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        donor = self.create_test_donor(
            donor_name="Single Match Donor", donor_email=user_email, donor_type="Individual"
        )

        with self.as_user(user_email):
            resolved = get_or_create_donor_for_user()

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["name"], donor.name)
        self.assertEqual(
            frappe.db.count("Donor", {"donor_email": user_email}),
            1,
            "a single unambiguous match must be reused, not duplicated",
        )

    def test_ambiguous_email_match_with_no_member_creates_new_donor(self):
        """Two Donors share the logged-in user's e-mail, neither linked to
        any Member, and the user has no Member either (exercises the
        no-Member fallback tier directly). This is an unresolvable
        ambiguity: must refuse -- fall through to creating a new, unlinked
        Donor -- rather than picking one of the two arbitrarily."""
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            get_or_create_donor_for_user,
        )

        user_email = f"pda.ambiguous.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        first = self.create_test_donor(
            donor_name="First Ambiguous", donor_email=user_email, donor_type="Individual"
        )
        second = self.create_test_donor(
            donor_name="Second Ambiguous", donor_email=user_email, donor_type="Individual"
        )

        self.expectErrorLog("DONOR_001")
        with self.assertErrorLog("DONOR_001"):
            with self.as_user(user_email):
                resolved = get_or_create_donor_for_user()

        self.assertIsNotNone(resolved)
        self.track_doc("Donor", resolved["name"])
        self.assertNotIn(
            resolved["name"],
            (first.name, second.name),
            "an ambiguous match must never resolve to either existing Donor",
        )

    def test_process_agreement_form_ambiguous_donor_creates_new_donor_and_agreement(self):
        """Full endpoint, through the real @self_service_api decorator, as a
        real non-admin logged-in user (not Administrator): an ambiguous
        e-mail match (here via the user's linked Member's own e-mail tier,
        see get_donor_for_member) must never leave the new Agreement
        attached to either pre-existing Donor.

        Both pre-existing ambiguous Donors are given anbi_consent=1 and a
        valid BSN so they ALREADY satisfy every requirement
        create_agreement_from_form's validation checks (independent of
        #1450: a brand-new Donor from the create-new-Donor fallback always
        has anbi_consent=0, since ANBI consent has no write path anywhere
        in this flow -- filed separately, see #1450's PR description) --
        so if a regression picked one of them arbitrarily instead of
        refusing, the submission would SUCCEED against it, giving this
        test's "no Agreement for either" assertion something to catch
        regardless of the new donor's own eventual outcome.
        """
        from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        user_email = f"pda.ambiguous.e2e.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        self.create_test_member(email=user_email, user=user_email)
        first = self.create_test_donor(
            donor_name="First Ambiguous E2E",
            donor_email=user_email,
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=generate_valid_bsn(),
        )
        second = self.create_test_donor(
            donor_name="Second Ambiguous E2E",
            donor_email=user_email,
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=generate_valid_bsn(),
        )

        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "accept_five_year_term": 1,
            "accept_terms": 1,
        }

        self.expectErrorLog("DONOR_001")
        self.expectErrorLog("Agreement Form Error")
        with self.assertErrorLog("DONOR_001"):
            with self.as_user(user_email):
                result = process_agreement_form(form_data)

        # The new, unlinked Donor the fallback branch creates has
        # anbi_consent=0 (nothing in this flow sets ANBI consent), so
        # create_agreement_from_form's ANBI validation rejects it -- a
        # separate, pre-existing defect (default-claims-ANBI on every new
        # agreement) independent of donor *resolution*, which is what this
        # test targets. What matters here is WHICH donor was almost
        # attached, not whether the agreement ultimately completed.
        self.assertFalse(result.get("success"))
        self.assertIn("ANBI consent", result.get("message", ""))

        new_donor_name = frappe.db.get_value(
            "Donor",
            {"donor_email": user_email, "name": ["not in", [first.name, second.name]]},
            "name",
        )
        self.assertIsNotNone(new_donor_name, "the ambiguity fallback must create a new Donor")
        self.track_doc("Donor", new_donor_name)

        # Neither pre-existing ambiguous Donor received an agreement -- had
        # resolution picked one arbitrarily instead of refusing, this WOULD
        # have succeeded (both already satisfy consent/BSN/duration).
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": first.name}))
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": second.name}))
