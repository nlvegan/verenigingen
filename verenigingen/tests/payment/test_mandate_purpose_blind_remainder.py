"""The purpose-blind mandate sites #604 enumerated but did not fix (#605).

PR #604 fixed every purpose-blind resolution whose consequence it could measure as
a debit, and filed the enumerated remainder as #605: 52 sites, classified by
reading rather than by execution. This module executes them.

The fixture is the one #604 built -- a member holding an OLDER Active membership
mandate and a NEWER Active donation mandate, both legitimately Active through an
ordinary `save()`. It is imported rather than copied: the duplicate-helper ratchet
counts clone families, and `PurposeScopedMandateFixture` already carries the
control (`test_the_ambiguous_state_is_reachable`) that proves the state under test
is reachable at all.

Each test below names the consequence, not the query shape. "Resolves by recency"
is not a defect on its own; what makes each of these one is what the wrong mandate
then does -- a usage record written against a mandate that is not being debited, a
sign date that reaches the SEPA XML, a creation flow that declines to create the
membership mandate a member needs.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.payment.test_mandate_purpose_scoped_resolution import (
    DONATION_IBAN,
    MEMBERSHIP_IBAN,
    PurposeScopedMandateFixture,
    norm_iban,
)


def _record_collected_usage(mandate_name, usage_date, amount=25.0):
    """Give a mandate a collection history, so FRST/RCUR can tell it apart.

    Appended directly rather than through `create_mandate_usage_record`, which
    takes a mandate-level lock and re-derives the sequence type -- neither of
    which is the property under test here.
    """
    mandate = frappe.get_doc("SEPA Mandate", mandate_name)
    mandate.append(
        "usage_history",
        {
            "usage_date": usage_date,
            "reference_doctype": "Sales Invoice",
            "reference_name": f"HIST-{frappe.generate_hash(length=6)}",
            "sequence_type": "FRST",
            "amount": amount,
            "status": "Collected",
        },
    )
    mandate.save()
    return mandate


class TestBatchSequenceTypeFollowsTheDebitedMandate(PurposeScopedMandateFixture):
    """`dd_batch_optimizer` resolved a SECOND mandate after the batch row was built.

    `get_eligible_invoices_for_batching` selects `sm.mandate_id` through a join
    that #604 purpose-filtered, and that value becomes the batch row's
    `mandate_reference` -- the mandate that is actually debited. Both
    `determine_sequence_type` and `create_dd_batch_document` then threw that away
    and asked "an Active mandate for this member" again, unscoped, so the FRST/RCUR
    decision and the SEPA Mandate Usage row could belong to a different mandate
    than the debit.

    FRST vs RCUR is not cosmetic: it is carried in the XML, and a first-collection
    marker on a mandate the bank has already seen (or the reverse) is a rejection.
    """

    def setUp(self):
        super().setUp()
        # The DONATION mandate has been collected before; the membership mandate
        # never has. So "newest Active mandate" answers RCUR and "the mandate on
        # the batch row" answers FRST -- the two are distinguishable.
        _record_collected_usage(self.donation_mandate.name, today())

    def _batch_row(self):
        return {
            "invoice": None,
            "member": self.member.name,
            "mandate_reference": self.membership_mandate.mandate_id,
        }

    def test_sequence_type_comes_from_the_mandate_on_the_row(self):
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import determine_sequence_type

        self.assertEqual(
            determine_sequence_type([self._batch_row()]),
            "FRST",
            "the membership mandate has never been collected, so this batch is a first "
            "collection; RCUR here means the donation mandate's history was read",
        )

    def test_sequence_type_of_a_previously_collected_membership_mandate_is_rcur(self):
        """The control: the same code path must still answer RCUR when it should.

        Without this, `test_sequence_type_comes_from_the_mandate_on_the_row` is
        equally consistent with "always returns FRST".
        """
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import determine_sequence_type

        _record_collected_usage(self.membership_mandate.name, today())
        self.assertEqual(determine_sequence_type([self._batch_row()]), "RCUR")


class TestXMLSignDateIsNotAGuess(PurposeScopedMandateFixture):
    """`sepa_xml_adapter` fell back from "mandate not found" to "a mandate of this member".

    `_lookup_mandate_sign_date` is asked for the signature date of ONE mandate,
    named by `mandate_reference`; that date is written into the SEPA XML as the
    mandate's date of signature. When the reference did not resolve it took the
    member's most recently created Active mandate instead -- a different mandate's
    signature date, presented as this one's, with no purpose filter and no record
    that a substitution happened.
    """

    def _sign_date_for(self, mandate_reference):
        from verenigingen.verenigingen_payments.services.sepa_xml_adapter import SEPAXMLAdapter

        return SEPAXMLAdapter()._lookup_mandate_sign_date(
            mandate_reference=mandate_reference, member=self.member.name
        )

    def test_an_unresolvable_reference_does_not_borrow_another_mandates_sign_date(self):
        sign_date, used_fallback = self._sign_date_for("NO-SUCH-MANDATE-REFERENCE")

        self.assertTrue(
            used_fallback,
            "an unresolvable mandate reference is not a resolved one; reporting "
            "used_fallback=False tells the caller this date came from the named mandate",
        )
        # `getdate()` is the site-tz today the adapter now reports for "unknown", and
        # the fixture's sign dates are site-tz too, so both sides of these comparisons
        # are on one clock. Asserting the positive contract as well as the negative one:
        # "not the donation mandate's date" alone would also hold if the adapter had
        # borrowed the MEMBERSHIP mandate's date instead.
        self.assertEqual(
            getdate(sign_date),
            getdate(),
            "an unresolved reference reports today as the missing-date sentinel",
        )
        for other in (self.donation_mandate, self.membership_mandate):
            self.assertNotEqual(
                getdate(sign_date),
                getdate(other.sign_date),
                f"mandate {other.mandate_id}'s signature date reached the XML for this debit",
            )

    def test_the_named_mandate_still_resolves(self):
        """The control: the lookup must still work when the reference IS resolvable."""
        sign_date, used_fallback = self._sign_date_for(self.membership_mandate.mandate_id)

        self.assertFalse(used_fallback)
        self.assertEqual(getdate(sign_date), getdate(self.membership_mandate.sign_date))


class DonationOnlyMandateFixture(PurposeScopedMandateFixture):
    """A member who donates by direct debit and has NO membership mandate.

    This is the shape the creation flows get wrong. It is built from the shared
    two-mandate fixture by cancelling the membership half, so the member is left
    holding exactly one Active mandate -- a donation-only one, on the IBAN the
    member also pays dues from. Every "does this member already have a mandate?"
    check in the app answered yes for this member, and each of them exists to
    decide whether to CREATE the membership mandate they do not have.
    """

    def setUp(self):
        super().setUp()
        self.membership_mandate.status = "Cancelled"
        self.membership_mandate.is_active = 0
        self.membership_mandate.cancelled_date = today()
        self.membership_mandate.cancellation_reason = "Superseded for this fixture"
        self.membership_mandate.save()

        # The mandate inserts above link themselves into `Member.sepa_mandates`,
        # so the member row has moved on since `create_test_member` returned it.
        self.member.reload()
        self.member.iban = DONATION_IBAN
        self.member.payment_method = "SEPA Direct Debit"
        # `validate_bank_details` requires it once the payment method is direct debit
        self.member.bank_account_name = self.member.full_name
        self.member.save()

    def assert_fixture_shape(self):
        """The control: exactly one Active mandate, donation-only, on the member's IBAN."""
        active = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "iban", "used_for_memberships", "used_for_donations"],
        )
        self.assertEqual(len(active), 1, f"expected one Active mandate, got {active}")
        self.assertFalse(active[0].used_for_memberships)
        self.assertTrue(active[0].used_for_donations)
        self.assertEqual(norm_iban(active[0].iban), DONATION_IBAN)


class TestDonationMandateDoesNotSuppressMembershipMandateCreation(DonationOnlyMandateFixture):
    """The creation flows asked "any Active mandate?" and declined to create.

    The consequence is not a wrong IBAN -- it is no membership mandate at all.
    After #604 every collection path resolves mandates by purpose, so a member in
    this state is correctly found to have no membership mandate and their dues are
    simply never collected by direct debit, silently, while the UI reports that a
    mandate exists.
    """

    def test_the_fixture_is_the_donation_only_shape(self):
        self.assert_fixture_shape()

    def test_need_new_mandate_says_yes(self):
        from verenigingen.verenigingen.doctype.member.member_utils import need_new_mandate

        self.assertTrue(
            need_new_mandate(self.member.name, DONATION_IBAN)["need_new"],
            "the member has no membership mandate on this IBAN -- only a donation one",
        )

    def test_need_new_mandate_still_says_no_for_a_membership_mandate(self):
        """The control: a membership mandate on the same IBAN must still suppress creation."""
        from verenigingen.verenigingen.doctype.member.member_utils import need_new_mandate

        self._insert_active_mandate(
            iban=DONATION_IBAN,
            sign_date=today(),
            used_for_memberships=1,
            used_for_donations=0,
        )
        self.assertFalse(need_new_mandate(self.member.name, DONATION_IBAN)["need_new"])

    def test_check_and_handle_sepa_mandate_creates_rather_than_reuses(self):
        from verenigingen.verenigingen.doctype.member.member_utils import check_and_handle_sepa_mandate

        result = check_and_handle_sepa_mandate(self.member.name, DONATION_IBAN)
        self.assertEqual(
            result["action"],
            "create_new",
            "reusing the donation mandate leaves the member with no membership mandate",
        )

    def test_iban_mismatch_popup_does_not_offer_to_replace_the_donation_mandate(self):
        from verenigingen.verenigingen.doctype.member.member_utils import check_mandate_iban_mismatch

        result = check_mandate_iban_mismatch(self.member.name, MEMBERSHIP_IBAN)

        self.assertTrue(result["show_popup"])
        self.assertEqual(
            result["scenario"],
            "first_time_setup",
            "this member has never had a membership mandate; presenting it as a bank "
            "account change points the replacement flow at their donation mandate",
        )
        self.assertNotIn("existing_mandate", result)

    def test_the_missing_mandate_sweep_finds_this_member(self):
        from verenigingen.verenigingen_payments.api.sepa_mandate_management import (
            create_missing_sepa_mandates,
        )

        found = create_missing_sepa_mandates(dry_run=True)["results"]["mandates"]
        self.assertIn(
            self.member.name,
            [row["member"] for row in found],
            "the repair sweep skips members whose only Active mandate is for donations",
        )

        # The negative half: without it this asserts nothing about the filter --
        # a sweep that listed every member on the site would pass too.
        self._insert_active_mandate(
            iban=DONATION_IBAN, sign_date=today(), used_for_memberships=1, used_for_donations=0
        )
        still_found = create_missing_sepa_mandates(dry_run=True)["results"]["mandates"]
        self.assertNotIn(
            self.member.name,
            [row["member"] for row in still_found],
            "a member WITH a membership mandate must not be listed as needing one",
        )

    def test_fixing_one_member_creates_their_membership_mandate(self):
        from verenigingen.verenigingen_payments.api.sepa_mandate_management import (
            fix_specific_member_sepa_mandate,
        )

        result = fix_specific_member_sepa_mandate(self.member.name)

        self.assertTrue(result["success"], result.get("message"))
        created = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active", "used_for_memberships": 1},
            fields=["name", "iban"],
        )
        self.assertEqual(len(created), 1, f"expected one new membership mandate, got {created}")

    def test_fixing_one_member_touches_only_that_member(self):
        """`fix_specific_member_sepa_mandate` ran the whole-site creation sweep.

        It then filtered the results for the member named in the request, so it
        reported correctly while creating mandates for every other eligible member
        on the site as a side effect of one operator clicking "fix this member".
        """
        from verenigingen.verenigingen_payments.api.sepa_mandate_management import (
            fix_specific_member_sepa_mandate,
        )

        before = {row.name for row in frappe.get_all("SEPA Mandate", fields=["name"])}
        fix_specific_member_sepa_mandate(self.member.name)
        after = frappe.get_all(
            "SEPA Mandate", filters={"name": ["not in", list(before) or [""]]}, fields=["name", "member"]
        )

        self.assertEqual(
            [row.member for row in after],
            [self.member.name],
            "mandates were created for members the request did not name",
        )


class TestDuesEligibilityIsNotAnsweredByADonationMandate(DonationOnlyMandateFixture):
    """"Can we collect this member's dues by direct debit?" was answered by any mandate.

    These are the gates and diagnostics around the batching pipeline. Since #604 the
    pipeline itself resolves by purpose, so leaving them unscoped means they disagree
    with it: an invoice is passed as eligible and then silently produces nothing, and
    the diagnostic whose whole job is to report members missing a mandate reports
    that this member has one.
    """

    def _billing_eligibility_row(self):
        return {
            "invoice": "SINV-PURPOSE-TEST",
            "member": self.member.name,
            "member_status": self.member.status,
            "membership_status": "Active",
            "payment_method": "SEPA Direct Debit",
        }

    def test_a_donation_mandate_does_not_make_dues_billable(self):
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import (
            validate_member_eligibility_for_billing,
        )

        # The gate records its refusal through `frappe.log_error`, which is the
        # behaviour under test succeeding -- declare it so the harness's automatic
        # Error Log check does not read it as an incident (and so this test still
        # passes under VERENIGINGEN_FAIL_ON_ERROR_LOG=1).
        self.expectErrorLog("SEPA Mandate Validation")

        self.assertFalse(
            validate_member_eligibility_for_billing(self._billing_eligibility_row()),
            "this member has no membership mandate, so there is nothing to debit dues under",
        )

    def test_a_membership_mandate_still_makes_dues_billable(self):
        """The control: the gate must still pass the member it exists to pass."""
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import (
            validate_member_eligibility_for_billing,
        )

        self._insert_active_mandate(
            iban=DONATION_IBAN, sign_date=today(), used_for_memberships=1, used_for_donations=0
        )
        self.assertTrue(validate_member_eligibility_for_billing(self._billing_eligibility_row()))

    def test_the_missing_payment_info_report_lists_this_member(self):
        from verenigingen.verenigingen.report.members_without_payment_info.members_without_payment_info import (
            get_data,
        )

        listed = [row["member_name"] for row in get_data(None)]
        self.assertIn(
            self.member.name,
            listed,
            "the member has no way to pay their dues, but a donation mandate counted as one",
        )


class TestPaymentPlanDoesNotAttachToADonationMandate(DonationOnlyMandateFixture):
    """A payment plan recorded the member's newest Active mandate as its payment account.

    `get_member_active_sepa_mandate` was the literal #584 shape -- `order_by="creation
    desc"`, first row wins -- and its result is written to `Payment Plan.payment_account`
    together with `payment_method = "SEPA Direct Debit"`. A member who donates by
    direct debit had their instalment plan pointed at the donation mandate.
    """

    def _request_plan(self):
        from verenigingen.api.payment_plan_management import request_payment_plan

        # `@self_service_api` serializes the OperationResult, so this comes back as a
        # plain dict rather than the object the function returns -- the same thing
        # `dues_invoice_workflow._unwrap_api_result` exists to absorb.
        result = request_payment_plan(
            member=self.member.name, total_amount=120.0, preferred_installments=3
        )
        result = result if isinstance(result, dict) else result.to_dict()
        self.assertTrue(result.get("success"), result)
        return frappe.get_doc("Payment Plan", result["data"]["payment_plan_id"])

    def test_a_donation_only_member_gets_no_direct_debit_plan(self):
        plan = self._request_plan()

        self.assertEqual(
            plan.payment_method,
            "Bank Transfer",
            "there is no membership mandate to collect these instalments under",
        )
        self.assertFalse(plan.payment_account)

    def test_a_membership_mandate_is_used_when_there_is_one(self):
        """The control: the plan must still attach to a real membership mandate."""
        membership = self._insert_active_mandate(
            iban=DONATION_IBAN, sign_date=today(), used_for_memberships=1, used_for_donations=0
        )
        plan = self._request_plan()

        self.assertEqual(plan.payment_method, "SEPA Direct Debit")
        self.assertEqual(plan.payment_account, membership.name)


class TestMandateCreationWarningIsAboutTheSamePurpose(DonationOnlyMandateFixture):
    """The member form's pre-creation check warned about the wrong mandate.

    `sepa_api.validate_mandate_creation` is what `sepa-utils.js` calls before
    creating a mandate; on `existing_mandate` it tells the member *"Existing
    mandate {0} will be replaced"* and afterwards *"Previous mandate has been
    marked as replaced."* Both were false for a member creating a MEMBERSHIP
    mandate on the account their DONATION mandate already uses:
    `cancel_active_mandates` supersedes only overlapping purposes, so the donation
    mandate is untouched -- as it should be (#605).
    """

    def _validate_mandate_creation(self, iban):
        from verenigingen.api.member import sepa_api

        return sepa_api.validate_mandate_creation(
            self.member.name, iban, f"NEW-{frappe.generate_hash(length=8)}"
        )

    def test_a_donation_mandate_on_the_same_iban_is_not_reported_as_replaceable(self):
        result = self._validate_mandate_creation(DONATION_IBAN)

        self.assertTrue(result["valid"], result)
        self.assertNotIn(
            "existing_mandate",
            result,
            "the member would be told their donation mandate is about to be replaced",
        )

    def test_a_membership_mandate_on_the_same_iban_still_warns(self):
        """The control: the warning must still fire for a real same-purpose clash."""
        membership = self._insert_active_mandate(
            iban=DONATION_IBAN, sign_date=today(), used_for_memberships=1, used_for_donations=0
        )
        result = self._validate_mandate_creation(DONATION_IBAN)

        self.assertEqual(result.get("existing_mandate"), membership.mandate_id)


class TestTheMemberFacingAnswersAreAboutDues(DonationOnlyMandateFixture):
    """"Does this member have a mandate?" is asked by four member-facing readers.

    Each of them then decides something about DUES: the member form suppresses its
    "Create SEPA Mandate" button on a truthy `get_active_sepa_mandate`
    (`sepa-utils.js:419`), the dashboard indicator reports a mandate exists, and
    the payment dashboard shows the member the IBAN it says they are debited from.
    All four read an unfiltered Active list, so for a member who donates by direct
    debit and has no membership mandate they answered yes -- and the button that
    would have created the missing mandate never appeared (#605).
    """

    def test_the_member_form_reports_no_membership_mandate(self):
        from verenigingen.api.member import sepa_api

        self.assertIsNone(
            sepa_api.get_active_sepa_mandate(self.member.name),
            "a truthy answer here hides the button that creates the membership mandate",
        )

    def test_the_member_form_still_reports_a_membership_mandate(self):
        """The control: the endpoint must still find the mandate it is asked about."""
        from verenigingen.api.member import sepa_api

        membership = self._insert_active_mandate(
            iban=MEMBERSHIP_IBAN, sign_date=today(), used_for_memberships=1, used_for_donations=0
        )
        self.assertEqual(
            sepa_api.get_active_sepa_mandate(self.member.name)["mandate_id"], membership.mandate_id
        )

    def test_the_dashboard_indicator_reports_no_active_mandate(self):
        from verenigingen.verenigingen.doctype.member.member_utils import check_sepa_mandate_status

        self.assertFalse(check_sepa_mandate_status(self.member.name)["has_active_mandate"])

    def test_the_payment_dashboard_does_not_show_the_donation_iban(self):
        from verenigingen.api.payment_dashboard import get_payment_method

        result = get_payment_method(self.member.name)
        data = result if isinstance(result, dict) else result.to_dict()
        payload = data.get("data", data)

        self.assertFalse(
            payload.get("has_active_mandate"),
            "the member was shown their donation account as the one dues are collected from",
        )
