"""An Active SEPA Mandate must be marked for at least one purpose (#606).

`SEPAMandate.validate_single_active_mandate_per_purpose` (#584/#597) enforces one
Active mandate per member PER PURPOSE. It did so by collecting the purpose flags
that are set and looping over them -- so a mandate with NONE of them set had an
empty loop and returned early, and the invariant simply did not apply to it. Two
all-purposes-zero Active mandates for one member were measured coexisting.

Bucketing "no purpose" as a fourth purpose would close that specific hole and
leave the larger one open: since #597 every mandate-resolution query filters by
purpose, so an all-zero Active mandate can be found by NONE of them. It is an
authorization that authorizes nothing, silently, on a member who believes they
have signed one. Requiring a purpose makes the shape unreachable rather than
merely unique.

The realistic producer is Frappe's Data Import, which sets
`frappe.flags.in_import` -- and `Document._set_defaults` returns early under that
flag, so the JSON default `used_for_memberships = 1` is not applied.
`test_an_imported_active_mandate_with_no_purpose_is_rejected` covers it, with
`test_the_import_flag_really_does_suppress_the_default` as the control proving
the flag is what makes the state reachable.

Scope of what the guard touches: it runs only for `status == "Active"`, so a
purposeless Draft or Suspended mandate can still be staged and saved, and a
Cancelled one is untouched. Measured 2026-08-27: `tabSEPA Mandate` holds zero
all-zero rows on veg11 (71 rows, all `used_for_memberships = 1`) and zero on
test_site_1. Fixture sweep (AST over every `SEPA Mandate` dict literal plus every
`used_for_*` assigned a falsy literal): 20 sites, 19 of which either pair
`used_for_memberships = 0` with another purpose or omit the flag and take the
docfield default of 1. The twentieth,
`doctype/membership/test_membership_coverage.py`'s
`test_get_member_sepa_mandates_excludes_non_membership_mandate`, did create an
all-zero Active mandate and is fixed in this branch -- an earlier draft of this
docstring asserted the class was already clean, which was one instance too
generous. The sweep is static, so a fixture building purposes from a runtime
value would escape it.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

IBAN_A = "NL91ABNA0417164300"
IBAN_B = "NL02ABNA0123456789"


class _PurposeFixture(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="PurposeReq", last_name="Test")

    def _purpose_mandate(self, iban, status="Active", **purposes):
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
            self._purpose_mandate(IBAN_A)

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
            self._purpose_mandate(IBAN_A)
        with self.assertRaises(frappe.ValidationError):
            self._purpose_mandate(IBAN_B)

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
        mandate = self._purpose_mandate(IBAN_A, status="Draft")
        mandate.status = "Active"
        mandate.is_active = 1

        with self.assertRaises(frappe.ValidationError):
            mandate.save()


class TestTheGuardDoesNotOverreach(_PurposeFixture):
    """Controls. Without these a guard that rejected every mandate would pass the
    class above."""

    def test_a_memberships_mandate_is_accepted(self):
        mandate = self._purpose_mandate(IBAN_A, used_for_memberships=1)
        self.assertEqual(mandate.status, "Active")

    def test_a_donations_only_mandate_is_accepted(self):
        mandate = self._purpose_mandate(IBAN_A, used_for_donations=1)
        self.assertEqual(mandate.status, "Active")

    def test_an_other_only_mandate_is_accepted(self):
        mandate = self._purpose_mandate(IBAN_A, used_for_other=1)
        self.assertEqual(mandate.status, "Active")

    def test_a_purposeless_draft_mandate_is_accepted(self):
        """A replacement can still be staged before its purposes are decided;
        the guard only fires when the mandate becomes able to collect."""
        mandate = self._purpose_mandate(IBAN_A, status="Draft")
        self.assertEqual(mandate.status, "Draft")

    def test_the_per_purpose_guard_still_permits_memberships_plus_donations(self):
        """The capability the app models, unchanged by this guard."""
        self._purpose_mandate(IBAN_A, used_for_memberships=1)
        self._purpose_mandate(IBAN_B, used_for_donations=1)

        self.assertEqual(
            frappe.db.count("SEPA Mandate", {"member": self.member.name, "status": "Active"}), 2
        )

    def test_the_per_purpose_guard_still_rejects_a_same_purpose_second(self):
        self._purpose_mandate(IBAN_A, used_for_memberships=1)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._purpose_mandate(IBAN_B, used_for_memberships=1)
        self.assertIn("memberships", str(ctx.exception))


class TestTheImportRoute(_PurposeFixture):
    """Frappe's Data Import is the one realistic producer of the all-zero shape.

    `Document._set_defaults` (`apps/frappe/frappe/model/document.py`) opens with
    `if frappe.flags.in_import: return`, so a document built from a dict does NOT
    receive the JSON default `used_for_memberships = 1` during an import. The
    column's `NOT NULL DEFAULT 1` does not rescue it either -- Frappe writes an
    explicit 0 for the Check field.
    """

    def _import_mandate(self, status="Active"):
        """Insert exactly as a Data Import row would: a dict with no purpose keys."""
        previous = getattr(frappe.flags, "in_import", False)
        frappe.flags.in_import = True
        try:
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": self.member.name,
                    "mandate_id": f"IMPORT-{frappe.generate_hash(length=8)}",
                    "account_holder_name": self.member.full_name,
                    "iban": IBAN_A,
                    "sign_date": "2024-01-01",
                    "mandate_type": "RCUR",
                    "scheme": "SEPA",
                    "status": status,
                }
            )
            mandate.insert()
            return mandate
        finally:
            frappe.flags.in_import = previous

    def test_an_imported_active_mandate_with_no_purpose_is_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._import_mandate()
        self.assertIn("used_for_memberships", str(ctx.exception))

    def test_the_import_flag_really_does_suppress_the_default(self):
        """The control for the class above.

        Without this, the rejection test would be equally consistent with "the
        import flag changes nothing and the mandate was all-zero for some other
        reason". A Draft import is not blocked by the guard, so its stored purpose
        flags can be read back: they are all 0, whereas the identical dict outside
        an import stores `used_for_memberships = 1`.
        """
        imported = self._import_mandate(status="Draft")
        self.assertEqual(
            frappe.db.get_value(
                "SEPA Mandate",
                imported.name,
                ["used_for_memberships", "used_for_donations", "used_for_other"],
                as_dict=True,
            ),
            {"used_for_memberships": 0, "used_for_donations": 0, "used_for_other": 0},
        )

        ordinary = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "mandate_id": f"PLAIN-{frappe.generate_hash(length=8)}",
                "account_holder_name": self.member.full_name,
                "iban": IBAN_B,
                "sign_date": "2024-01-01",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "status": "Draft",
            }
        )
        ordinary.insert()
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", ordinary.name, "used_for_memberships"), 1
        )
