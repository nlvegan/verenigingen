"""Regression test for #987: the Mollie-subscription factory's SEPA Mandate
get-or-create filter can never match.

``EnhancedTestFactoryBridge.create_test_mollie_subscription`` (enhanced_test_
factory.py) looks for a reusable mandate with
``frappe.db.get_value("SEPA Mandate", {"member": ..., "docstatus": 1}, ...)``.
SEPA Mandate has no ``is_submittable`` in its DocType JSON, so every mandate a
normal path creates sits at docstatus 0 forever -- the filter matches nothing,
and the factory silently creates a brand-new mandate on every call instead of
reusing the member's existing one.

A test that only inspected the filter STRING would pass for the wrong reason
(see CLAUDE.md's TDD section): the actual behaviour this bug destroys is
REUSE, so the test below calls the factory method twice for the same member
and asserts the second call returns the SAME mandate, not a second one.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieSubscriptionFactoryMandateReuse(EnhancedTestCase):
    def test_second_call_reuses_the_first_mandate(self):
        member = self.create_test_member(
            first_name="Mandate",
            last_name="Reuse",
            email=f"mandate.reuse.{frappe.generate_hash(length=8)}@example.com",
            birth_date="1985-01-01",
        )

        first = self.create_test_mollie_subscription(member=member, iban="NL91ABNA0417164300")
        first_mandate_name = first["sepa_mandate"].name

        second = self.create_test_mollie_subscription(member=member, iban="NL91ABNA0417164300")
        second_mandate_name = second["sepa_mandate"].name

        self.assertEqual(
            first_mandate_name,
            second_mandate_name,
            "the second call must REUSE the member's existing active mandate, not create another one",
        )

        mandate_count = frappe.db.count("SEPA Mandate", {"member": member.name})
        self.assertEqual(1, mandate_count, "exactly one SEPA Mandate should exist for this member")

    def test_a_donation_only_mandate_is_not_reused_for_a_membership_subscription(self):
        """Regression test for #996: the reuse filter must be purpose-scoped.

        #987's fix replaced an unmatchable ``docstatus = 1`` filter with
        ``status``/``is_active``, which reuses a live mandate -- but any live
        mandate, regardless of what it is authorised FOR. SEPA Mandate models
        purpose explicitly (``used_for_memberships`` / ``used_for_donations`` /
        ``used_for_other``) and validates one active mandate PER PURPOSE, and
        the app's other get-or-create
        (``services/payment/sepa_mandate_manager.py``) scopes its lookup by
        ``used_for_memberships`` for exactly this reason -- #605: "Unscoped, a
        member holding only a donation mandate was reported as an IBAN mismatch
        rather than as missing the mandate their dues need."

        So a member whose only live mandate is donation-only must NOT have it
        handed back for a membership subscription. Asserting on the purpose flag
        rather than on the mandate name is deliberate: a name assertion would
        also pass if the factory returned some unrelated third mandate.
        """
        member = self.create_test_member(
            first_name="Donation",
            last_name="OnlyMandate",
            email=f"donation.only.{frappe.generate_hash(length=8)}@example.com",
            birth_date="1985-01-01",
        )

        donation_only = self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL91ABNA0417164300",
            used_for_memberships=0,
            used_for_donations=1,
        )
        # Control: the precondition this test depends on actually holds.
        self.assertEqual(0, int(donation_only.used_for_memberships))
        self.assertEqual("Active", donation_only.status)

        result = self.create_test_mollie_subscription(member=member, iban="NL91ABNA0417164300")
        used = result["sepa_mandate"]

        self.assertEqual(
            1,
            int(used.used_for_memberships),
            "the factory handed back a mandate not authorised for memberships "
            f"({used.name}); a donation-only mandate must not be reused here",
        )
        self.assertNotEqual(
            donation_only.name,
            used.name,
            "the donation-only mandate must not be reused for a membership subscription",
        )
