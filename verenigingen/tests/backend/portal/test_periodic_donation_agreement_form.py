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


class TestPeriodicDonationAgreementFormAnbiConsent(EnhancedTestCase):
    """#1461: the schema default `anbi_eligible: 1` made every new agreement
    run the strict, consent-requiring ANBI validation path regardless of what
    the submitter actually intended, and nothing in this form's pipeline ever
    recorded ANBI consent on the Donor -- so every first-time donor's
    submission failed with "Donor must provide ANBI consent...".

    Maintainer ruling (issue comment, 2026-09-26): the controller stays
    untouched (fail-closed `validate_donor_consent(strict=True)` is correct
    and `test_anbi_validation_failure_system_disabled` keeps encoding the
    current rule). The fix is in this web form: an explicit ANBI-consent
    checkbox (`anbi_tax_consent` in form_data). Ticked -> record consent on
    the Donor, then create a 5-year ANBI agreement. Unticked -> create a
    plain, non-ANBI pledge (`anbi_eligible=0`), so an unconsented submission
    never reaches the ANBI validation path at all.
    """

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _pledge_form_data(self, **overrides):
        data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "accept_terms": 1,
        }
        data.update(overrides)
        return data

    def test_anbi_consent_ticked_records_consent_and_creates_anbi_agreement(self):
        """An existing donor (already carrying a valid BSN from an earlier
        interaction, but never asked for ANBI consent specifically) ticks the
        new consent checkbox for their FIRST periodic donation agreement.
        Before the fix this fails with the consent error even though the
        checkbox exists nowhere yet to tick; after the fix it must succeed,
        record consent on the Donor, and produce an ANBI-eligible agreement.
        """
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        user_email = f"pda.anbiconsent.ticked.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        member = self.create_test_member(email=user_email, user=user_email)
        donor = self.create_test_donor(
            donor_name="Anbi Consent Ticked Donor",
            donor_type="Individual",
            member=member.name,
            bsn_citizen_service_number=generate_valid_bsn(),
        )
        self.assertFalse(donor.anbi_consent, "fixture must start withOUT consent recorded")

        form_data = self._pledge_form_data(
            accept_five_year_term=1,
            anbi_tax_consent=1,
        )

        self.expectErrorLog("Agreement Form Audit")  # process_agreement_form's own success audit log
        with self.as_user(user_email):
            result = process_agreement_form(form_data)

        self.assertTrue(result.get("success"), f"expected success, got: {result}")
        self.track_doc("Periodic Donation Agreement", result["agreement"])

        donor.reload()
        self.assertTrue(donor.anbi_consent, "consent must be recorded on the donor")

        agreement = frappe.get_doc("Periodic Donation Agreement", result["agreement"])
        self.assertEqual(agreement.donor, donor.name)
        self.assertTrue(agreement.anbi_eligible, "a consented submission must be ANBI-eligible")

    def test_anbi_consent_unticked_creates_non_anbi_pledge_without_recording_consent(self):
        """A genuinely first-time donor (no prior Donor record at all) submits
        WITHOUT ticking ANBI consent. This must succeed as a plain pledge --
        no BSN, no consent, no 5-year ANBI validation involved at all -- and
        must NOT record any ANBI consent on the newly created Donor.
        """
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        user_email = f"pda.anbiconsent.unticked.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        self.create_test_member(email=user_email, user=user_email)

        form_data = self._pledge_form_data()  # no anbi_tax_consent, no accept_five_year_term

        self.expectErrorLog("Agreement Form Audit")  # process_agreement_form's own success audit log
        with self.as_user(user_email):
            result = process_agreement_form(form_data)

        self.assertTrue(result.get("success"), f"expected success, got: {result}")
        self.track_doc("Periodic Donation Agreement", result["agreement"])

        agreement = frappe.get_doc("Periodic Donation Agreement", result["agreement"])
        self.track_doc("Donor", agreement.donor)
        self.assertFalse(agreement.anbi_eligible, "an unconsented submission must be a plain pledge")

        donor = frappe.get_doc("Donor", agreement.donor)
        self.assertFalse(donor.anbi_consent, "consent must NOT be recorded when the checkbox was unticked")

    def test_explicit_anbi_claim_without_consent_is_still_refused_by_the_controller(self):
        """CONTROL: the controller-level fail-closed rule is untouched by this
        fix. An explicit anbi_eligible=1 claim against a donor who has never
        consented must still be refused, exactly as
        test_anbi_validation_failure_system_disabled (a sibling control)
        keeps the system-disabled case refused. This is NOT reachable through
        the web form's own branching (which only ever sets anbi_eligible=1
        after recording consent) -- it exercises the controller directly, the
        layer the maintainer ruling says must NOT change.
        """
        donor = self.create_test_donor(
            donor_type="Individual",
            bsn_citizen_service_number=generate_valid_bsn(),
        )
        self.assertFalse(donor.anbi_consent, "control fixture must have NO consent on record")

        agreement = frappe.get_doc(
            {
                "doctype": "Periodic Donation Agreement",
                "donor": donor.name,
                "agreement_type": "Private Written",
                "start_date": frappe.utils.today(),
                "annual_amount": 600,
                "payment_frequency": "Monthly",
                "anbi_eligible": 1,
                "agreement_duration_years": "5 Years (ANBI Minimum)",
                "status": "Draft",
            }
        )

        with self.assertRaises(frappe.ValidationError) as cm:
            agreement.insert()

        self.assertIn("consent", str(cm.exception).lower())
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": donor.name}))


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
    Donor.member link wins over a donor_email match; falling back to a
    plain email match only when the user has no linked Member. Maintainer
    ruling (issue comment, 2026-09-26): on RESIDUAL ambiguity (2+ matches at
    a tier, no unique member-linked Donor) the submission is REFUSED
    outright -- no new Donor, no BSN write, no agreement -- deliberately
    stricter than #1396's "create a new unlinked Donor" ruling for the
    public, unauthenticated donation form, because this endpoint creates a
    legal/tax agreement carrying a BSN. A genuine NO-MATCH (zero Donors at
    any tier) is unaffected: it still creates a new Donor, exactly as
    before.
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

    def test_no_match_at_all_still_creates_new_donor(self):
        """Control for the ambiguity-refusal tests below: a genuine NO-MATCH
        (zero Donors anywhere, no Member either) is NOT an ambiguity and
        must still create a new Donor exactly as before -- the maintainer
        ruling narrows the refusal to residual ambiguity, it does not touch
        the ordinary first-time-donor path."""
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            get_or_create_donor_for_user,
        )

        user_email = f"pda.nomatch.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])

        with self.assertNoErrorLog():
            with self.as_user(user_email):
                resolved = get_or_create_donor_for_user()

        self.assertIsNotNone(resolved)
        self.track_doc("Donor", resolved["name"])
        self.assertEqual(frappe.db.get_value("Donor", resolved["name"], "donor_email"), user_email)

    def test_ambiguous_email_match_with_no_member_refuses_and_creates_nothing(self):
        """Two Donors share the logged-in user's e-mail, neither linked to
        any Member, and the user has no Member either (exercises the
        no-Member fallback tier directly). Maintainer ruling: this residual
        ambiguity must REFUSE outright -- no new Donor, no BSN write, no
        agreement -- not fall through to creating a new Donor."""
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
        donor_count_before = frappe.db.count("Donor", {"donor_email": user_email})
        # create_test_donor defaults a valid BSN onto an "Individual" donor
        # when none is given, so these are NOT empty to start with -- assert
        # unchanged (before/after), not falsy.
        first_bsn_before = first.bsn_citizen_service_number
        second_bsn_before = second.bsn_citizen_service_number

        self.expectErrorLog("DONOR_001")
        with self.assertErrorLog("DONOR_001"):
            with self.as_user(user_email):
                with self.assertRaises(frappe.ValidationError) as cm:
                    get_or_create_donor_for_user()

        self.assertIn("contact the association", str(cm.exception))

        # No new Donor was created for this ambiguous e-mail.
        self.assertEqual(
            frappe.db.count("Donor", {"donor_email": user_email}),
            donor_count_before,
            "refusing an ambiguous match must never create a new Donor",
        )
        # Neither pre-existing ambiguous Donor was written to.
        first.reload()
        second.reload()
        self.assertEqual(first.bsn_citizen_service_number, first_bsn_before)
        self.assertEqual(second.bsn_citizen_service_number, second_bsn_before)

    def test_process_agreement_form_ambiguous_donor_refuses_with_no_side_effects(self):
        """Full endpoint, through the real @self_service_api decorator, as a
        real non-admin logged-in user (not Administrator): an ambiguous
        e-mail match (here via the user's linked Member's own e-mail tier,
        see get_donor_for_member) must refuse the submission -- no new
        Donor, no BSN write, no agreement against either pre-existing
        Donor.

        Both pre-existing ambiguous Donors are given anbi_consent=1 and a
        valid BSN so they ALREADY satisfy every requirement
        create_agreement_from_form's validation checks -- so if a
        regression picked one of them arbitrarily instead of refusing, the
        submission would SUCCEED against it, giving this test's assertions
        something real to catch.
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
        donor_count_before = frappe.db.count("Donor", {"donor_email": user_email})
        first_bsn_before = first.bsn_citizen_service_number
        second_bsn_before = second.bsn_citizen_service_number

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

        self.assertFalse(result.get("success"))
        self.assertIn("contact the association", result.get("message", ""))

        # No new Donor was created for this ambiguous e-mail.
        self.assertEqual(
            frappe.db.count("Donor", {"donor_email": user_email}),
            donor_count_before,
            "refusing an ambiguous match must never create a new Donor",
        )

        # Neither pre-existing ambiguous Donor received an agreement or a
        # BSN write -- had resolution picked one arbitrarily instead of
        # refusing, the agreement WOULD have succeeded (both already
        # satisfy consent/BSN/duration).
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": first.name}))
        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": second.name}))
        first.reload()
        second.reload()
        self.assertEqual(first.bsn_citizen_service_number, first_bsn_before)
        self.assertEqual(second.bsn_citizen_service_number, second_bsn_before)

    def test_ambiguous_member_tier_never_falls_through_to_email_tier(self):
        """Two Donors both linked to the user's Member (ambiguous at the
        AUTHORITATIVE tier) plus a THIRD Donor that uniquely matches the
        user's e-mail: the third Donor must NEVER be used. Member-tier
        ambiguity must refuse immediately, not fall through to try the
        (unambiguous) email tier instead -- the exact fallthrough bug
        #1392's review found and fixed elsewhere in this family, and the
        reason find_donors_by_field's own docstring says an ambiguous match
        at one tier must never be resolved via a completely unrelated donor
        found at a weaker one.
        """
        from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
        from verenigingen.verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form import (
            process_agreement_form,
        )

        user_email = f"pda.membertier.ambiguous.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])
        member = self.create_test_member(email=user_email, user=user_email)

        self.create_test_donor(
            donor_name="Member Tier A",
            donor_email=f"unrelated-a.{frappe.generate_hash(length=6)}@example.com",
            donor_type="Individual",
            member=member.name,
        )
        self.create_test_donor(
            donor_name="Member Tier B",
            donor_email=f"unrelated-b.{frappe.generate_hash(length=6)}@example.com",
            donor_type="Individual",
            member=member.name,
        )
        # Uniquely matches the user's e-mail at the weaker email tier, and
        # already satisfies every ANBI requirement -- if member-tier
        # ambiguity ever fell through to the email tier, this donor would
        # be picked AND the agreement would succeed against it.
        third = self.create_test_donor(
            donor_name="Email Tier Unique",
            donor_email=user_email,
            donor_type="Individual",
            anbi_consent=1,
            bsn_citizen_service_number=generate_valid_bsn(),
        )
        third_bsn_before = third.bsn_citizen_service_number

        form_data = {
            "agreement_type": "Private Written",
            "start_date": frappe.utils.today(),
            "annual_amount": 600,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "accept_five_year_term": 1,
            "accept_terms": 1,
        }

        message_log_before_len = len(frappe.local.message_log)
        self.expectErrorLog("DONOR_001")
        self.expectErrorLog("Agreement Form Error")
        with self.assertErrorLog("DONOR_001"):
            with self.as_user(user_email):
                result = process_agreement_form(form_data)
        new_messages = frappe.local.message_log[message_log_before_len:]

        self.assertFalse(result.get("success"))
        self.assertIn("contact the association", result.get("message", ""))

        # The unique-email-match Donor's name must appear NOWHERE: not in
        # the result, and not in message_log (frappe.throw() appends there
        # before raising, so catching the exception is not enough on its
        # own to prove nothing was disclosed).
        self.assertNotIn(third.name, result.get("message", ""))
        self.assertNotIn(third.name, str(new_messages))

        self.assertFalse(frappe.db.exists("Periodic Donation Agreement", {"donor": third.name}))
        third.reload()
        self.assertEqual(third.bsn_citizen_service_number, third_bsn_before)
