"""An empty purpose list is not "every purpose" (#617).

`cancel_active_mandates` opened with ``tuple(purposes) if purposes else PURPOSE_FLAGS``,
so a caller computing its purposes with a list comprehension handed in ``[]`` whenever
the request set no purpose -- and ``[]`` was read as "supersede every Active mandate
regardless of purpose". That is the same falsy-vs-None trap #597 fixed in
`resolve_purpose_flag`, where ``if purpose and ...`` silently restored purpose-blind
resolution.

The property under test is a MONEY property, not an argument-passing one: a member's
donation mandate must survive the creation of a mandate that serves nothing. Asserting
only that `cancel_active_mandates` was *called* with `[]` would pass for both the broken
and the fixed helper, because the helper is where the two spellings diverge.

`purposes=None` still means every purpose, deliberately -- three of the five production
call sites and every existing test in `test_mandate_candidates.py` rely on it -- so each
test here has its `None` control beside it.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.mandate_candidates import cancel_active_mandates

MEMBERSHIP_IBAN = "NL91ABNA0417164300"
DONATION_IBAN = "NL39RABO0300065264"


class MandatePairFixture(EnhancedTestCase):
    """A member holding one Active membership mandate and one Active donation mandate.

    This is a legitimate shape, not a contrived one:
    `SEPAMandate.validate_single_active_mandate_per_purpose` permits exactly one Active
    mandate PER PURPOSE, so both rows below are inserted with an ordinary `save()` --
    no `frappe.db.set_value` is needed to reach the state under test.
    """

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="EmptyPurp", last_name="Test")

    def _active_mandate_for_purposes(self, iban, **purposes):
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"EMPT-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                # The DocType JSON defaults `used_for_memberships` to 1, so every
                # purpose is stated explicitly here rather than inherited.
                "used_for_memberships": 0,
                "used_for_donations": 0,
                "used_for_other": 0,
                **purposes,
            }
        )
        doc.insert()
        return doc

    def _status_of(self, mandate):
        return frappe.db.get_value("SEPA Mandate", mandate.name, "status")


class TestAnEmptyPurposeListSupersedesNothing(MandatePairFixture):
    def test_an_empty_list_cancels_nothing(self):
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        result = cancel_active_mandates(self.member.name, "test reason", purposes=[])

        self.assertEqual(
            result["names"],
            [],
            "an empty purpose list superseded mandates it does not overlap",
        )
        self.assertEqual(self._status_of(membership), "Active")
        self.assertEqual(self._status_of(donation), "Active")
        self.assertEqual(
            result["purposes"],
            {"used_for_memberships": 0, "used_for_donations": 0, "used_for_other": 0},
        )

    def test_an_empty_tuple_cancels_nothing_either(self):
        """The same shape a caller writing `tuple(...)` produces."""
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)

        result = cancel_active_mandates(self.member.name, "test reason", purposes=())

        self.assertEqual(result["names"], [])
        self.assertEqual(self._status_of(membership), "Active")

    def test_none_still_means_every_purpose(self):
        """The control. Three production call sites and every existing test rely on
        the default meaning "supersede everything"; the fix must not touch it."""
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        result = cancel_active_mandates(self.member.name, "test reason", purposes=None)

        self.assertCountEqual(result["names"], [membership.name, donation.name])
        self.assertEqual(self._status_of(membership), "Cancelled")
        self.assertEqual(self._status_of(donation), "Cancelled")

    def test_a_populated_list_still_supersedes_only_the_overlap(self):
        """The second control: purpose scoping itself must keep working."""
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        result = cancel_active_mandates(
            self.member.name, "test reason", purposes=["used_for_memberships"]
        )

        self.assertEqual(result["names"], [membership.name])
        self.assertEqual(self._status_of(membership), "Cancelled")
        self.assertEqual(self._status_of(donation), "Active")


class TestAPurposelessMandateDoesNotCancelTheMemberSMandates(MandatePairFixture):
    """The call site the issue was filed from.

    `sepa_api.create_and_link_mandate_enhanced` computes
    ``wanted = [f for f in ("used_for_memberships", "used_for_donations")
                if mandate_doc.get(f)]``
    which is `[]` for a request that ticks neither purpose. Before the fix that
    cancelled the member's donation mandate, and the replacement only kept collecting
    donations because `carry_forward_purposes` ORed the superseded flag back in -- i.e.
    the member's donation authorization silently moved to a different IBAN.
    """

    def _create_purposeless_mandate(self):
        """Call the endpoint with neither purpose ticked.

        Since #606 `SEPAMandate.validate_active_mandate_has_a_purpose` refuses to
        ACTIVATE a mandate that serves nothing, so with the fix in place this call
        raises rather than returning. The refusal is not the subject of these tests
        -- what happened to the mandates the member already held is -- but it IS
        asserted, by `_assert_reached_the_activation` below.
        """
        from verenigingen.api.member.sepa_api import create_and_link_mandate_enhanced

        try:
            return create_and_link_mandate_enhanced(
                member=self.member.name,
                mandate_id=f"EMPT-NEW-{frappe.generate_hash(length=8)}",
                iban="NL02ABNA0123456789",
                account_holder_name=self.member.full_name,
                used_for_memberships=0,
                used_for_donations=0,
            )
        except frappe.ValidationError as refusal:
            return {"refused": str(refusal)}

    def _assert_reached_the_activation(self, outcome):
        """A surviving mandate proves nothing if the endpoint never ran.

        Asserting only ``status == "Active"`` is one-sided: it cannot tell "the flow
        ran and correctly superseded nothing" from "the flow never got as far as
        `cancel_active_mandates`". Measured -- stubbing
        `sepa_api.create_and_link_mandate_enhanced`'s ``if
        response_data.get("mandate_name"):`` to `False` left both tests below GREEN.
        #606's refusal is raised by `mandate_doc.save()`, which is the statement
        AFTER the supersede call, so seeing it pins that execution got past the code
        under test.
        """
        self.assertIn(
            "not marked for any purpose",
            outcome.get("refused", ""),
            f"the endpoint did not reach the activation, so nothing exercised "
            f"cancel_active_mandates: {outcome}",
        )

    def test_a_purposeless_request_leaves_the_donation_mandate_alone(self):
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        self._assert_reached_the_activation(self._create_purposeless_mandate())

        self.assertEqual(
            self._status_of(donation),
            "Active",
            "creating a mandate that serves nothing cancelled the member's donation "
            "mandate -- their donations would be collected from a different IBAN",
        )

    def test_a_purposeless_request_leaves_the_membership_mandate_alone(self):
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)

        self._assert_reached_the_activation(self._create_purposeless_mandate())

        self.assertEqual(
            self._status_of(membership),
            "Active",
            "creating a mandate that serves nothing cancelled the member's membership "
            "mandate",
        )

    def test_a_membership_request_still_supersedes_the_membership_mandate(self):
        """The control: the supersede path this endpoint exists for must still run."""
        from verenigingen.api.member.sepa_api import create_and_link_mandate_enhanced

        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        result = create_and_link_mandate_enhanced(
            member=self.member.name,
            mandate_id=f"EMPT-NEW-{frappe.generate_hash(length=8)}",
            iban="NL02ABNA0123456789",
            account_holder_name=self.member.full_name,
            used_for_memberships=1,
            used_for_donations=0,
        )

        self.assertTrue(result.get("success"), result)
        self.assertEqual(self._status_of(membership), "Cancelled")
        self.assertEqual(
            self._status_of(donation),
            "Active",
            "a membership replacement superseded the donation mandate too",
        )


class TestTheThirdCallSiteIsTheOneThatIsNotDeprecated(MandatePairFixture):
    """The same defect, in the site nobody had labelled deprecated (rule 6).

    Three endpoints build `purposes` with a comprehension over the flags the request
    set, so all three produce `[]` for a 0/0 request:
    `api/member/sepa_api.py:173` `create_and_link_mandate_enhanced` (deprecated),
    `doctype/member/member_utils.py:886` `create_and_link_mandate` (deprecated), and
    this one -- `doctype/member/member_utils.py:381`
    `create_sepa_mandate_from_bank_details`, which carries `@frappe.whitelist()` and
    `@critical_api(FINANCIAL)` and NO deprecation marker. Testing only the two
    deprecated ones would have been testing the class by its least important member.

    This site swallows the guard's message: `secure_document_operation` turns the
    ValidationError into `mandate_result.errors` and `member_utils.py:439` re-throws
    the generic "Failed to create SEPA mandate for member {0}". So the assertion
    here is the surviving mandate plus the fact that creation failed at all.
    """

    def _create_purposeless_mandate(self):
        from verenigingen.verenigingen.doctype.member import member_utils as mu

        self.expectErrorLog("SEPA Mandate Security")
        self.expectErrorLog("SEPA Audit Trail")
        with self.assertRaises(frappe.ValidationError) as raised:
            mu.create_sepa_mandate_from_bank_details(
                member=self.member.name,
                iban="NL02ABNA0123456789",
                account_holder_name=self.member.full_name,
                used_for_memberships=0,
                used_for_donations=0,
            )
        self.assertIn("Failed to create SEPA mandate", str(raised.exception))

    def test_a_purposeless_request_leaves_the_donation_mandate_alone(self):
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        self._create_purposeless_mandate()

        self.assertEqual(
            self._status_of(donation),
            "Active",
            "the non-deprecated endpoint still cancels a purposeless request's "
            "unrelated mandates",
        )

    def test_a_membership_request_still_supersedes_the_membership_mandate(self):
        """The control: this endpoint's ordinary supersede path must still run."""
        from verenigingen.verenigingen.doctype.member import member_utils as mu

        self.expectErrorLog("SEPA Audit Trail")
        membership = self._active_mandate_for_purposes(MEMBERSHIP_IBAN, used_for_memberships=1)
        donation = self._active_mandate_for_purposes(DONATION_IBAN, used_for_donations=1)

        name = mu.create_sepa_mandate_from_bank_details(
            member=self.member.name,
            iban="NL02ABNA0123456789",
            account_holder_name=self.member.full_name,
            used_for_memberships=1,
            used_for_donations=0,
        )

        self.assertTrue(frappe.db.exists("SEPA Mandate", name))
        self.assertEqual(self._status_of(membership), "Cancelled")
        self.assertEqual(
            self._status_of(donation),
            "Active",
            "a membership replacement superseded the donation mandate too",
        )
