"""An Active SEPA Mandate must be marked for at least one purpose (#606).

`SEPAMandate.validate_single_active_mandate_per_purpose` (#584/#597) enforces one
Active mandate per member PER PURPOSE. It did so by collecting the purpose flags
that are set and looping over them -- so a mandate with NONE of them set had an
empty loop and returned early, and the invariant simply did not apply to it. Two
all-purposes-zero Active mandates for one member were measured coexisting.

Bucketing "no purpose" as a fourth purpose would close that specific hole and
leave the larger one open: since #597 every mandate-resolution query filters by
purpose, so an all-zero Active mandate can be found by NONE of them. It is an
authorization that authorizes nothing -- and creating one is not inert. The
whitelisted `create_and_link_mandate_enhanced(used_for_memberships=0,
used_for_donations=0)` computes `wanted = []` and passes it to
`cancel_active_mandates(purposes=[])`, where an empty list means "every purpose",
so it CANCELS the member's real membership mandate and installs one that cannot
collect. Requiring a purpose makes the shape unreachable rather than merely
unique.

Scope of what the guard touches: it runs only for `status == "Active"`, so a
purposeless Draft or Suspended mandate can still be staged and saved, and a
Cancelled one is untouched. Measured 2026-08-27: `tabSEPA Mandate` holds zero
all-zero rows on veg11 (71 rows, all `used_for_memberships = 1`) and zero on
test_site_1, and no test fixture in this app creates one -- every site that sets
`used_for_memberships = 0` also sets `used_for_donations = 1`.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

IBAN_A = "NL91ABNA0417164300"
IBAN_B = "NL02ABNA0123456789"


class _PurposeFixture(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="PurposeReq", last_name="Test")

    def _mandate(self, iban, status="Active", **purposes):
        """A mandate built with `new_doc` + `insert()`, i.e. no bypass.

        `new_doc` applies the JSON default `used_for_memberships = 1`, which is
        why every purpose flag is written explicitly here: an omitted flag would
        silently give the mandate a purpose and the test would measure nothing.
        """
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = self.member.name
        mandate.mandate_id = f"PURPREQ-{frappe.generate_hash(length=8)}"
        mandate.account_holder_name = self.member.full_name
        mandate.iban = iban
        mandate.sign_date = "2024-01-01"
        mandate.mandate_type = "RCUR"
        mandate.status = status
        mandate.used_for_memberships = purposes.get("used_for_memberships", 0)
        mandate.used_for_donations = purposes.get("used_for_donations", 0)
        mandate.used_for_other = purposes.get("used_for_other", 0)
        mandate.insert()
        return mandate


class TestActiveMandateRequiresAPurpose(_PurposeFixture):
    def test_an_active_mandate_with_no_purpose_is_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._mandate(IBAN_A)

        message = str(ctx.exception)
        self.assertIn("used_for_memberships", message)
        self.assertIn("used_for_donations", message)
        self.assertIn("used_for_other", message)

    def test_the_second_all_zero_active_mandate_is_rejected_too(self):
        """The state #606 measured: two all-zero Active mandates coexisting.

        Reached here from the other side -- the first one can no longer be
        created at all, so the pair is unreachable rather than merely unique.
        """
        with self.assertRaises(frappe.ValidationError):
            self._mandate(IBAN_A)
        with self.assertRaises(frappe.ValidationError):
            self._mandate(IBAN_B)

        self.assertEqual(
            frappe.db.count(
                "SEPA Mandate",
                {
                    "member": self.member.name,
                    "status": "Active",
                    "used_for_memberships": 0,
                    "used_for_donations": 0,
                    "used_for_other": 0,
                },
            ),
            0,
        )

    def test_activating_an_existing_purposeless_mandate_is_rejected(self):
        """The other route in: a Draft mandate that is later activated."""
        mandate = self._mandate(IBAN_A, status="Draft")
        mandate.status = "Active"
        mandate.is_active = 1

        with self.assertRaises(frappe.ValidationError):
            mandate.save()


class TestTheGuardDoesNotOverreach(_PurposeFixture):
    """Controls. Without these a guard that rejected every mandate would pass the
    class above."""

    def test_a_memberships_mandate_is_accepted(self):
        mandate = self._mandate(IBAN_A, used_for_memberships=1)
        self.assertEqual(mandate.status, "Active")

    def test_a_donations_only_mandate_is_accepted(self):
        mandate = self._mandate(IBAN_A, used_for_donations=1)
        self.assertEqual(mandate.status, "Active")

    def test_an_other_only_mandate_is_accepted(self):
        mandate = self._mandate(IBAN_A, used_for_other=1)
        self.assertEqual(mandate.status, "Active")

    def test_a_purposeless_draft_mandate_is_accepted(self):
        """A replacement can still be staged before its purposes are decided;
        the guard only fires when the mandate becomes able to collect."""
        mandate = self._mandate(IBAN_A, status="Draft")
        self.assertEqual(mandate.status, "Draft")

    def test_the_per_purpose_guard_still_permits_memberships_plus_donations(self):
        """The capability the app models, unchanged by this guard."""
        self._mandate(IBAN_A, used_for_memberships=1)
        self._mandate(IBAN_B, used_for_donations=1)

        self.assertEqual(
            frappe.db.count("SEPA Mandate", {"member": self.member.name, "status": "Active"}), 2
        )

    def test_the_per_purpose_guard_still_rejects_a_same_purpose_second(self):
        self._mandate(IBAN_A, used_for_memberships=1)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._mandate(IBAN_B, used_for_memberships=1)
        self.assertIn("memberships", str(ctx.exception))
