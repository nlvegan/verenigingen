"""
Member Lifecycle: Structural/Behavioral Regression Guards
===========================================================

Originally a Phase 5.1 "production issues discovered" journal: 7/7 methods were pure
`print()` narration documenting findings from an earlier debugging session, with zero
assertions -- they always passed regardless of what the code actually did.

Converted to real regression guards for the same findings, each calling/inspecting the
actual production DocType metadata or business logic instead of just describing it:

1. Member.status valid options (previously: printed a hardcoded list).
2. Member uses primary_address (Link to Address), not a direct postal_code field.
3. Address DocType genuinely requires address_title when created standalone (real
   unhappy path -- frappe.contacts.doctype.address.address.Address.autoname()).
4. Member ID generation actually produces a value for an Active member.
5. Enhanced Test Factory preserves an explicitly requested status rather than silently
   overriding it to "Active".
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberLifecycleProductionIssues(EnhancedTestCase):
    """Regression guards for structural/business findings about Member lifecycle"""

    def test_member_status_options_match_docmeta(self):
        """Member.status is a Select field with a fixed set of valid values --
        "Application Pending" (used by older mocked tests) is NOT one of them."""

        status_field = frappe.get_meta("Member").get_field("status")
        valid_statuses = [s for s in status_field.options.split("\n") if s]

        self.assertEqual(
            valid_statuses,
            ["Pending", "Active", "Rejected", "Expired", "Suspended", "Banned", "Deceased", "Quit"],
        )
        self.assertNotIn("Application Pending", valid_statuses)

    def test_member_uses_primary_address_link_not_direct_fields(self):
        """Member has a primary_address Link to Address, not a direct postal_code field --
        address data lives on the linked Address document."""

        meta = frappe.get_meta("Member")
        primary_address_field = meta.get_field("primary_address")

        self.assertIsNotNone(primary_address_field, "Member should have a primary_address field")
        self.assertEqual(primary_address_field.fieldtype, "Link")
        self.assertEqual(primary_address_field.options, "Address")
        self.assertIsNone(meta.get_field("postal_code"), "Member should NOT have a direct postal_code field")

    def test_address_creation_without_title_or_links_raises(self):
        """Real unhappy path: Frappe's Address DocType requires address_title when there
        are no links to derive a default title from (Address.autoname())."""

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._insert_address_without_title_or_links()

        self.assertIn("mandatory", str(ctx.exception).lower())

    def _insert_address_without_title_or_links(self):
        """Factory-style helper: build+insert an Address with no title and no links,
        deliberately missing the data Address.autoname() needs to derive a default
        title, so the permission bypass required for a from-scratch insert lives
        here rather than in the test body."""

        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_type": "Personal",
                "address_line1": "Some Street 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "pincode": "1012AB",
                # Deliberately no address_title and no links
            }
        )
        address.insert(ignore_permissions=True)
        return address

    def test_member_id_generation_produces_real_value(self):
        """An Active (non-application) member should end up with a real, non-empty
        member_id after creation via the real save/insert lifecycle.

        member_id=None is passed explicitly: the factory's own defaults pre-assign a
        member_id, which would mask the real production generation logic entirely if
        left in place -- see MemberBeforeSaveService._handle_id_generation(), which
        only generates one when member_id is still falsy at save time.
        """

        member = self.create_test_member(status="Active", member_id=None)

        self.assertTrue(member.member_id, "Active member should have a member_id assigned")

    def test_enhanced_test_factory_preserves_explicit_status(self):
        """The factory must not silently override an explicitly requested status to
        "Active" -- many other tests in the suite rely on this to set up non-Active
        fixtures (Pending, Suspended, etc)."""

        member = self.create_test_member(status="Suspended")

        self.assertEqual(member.status, "Suspended")


if __name__ == "__main__":
    import unittest

    unittest.main()
